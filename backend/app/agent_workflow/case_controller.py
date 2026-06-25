"""Case Controller — Person B.

Looks at everything gathered so far (raw evidence + Librarian + OSINT) and decides
what is still MISSING to reach a confident verdict, turning it into concrete
research questions for the OSINT Researcher. Sets evidence_complete when no useful
external research remains. No tools — pure reasoning over the assembled case.

run(suspicion, raw, librarian, osint) -> dict | None  {missing_info, research_questions, evidence_complete}
"""

import json

from . import agent_base

AGENT = "Case Controller"

_SYSTEM = (
    "You are the Case Controller for a maritime-infrastructure investigation. You see "
    "the raw evidence, the Aiven Librarian's summary/gaps, and any OSINT gathered so "
    "far. Decide what is still MISSING or UNVERIFIED to reach a confident verdict on "
    "whether this vessel is a credible threat to undersea infrastructure. Produce a few "
    "concrete, answerable research questions for an OSINT researcher (web search) — e.g. "
    "'Is <name> / IMO <x> publicly reported as part of the sanctioned shadow fleet?', "
    "'Has this vessel been involved in prior cable/anchor incidents?'. Do not ask for "
    "things already answered. Set evidence_complete=true only when further web research "
    "would not meaningfully change the verdict (or all gaps are already addressed)."
)

_SUBMIT = {
    "name": "submit_gaps",
    "description": "Report missing info and research questions.",
    "input_schema": {"type": "object", "properties": {
        "missing_info": {"type": "array", "items": {"type": "string"}},
        "research_questions": {"type": "array", "items": {"type": "string"},
                               "description": "Concrete questions for OSINT web search. [] if none."},
        "evidence_complete": {"type": "boolean"}},
        "required": ["research_questions", "evidence_complete"]},
}


def run(suspicion: dict, raw: dict, librarian: dict | None, osint: dict | None) -> dict | None:
    user = (
        f"Subject: name={suspicion.get('name')!r} mmsi={suspicion.get('mmsi')} "
        f"imo={suspicion.get('imo')} flag={suspicion.get('flag')}.\n\n"
        f"Raw evidence: {json.dumps(raw, default=str)[:3000]}\n\n"
        f"Librarian: {json.dumps(librarian, default=str)[:1500] if librarian else 'unavailable'}\n\n"
        f"OSINT so far: {json.dumps(osint, default=str)[:1500] if osint else 'none yet'}\n\n"
        "Identify what's missing and call submit_gaps."
    )
    return agent_base.run_tool_loop(agent_name=AGENT, system=_SYSTEM, user=user,
                                    submit_tool=_SUBMIT, force_first=True)
