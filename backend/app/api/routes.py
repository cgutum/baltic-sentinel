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

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

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


# --- Person B (stubs until wired) -----------------------------------------

@router.get("/assessment/latest")
def assessment_latest():
    return JSONResponse(status_code=501,
                        content={"ok": False, "todo": "assessment not implemented yet (Person B)"})


@router.get("/voice/latest")
def voice_latest():
    return JSONResponse(status_code=501,
                        content={"ok": False, "todo": "voice not implemented yet (Person B)"})


@router.get("/events")
def events():
    return JSONResponse(status_code=501,
                        content={"ok": False, "todo": "events stream not implemented yet"})
