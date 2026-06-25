"""Infrastructure Environment Analyst — Person B.

Interprets the environment evidence (real GPS-jam check, nearest-cable distance,
nearby vessels) to judge AIS/GPS trust, cable proximity, and the surrounding
scene. Honest when data is unavailable: it must say 'GPS context unavailable' /
'cable context unavailable' rather than assert.

run(case) -> list[finding]
"""

import json

from . import agent_base

AGENT = "Infrastructure Environment"

_SYSTEM = (
    "You are the Infrastructure Environment Analyst. Using ONLY the provided evidence, "
    "judge: (1) GPS/AIS TRUST — if the GPS-jam check says available=false, state 'GPS "
    "context unavailable'; if available, report whether it's in a jammed zone and what "
    "that does to position confidence. (2) CABLE PROXIMITY — use the real nearest-cable "
    "distance; if it is not inside a corridor and the distance is large, say it is NOT "
    "near a cable rather than implying it is; if cable data is unavailable say so. "
    "(3) SCENE — note any meaningful clustering of nearby vessels (a second loiterer, "
    "an anchorage, adjacent-MMSI group). Cable corridors are approximate. Submit 1-2 findings."
)


def run(case: dict) -> list[dict]:
    raw = case.get("raw", {})
    lib = case.get("librarian") or {}
    user = (
        f"GPS environment: {json.dumps(raw.get('gps'), default=str)}\n"
        f"Nearest cable: {json.dumps(raw.get('cable'), default=str)}\n"
        f"Nearby vessels ({len(raw.get('nearby', []))}): "
        f"{json.dumps(raw.get('nearby'), default=str)[:2500]}\n"
        f"Librarian additional findings: {json.dumps(lib.get('additional_findings', []), default=str)[:1500]}\n\n"
        "Analyze GPS/AIS trust, cable proximity, and the surrounding scene, then submit_findings."
    )
    return agent_base.run_specialist(agent_name=AGENT, system=_SYSTEM, user=user,
                                     suspicion=case["suspicion"], force_first=True)
