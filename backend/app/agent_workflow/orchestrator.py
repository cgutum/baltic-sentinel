"""Investigation conductor — Person B.

Runs a lean investigation workflow that feeds the autonomous Sentinel:

  suspicion arrives
   -> deterministic raw evidence pulled from Aiven (track, history, nearby,
      sanctions, IMO check, GPS, cable)
   -> ONE parallel batch:
        * Maritime Analyst         — judges identity / behaviour / environment
        * Aiven Evidence Librarian — digs Aiven via SQL + MCP service health
        * OSINT Researcher         — web search (questions seeded from the identity)
   -> Watch Officer (Opus) produces the calibrated verdict
   -> render_briefing (deterministic) builds the report / email / voice payload
   -> record_watch hands a monitoring record to the Sentinel

No canned data and no special-case logic — Eagle S is treated like any vessel.
When evidence is missing, agents say so and the verdict's confidence drops.

This is deliberately a WORKFLOW (fast, code-orchestrated). The genuinely autonomous,
stateful, tool-driven agent is the Sentinel (sentinel.py).
"""

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from ..models import AgentFinding
from . import agent_base, analyst, evidence_librarian, osint_researcher, synthesis_agent, tools

# Hard wall-clock cap (s) for the parallel batch. The Aiven MCP connector / web
# search can occasionally stall; past this we proceed with whatever completed, so
# an investigation ALWAYS finishes well under the UI poll window.
_PARALLEL_BUDGET_SEC = 220


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
    if key == "Maritime Analyst":
        return f"{len(res)} finding(s)"
    if key == "Aiven Evidence Librarian":
        return (f"summary={'yes' if res.get('summary') else 'no'}, "
                f"+{len(res.get('additional_findings', []))} SQL/MCP finding(s), "
                f"{len(res.get('gaps', []))} gap(s)")
    if key == "OSINT Researcher":
        return (f"{len(res.get('findings', []))} web finding(s), "
                f"{len(res.get('unresolved', []))} unresolved")
    return "ok"


def _build_watch(suspicion: dict, raw: dict, case: dict, assessment: dict,
                 findings: list[dict]) -> dict:
    """Distil the investigation into a durable monitoring record for the Sentinel:
    the verdict baseline, the observable signals to watch, what's still unresolved,
    and what should trigger a re-check."""
    gps = raw.get("gps") or {}
    cable = raw.get("cable") or {}
    signals: list[str] = []
    if gps.get("in_jammed_zone"):
        signals.append("inside a GPS-jamming zone")
    if cable.get("inside_corridor"):
        signals.append(f"inside cable corridor: {cable.get('nearest_cable')}")
    elif cable.get("nearest_cable") is not None:
        signals.append(f"near cable {cable.get('nearest_cable')} (~{cable.get('distance_km')} km)")
    for r in (raw.get("scoring_reasons") or []):
        signals.append(f"score reason: {r}")
    for f in findings:
        if (f.get("severity") or 0) >= 0.6:
            signals.append(f"{f.get('agent')}: {str(f.get('finding'))[:120]}")
    lib = case.get("librarian") or {}
    osint = case.get("osint") or {}
    open_q = [str(g) for g in (lib.get("gaps") or [])] + \
             [str(u) for u in (osint.get("unresolved") or [])]
    triggers = [
        "new track points for this MMSI",
        "re-enters a cable corridor or GPS-jamming zone",
        "a new suspicion_event fires for this MMSI",
        "scheduled review (next_review_at)",
    ]
    return {"mmsi": suspicion.get("mmsi"), "name": suspicion.get("name"),
            "imo": suspicion.get("imo"), "suspicion_id": suspicion.get("suspicion_id"),
            "level": assessment.get("level"), "confidence": assessment.get("confidence"),
            "watch_signals": signals[:12], "open_questions": open_q[:12],
            "recheck_triggers": triggers, "status": "active"}  # MEDIUM+ go straight onto active watch


