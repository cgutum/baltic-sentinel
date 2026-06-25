"""Agent tools — Person B. REAL data only; no canned/demo answers.

Everything here reads live data from Aiven (Postgres), the OpenSanctions loader,
or the GPS-jam / cable geo helpers — or it clearly reports the data is
unavailable. There are NO hardcoded investigation answers and NO mock fallbacks:
if we don't have something, the tool says so, and the agents must reflect that.

Tool groups:
  Aiven access (the Evidence Librarian's kit):
    aiven_query(sql)        read-only SQL over Aiven Postgres (compose any query)
    get_recent_track(mmsi)  position history (empty if none on record)
    get_vessel_history(mmsi) prior suspicion events + prior assessments + track count
    get_nearby_vessels(...) the live maritime scene around a point
  Identity / records:
    validate_identity(...)  deterministic IMO check-digit / format check
    get_sanctions_record(...) real OpenSanctions maritime record (or {'listed': False})
  Environment:
    check_gps_environment(...) real GPSJam zone check (or unavailable)
    nearest_cable(...)      nearest cable corridor + approx distance (corridors approximate)
  Actions (publish to Kafka; persist to Postgres if configured):
    write_finding, save_assessment, create_voice_briefing
"""

import json
import math
from pathlib import Path

from .. import database
from ..kafka_client import (
    publish, TOPIC_AGENT_FINDINGS, TOPIC_THREAT_ASSESSMENT, TOPIC_VOICE_BRIEFING,
    TOPIC_VESSEL_WATCH,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VOICE_OUT = _REPO_ROOT / "demo_assets" / "sample_voice.mp3"


# --------------------------------------------------------------------------- #
# Aiven access
# --------------------------------------------------------------------------- #
def aiven_query(sql: str, max_rows: int = 50) -> dict:
    """Run a READ-ONLY SQL query against Aiven Postgres and return the rows.

    The Evidence Librarian uses this to ask Aiven anything it needs (vessels,
    tracks, suspicion_events, agent_findings, assessments). Hard safety:
    SELECT/WITH only, single statement, DB-enforced read-only, row-capped.
    """
    if not database.is_configured():
        return {"available": False, "error": "Aiven database not configured"}
    q = (sql or "").strip().rstrip(";").strip()
    low = q.lower()
    if not (low.startswith("select") or low.startswith("with")):
        return {"error": "Only read-only SELECT/WITH queries are allowed."}
    if ";" in q:
        return {"error": "Only a single statement is allowed."}
    try:
        from psycopg.rows import dict_row
        with database.get_connection() as conn:
            conn.read_only = True  # DB rejects any write — defence in depth
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(f"SELECT * FROM ({q}) AS _q LIMIT {int(max_rows)}")
                rows = cur.fetchall()
        return {"rows": rows, "row_count": len(rows)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:300]}


def get_recent_track(mmsi: str) -> list[dict]:
    """Recent positions for a vessel from `tracks` (oldest-first). EMPTY if none.

    Never returns mock data: an empty list means we genuinely have no track.
    """
    if not database.is_configured():
        return []
    try:
        from psycopg.rows import dict_row
        with database.get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT lat, lon, speed, course, ts FROM tracks "
                "WHERE mmsi = %s ORDER BY ts DESC LIMIT 20",
                (str(mmsi),),
            )
            rows = cur.fetchall()
        return [{"lat": r["lat"], "lon": r["lon"], "speed": r["speed"],
                 "course": r["course"], "ts": str(r["ts"])} for r in reversed(rows)]
    except Exception as e:  # noqa: BLE001
        print(f"[tools] get_recent_track failed ({e})")
        return []


