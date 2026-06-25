"""Aiven Evidence Librarian — Person B.

Reads what we already know from Aiven (Postgres). It is given the deterministic
raw evidence already pulled for the case, and it uses a READ-ONLY SQL tool to dig
for connections the fixed gather misses — adjacent-MMSI fleets, prior events for
nearby vessels, fleet-wide patterns near the same cable, etc. It reports what
Aiven reliably tells us and what is still unknown. It never invents.

run(suspicion, raw, osint) -> dict | None  with {summary, additional_findings, gaps}
"""

import json

from . import agent_base, tools
from ..config import settings

AGENT = "Aiven Evidence Librarian"

_SCHEMA = (
    "Aiven Postgres tables (read-only):\n"
    "  vessels(mmsi, name, flag, ship_type, last_lat, last_lon, last_speed, "
    "last_course, nav_status, last_seen, suspicion_score, suspicion_reasons jsonb, is_candidate)\n"
    "  tracks(mmsi, lat, lon, speed, course, ts, source)\n"
    "  suspicion_events(suspicion_id, mmsi, imo, name, rule, cable, severity, summary, ts)\n"
    "  agent_findings(suspicion_id, agent, severity, finding, evidence jsonb)\n"
    "  assessments(suspicion_id, level, confidence, summary, reasoning jsonb, "
    "recommended_action, voice_script, created_at)"
)

_SYSTEM = (
    "You are the Aiven Evidence Librarian for Baltic Sentinel. Your only sources are "
    "the case's raw evidence (already pulled) and the live Aiven Postgres database, "
    "which you query with the read-only `aiven_query` SQL tool.\n\n"
    + _SCHEMA + "\n\n"
    "Use aiven_query to surface connections the raw evidence does not already show — "
    "e.g. vessels with MMSIs adjacent to the subject (possible common operator), other "
    "vessels in the same anchorage, prior suspicion_events or assessments for the subject "
    "or its neighbours, repeated patterns near the same cable. Then report: a SUMMARY of "
    "what Aiven reliably tells us, ADDITIONAL_FINDINGS from your own queries, and GAPS "
    "(what Aiven does NOT tell us and would need external research). Base everything on "
    "real query results. aiven_query accepts ONLY plain read-only SELECT/WITH statements "
    "(no SHOW/EXPLAIN/DDL/DML — they are rejected). If a query returns nothing, say the "
    "data is absent — never invent.\n\n"
    "You also have the official Aiven MCP tools (`aiven_*`). Use them when they genuinely "
    "help judge how much to TRUST this evidence: confirm the Aiven service backing the "
    "data is healthy and how fresh the ingest is (recent service activity / metrics / "
    "logs). Fold that into your SUMMARY as data-provenance, and into GAPS if the data "
    "looks stale or the pipeline looks unhealthy. Don't call MCP just to call it — skip "
    "it if it adds nothing. Be efficient: a few targeted queries (plus at most one MCP "
    "health check), then call submit_evidence.\n\n"
    "IMPORTANT: after 2-3 queries STOP querying and call submit_evidence with your summary "
    "+ findings + gaps. Never keep querying until you run out of turns — a thin-but-real "
    "summary ('Aiven shows N tracks and no prior events for this vessel') is far better "
    "than an empty submission."
)

_TOOLS = [
    {"name": "aiven_query",
     "description": "Run a READ-ONLY SQL SELECT/WITH against Aiven Postgres (writes/DDL are "
                    "rejected — query only). Columns: tracks(...,ts,source); vessels(mmsi,name,"
                    "flag,last_seen,suspicion_score,...); suspicion_events(...,ts). Returns rows.",
     "input_schema": {"type": "object",
                      "properties": {"sql": {"type": "string"},
                                     "max_rows": {"type": "integer"}},
                      "required": ["sql"]}},
    {"name": "get_nearby_vessels",
     "description": "Convenience: live vessels within radius_nm of a point.",
     "input_schema": {"type": "object",
                      "properties": {"lat": {"type": "number"}, "lon": {"type": "number"},
                                     "radius_nm": {"type": "number"}}}},
]

_SUBMIT = {
    "name": "submit_evidence",
    "description": "Report what Aiven tells us and what is missing.",
    "input_schema": {"type": "object", "properties": {
        "summary": {"type": "string", "description": "What Aiven reliably tells us about this case."},
        "additional_findings": {"type": "array", "items": {"type": "string"},
                                "description": "New connections found via your own SQL queries."},
        "gaps": {"type": "array", "items": {"type": "string"},
                 "description": "What Aiven does NOT tell us / needs external research."}},
        "required": ["summary", "gaps"]},
}


def run(suspicion: dict, raw: dict, osint: dict | None = None) -> dict | None:
    lp = suspicion.get("last_position") or {}
    user = (
        f"Subject vessel: name={suspicion.get('name')!r} mmsi={suspicion.get('mmsi')} "
        f"imo={suspicion.get('imo')} flag={suspicion.get('flag')} "
        f"position lat={lp.get('lat')} lon={lp.get('lon')}.\n\n"
        f"Raw evidence already pulled:\n{json.dumps(raw, default=str)[:4000]}\n\n"
        f"OSINT gathered so far: {json.dumps(osint, default=str)[:1500] if osint else 'none yet'}\n\n"
        "Query Aiven for connections/patterns beyond the raw evidence, then call "
        "submit_evidence."
    )
    dispatch = {
        "aiven_query": lambda i: tools.aiven_query(i.get("sql", ""), i.get("max_rows", 50)),
        "get_nearby_vessels": lambda i: tools.get_nearby_vessels(
            i.get("lat", lp.get("lat")), i.get("lon", lp.get("lon")),
            radius_nm=float(i.get("radius_nm", 10)), exclude_mmsi=suspicion.get("mmsi")),
    }
    # Official Aiven MCP, when a real token is configured (12-char placeholder ignored).
    mcp = None
    if settings.aiven_mcp_token and len(settings.aiven_mcp_token) > 20:
        mcp = [{"type": "url", "name": "aiven", "url": settings.aiven_mcp_url,
                "authorization_token": settings.aiven_mcp_token}]
    # 60s/request, no retry: enough for a genuine Aiven MCP service-health check to
    # complete (the connector is slow) while still bailing rather than hanging. The
    # Librarian runs in parallel with OSINT (the long pole), so this is hidden.
    return agent_base.run_tool_loop(agent_name=AGENT, system=_SYSTEM, user=user,
                                    submit_tool=_SUBMIT, tool_defs=_TOOLS,
                                    dispatch=dispatch, max_steps=5, mcp_servers=mcp,
                                    client_timeout=60.0, max_retries=0)
