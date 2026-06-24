"""Identity & Records specialist — Person B.

Answers "who is this vessel really, and does its record raise concern?"
- deterministic identity checks (IMO check-digit, etc.)  -> context
- real OpenSanctions maritime record                     -> context
- live web search (OSINT: ownership, flag history, prior detentions, news) -> tool

This adds NEW information beyond the suspicion packet, instead of restating it.
"""

from . import agent_base, tools

AGENT = "Identity & Records"

_SYSTEM = (
    "You are the Identity & Records analyst for Baltic Sentinel, a maritime "
    "infrastructure threat monitor. Your job: establish who this vessel really is "
    "and whether its record raises concern. You are given deterministic identity "
    "checks and the OpenSanctions maritime record. Use web_search to corroborate "
    "and expand — vessel ownership, flag/registry history, prior detentions or "
    "incidents, shadow-/dark-fleet reporting, and recent news tied to the name or "
    "IMO. Base every finding on evidence and clearly mark anything unverified; do "
    "not assert sanctions or affiliations the data doesn't support. Finish by "
    "calling submit_findings with 1-2 findings."
)


def run(suspicion: dict) -> list[dict]:
    ident = tools.validate_identity(
        mmsi=suspicion.get("mmsi"), imo=suspicion.get("imo"),
        name=suspicion.get("name"), flag=suspicion.get("flag"))
    record = tools.get_sanctions_record(
        imo=suspicion.get("imo"), name=suspicion.get("name"))

    user = (
        f"Vessel: name={suspicion.get('name')!r} mmsi={suspicion.get('mmsi')} "
        f"imo={suspicion.get('imo')} flag={suspicion.get('flag')}\n"
        f"Deterministic identity checks: {ident['checks']}\n"
        f"OpenSanctions maritime record: {record}\n\n"
        "Investigate the vessel's identity authenticity and record risk. Use "
        "web_search for open-source corroboration, then call submit_findings."
    )
    return agent_base.run_specialist(
        agent_name=AGENT, system=_SYSTEM, user=user, suspicion=suspicion,
        web_search=True, max_steps=6)
