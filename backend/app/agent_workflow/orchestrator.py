"""Investigation conductor — Person B.

Runs the investigation-loop architecture:

  suspicion arrives
   -> deterministic raw evidence pulled from Aiven
   -> ONE parallel batch (everything that doesn't depend on another agent):
        Aiven Evidence Librarian (SQL + MCP), OSINT Researcher (web; questions
        seeded from the vessel identity), Case Controller, and the Identity /
        Maritime Behavior / Infrastructure Environment analysts
   -> Watch Officer produces the verdict from findings + enrichment
   -> Action Briefing Agent produces report / email / voice payload

No canned data and no special-case logic — Eagle S is treated like any vessel.
When evidence is missing, agents say so and the verdict's confidence drops.

Latency note: the enrichment used to be a serial chain (Librarian -> Controller
-> OSINT), which stacked the two slowest calls (MCP relay + web search) back to
back. Running the whole batch concurrently collapses that into the single slowest
call, and read-only agents submit in one round-trip (agent_base force_first).
"""

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from ..models import AgentFinding
from . import (action_briefing, behavior_agent, case_controller, evidence_librarian,
               gps_environment_agent, identity_agent, osint_researcher, synthesis_agent, tools)

# Hard wall-clock cap (s) for the parallel batch. The Aiven MCP connector / web
# search can occasionally stall; past this we proceed with whatever completed, so
# an investigation ALWAYS finishes well under the UI poll window.
_PARALLEL_BUDGET_SEC = 190


def _gather_raw(suspicion: dict) -> dict:
    """Deterministically pull the ground-truth evidence (no Claude, reliable)."""
    mmsi = suspicion.get("mmsi")
    lp = suspicion.get("last_position") or {}
    lat, lon = lp.get("lat"), lp.get("lon")
    return {
        "vessel": {"name": suspicion.get("name"), "mmsi": mmsi,
                   "imo": suspicion.get("imo"), "flag": suspicion.get("flag")},
        "track": tools.get_recent_track(mmsi),
        "history": tools.get_vessel_history(mmsi),
        "nearby": tools.get_nearby_vessels(lat, lon, exclude_mmsi=mmsi) if lat is not None else [],
        "sanctions": tools.get_sanctions_record(imo=suspicion.get("imo"), name=suspicion.get("name")),
        "identity_check": tools.validate_identity(mmsi=mmsi, imo=suspicion.get("imo"),
                                                  name=suspicion.get("name"), flag=suspicion.get("flag")),
        "gps": tools.check_gps_environment(lat, lon),
        "cable": tools.nearest_cable(lat, lon),
        "scoring_reasons": suspicion.get("reasons", []),
    }


def _seed_osint_questions(suspicion: dict) -> list[str]:
    """OSINT's questions are predictable from the vessel identity, so we seed them
    deterministically instead of waiting on the Librarian + Case Controller. That
    serial dependency was the main latency cost, and these are the same questions an
    analyst would ask of any vessel."""
    name = suspicion.get("name") or suspicion.get("mmsi")
    imo = suspicion.get("imo")
    flag = suspicion.get("flag")
    ident = f"{name!r}" + (f" (IMO {imo})" if imo else "") + (f", flag {flag}" if flag else "")
    return [
        f"Is the vessel {ident} publicly reported as part of a sanctioned, shadow, or "
        "dark fleet, or otherwise linked to sanctions evasion?",
        f"Ownership/operator and flag history of {ident}, and any prior detentions, "
        "cable/anchor incidents, or AIS-gap reports?",
    ]


def _result_summary(key: str, res) -> str:
    """Human-readable one-liner of an agent's output, for the conductor log."""
    if res is None:
        return "no result"
    if key in ("Identity & Records", "Maritime Behavior", "Infrastructure Environment"):
        return f"{len(res)} finding(s)"
    if key == "Aiven Evidence Librarian":
        return (f"summary={'yes' if res.get('summary') else 'no'}, "
                f"+{len(res.get('additional_findings', []))} SQL/MCP finding(s), "
                f"{len(res.get('gaps', []))} gap(s)")
    if key == "OSINT Researcher":
        return (f"{len(res.get('findings', []))} web finding(s), "
                f"{len(res.get('unresolved', []))} unresolved")
    if key == "Case Controller":
        return (f"{len(res.get('research_questions', []))} research question(s), "
                f"evidence_complete={res.get('evidence_complete')}")
    return "ok"


