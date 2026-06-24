"""Agent workflow orchestrator — Person B.

Runs the investigation: get suspicion -> investigate -> synthesize -> voice.

Right now (H3-H5) the brain is CANNED (fallback_outputs) so the whole flow runs
end-to-end with no external services — the demo safety net. At H5+ the real
Investigator / Watch Officer logic slots into investigate() / synthesize();
run_once() and the tools layer stay unchanged.

Run the canned flow:  python -m app.agent_workflow.orchestrator
"""

from ..config import settings
from ..models import AgentFinding, ThreatAssessment
from . import fallback_outputs, tools


def investigate(suspicion: dict) -> list[dict]:
    """Produce agent findings for a suspicion, publish/persist each one."""
    # Option A round-trip: the orchestrator calls a tool and gets data back.
    track = tools.get_recent_track(suspicion["mmsi"])
    print(f"[orchestrator] tool get_recent_track -> {len(track)} points")

    if settings.demo_mode:
        results = fallback_outputs.findings(suspicion)
    else:
        from . import investigator
        results = investigator.run(suspicion)  # real Claude loop; falls back on error

    for finding in results:
        AgentFinding(**finding)  # drift guard vs contracts.md
        print(
            f"[orchestrator] finding: {finding['agent']} "
            f"(severity={finding['severity']}) — {finding['finding']}"
        )
        tools.write_finding(finding)
    return results


def synthesize(suspicion: dict, findings: list[dict]) -> dict:
    """Combine findings into one threat assessment; make voice; publish/persist."""
    # TODO (H10): real Watch Officer agent. Until then synthesis is always canned,
    # even when DEMO_MODE is off (so the H5 Investigator can run live end-to-end).
    result = fallback_outputs.assessment(suspicion, findings)

    ThreatAssessment(**result)  # drift guard vs contracts.md

    voice = tools.create_voice_briefing(result["voice_script"], result["suspicion_id"])
    tools.save_assessment(result, voice_path=voice["voice_path"])

    print(
        f"[orchestrator] ASSESSMENT {result['level']} "
        f"(confidence={result['confidence']}) — {result['summary']}"
    )
    print(
        f"[orchestrator] voice briefing ready: {voice['voice_path']} "
        f"(exists={voice['exists']})"
    )
    return result


def run_once(suspicion: dict | None = None) -> dict:
    """End-to-end investigation for one suspicion. Mode-agnostic on purpose."""
    suspicion = suspicion or tools.get_suspicion_event()
    print(
        f"[orchestrator] investigating {suspicion.get('name')} "
        f"({suspicion.get('mmsi')}) — {suspicion.get('rule')} near {suspicion.get('cable')}"
    )
    findings = investigate(suspicion)
    print(f"[orchestrator] {len(findings)} findings collected")
    assessment = synthesize(suspicion, findings)
    print("[orchestrator] done")
    return assessment


if __name__ == "__main__":
    run_once()
