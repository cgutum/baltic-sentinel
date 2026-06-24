"""Shared specialist-agent loop runner — Person B.

Runs ONE Claude tool-using specialist: a bounded loop with a given system
prompt + tool set, ending when the agent calls submit_findings. Handles Claude's
server-side web_search (skip its blocks; continue on pause_turn) alongside our
client tools. Returns AgentFinding-shaped dicts (suspicion_id + agent filled in).

Each specialist (identity / behavior / environment) is just a thin config on top
of run_specialist — that's what makes them genuinely different: distinct tools
and prompts, not four paraphrases of the same data.
"""

import json

from ..config import settings

MODEL = "claude-opus-4-8"

# COST KNOB: max web searches the Identity agent may run per investigation.
# Each search is ~$0.01 + the tokens for its results. 8 lets it actually
# corroborate (name + IMO + sanctions basis + ownership) while staying cheap.
# Lower this to spend less; raise it for deeper OSINT.
WEB_SEARCH_MAX_USES = 8

# Dynamic-filtering web search for Opus 4.8 (runs code-exec under the hood — do
# NOT also declare code_execution).
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search",
                   "max_uses": WEB_SEARCH_MAX_USES}

_SUBMIT = {
    "name": "submit_findings",
    "description": "Report your 1-2 findings and end. Each: severity 0-1, finding text, evidence list.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "number", "description": "0 (benign) to 1 (severe)"},
                        "finding": {"type": "string"},
                        "evidence": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["severity", "finding", "evidence"],
                },
            }
        },
        "required": ["findings"],
    },
}


def _normalize(raw: list, agent_name: str, suspicion_id: str) -> list[dict]:
    out = []
    for f in raw or []:
        finding = str(f.get("finding", "")).strip()
        if not finding:
            continue
        try:
            sev = max(0.0, min(1.0, float(f.get("severity", 0.5))))
        except (TypeError, ValueError):
            sev = 0.5
        out.append({
            "suspicion_id": suspicion_id,
            "agent": agent_name,
            "severity": sev,
            "finding": finding,
            "evidence": [str(e) for e in f.get("evidence", [])],
        })
    return out


def run_specialist(*, agent_name: str, system: str, user: str, suspicion: dict,
                   tool_defs: list | None = None, dispatch: dict | None = None,
                   web_search: bool = False, max_steps: int = 5) -> list[dict]:
    """Run one specialist tool-loop. Returns list[finding] (possibly empty on failure)."""
    if not settings.anthropic_api_key:
        return []
    import anthropic

    dispatch = dispatch or {}
    tools = list(tool_defs or [])
    if web_search:
        tools.append(WEB_SEARCH_TOOL)
    tools.append(_SUBMIT)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    messages = [{"role": "user", "content": user}]
    sid = suspicion["suspicion_id"]

    try:
        for _ in range(max_steps):
            resp = client.messages.create(
                model=MODEL, max_tokens=1500, system=system, tools=tools, messages=messages,
            )
            messages.append({"role": "assistant", "content": resp.content})

            # Resolve EVERY client tool_use this turn (submit ends; others get a
            # result — even unknown ones get an error result — so we never leave a
            # dangling tool_use that 400s the next request). Server blocks
            # (server_tool_use / web_search_tool_result) are auto-handled — skip them.
            tool_results = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                if block.name == "submit_findings":
                    return _normalize(block.input.get("findings", []), agent_name, sid)
                fn = dispatch.get(block.name)
                result = fn(block.input or {}) if fn else {"error": f"unknown tool {block.name}"}
                tool_results.append({
                    "type": "tool_result", "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })

            if tool_results:
                messages.append({"role": "user", "content": tool_results})
                continue
            if resp.stop_reason == "pause_turn":
                continue  # server tool (web search) still running — resume it
            break  # end_turn / no actionable tool calls -> leave the loop

        # Loop ended without an explicit submit — force one final submit_findings
        # so the agent always reports what it gathered.
        resp = client.messages.create(
            model=MODEL, max_tokens=1500, system=system, tools=tools,
            tool_choice={"type": "tool", "name": "submit_findings"}, messages=messages,
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "submit_findings":
                return _normalize(block.input.get("findings", []), agent_name, sid)
    except Exception as e:  # noqa: BLE001 — a specialist failure must not break the team
        print(f"[{agent_name}] error ({e})")
        return []
    return []
