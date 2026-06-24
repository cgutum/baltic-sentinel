"""Aiven Postgres helpers (shared).

Wired in H1-H3 to the real Aiven Postgres service (psycopg 3).
Public names kept stable so both owners can import them:
  - is_configured()
  - get_connection()    -> a live psycopg connection (use as a context manager)
  - init_tables()       -> CREATE TABLE IF NOT EXISTS for all four tables

Tables (columns match contracts.md):
  tracks            (Person A)  ship positions
  suspicion_events  (Person A)  tripwire hits
  agent_findings    (Person B)  per-agent outputs
  assessments       (Person B)  final verdicts + voice
"""

from app.config import settings

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS tracks (
        id serial PRIMARY KEY, mmsi text, imo text, name text,
        lat double precision, lon double precision,
        speed double precision, course double precision,
        ts timestamptz, source text)""",
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


def is_configured() -> bool:
    return bool(settings.aiven_postgres_url)


def get_connection():
    """Return a live psycopg connection. Use as a context manager:

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(...)
    """
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
