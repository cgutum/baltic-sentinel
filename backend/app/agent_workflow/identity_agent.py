"""Identity & Records Analyst — Person B.

Interprets the ALREADY-GATHERED evidence (deterministic IMO check, real
OpenSanctions record, OSINT findings) to judge identity authenticity and record
risk. It does not fetch — gathering is the Librarian's/OSINT's job. It must mark
anything unverified and reduce confidence when public corroboration is missing.

run(case) -> list[finding]
"""

import json

from . import agent_base

AGENT = "Identity & Records"

_SYSTEM = (
    "You are the Identity & Records Analyst. Judge (a) whether the vessel's identity is "
    "authentic/consistent and (b) whether its record raises concern — using ONLY the "
    "provided evidence: the deterministic IMO check, the OpenSanctions record, and the "
    "OSINT findings. Rules: if OpenSanctions shows listed=false, do not call it sanctioned. "
    "Distinguish a port-state DETENTION from an active SANCTIONS designation. If OSINT "
    "found 'no confirmed public source', state that the listing/affiliation is UNVERIFIED "
    "beyond OpenSanctions and lower the severity accordingly. Never assert facts the "
    "evidence does not support. Submit 1-2 findings."
)


def run(case: dict) -> list[dict]:
    raw = case.get("raw", {})
    user = (
        f"Identity check: {json.dumps(raw.get('identity_check'), default=str)}\n"
        f"OpenSanctions record: {json.dumps(raw.get('sanctions'), default=str)}\n"
        f"Vessel: {json.dumps(raw.get('vessel'), default=str)}\n"
        f"OSINT findings: {json.dumps(case.get('osint', {}).get('findings', []), default=str)[:2000]}\n"
        f"OSINT unresolved: {json.dumps(case.get('osint', {}).get('unresolved', []), default=str)[:1000]}\n\n"
        "Analyze identity authenticity and record risk, then submit_findings."
    )
    return agent_base.run_specialist(agent_name=AGENT, system=_SYSTEM, user=user,
                                     suspicion=case["suspicion"], force_first=True)