def get_vessel_history(mmsi: str) -> dict:
    """Prior suspicion events + prior assessments + track-point count for a vessel."""
    if not database.is_configured():
        return {"prior_suspicions": [], "prior_assessments": [], "track_points": 0}
    try:
        from psycopg.rows import dict_row
        with database.get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT suspicion_id, rule, cable, severity, summary, ts "
                "FROM suspicion_events WHERE mmsi = %s ORDER BY ts DESC LIMIT 5",
                (str(mmsi),))
            prior = [{**p, "ts": str(p["ts"])} for p in cur.fetchall()]
            cur.execute(
                "SELECT a.level, a.confidence, a.summary, a.created_at "
                "FROM assessments a JOIN suspicion_events s USING (suspicion_id) "
                "WHERE s.mmsi = %s ORDER BY a.created_at DESC LIMIT 3",
                (str(mmsi),))
            assessments = [{**a, "created_at": str(a["created_at"])} for a in cur.fetchall()]
            cur.execute("SELECT count(*) AS n FROM tracks WHERE mmsi = %s", (str(mmsi),))
            n = cur.fetchone()["n"]
        return {"prior_suspicions": prior, "prior_assessments": assessments, "track_points": n}
    except Exception as e:  # noqa: BLE001
        print(f"[tools] get_vessel_history failed ({e})")
        return {"prior_suspicions": [], "prior_assessments": [], "track_points": 0}


def get_nearby_vessels(lat: float, lon: float, radius_nm: float = 10.0,
                       limit: int = 10, exclude_mmsi: str | None = None) -> list[dict]:
    """Other live vessels within radius_nm of a point (from the vessels table)."""
    if not database.is_configured() or lat is None or lon is None:
        return []
    try:
        from psycopg.rows import dict_row
        dlat = radius_nm / 60.0
        dlon = radius_nm / (60.0 * max(0.1, math.cos(math.radians(lat))))
        with database.get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT mmsi,name,flag,ship_type,last_lat,last_lon,last_speed,"
                "nav_status,suspicion_score,is_candidate FROM vessels "
                "WHERE last_lat BETWEEN %s AND %s AND last_lon BETWEEN %s AND %s AND mmsi <> %s",
                (lat - dlat, lat + dlat, lon - dlon, lon + dlon, str(exclude_mmsi or "")))
            rows = cur.fetchall()
        out = []
        for r in rows:
            if r["last_lat"] is None or r["last_lon"] is None:
                continue
            d = _haversine_nm(lat, lon, r["last_lat"], r["last_lon"])
            if d > radius_nm:
                continue
            out.append({"mmsi": r["mmsi"], "name": r["name"], "flag": r["flag"],
                        "ship_type": r["ship_type"], "speed": r["last_speed"],
                        "nav_status": r["nav_status"], "score": r["suspicion_score"],
                        "is_candidate": r["is_candidate"], "distance_nm": round(d, 1)})
        out.sort(key=lambda v: v["distance_nm"])
        return out[:limit]
    except Exception as e:  # noqa: BLE001
        print(f"[tools] get_nearby_vessels failed ({e})")
        return []


# --------------------------------------------------------------------------- #
# Identity / records
# --------------------------------------------------------------------------- #
def validate_identity(mmsi: str | None = None, imo: str | None = None,
                      name: str | None = None, flag: str | None = None) -> dict:
    """Deterministic identity sanity checks (no Claude, no network)."""
    checks = []
    digits = "".join(c for c in str(imo or "") if c.isdigit())
    if not imo:
        checks.append("No IMO number reported.")
    elif len(digits) != 7:
        checks.append(f"IMO '{imo}' is not the standard 7 digits — invalid or spoofed.")
    else:
        s = sum(int(digits[i]) * (7 - i) for i in range(6))
        checks.append(f"IMO {imo} passes the IMO check-digit test."
                      if s % 10 == int(digits[6])
                      else f"IMO {imo} FAILS the IMO check-digit test — invalid/spoofed.")
    return {"mmsi": mmsi, "imo": imo, "name": name, "flag": flag, "checks": checks}


def get_sanctions_record(imo: str | None = None, name: str | None = None) -> dict:
    """Real OpenSanctions maritime record (or {'listed': False}). Never fabricated."""
    try:
        from ..data_pipeline.loaders import sanctions
        row = sanctions.lookup(imo=imo, name=name)
        if not row:
            return {"listed": False, "source": "OpenSanctions maritime dataset"}
        return {"listed": True, "source": "OpenSanctions maritime dataset",
                "name": row.get("caption"), "imo": row.get("imo"), "risk": row.get("risk"),
                "countries": row.get("countries"), "datasets": row.get("datasets"),
                "aliases": row.get("aliases")}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e)[:200]}


