"""Agent tools — Person B ("Option A" capability layer).

These are the plain functions the orchestrator calls. Later (H5+) the same
functions become the Claude Managed Agent's custom tools, executed by a local
orchestrator — so keeping signatures stable here avoids touching call sites.

Two kinds:
  - READ tools  -> in DEMO_MODE return canned data; a `# TODO live` branch is
                   where the real Postgres/web lookups go later.
  - ACTION tools -> publish to Kafka and (if Postgres is configured) persist.
                    Guarded so they work fully offline (print-only) AND for free
                    when Aiven is connected.

Mirrors Person A's conventions: reuse kafka_client.publish, guard DB writes on
database.is_configured(), `[tag]` print logging.
"""

import json
from pathlib import Path

from .. import database
from ..kafka_client import (
    publish,
    TOPIC_AGENT_FINDINGS,
    TOPIC_THREAT_ASSESSMENT,
    TOPIC_VOICE_BRIEFING,
)
from . import fallback_outputs

# Repo root: <repo>/backend/app/agent_workflow/tools.py -> parents[3] == <repo>
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SAMPLE_VOICE = _REPO_ROOT / "demo_assets" / "sample_voice.mp3"


# --------------------------------------------------------------------------- #
# READ tools (DEMO: canned; TODO live at H5+)
# --------------------------------------------------------------------------- #
def get_suspicion_event(suspicion_id: str | None = None) -> dict:
    """Return the suspicion to investigate. DEMO: the canned Eagle S event."""
    # TODO live (H5+): SELECT ... FROM suspicion_events WHERE suspicion_id=...
    return fallback_outputs.SAMPLE_SUSPICION


def get_recent_track(mmsi: str) -> list[dict]:
    """Recent positions for a vessel from the `tracks` table (oldest-first).

    When Postgres is configured we return the REAL track — which may be **empty**
    if we haven't recorded positions for this vessel yet. We deliberately do NOT
    fall back to mock data here, so the agents can never hallucinate movement
    from canned positions. Only with no DB at all (pure local CLI demo) do we
    return a canned slow-drift track.
    """
    if database.is_configured():
        try:
            from psycopg.rows import dict_row

            with database.get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT lat, lon, speed, course, ts FROM tracks "
                    "WHERE mmsi = %s ORDER BY ts DESC LIMIT 12",
                    (str(mmsi),),
                )
                rows = cur.fetchall()
            return [
                {"lat": r["lat"], "lon": r["lon"], "speed": r["speed"],
                 "course": r["course"], "ts": str(r["ts"])}
                for r in reversed(rows)
            ]  # may be [] — that's honest, not mock
        except Exception as e:  # noqa: BLE001
            print(f"[tools] get_recent_track DB read failed ({e}) — returning empty")
            return []
    # No DB (pure local demo / CLI only): canned slow-drift track.
    return [
        {"lat": 59.66, "lon": 24.90, "speed": 3.4, "course": 18},
        {"lat": 59.69, "lon": 24.91, "speed": 2.2, "course": 25},
        {"lat": 59.71, "lon": 24.92, "speed": 1.6, "course": 30},
        {"lat": 59.73, "lon": 24.93, "speed": 1.9, "course": 35},
    ]


