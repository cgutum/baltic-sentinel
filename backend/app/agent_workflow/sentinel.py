"""Sentinel — the autonomous monitoring agent (Person B).

Unlike the one-shot investigation *workflow*, the Sentinel is a genuinely autonomous,
stateful *agent*. Each cycle it:

  1. reads the watchlist (its persistent memory in Aiven Postgres),
  2. decides — on its own — which watched vessels changed enough to matter,
  3. checks the Aiven data pipeline's health via the Aiven MCP (so it can tell
     "calm" from "ingest is down"),
  4. re-investigates the ones that warrant it, escalates genuine high concern to a
     human, and records its decision back into memory.

The model drives the trajectory (which vessels, which tools, what action); the code
only supplies the tools and a small per-cycle budget so it can't run away.

Run as a worker:   python -m app.agent_workflow.sentinel
One cycle (debug): python -c "from app.agent_workflow import sentinel; sentinel.run_cycle()"
"""

import json
import time

from . import agent_base, orchestrator, tools
from .. import database
from ..config import settings

AGENT = "Sentinel"
CYCLE_SEC = 120                 # seconds between monitoring cycles
_REINVESTIGATE_BUDGET = 2       # max full re-investigations per cycle (cost guard)
_ESCALATE_BUDGET = 3            # max human escalations per cycle (alert-spam guard)

_SYSTEM = (
    "You are the Sentinel, the autonomous maritime-infrastructure monitoring agent for "
    "Baltic Sentinel. You are given the current watchlist: vessels that were already "
    "investigated, each with its verdict baseline and the specific signals to watch. Your "
    "job each cycle is to decide, per vessel, whether anything has MATERIALLY changed and "
    "what to do about it.\n\n"
    "Your tools:\n"
    "- check_changes(mmsi): new track points, new suspicion events, and the current score "
    "since that vessel was last reviewed.\n"
    "- aiven_query(sql): read-only SELECT/WITH over Aiven (vessels, tracks, suspicion_events, "
    "agent_findings, assessments, watchlist) to dig into what actually changed.\n"
    "- the Aiven MCP tools (aiven_*): check the data pipeline's health/freshness so you can "
    "tell 'calm — no real change' from 'no data because ingest is DOWN' — say which in your notes.\n"
    "- web_search: a quick open-source check (e.g. breaking news on a named vessel) — use sparingly.\n"
    "- reinvestigate(mmsi): run a fresh FULL investigation (expensive) — only when something "
    "materially changed.\n"
    "- escalate(mmsi, reason): alert a human — ONLY after a reinvestigate has confirmed a "
    "genuine, corroborated HIGH verdict. Never escalate on stale or unchanged data.\n"
    "- update_watch(mmsi, note): record your decision and reschedule the vessel.\n\n"
    "Guardrails: be conservative — most cycles should be mostly update_watch. Do NOT "
    "reinvestigate or escalate without a real, evidenced change. You have a limited budget of "
    "reinvestigations and escalations per cycle; spend them only where warranted. Base every "
    "decision on tool results, never assume, and never take destructive action.\n\n"
    "YOUR LONG-TERM MEMORY lives in Aiven and you manage it YOURSELF through the MCP Postgres "
    "tools (aiven_pg_write / aiven_pg_read). It is the table sentinel_memory(id serial primary "
    "key, ts timestamptz default now(), mmsi text, event_type text, headline text, cycle_note "
    "text). Each cycle: (a) ensure it exists — aiven_pg_write 'CREATE TABLE IF NOT EXISTS "
    "sentinel_memory (id serial primary key, ts timestamptz default now(), mmsi text, "
    "event_type text, headline text, cycle_note text)'; (b) optionally recall history — "
    "aiven_pg_read 'SELECT headline, ts FROM sentinel_memory WHERE mmsi=... ORDER BY ts DESC "
    "LIMIT 3'; (c) after deciding on a vessel, log ONE row — aiven_pg_write 'INSERT INTO "
    "sentinel_memory (mmsi, event_type, headline, cycle_note) VALUES (...)' where event_type is "
    "exactly 'monitor', 'reinvestigate' or 'escalate', headline is a punchy one-liner (e.g. "
    "'No material change — score stable at 30'), and cycle_note is 1-3 sentences of detail. "
    "Keep it a DELTA — what changed and what you decided — NOT a re-summary of the verdict (the "
    "Watch Officer owns the verdict). aiven_pg_write blocks DROP/TRUNCATE. The project / "
    "service_name / database are in the cycle message.\n\n"
    "When you have handled the vessels, call submit_cycle."
)

