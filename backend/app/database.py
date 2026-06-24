"""Aiven Postgres helpers (shared).

H0 stub. Real connection + tables happen in H1-H3 once Aiven Postgres is
connected. Keep the public function names stable so both owners can import them.
"""

from app.config import settings


def is_configured() -> bool:
    return bool(settings.aiven_postgres_url)


def get_connection():
    """Return a Postgres connection.

    TODO (H1-H3): open a psycopg connection to settings.aiven_postgres_url.
    """
    if not is_configured():
        raise RuntimeError("AIVEN_POSTGRES_URL not set yet (H1-H3).")
    raise NotImplementedError("Real Postgres connection not wired yet (H1-H3).")


def init_tables() -> None:
    """Create tables for tracks, suspicions, findings, assessments.

    TODO (H1-H3): run CREATE TABLE IF NOT EXISTS statements.
    """
    raise NotImplementedError("Table init not wired yet (H1-H3).")
