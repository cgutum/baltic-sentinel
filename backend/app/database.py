"""Aiven Postgres helpers (shared).

Wired in H1-H3 to the real Aiven Postgres service (psycopg 3).
Public names kept stable so both owners can import them:
  - is_configured()
  - get_connection()    -> a live psycopg connection (use as a context manager)
  - init_tables()       -> CREATE TABLE IF NOT EXISTS for all tables

Tables:
  vessels           (Person A)  latest position + suspicion score per vessel  [data foundation]
  tracks            (Person A)  ship position history
  suspicion_events  (Person A)  operator-launched investigations
  agent_findings    (Person B)  per-agent outputs
  assessments       (Person B)  final verdicts + voice
"""
import json

from app.config import settings

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS vessels (
        mmsi text PRIMARY KEY, imo text, name text, ship_type text, flag text,
        last_lat double precision, last_lon double precision,
        last_speed double precision, last_course double precision, nav_status text,
        last_seen timestamptz,
        suspicion_score double precision DEFAULT 0,
        suspicion_reasons jsonb DEFAULT '[]',
        is_candidate boolean DEFAULT false,
        updated_at timestamptz DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS tracks (
        id serial PRIMARY KEY, mmsi text, imo text, name text,
        lat double precision, lon double precision,
        speed double precision, course double precision,
        ts timestamptz, source text)""",
    "CREATE INDEX IF NOT EXISTS idx_tracks_mmsi_ts ON tracks (mmsi, ts DESC)",
    """CREATE TABLE IF NOT EXISTS suspicion_events (
        suspicion_id text PRIMARY KEY, mmsi text, imo text, name text,
        rule text, cable text, severity double precision,
        summary text, ts timestamptz)""",
    """CREATE TABLE IF NOT EXISTS agent_findings (
        id serial PRIMARY KEY, suspicion_id text, agent text,
        severity double precision, finding text, evidence jsonb)""",
    """CREATE TABLE IF NOT EXISTS assessments (
        suspicion_id text PRIMARY KEY, level text, confidence double precision,
        summary text, reasoning jsonb, recommended_action text,
        voice_script text, voice_path text,
        created_at timestamptz DEFAULT now())""",
]

# Columns returned by the vessel read helpers (also the keys scoring.score_vessel reads).
_VESSEL_COLS = ("mmsi", "imo", "name", "ship_type", "flag", "last_lat", "last_lon",
                "last_speed", "last_course", "nav_status", "last_seen",
                "suspicion_score", "suspicion_reasons", "is_candidate")


def is_configured() -> bool:
    return bool(settings.aiven_postgres_url)


def get_connection():
    """Return a live psycopg connection. Use as a context manager."""
    if not is_configured():
        raise RuntimeError("AIVEN_POSTGRES_URL not set (check .env).")
    import psycopg
    return psycopg.connect(settings.aiven_postgres_url)


def init_tables() -> None:
    """Create all tables. Idempotent — safe to call on every startup."""
    if not is_configured():
        print("[db:stub] AIVEN_POSTGRES_URL not set; skipping init_tables()")
        return
    with get_connection() as conn, conn.cursor() as cur:
        for stmt in _SCHEMA:
            cur.execute(stmt)
    print("[db] tables ready")


# --- vessels (data foundation, Person A) ----------------------------------

def upsert_vessel(rec: dict) -> None:
    """Insert or update one vessel's latest state + score."""
    if not is_configured():
        return
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO vessels
               (mmsi,imo,name,ship_type,flag,last_lat,last_lon,last_speed,last_course,
                nav_status,last_seen,suspicion_score,suspicion_reasons,is_candidate,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,now())
               ON CONFLICT (mmsi) DO UPDATE SET
                 imo=EXCLUDED.imo, name=EXCLUDED.name, ship_type=EXCLUDED.ship_type,
                 flag=EXCLUDED.flag, last_lat=EXCLUDED.last_lat, last_lon=EXCLUDED.last_lon,
                 last_speed=EXCLUDED.last_speed, last_course=EXCLUDED.last_course,
                 nav_status=EXCLUDED.nav_status, last_seen=EXCLUDED.last_seen,
                 suspicion_score=EXCLUDED.suspicion_score,
                 suspicion_reasons=EXCLUDED.suspicion_reasons,
                 is_candidate=EXCLUDED.is_candidate, updated_at=now()""",
            (rec["mmsi"], rec.get("imo"), rec.get("name"), rec.get("ship_type"),
             rec.get("flag"), rec.get("last_lat"), rec.get("last_lon"),
             rec.get("last_speed"), rec.get("last_course"), rec.get("nav_status"),
             rec.get("last_seen"), rec.get("suspicion_score", 0),
             json.dumps(rec.get("suspicion_reasons", [])), rec.get("is_candidate", False)),
        )
        conn.commit()


def _read_vessels(where: str = "", params: tuple = (), limit: int = 500) -> list[dict]:
    if not is_configured():
        return []
    from psycopg.rows import dict_row
    cols = ",".join(_VESSEL_COLS)
    sql = f"SELECT {cols} FROM vessels {where} ORDER BY suspicion_score DESC, updated_at DESC LIMIT %s"
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params + (limit,))
        return cur.fetchall()


def get_vessels(limit: int = 500) -> list[dict]:
    """All known vessels (map source). Includes score so the UI can color them."""
    return _read_vessels(limit=limit)


def get_candidates(limit: int = 100) -> list[dict]:
    """Suspicious vessels only (score >= threshold)."""
    return _read_vessels("WHERE is_candidate = true", limit=limit)


def get_vessel(mmsi: str) -> dict | None:
    rows = _read_vessels("WHERE mmsi = %s", (str(mmsi),), limit=1)
    return rows[0] if rows else None