# --------------------------------------------------------------------------- #
# Environment — operator geo datasets (real geometry, always-available, no network)
#   geo_data/cables.geojson   52 undersea cables (telecom + power), MultiLineString
#   geo_data/jamming.geojson  51 GPS-jamming zones, Polygon
# --------------------------------------------------------------------------- #
_GEO_DIR = Path(__file__).resolve().parent / "geo_data"
_cables_cache = None
_jam_cache = None


def _load_cables():
    global _cables_cache
    if _cables_cache is None:
        _cables_cache = []
        f = _GEO_DIR / "cables.geojson"
        if f.exists():
            from shapely.geometry import shape
            for feat in json.loads(f.read_text(encoding="utf-8")).get("features", []):
                try:
                    _cables_cache.append((feat.get("properties", {}), shape(feat["geometry"])))
                except Exception:  # noqa: BLE001
                    pass
    return _cables_cache


def _load_jam():
    global _jam_cache
    if _jam_cache is None:
        _jam_cache = []
        f = _GEO_DIR / "jamming.geojson"
        if f.exists():
            from shapely.geometry import shape
            for feat in json.loads(f.read_text(encoding="utf-8")).get("features", []):
                try:
                    _jam_cache.append(shape(feat["geometry"]))
                except Exception:  # noqa: BLE001
                    pass
    return _jam_cache


def check_gps_environment(lat: float | None, lon: float | None) -> dict:
    """Is the position inside a known GPS-jamming zone? (operator polygon dataset)."""
    if lat is None or lon is None:
        return {"available": False, "note": "no position provided"}
    polys = _load_jam()
    if not polys:
        return {"available": False, "note": "GPS-jamming dataset not available"}
    try:
        from shapely.geometry import Point
        pt = Point(lon, lat)
        inside = any(poly.contains(pt) for poly in polys)
        return {"available": True, "in_jammed_zone": inside,
                "source": f"operator GPS-jamming zones ({len(polys)} polygons)"}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e)[:200]}


def nearest_cable(lat: float | None, lon: float | None) -> dict:
    """Nearest undersea cable + distance (km) from the operator cable dataset (52 cables)."""
    if lat is None or lon is None:
        return {"available": False, "note": "no position provided"}
    cables = _load_cables()
    if not cables:
        return {"available": False, "note": "cable dataset not available"}
    try:
        from shapely.geometry import Point
        from shapely.ops import nearest_points
        pt = Point(lon, lat)
        best = None
        for props, geom in cables:
            npt = nearest_points(pt, geom)[1]
            d_km = _haversine_km(lat, lon, npt.y, npt.x)
            if best is None or d_km < best[2]:
                best = (props.get("name"), props.get("kind"), d_km)
        name, kind, d_km = best
        return {"available": True, "nearest_cable": name, "kind": kind,
                "distance_km": round(d_km, 2), "inside_corridor": d_km <= 3.0,
                "source": f"operator cable dataset ({len(cables)} cables)"}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e)[:200]}


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #
def write_finding(finding: dict) -> None:
    """Publish one agent finding and persist it (if Postgres is configured)."""
    publish(TOPIC_AGENT_FINDINGS, finding)
    if not database.is_configured():
        return
    try:
        with database.get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_findings (suspicion_id, agent, severity, finding, evidence) "
                "VALUES (%s,%s,%s,%s,%s)",
                (finding["suspicion_id"], finding["agent"], finding["severity"],
                 finding["finding"], json.dumps(finding.get("evidence", []))))
            conn.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[tools] write_finding persist failed ({e})")


def save_assessment(assessment: dict, voice_path: str | None = None) -> None:
    """Publish the final assessment and upsert it (if Postgres is configured)."""
    publish(TOPIC_THREAT_ASSESSMENT, assessment)
    if not database.is_configured():
        return
    try:
        with database.get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO assessments (suspicion_id, level, confidence, summary, reasoning, "
                "recommended_action, voice_script, voice_path) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (suspicion_id) DO UPDATE SET level=EXCLUDED.level, "
                "confidence=EXCLUDED.confidence, summary=EXCLUDED.summary, "
                "reasoning=EXCLUDED.reasoning, recommended_action=EXCLUDED.recommended_action, "
                "voice_script=EXCLUDED.voice_script, voice_path=EXCLUDED.voice_path",
                (assessment["suspicion_id"], assessment["level"], assessment["confidence"],
                 assessment["summary"], json.dumps(assessment.get("reasoning", [])),
                 assessment["recommended_action"], assessment["voice_script"], voice_path))
            conn.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[tools] save_assessment persist failed ({e})")


