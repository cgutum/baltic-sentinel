"""Maritime Investigation Analyst — Person B.

ONE focused reasoning pass over all the gathered Aiven evidence, covering the three
dimensions that used to be separate agents — identity/records, movement behaviour,
and infrastructure environment — and emitting calibrated findings. No tools: the
Evidence Librarian (Aiven SQL + MCP) and OSINT (web) gather in parallel; this agent
judges. Single round-trip (force_first), Sonnet. Honest about thin data: it says
what is unavailable rather than inventing.

run(case) -> list[finding]
"""

import json

from . import agent_base

AGENT = "Maritime Analyst"

_SYSTEM = (
    "You are the Maritime Investigation Analyst for Baltic Sentinel. Using ONLY the "
    "provided evidence, produce calibrated findings across THREE dimensions:\n"
    "1) IDENTITY & RECORDS — is the identity authentic/consistent (IMO check-digit, "
    "MMSI vs flag)? Does OpenSanctions list it? Distinguish a port-state DETENTION from an "
    "active SANCTIONS designation; if listed=false, do NOT call it sanctioned.\n"
    "2) MARITIME BEHAVIOUR — how is it moving (use the track)? If the track is empty or a "
    "single point, say 'insufficient track data' — do NOT infer loitering from nothing. "
    "Distinguish STOPPED/anchored (~0 kn) from SLOW LOITERING (sustained <3 kn). Note prior "
    "history/events.\n"
    "3) INFRASTRUCTURE ENVIRONMENT — GPS/AIS trust (is it in a jammed zone?), the real "
    "nearest-cable distance (say plainly if it is NOT near a cable), and any meaningful "
    "clustering of nearby vessels.\n\n"
    "Rules: never assert what the evidence does not support; when something is unavailable, "
    "say so and lower the severity. Tag each finding with its dimension in the text. "
    "Submit 3-6 findings total (severity 0-1)."
)


def run(case: dict) -> list[dict]:
    raw = case.get("raw", {})
    user = (
        f"Vessel: {json.dumps(raw.get('vessel'), default=str)}\n"
        f"Identity check: {json.dumps(raw.get('identity_check'), default=str)}\n"
        f"OpenSanctions: {json.dumps(raw.get('sanctions'), default=str)}\n"
        f"Recent track ({len(raw.get('track', []))} pts): "
        f"{json.dumps(raw.get('track'), default=str)[:2000]}\n"
        f"History: {json.dumps(raw.get('history'), default=str)[:1200]}\n"
        f"GPS environment: {json.dumps(raw.get('gps'), default=str)}\n"
        f"Nearest cable: {json.dumps(raw.get('cable'), default=str)}\n"
        f"Nearby vessels ({len(raw.get('nearby', []))}): "
        f"{json.dumps(raw.get('nearby'), default=str)[:2000]}\n"
        f"Scoring reasons: {json.dumps(raw.get('scoring_reasons', []), default=str)}\n\n"
        "Analyze all three dimensions, then submit_findings."
    )
    return agent_base.run_specialist(agent_name=AGENT, system=_SYSTEM, user=user,
                                     suspicion=case["suspicion"], force_first=True)
