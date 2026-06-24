"""HTTP routes (shared file — announce before editing).

H0: stubs return 501 / placeholders so the contract is visible and the app
boots. Owners fill these in as their parts come online:
  - /replay/eagle-s   Person A (H3-H5)
  - /assessment/latest, /voice/latest, /events  Person B (H10+)
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/replay/eagle-s")
def replay_eagle_s():
    """Start the Eagle S replay (Person A)."""
    from app.data_pipeline import replay_eagle_s as replay
    result = replay.start()
    return JSONResponse(content={"ok": True, **result})


@router.get("/assessment/latest")
def assessment_latest():
    """Return the latest threat assessment. TODO Person B (H10-H13)."""
    return JSONResponse(
        status_code=501,
        content={"ok": False, "todo": "assessment not implemented yet (Person B)"},
    )


@router.get("/voice/latest")
def voice_latest():
    """Return the latest voice briefing. TODO Person B (H13-H16)."""
    return JSONResponse(
        status_code=501,
        content={"ok": False, "todo": "voice not implemented yet (Person B)"},
    )


@router.get("/events")
def events():
    """Stream live events for the UI. TODO (H3+)."""
    return JSONResponse(
        status_code=501,
        content={"ok": False, "todo": "events stream not implemented yet"},
    )