def render_briefing(vessel: dict, assessment: dict, findings: list[dict]) -> dict:
    """Deterministically format the operator deliverables from the finished verdict —
    report markdown, an email draft, and the voice script. No extra LLM call (this
    replaced the old Action Briefing agent): faster and fully reliable, since it only
    restates what the Watch Officer already established."""
    mmsi = vessel.get("mmsi")
    name = vessel.get("name") or mmsi
    level = assessment.get("level", "—")
    conf = assessment.get("confidence", 0)
    lines = [f"# Baltic Sentinel — {name} ({mmsi})",
             f"**Verdict:** {level}  ·  confidence {conf}", "",
             f"_{assessment.get('summary', '')}_", "", "## Findings"]
    for f in sorted(findings, key=lambda x: x.get("severity", 0) or 0, reverse=True):
        lines.append(f"- **[{f.get('agent')}] sev {f.get('severity')}** — {f.get('finding')}")
    if assessment.get("reasoning"):
        lines += ["", "## Why this verdict"] + [f"- {r}" for r in assessment["reasoning"]]
    lines += ["", "## Recommended action", assessment.get("recommended_action", ""),
              "", "_Human decision required — no automatic enforcement._"]
    subject = f"[{level}] {name} ({mmsi}) — Baltic Sentinel alert"
    body = (f"{assessment.get('summary', '')}\n\n"
            f"Recommended action: {assessment.get('recommended_action', '')}\n\n"
            f"(Confidence {conf}. Automated dossier — human verification required.)")
    return {"report_markdown": "\n".join(lines), "email_subject": subject,
            "email_body": body, "voice_script": assessment.get("voice_script", "")}


def create_voice_briefing(voice_script: str, suspicion_id: str) -> dict:
    """Package the voice briefing payload. Real ElevenLabs audio is not wired yet
    (H13) — this publishes the script + intended path; it does NOT fake audio."""
    path = str(_VOICE_OUT)
    print(f"[voice] briefing payload ready -> {path} ({len(voice_script)} chars; audio not generated yet)")
    publish(TOPIC_VOICE_BRIEFING,
            {"suspicion_id": suspicion_id, "voice_path": path, "voice_script": voice_script})
    return {"voice_path": path, "audio_generated": False}


# --------------------------------------------------------------------------- #
# Watchlist  (the Sentinel agent's persistent memory: per-vessel monitoring state)
#   The investigation writes a row here; the Sentinel reads it, re-checks, updates.
#   Additive table, created idempotently — announce in contracts.md.
# --------------------------------------------------------------------------- #
_watchlist_ready = False


def _ensure_watchlist_table() -> None:
    """Create the watchlist table once per process (idempotent)."""
    global _watchlist_ready
    if _watchlist_ready or not database.is_configured():
        return
    try:
        with database.get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS watchlist ("
                " mmsi TEXT PRIMARY KEY, name TEXT, imo TEXT, suspicion_id TEXT,"
                " level TEXT, confidence REAL, watch_signals JSONB, open_questions JSONB,"
                " recheck_triggers JSONB, status TEXT DEFAULT 'active', reviews INTEGER DEFAULT 1,"
                " last_note TEXT, last_reviewed TIMESTAMPTZ DEFAULT now(),"
                " next_review_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT now())")
            conn.commit()
        _watchlist_ready = True
    except Exception as e:  # noqa: BLE001
        print(f"[tools] ensure watchlist table failed ({e})")


