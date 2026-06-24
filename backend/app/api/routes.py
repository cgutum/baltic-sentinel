"""HTTP routes (shared file — announce before editing).

Person A (data foundation):
  POST /replay/eagle-s        start the Eagle S replay
  GET  /vessels               all known vessels (map source, with score)
  GET  /candidates            suspicious vessels only
  POST /investigate/{mmsi}    operator trigger -> publishes vessel.suspicion (+dossier)
Person B (agents):
  GET  /assessment/latest, /voice/latest, /events   (stubs until wired)
"""
import datetime
import time
import uuid
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse, FileResponse

router = APIRouter()

# Frontend (served at GET /): the Gotham watch console at repo/frontend/prototype.html
_UI_FILE = Path(__file__).resolve().parents[3] / "frontend" / "prototype.html"

# Simple per-vessel debounce so a double-click doesn't fire two investigations.
_INVESTIGATE_DEBOUNCE_SEC = 5
_recent_investigations: dict[str, float] = {}


@router.post("/replay/eagle-s")
def replay_eagle_s():
    """Start the Eagle S replay (Person A)."""
    from app.data_pipeline import replay_eagle_s as replay
    result = replay.start()
    return JSONResponse(content={"ok": True, **result})


@router.get("/vessels")
def vessels():
    """All known vessels for the map (regular boats + candidates, with score)."""
    from app import database
    return {"vessels": database.get_vessels()}


@router.get("/candidates")
def candidates():
    """Suspicious vessels only (score >= threshold)."""
    from app import database
    return {"candidates": database.get_candidates()}


@router.post("/investigate/{mmsi}")
def investigate(mmsi: str):
    """Operator-triggered: assemble a dossier and publish vessel.suspicion for the agents."""
    from app import database, scoring  # noqa: F401 (scoring import keeps loaders warm)
    from app.kafka_client import publish, TOPIC_VESSEL_SUSPICION
    from app.data_pipeline import geo_rules
    from app.data_pipeline.loaders import sanctions, gpsjam

    v = database.get_vessel(mmsi)
    if not v:
        return JSONResponse(status_code=404, content={"ok": False, "error": "unknown vessel"})

    # Debounce double-clicks.
    now_mono = time.monotonic()
    last = _recent_investigations.get(mmsi)
    if last and now_mono - last < _INVESTIGATE_DEBOUNCE_SEC:
        return {"ok": True, "deduped": True, "mmsi": mmsi}
    _recent_investigations[mmsi] = now_mono

    lat, lon = v.get("last_lat"), v.get("last_lon")
    cable = geo_rules.cable_near(lat, lon) if lat is not None and lon is not None else None
    hit = sanctions.lookup(imo=v.get("imo"), name=v.get("name"))
    score = v.get("suspicion_score") or 0

    dossier = {
        "score": score,
        "reasons": v.get("suspicion_reasons") or [],
        "flag": v.get("flag"),
        "gps_jammed": gpsjam.in_jammed_zone(lat, lon) if lat is not None else False,
        "sanctions_hit": {"risk": hit.get("risk"), "flag": hit.get("flag")} if hit else None,
        "last_position": {"lat": lat, "lon": lon, "speed": v.get("last_speed"),
                          "course": v.get("last_course"), "ts": str(v.get("last_seen"))},
    }
    sid = "sus_" + uuid.uuid4().hex[:8]
    summary = (f"Operator launched investigation on {v.get('name') or mmsi}. "
               f"Score {score}/100" + (f" near {cable}." if cable else "."))
    msg = {
        "suspicion_id": sid, "mmsi": mmsi, "imo": v.get("imo"), "name": v.get("name"),
        "rule": "operator_launch", "cable": cable or "(none)", "severity": round(score / 100, 2),
        "summary": summary,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "dossier": dossier,
    }
    publish(TOPIC_VESSEL_SUSPICION, msg)

    try:
        with database.get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO suspicion_events (suspicion_id,mmsi,imo,name,rule,cable,severity,summary,ts) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (suspicion_id) DO NOTHING",
                (sid, mmsi, v.get("imo"), v.get("name"), "operator_launch", cable,
                 msg["severity"], summary),
            )
            conn.commit()
    except Exception as e:  # noqa: BLE001 — publish already succeeded; persistence is best-effort
        print(f"[investigate] save failed: {e}")

    return {"ok": True, "suspicion_id": sid, "published_to": "vessel.suspicion", "dossier": dossier}


