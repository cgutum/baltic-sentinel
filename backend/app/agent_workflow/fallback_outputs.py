"""Fallback outputs — Person B.

Hard-coded Eagle S findings / assessment used when Claude fails (or when
DEMO_MODE is on). Keeps the demo reliable: the same investigation always runs.

Pure data — no Kafka, no Postgres, no model imports. This is the file the real
Investigator / Watch Officer agents (H5+) will REPLACE, and the literal
`except:` fallback when a live Claude call fails.

Field names match contracts.md exactly:
  - findings()   -> list of AgentFinding-shaped dicts
  - assessment() -> one ThreatAssessment-shaped dict
"""

# A hardcoded vessel.suspicion (same shape Person A's tripwire produces), so the
# orchestrator can run with no input. Stable id -> reruns upsert cleanly.
SAMPLE_SUSPICION: dict = {
    "suspicion_id": "sus_eagle_s_demo",
    "mmsi": "518998000",
    "imo": "9329760",
    "name": "Eagle S",
    "rule": "slow_near_cable",
    "cable": "Estlink 2",
    "severity": 0.85,
    "summary": "Vessel moving below 3 knots inside Estlink 2 cable corridor.",
    "timestamp": "2024-12-25T12:00:00Z",
}


def findings(suspicion: dict) -> list[dict]:
    """Return the canned agent findings for this suspicion (AgentFinding shape)."""
    sid = suspicion["suspicion_id"]
    cable = suspicion.get("cable", "the cable corridor")
    name = suspicion.get("name", "the vessel")
    return [
        {
            "suspicion_id": sid,
            "agent": "Identity Agent",
            "severity": 0.95,
            "finding": (
                f"MMSI {suspicion.get('mmsi')} / IMO {suspicion.get('imo')} "
                f"resolve to the tanker {name}, publicly linked to the sanctioned "
                "Russian shadow fleet."
            ),
            "evidence": [
                f"MMSI matches {name}",
                f"IMO matches {name}",
                "Flag-of-convenience registration",
            ],
        },
        {
            "suspicion_id": sid,
            "agent": "Behavior Agent",
            "severity": 0.9,
            "finding": (
                f"Sustained loiter below 3 knots inside the {cable} corridor — "
                "consistent with anchor-dragging over the cable."
            ),
            "evidence": [
                "Speed below 3 knots",
                f"Position overlaps {cable} corridor",
                "Slow track sustained across several positions",
            ],
        },
        {
            "suspicion_id": sid,
            "agent": "Sanctions Agent",
            "severity": 0.8,
            "finding": (
                f"{name} and its operator appear on shadow-fleet / sanctions "
                "watchlists; ownership is opaque."
            ),
            "evidence": [
                "OpenSanctions-style watchlist entry",
                "Opaque beneficial ownership",
            ],
        },
        {
            "suspicion_id": sid,
            "agent": "GPS Environment Agent",
            "severity": 0.6,
            "finding": (
                "Elevated GNSS interference reported in the Gulf of Finland — "
                "AIS position should be independently verified."
            ),
            "evidence": [
                "Regional GNSS interference reports",
                "Possible AIS gaps in the area",
            ],
        },
    ]


def assessment(suspicion: dict, findings: list[dict]) -> dict:
    """Return the canned final threat assessment (ThreatAssessment shape).

    `findings` is accepted for signature parity with the future Watch Officer
    synthesis agent; the canned output does not read its contents.
    """
    cable = suspicion.get("cable", "the cable corridor")
    name = suspicion.get("name", "the vessel")
    return {
        "suspicion_id": suspicion["suspicion_id"],
        "level": "HIGH",
        "confidence": 0.86,
        "summary": f"Suspicious vessel movement detected near {cable}.",
        "reasoning": [
            f"{name} loitered slowly inside the {cable} corridor",
            "Vessel is linked to the sanctioned shadow fleet",
            "Critical undersea infrastructure is at risk",
            "AIS/GPS trust may be degraded in the region",
        ],
        "recommended_action": (
            "Escalate to a human watch officer and notify the cable operator. "
            "Do not take automatic action."
        ),
        "voice_script": (
            f"High risk alert. Suspicious vessel movement detected near {cable}. "
            f"{name}, a vessel linked to the sanctioned shadow fleet, loitered "
            "over the cable corridor. Recommend human escalation and independent "
            "verification."
        ),
    }