# --------------------------------------------------------------------------- #
# Phase 1 — real tools that fetch NEW information (not in the suspicion packet)
# --------------------------------------------------------------------------- #
def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    r = 3440.065  # nautical miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def get_nearby_vessels(lat: float, lon: float, radius_nm: float = 10.0,
                       limit: int = 8, exclude_mmsi: str | None = None) -> list[dict]:
    """Other live vessels within radius_nm of a point (from the vessels table).

    Powers spatial/pattern reasoning: a second loitering vessel, a cluster near
    the cable, an escort. Empty when no DB or nothing nearby.
    """
    if not database.is_configured() or lat is None or lon is None:
        return []
    try:
        import math
        from psycopg.rows import dict_row

        dlat = radius_nm / 60.0
        dlon = radius_nm / (60.0 * max(0.1, math.cos(math.radians(lat))))
        with database.get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT mmsi,name,flag,ship_type,last_lat,last_lon,last_speed,"
                "nav_status,suspicion_score,is_candidate FROM vessels "
                "WHERE last_lat BETWEEN %s AND %s AND last_lon BETWEEN %s AND %s "
                "AND mmsi <> %s",
                (lat - dlat, lat + dlat, lon - dlon, lon + dlon, str(exclude_mmsi or "")),
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            if r["last_lat"] is None or r["last_lon"] is None:
                continue
            d = _haversine_nm(lat, lon, r["last_lat"], r["last_lon"])
            if d > radius_nm:
                continue
            out.append({
                "mmsi": r["mmsi"], "name": r["name"], "flag": r["flag"],
                "ship_type": r["ship_type"], "speed": r["last_speed"],
                "nav_status": r["nav_status"], "score": r["suspicion_score"],
                "is_candidate": r["is_candidate"], "distance_nm": round(d, 1),
            })
        out.sort(key=lambda v: v["distance_nm"])
        return out[:limit]
    except Exception as e:  # noqa: BLE001
        print(f"[tools] get_nearby_vessels failed ({e})")
        return []


def get_vessel_history(mmsi: str) -> dict:
    """Prior suspicion events for this vessel + how many track points we hold.

    Powers temporal reasoning: repeat offender? prior incidents near cables?
    """
    if not database.is_configured():
        return {"prior_suspicions": [], "track_points": 0}
    try:
        from psycopg.rows import dict_row

        with database.get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT suspicion_id, rule, cable, severity, summary, ts "
                "FROM suspicion_events WHERE mmsi = %s ORDER BY ts DESC LIMIT 5",
                (str(mmsi),),
            )
            prior = [{**p, "ts": str(p["ts"])} for p in cur.fetchall()]
            cur.execute("SELECT count(*) AS n FROM tracks WHERE mmsi = %s", (str(mmsi),))
            n = cur.fetchone()["n"]
        return {"prior_suspicions": prior, "track_points": n}
    except Exception as e:  # noqa: BLE001
        print(f"[tools] get_vessel_history failed ({e})")
        return {"prior_suspicions": [], "track_points": 0}


def get_sanctions_record(imo: str | None = None, name: str | None = None) -> dict:
    """Real OpenSanctions maritime record (or {'listed': False}) via Person A's loader."""
    try:
        from ..data_pipeline.loaders import sanctions

        row = sanctions.lookup(imo=imo, name=name)
        if not row:
            return {"listed": False}
        return {
            "listed": True,
            "name": row.get("caption"),
            "imo": row.get("imo"),
            "risk": row.get("risk"),
            "countries": row.get("countries"),
            "datasets": row.get("datasets"),
            "aliases": row.get("aliases"),
        }
    except Exception as e:  # noqa: BLE001
        print(f"[tools] get_sanctions_record failed ({e})")
        return {"listed": None, "error": str(e)}


def validate_identity(mmsi: str | None = None, imo: str | None = None,
                      name: str | None = None, flag: str | None = None) -> dict:
    """Deterministic identity sanity checks (no Claude). Catches spoofed/invalid IDs."""
    checks = []
    digits = "".join(c for c in str(imo or "") if c.isdigit())
    if not imo:
        checks.append("No IMO number reported.")
    elif len(digits) != 7:
        checks.append(f"IMO '{imo}' is not the standard 7 digits — likely invalid or spoofed.")
    else:
        s = sum(int(digits[i]) * (7 - i) for i in range(6))
        if s % 10 == int(digits[6]):
            checks.append(f"IMO {imo} passes the IMO check-digit test.")
        else:
            checks.append(f"IMO {imo} FAILS the IMO check-digit test — likely invalid/spoofed.")
    return {"mmsi": mmsi, "imo": imo, "name": name, "flag": flag, "checks": checks}