# --- Person B (agent workflow) --------------------------------------------

# In-memory cache of the most recent investigation (for /assessment/latest + the UI).
_last_result: dict = {}
# Per-vessel debounce so a double-click doesn't fire two Claude investigations.
_AGENT_DEBOUNCE_SEC = 8
_agent_debounce: dict[str, float] = {}


def _suspicion_from_vessel(mmsi: str, v: dict) -> dict:
    """Build a vessel.suspicion-shaped dict from a live vessel row for the agent."""
    from app.data_pipeline import geo_rules

    lat, lon = v.get("last_lat"), v.get("last_lon")
    cable = geo_rules.cable_near(lat, lon) if lat is not None and lon is not None else None
    score = v.get("suspicion_score") or 0
    return {
        "suspicion_id": "sus_" + uuid.uuid4().hex[:8],
        "mmsi": mmsi, "imo": v.get("imo"), "name": v.get("name"),
        "rule": "operator_launch", "cable": cable or "(none)",
        "severity": round((score or 0) / 100, 2),
        "summary": (f"Operator launched investigation on {v.get('name') or mmsi}. "
                    f"Score {score}/100" + (f" near {cable}." if cable else ".")),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        # Extra context the agent sees via get_suspicion_event:
        "flag": v.get("flag"),
        "reasons": v.get("suspicion_reasons") or [],
        "last_position": {"lat": lat, "lon": lon,
                          "speed": v.get("last_speed"), "course": v.get("last_course")},
    }


@router.post("/agent/investigate/{mmsi}")
def agent_investigate(mmsi: str):
    """Run the Claude agent on a chosen vessel; return findings + assessment.

    Synchronous (the UI shows a spinner). Debounced per vessel. Uses live vessel
    data when Postgres is configured, else the canned Eagle S demo case.
    """
    from app import database
    from app.agent_workflow import orchestrator, fallback_outputs

    now = time.monotonic()
    last = _agent_debounce.get(mmsi)
    if last and now - last < _AGENT_DEBOUNCE_SEC and _last_result.get("mmsi") == mmsi:
        return {"ok": True, "deduped": True, **_last_result}
    _agent_debounce[mmsi] = now

    v = database.get_vessel(mmsi) if database.is_configured() else None
    if v:
        suspicion = _suspicion_from_vessel(mmsi, v)
        vessel = {"mmsi": mmsi, "name": v.get("name"), "flag": v.get("flag"),
                  "score": v.get("suspicion_score")}
    elif str(mmsi) == fallback_outputs.SAMPLE_SUSPICION["mmsi"]:
        suspicion = fallback_outputs.SAMPLE_SUSPICION
        vessel = {"mmsi": mmsi, "name": "Eagle S", "flag": "Cook Islands", "score": 85}
    else:
        return JSONResponse(status_code=404, content={
            "ok": False, "error": "Unknown vessel (no live DB connected, and not the demo vessel)."})

    result = orchestrator.run_once(suspicion)
    payload = {"mmsi": mmsi, "vessel": vessel,
               "findings": result["findings"], "assessment": result["assessment"]}
    _last_result.clear()
    _last_result.update(payload)
    return {"ok": True, **payload}


@router.get("/assessment/latest")
def assessment_latest():
    """Return the most recent investigation result (findings + assessment)."""
    if _last_result:
        return {"ok": True, **_last_result}
    return JSONResponse(status_code=404, content={"ok": False, "error": "no investigation yet"})


@router.get("/voice/latest")
def voice_latest():
    """Return the latest voice briefing path. TODO real ElevenLabs (H13)."""
    a = _last_result.get("assessment")
    if a:
        return {"ok": True, "voice_script": a.get("voice_script")}
    return JSONResponse(status_code=404, content={"ok": False, "error": "no voice yet"})


@router.get("/events")
def events():
    return JSONResponse(status_code=501,
                        content={"ok": False, "todo": "events stream not implemented yet"})


@router.get("/")
def ui():
    """Serve the Gotham watch console (frontend/prototype.html)."""
    return FileResponse(str(_UI_FILE))


@router.get("/prototype_data.js")
def ui_data():
    """Serve the console's data bundle so it loads same-origin."""
    return FileResponse(str(_UI_FILE.parent / "prototype_data.js"),
                        media_type="application/javascript")