_TOOLS = [
    {"name": "check_changes",
     "description": "What changed for a vessel since its last review: new track points, "
                    "new suspicion events, current suspicion score and last position.",
     "input_schema": {"type": "object", "properties": {"mmsi": {"type": "string"}},
                      "required": ["mmsi"]}},
    {"name": "aiven_query",
     "description": "READ-ONLY SELECT/WITH over Aiven Postgres to dig into what changed "
                    "(writes are rejected — to change a watch record use update_watch). "
                    "Columns: tracks(mmsi,lat,lon,speed,course,ts,source); "
                    "vessels(mmsi,name,flag,last_lat,last_lon,last_speed,last_seen,"
                    "suspicion_score,is_candidate); suspicion_events(mmsi,imo,name,rule,"
                    "cable,severity,summary,ts); watchlist(mmsi,level,confidence,status,"
                    "reviews,last_reviewed,next_review_at).",
     "input_schema": {"type": "object", "properties": {
         "sql": {"type": "string"}, "max_rows": {"type": "integer"}}, "required": ["sql"]}},
    {"name": "reinvestigate",
     "description": "Run a fresh FULL investigation on a vessel (expensive — use only when "
                    "something materially changed). Returns the new verdict and updates the "
                    "vessel's watch record automatically.",
     "input_schema": {"type": "object", "properties": {"mmsi": {"type": "string"}},
                      "required": ["mmsi"]}},
    {"name": "escalate",
     "description": "Escalate a vessel to a human watch officer. Use ONLY for genuine, "
                    "corroborated high concern — never automatic enforcement.",
     "input_schema": {"type": "object", "properties": {
         "mmsi": {"type": "string"}, "reason": {"type": "string"},
         "level": {"type": "string"}}, "required": ["mmsi", "reason"]}},
    {"name": "update_watch",
     "description": "Record your decision for a vessel and reschedule its next review.",
     "input_schema": {"type": "object", "properties": {
         "mmsi": {"type": "string"},
         "status": {"type": "string", "enum": ["active", "cleared", "escalated"]},
         "note": {"type": "string"}}, "required": ["mmsi", "note"]}},
]

