"""Investigator agent — Person B (H5-H7).

The real "brain" for the investigation: an own-harness Claude tool-calling loop
(raw Anthropic SDK, we run the loop locally). Claude is handed a suspicion id,
calls the read tools to gather evidence (multi-step), then reports findings via
a submit_findings tool.

This is the non-DEMO path. On ANY error (no key, API failure, bad output) it
falls back to fallback_outputs.findings() so the demo never breaks.

run(suspicion) -> list[dict]   # AgentFinding-shaped dicts (suspicion_id added)
"""

import json

from ..config import settings
from . import fallback_outputs, tools

MODEL = "claude-opus-4-8"
_MAX_STEPS = 6  # safety cap on the tool-use loop

_SYSTEM = """You are the Investigator, an autonomous maritime-incident analyst for \
Baltic Sentinel. A tripwire has flagged a vessel behaving suspiciously near an \
undersea cable corridor.

Your job: use your tools to gather evidence, then report 3-5 short findings.

Work in steps:
1. Call get_suspicion_event to load the case details.
2. Call get_recent_track to inspect how the vessel has been moving.
3. When you have enough, call submit_findings with 3-5 findings.

Cover these angles where the evidence supports them: vessel identity, movement \
behavior, sanctions/record risk, and GPS/navigation-trust environment. Base every \
finding only on the data your tools return and the suspicion itself — do not invent \
specifics you cannot support. Keep each finding to one or two sentences, with a \
severity from 0 to 1 and a short list of evidence strings."""

# Tool schemas exposed to Claude (raw JSON schema — stable across SDK versions).
_TOOLS = [
    {
        "name": "get_suspicion_event",
        "description": "Load the full details of the flagged suspicion by its id.",
        "input_schema": {
            "type": "object",
            "properties": {"suspicion_id": {"type": "string"}},
            "required": ["suspicion_id"],
        },
    },
    {
        "name": "get_recent_track",
        "description": "Return the vessel's recent positions (lat, lon, speed, course).",
        "input_schema": {
            "type": "object",
            "properties": {"mmsi": {"type": "string"}},
            "required": ["mmsi"],
        },
    },
    {
        "name": "submit_findings",
        "description": "Report your final findings and end the investigation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "agent": {
                                "type": "string",
                                "description": "Which lens, e.g. 'Identity Agent'.",
                            },
                            "severity": {"type": "number"},
                            "finding": {"type": "string"},
                            "evidence": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["agent", "severity", "finding", "evidence"],
                    },
                }
            },
            "required": ["findings"],
        },
    },
]


def _run_read_tool(name: str, tool_input: dict, suspicion: dict):
    """Dispatch a read tool call. get_suspicion_event returns THIS case's real
    suspicion (so any chosen vessel is investigated correctly, not the canned one)."""
    if name == "get_suspicion_event":
        return suspicion
    if name == "get_recent_track":
        return tools.get_recent_track(tool_input.get("mmsi") or suspicion.get("mmsi"))
    return {"error": f"unknown tool {name}"}


def _investigate_with_claude(suspicion: dict) -> list[dict]:
    """The real loop. Raises on any failure so run() can fall back."""
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    messages = [
        {
            "role": "user",
            "content": (
                f"A vessel was flagged: suspicion_id={suspicion['suspicion_id']}. "
                "Investigate it and submit your findings."
            ),
        }
    ]

    for _ in range(_MAX_STEPS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=_SYSTEM,
            tools=_TOOLS,
            messages=messages,
        )

        if resp.stop_reason != "tool_use":
            raise RuntimeError(f"investigator stopped without findings ({resp.stop_reason})")

        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            if block.name == "submit_findings":
                raw = block.input.get("findings", [])
                print(f"[investigator] Claude submitted {len(raw)} findings")
                return [
                    {
                        "suspicion_id": suspicion["suspicion_id"],
                        "agent": str(f.get("agent", "Investigator")),
                        "severity": float(f.get("severity", 0.5)),
                        "finding": str(f.get("finding", "")),
                        "evidence": [str(e) for e in f.get("evidence", [])],
                    }
                    for f in raw
                ]
            result = _run_read_tool(block.name, block.input or {}, suspicion)
            print(f"[investigator] tool {block.name} -> ok")
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError("investigator hit step limit without submitting findings")


def run(suspicion: dict) -> list[dict]:
    """Investigate via Claude; fall back to canned findings on any problem."""
    if not settings.anthropic_api_key:
        print("[investigator] no ANTHROPIC_API_KEY — using fallback findings")
        return fallback_outputs.findings(suspicion)
    try:
        findings = _investigate_with_claude(suspicion)
        if not findings:
            raise RuntimeError("no findings returned")
        return findings
    except Exception as e:  # noqa: BLE001 — never let the demo break
        print(f"[investigator] Claude failed ({e}) — using fallback findings")
        return fallback_outputs.findings(suspicion)
