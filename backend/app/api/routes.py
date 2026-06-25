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
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse, FileResponse

router = APIRouter()

# Frontend (served at GET /): the Gotham watch console. Resolve robustly so it works
# both in the repo (parents[3]/frontend) and in the Docker image (WORKDIR /app, the app
# package at /app/app and the UI copied to /app/frontend -> parents[2]/frontend).
def _resolve_ui() -> Path:
    here = Path(__file__).resolve()
    for base in (here.parents[3], here.parents[2], here.parents[1]):
        cand = base / "frontend" / "prototype.html"
        if cand.exists():
            return cand
    return here.parents[3] / "frontend" / "prototype.html"


_UI_FILE = _resolve_ui()

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


@router.get("/track/{mmsi}")
def track(mmsi: str):
    """Recent position history for a vessel (for the map route trail)."""
    from app import database
    if not database.is_configured():
        return {"mmsi": mmsi, "track": []}
    from psycopg.rows import dict_row
    with database.get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT lon, lat FROM tracks WHERE mmsi=%s AND lon IS NOT NULL "
                    "ORDER BY ts DESC LIMIT 1000", (str(mmsi),))
        rows = cur.fetchall()
    coords = [[r["lon"], r["lat"]] for r in reversed(rows)]
    return {"mmsi": mmsi, "track": coords}


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
# Async investigation jobs: mmsi -> {"status": "running"|"done"|"error", result/error, ts}.
# Investigations take minutes (Claude agents + Aiven MCP + web search) — longer than a
# browser holds a fetch open — so POST starts a thread and the UI polls /agent/result.
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def cache_investigation(mmsi: str, result: dict, vessel: dict | None = None) -> dict:
    """Cache a finished investigation so GET /agent/result/{mmsi} returns it. Called by
    both the operator-triggered run AND the Sentinel's re-investigation, so the dossier
    always shows the freshest verdict whoever produced it."""
    payload = {"mmsi": str(mmsi), "vessel": vessel or {"mmsi": str(mmsi)},
               "findings": result.get("findings"), "assessment": result.get("assessment"),
               "osint": result.get("osint"), "briefing": result.get("briefing"),
               "evidence": result.get("evidence")}
    with _jobs_lock:
        _jobs[str(mmsi)] = {"status": "done", "result": payload, "ts": time.time()}
    _last_result.clear()
    _last_result.update(payload)
    return payload


def _run_investigation(mmsi: str, suspicion: dict, vessel: dict) -> None:
    """Background worker: run the agent team, stash the result for polling."""
    from app.agent_workflow import orchestrator
    try:
        cache_investigation(mmsi, orchestrator.run_once(suspicion), vessel)
    except Exception as e:  # noqa: BLE001 — surface failure via the poll endpoint
        with _jobs_lock:
            _jobs[mmsi] = {"status": "error", "error": str(e), "ts": time.time()}
        print(f"[agent] investigation failed for {mmsi}: {e}")


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
    """Kick off the investigation team on a vessel and return immediately.

    Investigations take minutes (Claude agents + Aiven MCP + web search) — far longer
    than a browser holds a fetch open — so we run them in a background thread and
    return {status:'running'}. The UI polls /agent/result/{mmsi}. Uses ONLY live
    vessel data from Aiven — Eagle S is treated like any other vessel.
    """
    from app import database

    v = database.get_vessel(mmsi) if database.is_configured() else None
    if not v:
        return JSONResponse(status_code=404, content={
            "ok": False, "error": "Unknown vessel — no live data for this MMSI. Make sure the "
            "ingest + state_builder workers are running (replay Eagle S like any other vessel)."})

    with _jobs_lock:
        job = _jobs.get(mmsi)
        if job and job.get("status") == "running":
            return {"ok": True, "status": "running", "mmsi": mmsi}  # already investigating
        _jobs[mmsi] = {"status": "running", "ts": time.time()}

    suspicion = _suspicion_from_vessel(mmsi, v)
    vessel = {"mmsi": mmsi, "name": v.get("name"), "flag": v.get("flag"),
              "score": v.get("suspicion_score")}
    threading.Thread(target=_run_investigation, args=(mmsi, suspicion, vessel),
                     daemon=True).start()
    return {"ok": True, "status": "running", "mmsi": mmsi}