def run_once(suspicion: dict) -> dict:
    sid = suspicion.get("suspicion_id")
    print(f"[conductor] investigating {suspicion.get('name')} ({suspicion.get('mmsi')})")

    raw = _gather_raw(suspicion)
    print(f"[conductor] raw: track={len(raw['track'])}pts nearby={len(raw['nearby'])} "
          f"sanctions_listed={raw['sanctions'].get('listed')} gps={raw['gps'].get('available')}")

    # ONE parallel batch: every step that doesn't depend on another agent's output.
    # The analysts work off the deterministic raw evidence; OSINT's questions are
    # seeded from the vessel identity (so it no longer waits on the Librarian +
    # Controller). The Watch Officer later sees the analysts' findings AND the
    # Librarian/OSINT enrichment, so nothing is lost.
    analyst_case = {"suspicion": suspicion, "raw": raw, "librarian": None,
                    "controller": None, "osint": {"findings": [], "unresolved": []}}
    osint_questions = _seed_osint_questions(suspicion)
    jobs = {
        "Identity & Records": lambda: identity_agent.run(analyst_case),
        "Maritime Behavior": lambda: behavior_agent.run(analyst_case),
        "Infrastructure Environment": lambda: gps_environment_agent.run(analyst_case),
        "Aiven Evidence Librarian": lambda: evidence_librarian.run(suspicion, raw, osint=None),
        "OSINT Researcher": lambda: osint_researcher.run(suspicion, osint_questions),
        "Case Controller": lambda: case_controller.run(suspicion, raw, None, None),
    }
    print(f"[conductor] running {len(jobs)} agents in parallel: {', '.join(jobs)}")
    results: dict = {}
    ex = ThreadPoolExecutor(max_workers=len(jobs))
    try:
        t0 = time.monotonic()
        futs = {ex.submit(fn): key for key, fn in jobs.items()}
        for fut, key in futs.items():
            remaining = max(5.0, _PARALLEL_BUDGET_SEC - (time.monotonic() - t0))
            try:
                results[key] = fut.result(timeout=remaining)
                print(f"[conductor] <- {key}: {_result_summary(key, results[key])}")
            except FuturesTimeoutError:
                print(f"[conductor] <- {key}: SKIPPED (exceeded {_PARALLEL_BUDGET_SEC}s budget)")
                results[key] = None
            except Exception as e:  # noqa: BLE001
                print(f"[conductor] <- {key}: FAILED ({e})")
                results[key] = None
    finally:
        ex.shutdown(wait=False)  # don't block on an abandoned slow agent

    findings: list[dict] = []
    for key in ("Identity & Records", "Maritime Behavior", "Infrastructure Environment"):
        findings.extend(results.get(key) or [])
    for f in findings:
        try:
            AgentFinding(**f)  # drift guard vs contracts.md
        except Exception:  # noqa: BLE001
            pass
        tools.write_finding(f)

    # Verdict + deliverables (Watch Officer sees findings + the enrichment).
    case = {"suspicion": suspicion, "raw": raw,
            "librarian": results.get("Aiven Evidence Librarian"),
            "controller": results.get("Case Controller"),
            "osint": results.get("OSINT Researcher") or {"findings": [], "unresolved": []}}
    assessment = synthesis_agent.run(case, findings)
    print(f"[conductor] verdict {assessment['level']} (confidence={assessment['confidence']})")
    voice = tools.create_voice_briefing(assessment["voice_script"], sid)
    tools.save_assessment(assessment, voice_path=voice["voice_path"])
    briefing = action_briefing.run(case, assessment, findings)

    print("[conductor] done")
    return {"suspicion": suspicion, "evidence": raw, "librarian": case["librarian"],
            "osint": case["osint"], "findings": findings,
            "assessment": assessment, "briefing": briefing}
