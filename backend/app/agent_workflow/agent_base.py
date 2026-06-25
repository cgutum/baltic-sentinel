"""Shared agent loop runner — Person B.

run_tool_loop: a bounded Claude tool-using loop that ends when the agent calls a
given `submit` tool, and returns whatever structured object it submitted. Handles
server-side web_search (skip its blocks; continue on pause_turn) and client tools
(always resolved, so no dangling tool_use). On any failure it returns None — it
NEVER fabricates an answer (callers report 'unavailable' instead).

run_specialist: thin wrapper for analysts that produce AgentFinding-shaped findings.
"""

import json

from ..config import settings

# Sub-agents run on the faster Sonnet by default (much lower latency); the Watch
# Officer passes model="claude-opus-4-8" for the final verdict.
DEFAULT_MODEL = "claude-sonnet-4-6"

# COST/LATENCY KNOB: max web searches per agent run. ~$0.01 each + result tokens.
# Kept low because web search is the slowest step in the loop (balanced-latency mode).
WEB_SEARCH_MAX_USES = 2
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search",
                   "max_uses": WEB_SEARCH_MAX_USES}


def _log(msg: str) -> None:
    """Live progress line to the backend terminal (flush so it shows immediately)."""
    print(msg, flush=True)


def _short(result) -> str:
    """One-line summary of a client tool's result, for the terminal log."""
    if isinstance(result, dict):
        if "error" in result:
            return f"ERROR: {str(result['error'])[:90]}"
        if "rows" in result:
            return f"{len(result.get('rows') or [])} row(s)"
        return "dict(" + ", ".join(list(result)[:5]) + ")"
    if isinstance(result, list):
        return f"{len(result)} item(s)"
    return str(result)[:90]


# Submit schema for the finding-producing analysts.
_FINDINGS_SUBMIT = {
    "name": "submit_findings",
    "description": "Report your 1-2 findings and end. Each: severity 0-1, finding text, evidence list.",
    "input_schema": {
        "type": "object",
        "properties": {"findings": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "severity": {"type": "number", "description": "0 (benign) to 1 (severe)"},
                "finding": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["severity", "finding", "evidence"]}}},
        "required": ["findings"],
    },
}


def run_tool_loop(*, agent_name: str, system: str, user: str, submit_tool: dict,
                  tool_defs: list | None = None, dispatch: dict | None = None,
                  web_search: bool = False, max_steps: int = 6,
                  model: str | None = None, mcp_servers: list | None = None,
                  client_timeout: float = 90.0, max_retries: int = 1,
                  force_first: bool = False) -> dict | None:
    """Run one agent's tool-loop. Returns the dict it passed to `submit_tool`, or
    None if there's no API key / the agent never submitted / an error occurred.

    If mcp_servers is given, the loop uses the Anthropic API MCP connector (beta)
    so the agent can call the remote MCP server's tools (executed server-side)."""
    if not settings.anthropic_api_key:
        return None
    import anthropic

    mdl = model or DEFAULT_MODEL
    dispatch = dispatch or {}
    tools = list(tool_defs or [])
    if web_search:
        tools.append(WEB_SEARCH_TOOL)
    if mcp_servers:
        for s in mcp_servers:
            tools.append({"type": "mcp_toolset", "mcp_server_name": s["name"]})
    tools.append(submit_tool)
    submit_name = submit_tool["name"]

    caps = [t["name"] for t in (tool_defs or [])]
    if web_search:
        caps.append("web_search")
    if mcp_servers:
        caps += [f"mcp:{s['name']}" for s in mcp_servers]
    _log(f"[{agent_name}] START ({mdl}); tools: "
         f"{', '.join(caps) if caps else 'none (reasoning only)'}"
         + ("  [single-shot]" if force_first else ""))

    # Bounded per-request timeout (+ optional retry) so a slow/stalled MCP or web-search
    # call fails fast instead of hanging the whole investigation. Callers tune this per
    # agent (e.g. the MCP Librarian bails fast; OSINT web search gets longer). The
    # orchestrator also caps the whole enrichment leg as a backstop.
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key,
                                 timeout=client_timeout, max_retries=max_retries)
    messages = [{"role": "user", "content": user}]

    def _create(force: bool = False):
        kw = {"model": mdl, "max_tokens": 2000, "system": system,
              "tools": tools, "messages": messages}
        if force:
            kw["tool_choice"] = {"type": "tool", "name": submit_name}
        if mcp_servers:  # MCP connector requires the beta endpoint + header
            kw["betas"] = ["mcp-client-2025-11-20"]
            kw["mcp_servers"] = mcp_servers
            return client.beta.messages.create(**kw)
        return client.messages.create(**kw)

    try:
        if force_first:
            # No gathering tools needed — force the structured submit in ONE round-trip
            # (skips the model's "reason in text, then get force-submitted" second call).
            resp = _create(force=True)
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use" and block.name == submit_name:
                    _log(f"[{agent_name}] DONE (single-shot submit)")
                    return dict(block.input or {})
            _log(f"[{agent_name}] no submission (single-shot)")
            return None
        for step in range(max_steps):
            resp = _create()
            messages.append({"role": "assistant", "content": resp.content})

            tool_results = []
            for block in resp.content:
                btype = getattr(block, "type", None)
                if btype == "mcp_tool_use":  # Aiven MCP tool, executed server-side
                    _log(f"[{agent_name}] Aiven MCP call -> {getattr(block, 'name', '?')}")
                elif btype == "mcp_tool_result":
                    bad = getattr(block, "is_error", False)
                    _log(f"[{agent_name}] Aiven MCP result: {'ERROR' if bad else 'ok'}")
                elif btype == "server_tool_use":  # web search query, executed server-side
                    q = (getattr(block, "input", {}) or {}).get("query")
                    _log(f"[{agent_name}] web_search: {q!r}")
                elif btype == "web_search_tool_result":
                    c = getattr(block, "content", None)
                    _log(f"[{agent_name}] web_search -> "
                         f"{len(c) if isinstance(c, list) else '?'} result(s)")
                elif btype == "tool_use":
                    if block.name == submit_name:
                        _log(f"[{agent_name}] DONE (submitted at step {step + 1})")
                        return dict(block.input or {})
                    fn = dispatch.get(block.name)
                    result = fn(block.input or {}) if fn else {"error": f"unknown tool {block.name}"}
                    _log(f"[{agent_name}] tool {block.name} -> {_short(result)}")
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                         "content": json.dumps(result, default=str)})

            if tool_results:
                messages.append({"role": "user", "content": tool_results})
                continue
            if resp.stop_reason == "pause_turn":
                _log(f"[{agent_name}] ...server tool running, resuming")
                continue  # server tool (web search) running — resume
            break

        # Force a final submit so the agent reports what it has.
        _log(f"[{agent_name}] forcing final submit")
        resp = _create(force=True)
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == submit_name:
                _log(f"[{agent_name}] DONE (forced submit)")
                return dict(block.input or {})
    except Exception as e:  # noqa: BLE001 — never fabricate; report unavailable upstream
        _log(f"[{agent_name}] ERROR ({e})")
        return None
    _log(f"[{agent_name}] no result (never submitted)")
    return None