def run_once(suspicion: dict) -> dict:
    sid = suspicion.get("suspicion_id")
    mmsi = suspicion.get("mmsi")
    print(f"[conductor] investigating {suspicion.get('name')} ({mmsi})")
    agent_base.progress_reset(mmsi)
    agent_base.progress(mmsi, "Pulling live evidence from Aiven — track, sanctions, GPS, cable…")

    raw = _gather_raw(suspicion)
    print(f"[conductor] raw: track={len(raw['track'])}pts nearby={len(raw['nearby'])} "
          f"sanctions_listed={raw['sanctions'].get('listed')} gps={raw['gps'].get('available')}")
    agent_base.progress(mmsi, "Running the Analyst, Aiven Librarian and OSINT researcher in parallel…")

    # ONE parallel batch: the Analyst judges the raw evidence while the Librarian
    # (Aiven SQL + MCP) and OSINT (web) gather in parallel. OSINT's questions are
    # seeded from the vessel identity. The Watch Officer later sees the Analyst's
    # findings AND the Librarian/OSINT enrichment, so nothing is lost.
    analyst_case = {"suspicion": suspicion, "raw": raw}
    osint_questions = _seed_osint_questions(suspicion)
    jobs = {
        "Maritime Analyst": lambda: analyst.run(analyst_case),
        "Aiven Evidence Librarian": lambda: evidence_librarian.run(suspicion, raw, osint=None),
        "OSINT Researcher": lambda: osint_researcher.run(suspicion, osint_questions),
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
                agent_base.progress(mmsi, f"{key} — {_result_summary(key, results[key])}")
            except FuturesTimeoutError:
                print(f"[conductor] <- {key}: SKIPPED (exceeded {_PARALLEL_BUDGET_SEC}s budget)")
                results[key] = None
            except Exception as e:  # noqa: BLE001
                print(f"[conductor] <- {key}: FAILED ({e})")
                results[key] = None
    finally:
        ex.shutdown(wait=False)  # don't block on an abandoned slow agent

    findings: list[dict] = list(results.get("Maritime Analyst") or [])
    for f in findings:
        try:
            AgentFinding(**f)  # drift guard vs contracts.md
        except Exception:  # noqa: BLE001
            pass
        tools.write_finding(f)

    # Verdict + deliverables (Watch Officer sees findings + the enrichment).
    case = {"suspicion": suspicion, "raw": raw,
            "librarian": results.get("Aiven Evidence Librarian"),
            "osint": results.get("OSINT Researcher") or {"findings": [], "unresolved": []}}
    agent_base.progress(mmsi, "Watch Officer weighing the evidence into a calibrated verdict…")
    assessment = synthesis_agent.run(case, findings)
    print(f"[conductor] verdict {assessment['level']} (confidence={assessment['confidence']})")
    agent_base.progress(mmsi, f"Verdict: {assessment['level']} (confidence {assessment['confidence']})")
    voice = tools.create_voice_briefing(assessment["voice_script"], sid)
    tools.save_assessment(assessment, voice_path=voice["voice_path"])
    briefing = tools.render_briefing(raw.get("vessel", {}), assessment, findings)

    # Hand off to the Sentinel — but ONLY if the verdict warrants ongoing monitoring.
    # Benign LOW verdicts are not added. MEDIUM+ land 'active' so the Sentinel starts
    # monitoring them right away (the operator can still pause it per-vessel).
    if assessment["level"] in ("MEDIUM", "HIGH"):
        watch = _build_watch(suspicion, raw, case, assessment, findings)
        tools.record_watch(watch)
        print(f"[conductor] added to watchlist (active) for {watch['mmsi']} "
              f"({len(watch['watch_signals'])} signals) — Sentinel will monitor it")
    else:
        print(f"[conductor] verdict {assessment['level']} — benign, not added to watchlist")

    agent_base.progress(mmsi, "Done.")
    print("[conductor] done")
    return {"suspicion": suspicion, "evidence": raw, "librarian": case["librarian"],
            "osint": case["osint"], "findings": findings,
            "assessment": assessment, "briefing": briefing}