@router.get("/agent/result/{mmsi}")
def agent_result(mmsi: str):
    """Poll an investigation's status/result (started by POST /agent/investigate)."""
    with _jobs_lock:
        job = _jobs.get(mmsi)
    if not job:
        return JSONResponse(status_code=404, content={"ok": False, "status": "none"})
    if job["status"] == "running":
        from app.agent_workflow.agent_base import PROGRESS
        return {"ok": True, "status": "running", "mmsi": mmsi,
                "progress": PROGRESS.get(str(mmsi), [])}
    if job["status"] == "error":
        return JSONResponse(status_code=500, content={
            "ok": False, "status": "error", "error": job.get("error")})
    finished_at = None
    if job.get("ts"):
        finished_at = datetime.datetime.fromtimestamp(
            job["ts"], datetime.timezone.utc).isoformat()
    return {"ok": True, "status": "done", "finished_at": finished_at, **job["result"]}


# --- Sentinel (autonomous monitor) + watchlist control --------------------------
_sentinel_state: dict = {"running": False, "last": None}
_sentinel_lock = threading.Lock()


def _run_sentinel_cycle(only_mmsi: str | None = None) -> None:
    from app.agent_workflow import sentinel
    try:
        out = sentinel.run_cycle(only_mmsi=only_mmsi)
        with _sentinel_lock:
            _sentinel_state.update(running=False,
                                   last=out or {"summary": "watchlist had no active vessels"})
    except Exception as e:  # noqa: BLE001
        with _sentinel_lock:
            _sentinel_state.update(running=False, last={"error": str(e)})
        print(f"[sentinel-api] cycle failed: {e}")


@router.get("/watchlist")
def watchlist():
    """All watch records (any status) for the operator UI."""
    from app.agent_workflow import tools
    return {"ok": True, "watchlist": tools.get_watchlist(status=None, limit=100)}


@router.post("/watchlist/{mmsi}/activate")
def watch_activate(mmsi: str):
    """Operator grants the Sentinel authority to monitor this vessel."""
    from app.agent_workflow import tools
    print(f"[sentinel-api] operator ACTIVATED Sentinel on {mmsi}", flush=True)
    return tools.set_watch_status(mmsi, "active")


@router.post("/watchlist/{mmsi}/deactivate")
def watch_deactivate(mmsi: str):
    """Operator revokes the Sentinel's authority over this vessel."""
    from app.agent_workflow import tools
    print(f"[sentinel-api] operator DEACTIVATED Sentinel on {mmsi}", flush=True)
    return tools.set_watch_status(mmsi, "paused")


@router.post("/watchlist/{mmsi}/delete")
def watch_delete(mmsi: str):
    """Operator removes a vessel from the watchlist."""
    from app.agent_workflow import tools
    print(f"[sentinel-api] operator DELETED {mmsi} from watchlist", flush=True)
    return tools.delete_watch(mmsi)


@router.post("/sentinel/run")
def sentinel_run():
    """Trigger one Sentinel monitoring cycle now (over the ACTIVE watchlist)."""
    with _sentinel_lock:
        if _sentinel_state["running"]:
            return {"ok": True, "status": "running"}
        _sentinel_state["running"] = True
    print("[sentinel-api] monitoring cycle triggered by operator", flush=True)
    threading.Thread(target=_run_sentinel_cycle, daemon=True).start()
    return {"ok": True, "status": "running"}


@router.post("/sentinel/run/{mmsi}")
def sentinel_run_one(mmsi: str):
    """Run the Sentinel on a single vessel now (operator per-boat trigger)."""
    with _sentinel_lock:
        if _sentinel_state["running"]:
            return {"ok": True, "status": "running"}
        _sentinel_state["running"] = True
    print(f"[sentinel-api] monitoring cycle triggered for {mmsi}", flush=True)
    threading.Thread(target=_run_sentinel_cycle, kwargs={"only_mmsi": mmsi}, daemon=True).start()
    return {"ok": True, "status": "running", "mmsi": mmsi}


@router.get("/sentinel/memory/{mmsi}")
def sentinel_memory(mmsi: str):
    """The Sentinel's own memory (cycle notes) for a vessel — written via the MCP."""
    from app.agent_workflow import tools
    return {"ok": True, "memory": tools.get_sentinel_memory(mmsi)}


@router.get("/sentinel/status")
def sentinel_status():
    """Is a Sentinel cycle running, and what did the last one do?"""
    with _sentinel_lock:
        return {"ok": True, "running": _sentinel_state["running"], "last": _sentinel_state["last"]}


@router.get("/mcp/activity")
def mcp_activity():
    """Recent Aiven MCP tool calls the agents have made (for the UI activity panel)."""
    from app.agent_workflow.agent_base import MCP_ACTIVITY
    return {"ok": True, "activity": list(MCP_ACTIVITY)[-40:]}


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