def _coerce_to_list(raw) -> list:
    """The model sometimes returns `findings` as a JSON STRING (or a single obj).
    Coerce to a list of items WITHOUT ever iterating a string character-by-char."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, str):
        s = raw.strip()
        if "[" in s and "]" in s:  # pull out an embedded JSON array
            try:
                p = json.loads(s[s.index("["):s.rindex("]") + 1])
                if isinstance(p, list):
                    return p
            except Exception:  # noqa: BLE001
                pass
        try:
            p = json.loads(s)
            return p if isinstance(p, list) else [p]
        except Exception:  # noqa: BLE001
            return [{"finding": s[:600]}]  # last resort: one finding, truncated
    return []


def _normalize_findings(raw, agent_name: str, suspicion_id: str) -> list[dict]:
    out = []
    for f in _coerce_to_list(raw):
        if isinstance(f, str):
            try:
                fj = json.loads(f)
                f = fj if isinstance(fj, dict) else {"finding": f[:600]}
            except Exception:  # noqa: BLE001
                f = {"finding": f[:600]}
        if not isinstance(f, dict):
            continue
        finding = str(f.get("finding", "")).strip()
        if not finding:
            continue
        try:
            sev = max(0.0, min(1.0, float(f.get("severity", 0.5))))
        except (TypeError, ValueError):
            sev = 0.5
        out.append({"suspicion_id": suspicion_id, "agent": agent_name, "severity": sev,
                    "finding": finding, "evidence": [str(e) for e in f.get("evidence", [])]})
    return out


def run_specialist(*, agent_name: str, system: str, user: str, suspicion: dict,
                   tool_defs: list | None = None, dispatch: dict | None = None,
                   web_search: bool = False, max_steps: int = 5,
                   force_first: bool = False) -> list[dict]:
    """Run an analyst that produces AgentFinding-shaped findings (empty on failure)."""
    out = run_tool_loop(agent_name=agent_name, system=system, user=user,
                        submit_tool=_FINDINGS_SUBMIT, tool_defs=tool_defs,
                        dispatch=dispatch, web_search=web_search, max_steps=max_steps,
                        force_first=force_first)
    if not out:
        return []
    return _normalize_findings(out.get("findings", []), agent_name, suspicion["suspicion_id"])
