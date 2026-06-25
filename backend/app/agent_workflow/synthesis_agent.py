"""Watch Officer — Person B.

Produces the final, calibrated verdict from the analysts' findings + the evidence
gaps. No canned output: if synthesis can't run, it returns an explicit
"assessment unavailable" state (not a fabricated verdict). Confidence must track
how complete and corroborated the evidence actually is.

run(case, findings) -> dict  (always returns a dict; honest on failure)
"""

import json

from . import agent_base

AGENT = "Watch Officer"

_SYSTEM = (
    "You are the Watch Officer for Baltic Sentinel. Synthesize ONE calibrated verdict on "
    "whether this vessel is a credible threat to undersea infrastructure, using ONLY the "
    "analysts' findings and the listed evidence gaps. Rules: calibrate honestly — HIGH only "
    "when findings genuinely support serious, corroborated risk; MEDIUM for credible-but-"
    "unconfirmed; LOW for routine/benign or when evidence is too thin to support concern. "
    "Set confidence (0-1) to reflect how complete and corroborated the evidence is — LOWER "
    "it when key items are unverified (e.g. OSINT found no source, track is insufficient, "
    "GPS/cable context unavailable) and SAY SO in the summary. Do not assert anything the "
    "findings don't support. recommended_action scales with level (LOW: monitor/log; MEDIUM: "
    "analyst review; HIGH: escalate to a human watch officer + notify the cable operator) and "
    "must NEVER be automatic enforcement — a human decides. voice_script: 1-3 spoken sentences. "
    "headline: ONE punchy line, max 12 words, no period — the verdict at a glance "
    "(e.g. 'Shadow-fleet tanker loitering over Estlink 2, GPS untrustworthy')."
)

_SUBMIT = {
    "name": "submit_assessment",
    "description": "Submit the final calibrated threat assessment.",
    "input_schema": {"type": "object", "properties": {
        "level": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
        "confidence": {"type": "number", "description": "0 to 1"},
        "headline": {"type": "string", "description": "max 12 words, no period — verdict at a glance"},
        "summary": {"type": "string"},
        "reasoning": {"type": "array", "items": {"type": "string"}},
        "recommended_action": {"type": "string"},
        "voice_script": {"type": "string"}},
        "required": ["level", "confidence", "headline", "summary", "reasoning",
                     "recommended_action", "voice_script"]},
}


def run(case: dict, findings: list[dict]) -> dict:
    sid = case["suspicion"]["suspicion_id"]
    lib = case.get("librarian") or {}
    osint = case.get("osint") or {}
    user = (
        f"Subject: {json.dumps(case.get('raw', {}).get('vessel'), default=str)}\n\n"
        f"Analyst findings:\n{json.dumps(findings, default=str)[:3500]}\n\n"
        f"Known evidence gaps (Librarian): {json.dumps(lib.get('gaps', []), default=str)[:1200]}\n"
        f"OSINT unresolved: {json.dumps(osint.get('unresolved', []), default=str)[:1200]}\n\n"
        "Produce the final calibrated verdict and call submit_assessment."
    )
    out = agent_base.run_tool_loop(agent_name=AGENT, system=_SYSTEM, user=user,
                                   submit_tool=_SUBMIT, max_steps=2, model="claude-opus-4-8")
    if not out:
        return {"suspicion_id": sid, "level": "LOW", "confidence": 0.0,
                "headline": "Assessment unavailable — manual review required",
                "summary": "Assessment unavailable — the Watch Officer synthesis could not be completed.",
                "reasoning": ["Synthesis step failed or no model access."],
                "recommended_action": "Manual analyst review required.",
                "voice_script": "Assessment unavailable. Manual analyst review is required."}
    level = str(out.get("level", "MEDIUM")).upper()
    if level not in ("LOW", "MEDIUM", "HIGH"):
        level = "MEDIUM"
    try:
        conf = max(0.0, min(1.0, float(out.get("confidence", 0.5))))
    except (TypeError, ValueError):
        conf = 0.5
    return {"suspicion_id": sid, "level": level, "confidence": round(conf, 2),
            "headline": str(out.get("headline", "")).strip(),
            "summary": str(out.get("summary", "")),
            "reasoning": [str(r) for r in out.get("reasoning", [])],
            "recommended_action": str(out.get("recommended_action", "")),
            "voice_script": str(out.get("voice_script", ""))}
