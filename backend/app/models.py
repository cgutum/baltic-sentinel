"""Pydantic models for the Kafka message formats defined in contracts.md.

Shared file — announce before editing. Keep these in sync with contracts.md.
"""

from typing import List, Optional

from pydantic import BaseModel


class AisRaw(BaseModel):
    """Topic: ais.raw (Person A)."""

    mmsi: str
    imo: Optional[str] = None
    name: str
    lat: float
    lon: float
    speed: float
    course: float
    timestamp: str
    source: str = "replay"


class VesselSuspicion(BaseModel):
    """Topic: vessel.suspicion (Person A → Person B)."""

    suspicion_id: str
    mmsi: str
    imo: Optional[str] = None
    name: str
    rule: str
    cable: str
    severity: float
    summary: str
    timestamp: str


class AgentFinding(BaseModel):
    """Topic: agent.findings (Person B). One per Claude agent."""

    suspicion_id: str
    agent: str
    severity: float
    finding: str
    evidence: List[str] = []


class ThreatAssessment(BaseModel):
    """Topic: threat.assessment (Person B). Final synthesis output."""

    suspicion_id: str
    level: str  # LOW | MEDIUM | HIGH
    confidence: float
    summary: str
    reasoning: List[str] = []
    recommended_action: str
    voice_script: str
