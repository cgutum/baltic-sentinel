"""Watch Officer (synthesis) agent — Person B (H10).

Reads the Investigator's findings and produces ONE calibrated final threat
assessment via a single forced Claude tool call (cheap: one API call, no loop).
Honest by design — the level/confidence track the actual evidence, so a benign
vessel gets LOW/MEDIUM, not a blanket HIGH.

Falls back to canned output on any error (no key, API failure, bad output).

run(suspicion, findings) -> ThreatAssessment-shaped dict
"""

import json

from ..config import settings
from . import fallback_outputs

MODEL = "claude-opus-4-8"

_SYSTEM = """You are the Watch Officer for Baltic Sentinel, a maritime \
infrastructure threat monitor. An Investigator agent has examined a vessel \
flagged near an undersea cable and produced findings. Synthesize ONE final, \
calibrated threat assessment for a human watch officer.

Rules:
- Calibrate honestly to the evidence. Use HIGH only when the findings genuinely \
support serious risk (e.g. slow loitering directly over a cable PLUS identity or \
sanctions concerns). Use MEDIUM for a credible but unconfirmed concern, and LOW \
for routine or benign movement. Set confidence (0-1) to reflect how strong and \
corroborated the evidence actually is.
- Do NOT assert facts the findings do not support. If no finding confirms \
sanctions, do not state the vessel is sanctioned — describe it as unverified.
- reasoning: 2-4 short strings, each citing an actual finding.
- recommended_action must match the level: LOW -> continue monitoring / log; \
MEDIUM -> flag for analyst review; HIGH -> escalate to a human watch officer and \
notify the cable operator. NEVER recommend automatic enforcement — a human decides.
- voice_script: 1-3 plain spoken sentences for the watch officer, ending by \
recommending human escalation or independent verification.

Call submit_assessment with your result."""

_TOOL = {
    "name": "submit_assessment",
    "description": "Submit the final, calibrated threat assessment.",
    "input_schema": {
        "type": "object",
        "properties": {
            "level": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
            "confidence": {"type": "number", "description": "0 to 1"},
            "summary": {"type": "string"},
            "reasoning": {"type": "array", "items": {"type": "string"}},
            "recommended_action": {"type": "string"},
            "voice_script": {"type": "string"},
        },
        "required": ["level", "confidence", "summary", "reasoning",
                     "recommended_action", "voice_script"],
    },
}


def _synthesize_with_claude(suspicion: dict, findings: list[dict]) -> dict:
    """One forced tool call. Raises on any failure so run() can fall back."""
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    context = {k: suspicion.get(k) for k in
               ("name", "mmsi", "imo", "rule", "cable", "severity", "summary",
                "flag", "reasons")}
    user = (
        "Flagged vessel:\n" + json.dumps(context, indent=2)
        + "\n\nInvestigator findings:\n" + json.dumps(findings, indent=2)
        + "\n\nProduce the final assessment now."
    )

    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "submit_assessment"},
        messages=[{"role": "user", "content": user}],
    )

    for block in resp.content:
        if block.type == "tool_use" and block.name == "submit_assessment":
            a = block.input or {}
            level = str(a.get("level", "MEDIUM")).upper()
            if level not in ("LOW", "MEDIUM", "HIGH"):
                level = "MEDIUM"
            conf = max(0.0, min(1.0, float(a.get("confidence", 0.5))))
            return {
                "suspicion_id": suspicion["suspicion_id"],
                "level": level,
                "confidence": round(conf, 2),
                "summary": str(a.get("summary", "")),
                "reasoning": [str(r) for r in a.get("reasoning", [])],
                "recommended_action": str(a.get("recommended_action", "")),
                "voice_script": str(a.get("voice_script", "")),
            }
    raise RuntimeError("watch officer returned no assessment")


def run(suspicion: dict, findings: list[dict]) -> dict:
    """Synthesize via Claude; fall back to canned assessment on any problem."""
    if not settings.anthropic_api_key:
        print("[watch-officer] no ANTHROPIC_API_KEY — using fallback assessment")
        return fallback_outputs.assessment(suspicion, findings)
    try:
        a = _synthesize_with_claude(suspicion, findings)
        print(f"[watch-officer] Claude assessment: {a['level']} (confidence={a['confidence']})")
        return a
    except Exception as e:  # noqa: BLE001 — never let the demo break
        print(f"[watch-officer] Claude failed ({e}) — using fallback assessment")
        return fallback_outputs.assessment(suspicion, findings)
