"""OSINT Researcher — Person B.

Tries to fill the Case Controller's gaps using real web search. Reports each
finding WITH its source and a confidence, and lists anything it could not confirm
as 'no confirmed public source found'. It never fabricates sources or claims.

run(suspicion, questions) -> dict | None  {findings:[{claim, source, confidence}], unresolved:[...]}
"""

from . import agent_base

AGENT = "OSINT Researcher"

_SYSTEM = (
    "You are an OSINT Researcher for a maritime-infrastructure investigation. Use the "
    "web_search tool to answer the given research questions about a specific vessel — "
    "ownership, beneficial owner, flag/registry history, prior detentions or incidents, "
    "shadow-/dark-fleet and sanctions reporting, recent news tied to the name or IMO. "
    "Report each finding as a short claim WITH the source (publication/site) and a "
    "confidence (low/medium/high). If you cannot find a credible public source for a "
    "question, put it under `unresolved` as 'no confirmed public source found: <question>'. "
    "NEVER fabricate a source, a URL, or a claim. Vessel names can collide — only attribute "
    "a finding to this vessel if the IMO or other identifiers match."
)

_SUBMIT = {
    "name": "submit_osint",
    "description": "Report OSINT findings (with sources) and unresolved questions.",
    "input_schema": {"type": "object", "properties": {
        "findings": {"type": "array", "items": {"type": "object", "properties": {
            "claim": {"type": "string"}, "source": {"type": "string"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]}},
            "required": ["claim", "source", "confidence"]}},
        "unresolved": {"type": "array", "items": {"type": "string"}}},
        "required": ["findings", "unresolved"]},
}


def run(suspicion: dict, questions: list[str]) -> dict | None:
    questions = (questions or [])[:2]  # latency cap: research only the top gaps
    user = (
        f"Vessel: name={suspicion.get('name')!r} imo={suspicion.get('imo')} "
        f"mmsi={suspicion.get('mmsi')} flag={suspicion.get('flag')}.\n\n"
        "Research questions (most important first):\n"
        + "\n".join(f"- {q}" for q in questions) + "\n\n"
        "Use web_search to answer them, then call submit_osint. Mark anything you can't "
        "confirm from a credible source as unresolved."
    )
    # Web search legitimately needs time; give it a longer per-request timeout than the
    # default (but no retry, so a true stall fails once rather than re-running searches).
    return agent_base.run_tool_loop(agent_name=AGENT, system=_SYSTEM, user=user,
                                    submit_tool=_SUBMIT, web_search=True, max_steps=3,
                                    client_timeout=110.0, max_retries=0)