_SUBMIT = {
    "name": "submit_cycle",
    "description": "End the monitoring cycle with a summary of what you reviewed and did.",
    "input_schema": {"type": "object", "properties": {
        "reviewed": {"type": "integer"},
        "actions": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"}}, "required": ["summary"]},
}


# --- tool implementations (client-side; the MCP health tools run server-side) ----
def _check_changes(mmsi: str) -> dict:
    """Deltas for a vessel since its last watch review (read-only SQL)."""
    if not database.is_configured():
        return {"error": "database not configured"}
    try:
        from psycopg.rows import dict_row
        with database.get_connection() as conn:
            conn.read_only = True
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT last_reviewed FROM watchlist WHERE mmsi=%s", (mmsi,))
                row = cur.fetchone()
                since = row["last_reviewed"] if row else None
                cur.execute("SELECT count(*) AS n FROM tracks WHERE mmsi=%s "
                            "AND (%s IS NULL OR ts > %s)", (mmsi, since, since))
                new_tracks = cur.fetchone()["n"]
                cur.execute("SELECT count(*) AS n FROM suspicion_events WHERE mmsi=%s "
                            "AND (%s IS NULL OR ts > %s)", (mmsi, since, since))
                new_events = cur.fetchone()["n"]
                cur.execute("SELECT suspicion_score, last_seen, last_lat, last_lon, "
                            "nav_status, last_speed FROM vessels WHERE mmsi=%s", (mmsi,))
                v = cur.fetchone() or {}
        return {"mmsi": mmsi, "since": str(since), "new_track_points": new_tracks,
                "new_suspicion_events": new_events, "current_score": v.get("suspicion_score"),
                "last_seen": str(v.get("last_seen")), "last_speed": v.get("last_speed"),
                "nav_status": v.get("nav_status")}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


def _reinvestigate(mmsi: str) -> dict:
    """Run the full investigation workflow again (also re-records the watch record)."""
    if not database.is_configured():
        return {"error": "database not configured"}
    v = database.get_vessel(mmsi)
    if not v:
        return {"error": "unknown vessel — no live data"}
    from ..api.routes import _suspicion_from_vessel, cache_investigation  # reuse + refresh dossier
    res = orchestrator.run_once(_suspicion_from_vessel(mmsi, v))
    cache_investigation(mmsi, res, {"mmsi": mmsi, "name": v.get("name"),
                                    "flag": v.get("flag"), "score": v.get("suspicion_score")})
    a = res.get("assessment", {})
    return {"mmsi": mmsi, "level": a.get("level"), "confidence": a.get("confidence"),
            "summary": (a.get("summary") or "")[:300]}


def _escalate(mmsi: str, reason: str = "", level: str = "") -> dict:
    """Escalate to a human (P3 wires real email/PDF; for now publish + mark)."""
    print(f"[sentinel] ESCALATE {mmsi} ({level}): {reason[:140]}", flush=True)
    tools.update_watch(mmsi, status="escalated", note=f"escalated: {reason[:200]}")
    return {"escalated": True, "mmsi": mmsi}


def _update(mmsi: str, status: str | None = None, note: str | None = None) -> dict:
    tools.update_watch(mmsi, status=status, note=note)
    return {"updated": True, "mmsi": mmsi}


def _mcp_servers():
    if settings.aiven_mcp_token and len(settings.aiven_mcp_token) > 20:
        return [{"type": "url", "name": "aiven", "url": settings.aiven_mcp_url,
                 "authorization_token": settings.aiven_mcp_token}]
    return None


def run_cycle(only_mmsi: str | None = None) -> dict | None:
    """One autonomous monitoring pass. If only_mmsi is given, review just that vessel
    (any status — operator-triggered per-boat run); otherwise the ACTIVE watchlist."""
    if only_mmsi:
        watchlist = [w for w in tools.get_watchlist(status=None, limit=200)
                     if str(w.get("mmsi")) == str(only_mmsi)]
    else:
        watchlist = tools.get_watchlist(limit=20)
    if not watchlist:
        print(f"[sentinel] {'vessel ' + only_mmsi + ' not on watchlist' if only_mmsi else 'watchlist empty'}"
              " — nothing to monitor", flush=True)
        return None
    print(f"[sentinel] cycle start — {len(watchlist)} vessel(s)"
          + (f" (manual: {only_mmsi})" if only_mmsi else " on watch"), flush=True)

    budget = {"reinvestigate": _REINVESTIGATE_BUDGET, "escalate": _ESCALATE_BUDGET}

    def _reinv(mmsi: str) -> dict:
        if budget["reinvestigate"] <= 0:
            return {"skipped": "re-investigation budget for this cycle is spent"}
        budget["reinvestigate"] -= 1
        return _reinvestigate(mmsi)

    def _esc(mmsi: str, reason: str, level: str) -> dict:
        if budget["escalate"] <= 0:
            return {"skipped": "escalation budget for this cycle is spent"}
        budget["escalate"] -= 1
        return _escalate(mmsi, reason, level)

    dispatch = {
        "check_changes": lambda i: _check_changes(i.get("mmsi", "")),
        "aiven_query": lambda i: tools.aiven_query(i.get("sql", ""), i.get("max_rows", 50)),
        "reinvestigate": lambda i: _reinv(i.get("mmsi", "")),
        "escalate": lambda i: _esc(i.get("mmsi", ""), i.get("reason", ""), i.get("level", "")),
        "update_watch": lambda i: _update(i.get("mmsi", ""), i.get("status"), i.get("note")),
    }
    brief = [{"mmsi": w.get("mmsi"), "name": w.get("name"), "level": w.get("level"),
              "confidence": w.get("confidence"), "last_reviewed": str(w.get("last_reviewed")),
              "watch_signals": w.get("watch_signals"), "open_questions": w.get("open_questions")}
             for w in watchlist]
    user = (
        f"Aiven Postgres for the MCP tools -> project={settings.aiven_project!r}, "
        f"service_name={settings.aiven_pg_service!r}, database={settings.aiven_pg_database!r}.\n\n"
        f"Current watchlist ({len(brief)} vessels):\n{json.dumps(brief, default=str)[:6000]}\n\n"
        "Review them now: ensure your sentinel_memory table exists (via MCP), recall prior "
        "memory if useful, check what changed, check pipeline health, decide and act on each "
        "vessel, persist a short observation to sentinel_memory (via MCP), then call submit_cycle."
    )
    return agent_base.run_tool_loop(
        agent_name=AGENT, system=_SYSTEM, user=user, submit_tool=_SUBMIT,
        tool_defs=_TOOLS, dispatch=dispatch, mcp_servers=_mcp_servers(),
        web_search=True, max_steps=14, client_timeout=120.0, max_retries=0)


def run(cycle_sec: int = CYCLE_SEC) -> None:
    print(f"[sentinel] starting autonomous monitor; cycle every {cycle_sec}s", flush=True)
    while True:
        try:
            out = run_cycle()
            if out:
                print(f"[sentinel] cycle done: {out.get('summary', '')[:200]}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[sentinel] cycle error ({e})", flush=True)
        time.sleep(cycle_sec)


if __name__ == "__main__":
    run()