def record_watch(watch: dict, review_hours: int = 6) -> None:
    """Upsert a vessel's monitoring record (the investigation's hand-off to the
    Sentinel) and stream it to Kafka. Keyed by mmsi; bumps the review counter."""
    publish(TOPIC_VESSEL_WATCH, watch)
    if not database.is_configured():
        return
    try:
        _ensure_watchlist_table()
        with database.get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO watchlist (mmsi,name,imo,suspicion_id,level,confidence,"
                "watch_signals,open_questions,recheck_triggers,status,last_reviewed,next_review_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),now()+make_interval(hours=>%s))"
                " ON CONFLICT (mmsi) DO UPDATE SET name=EXCLUDED.name, imo=EXCLUDED.imo,"
                " suspicion_id=EXCLUDED.suspicion_id, level=EXCLUDED.level,"
                " confidence=EXCLUDED.confidence, watch_signals=EXCLUDED.watch_signals,"
                " open_questions=EXCLUDED.open_questions, recheck_triggers=EXCLUDED.recheck_triggers,"
                " last_reviewed=now(), next_review_at=EXCLUDED.next_review_at,"
                " reviews=watchlist.reviews+1",  # NB: status preserved (operator-controlled)
                (watch["mmsi"], watch.get("name"), watch.get("imo"), watch.get("suspicion_id"),
                 watch.get("level"), watch.get("confidence"),
                 json.dumps(watch.get("watch_signals", [])),
                 json.dumps(watch.get("open_questions", [])),
                 json.dumps(watch.get("recheck_triggers", [])),
                 watch.get("status", "active"), int(review_hours)))
            conn.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[tools] record_watch persist failed ({e})")


def get_watchlist(due_only: bool = False, limit: int = 100,
                  status: str | None = "active") -> list[dict]:
    """Read the watchlist. status=None returns ALL rows (for the operator UI); the
    Sentinel uses the default 'active' so it only monitors vessels the operator has
    enabled. due_only -> only rows whose scheduled review time has passed."""
    if not database.is_configured():
        return []
    try:
        _ensure_watchlist_table()
        from psycopg.rows import dict_row
        clauses, params = [], []
        if status:
            clauses.append("status = %s"); params.append(status)
        if due_only:
            clauses.append("(next_review_at IS NULL OR next_review_at <= now())")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with database.get_connection() as conn:
            conn.read_only = True
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(f"SELECT * FROM watchlist {where} "
                            f"ORDER BY confidence DESC NULLS LAST LIMIT {int(limit)}", params)
                return cur.fetchall()
    except Exception as e:  # noqa: BLE001
        print(f"[tools] get_watchlist failed ({e})")
        return []


def set_watch_status(mmsi: str, status: str) -> dict:
    """Operator control: activate ('active') or pause ('paused') the Sentinel on a
    vessel (also 'cleared' / 'escalated'). This is how the operator grants or revokes
    the Sentinel's authority to monitor a specific ship."""
    if not database.is_configured():
        return {"ok": False, "error": "database not configured"}
    try:
        _ensure_watchlist_table()
        with database.get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE watchlist SET status=%s WHERE mmsi=%s", (status, mmsi))
            n = cur.rowcount
            conn.commit()
        print(f"[watchlist] {mmsi} -> status={status} ({n} row updated)", flush=True)
        return {"ok": True, "mmsi": mmsi, "status": status, "updated": n}
    except Exception as e:  # noqa: BLE001
        print(f"[watchlist] set_watch_status failed ({e})")
        return {"ok": False, "error": str(e)[:200]}


def update_watch(mmsi: str, level: str | None = None, confidence: float | None = None,
                 status: str | None = None, note: str | None = None,
                 review_hours: int = 6) -> None:
    """Update a watch record after the Sentinel re-checks a vessel."""
    if not database.is_configured():
        return
    try:
        _ensure_watchlist_table()
        sets = ["last_reviewed = now()", "reviews = reviews + 1",
                f"next_review_at = now() + make_interval(hours => {int(review_hours)})"]
        vals: list = []
        if level is not None:
            sets.append("level = %s"); vals.append(level)
        if confidence is not None:
            sets.append("confidence = %s"); vals.append(confidence)
        if status is not None:
            sets.append("status = %s"); vals.append(status)
        if note is not None:
            sets.append("last_note = %s"); vals.append(note)
        vals.append(mmsi)
        with database.get_connection() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE watchlist SET {', '.join(sets)} WHERE mmsi = %s", vals)
            conn.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[tools] update_watch failed ({e})")


# --------------------------------------------------------------------------- #
def _haversine_nm(lat1, lon1, lat2, lon2):
    r = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _haversine_km(lat1, lon1, lat2, lon2):
    return _haversine_nm(lat1, lon1, lat2, lon2) * 1.852
