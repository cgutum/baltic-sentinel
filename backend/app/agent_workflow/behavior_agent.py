"""Maritime Behavior Analyst — Person B.

Interprets the vessel's real track + history (already gathered) to judge movement
behavior. Honest about thin data: an empty or single-point track means movement
cannot be characterized — it must say 'insufficient track data', never invent.

run(case) -> list[finding]
"""

import json

from . import agent_base

AGENT = "Maritime Behavior"

_SYSTEM = (
    "You are the Maritime Behavior Analyst. Judge how the vessel is moving and whether "
    "it has prior history, using ONLY the provided track and history. Rules: if the track "
    "is empty or a single point, state 'insufficient track data' and that movement cannot "
    "be characterized — do NOT infer loitering or anchor-dragging from nothing. Carefully "
    "distinguish STOPPED/anchored (~0 kn) from SLOW LOITERING (sustained motion below 3 kn). "
    "Note any prior suspicion events or assessments as repeat history. Submit 1-2 findings."
)


def run(case: dict) -> list[dict]:
    raw = case.get("raw", {})
    lp = case["suspicion"].get("last_position") or {}
    user = (
        f"Recent track ({len(raw.get('track', []))} points): "
        f"{json.dumps(raw.get('track'), default=str)[:2500]}\n"
        f"History: {json.dumps(raw.get('history'), default=str)[:1500]}\n"
        f"Last reported position/speed: {json.dumps(lp, default=str)}\n"
        f"Scoring reasons: {json.dumps(raw.get('scoring_reasons', []), default=str)}\n\n"
        "Analyze movement behavior and history, then submit_findings."
    )
    return agent_base.run_specialist(agent_name=AGENT, system=_SYSTEM, user=user,
                                     suspicion=case["suspicion"], force_first=True)