def get_vessel_identity(mmsi: str, imo: str | None = None) -> dict:
    """Return vessel identity. DEMO: canned Eagle S identity."""
    # TODO live (H5+): identity lookup / AIS static data
    return {
        "mmsi": mmsi,
        "imo": imo,
        "name": "Eagle S",
        "type": "Oil/chemical tanker",
        "flag": "Cook Islands",
    }


def lookup_sanctions(name: str, imo: str | None = None) -> dict:
    """Return sanctions/watchlist status. DEMO: canned listed result."""
    # TODO live (H5+): OpenSanctions API / web search
    return {
        "listed": True,
        "source": "OpenSanctions (demo)",
        "note": "Linked to the sanctioned Russian shadow fleet.",
    }


def check_gps_environment(lat: float, lon: float) -> dict:
    """Return GNSS-trust context for a location. DEMO: canned elevated risk."""
    # TODO live (H5+): space-weather / jamming feeds
    return {
        "gnss_interference": "elevated",
        "confidence": 0.6,
        "note": "Independent position verification recommended.",
    }


def get_cable_context(cable: str) -> dict:
    """Return context about a cable corridor. DEMO: static Estlink 2 facts."""
    # TODO live (H5+): cable registry
    return {
        "cable": cable,
        "kind": "HVDC power interconnector",
        "operator": "Fingrid / Elering",
        "note": "Critical cross-border infrastructure.",
    }


# --------------------------------------------------------------------------- #
# ACTION tools (publish to Kafka; persist if Postgres is configured)
# --------------------------------------------------------------------------- #
def write_finding(finding: dict) -> None:
    """Publish one agent finding and persist it (if Postgres is configured)."""
    publish(TOPIC_AGENT_FINDINGS, finding)
    if not database.is_configured():
        return
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_findings "
                "(suspicion_id, agent, severity, finding, evidence) "
                "VALUES (%s,%s,%s,%s,%s)",
                (
                    finding["suspicion_id"],
                    finding["agent"],
                    finding["severity"],
                    finding["finding"],
                    json.dumps(finding.get("evidence", [])),
                ),
            )
        conn.commit()


def save_assessment(assessment: dict, voice_path: str | None = None) -> None:
    """Publish the final assessment and upsert it (if Postgres is configured)."""
    publish(TOPIC_THREAT_ASSESSMENT, assessment)
    if not database.is_configured():
        return
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO assessments "
                "(suspicion_id, level, confidence, summary, reasoning, "
                "recommended_action, voice_script, voice_path) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (suspicion_id) DO UPDATE SET "
                "level=EXCLUDED.level, confidence=EXCLUDED.confidence, "
                "summary=EXCLUDED.summary, reasoning=EXCLUDED.reasoning, "
                "recommended_action=EXCLUDED.recommended_action, "
                "voice_script=EXCLUDED.voice_script, voice_path=EXCLUDED.voice_path",
                (
                    assessment["suspicion_id"],
                    assessment["level"],
                    assessment["confidence"],
                    assessment["summary"],
                    json.dumps(assessment.get("reasoning", [])),
                    assessment["recommended_action"],
                    assessment["voice_script"],
                    voice_path,
                ),
            )
        conn.commit()


def create_voice_briefing(voice_script: str, suspicion_id: str) -> dict:
    """Create the spoken briefing. DEMO: no ElevenLabs — point at the fallback mp3.

    Signature locked at (voice_script, suspicion_id) now: the real ElevenLabs
    impl (H13, in voice.py) needs suspicion_id for the voice.briefing message
    and the assessments.voice_path link, so the orchestrator call site won't change.
    Never fails when the mp3 is missing — the done-when is a confirmation, not a file.
    """
    path = str(_SAMPLE_VOICE)
    exists = _SAMPLE_VOICE.exists()
    print(f"[voice:stub] would create voice briefing -> {path} ({len(voice_script)} chars)")
    publish(
        TOPIC_VOICE_BRIEFING,
        {"suspicion_id": suspicion_id, "voice_path": path, "voice_script": voice_script},
    )
    return {"voice_path": path, "exists": exists}
