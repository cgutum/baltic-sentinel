"""Action Briefing Agent — Person B.

Turns the finished investigation into operator deliverables: a concise markdown
report, a short email draft to a human watch officer, and a voice script. It only
restates what the verdict + findings established; it invents nothing and always
recommends human escalation, never automatic action.

run(case, assessment, findings) -> dict | None  {report_markdown, email_subject, email_body, voice_script}
"""

import json

from . import agent_base

AGENT = "Action Briefing"

_SYSTEM = (
    "You are the Action Briefing Agent. Produce operator-ready deliverables from the "
    "completed investigation: (1) report_markdown — a concise briefing (vessel, verdict + "
    "confidence, key findings, what's unverified, recommended action); (2) email_subject + "
    "email_body — a short, professional alert to a human watch officer; (3) voice_script — "
    "1-3 spoken sentences. Reflect the verdict's uncertainty honestly, state clearly what is "
    "unverified, recommend human escalation/verification (never automatic enforcement), and "
    "do not introduce any claim not already in the verdict or findings."
)

_SUBMIT = {
    "name": "submit_briefing",
    "description": "Submit the operator deliverables.",
    "input_schema": {"type": "object", "properties": {
        "report_markdown": {"type": "string"},
        "email_subject": {"type": "string"},
        "email_body": {"type": "string"},
        "voice_script": {"type": "string"}},
        "required": ["report_markdown", "email_subject", "email_body", "voice_script"]},
}


def run(case: dict, assessment: dict, findings: list[dict]) -> dict | None:
    user = (
        f"Vessel: {json.dumps(case.get('raw', {}).get('vessel'), default=str)}\n\n"
        f"Verdict: level={assessment.get('level')} confidence={assessment.get('confidence')}\n"
        f"Summary: {assessment.get('summary')}\n"
        f"Reasoning: {json.dumps(assessment.get('reasoning', []), default=str)}\n"
        f"Recommended action: {assessment.get('recommended_action')}\n\n"
        f"Findings:\n{json.dumps(findings, default=str)[:3000]}\n\n"
        "Produce the deliverables and call submit_briefing."
    )
    return agent_base.run_tool_loop(agent_name=AGENT, system=_SYSTEM, user=user,
                                    submit_tool=_SUBMIT, force_first=True)
