"""Agent tools — Person B ("Option A" capability layer).

These are the plain functions the orchestrator calls. Later (H5+) the same
functions become the Claude Managed Agent's custom tools, executed by a local
orchestrator — so keeping signatures stable here avoids touching call sites.

Two kinds:
  - READ tools  -> in DEMO_MODE return canned data; a `# TODO live` branch is
                   where the real Postgres/web lookups go later.
  - ACTION tools -> publish to Kafka and (if Postgres is configured) persist.
                    Guarded so they work fully offline (print-only) AND for free
                    when Aiven is connected.

Mirrors Person A's conventions: reuse kafka_client.publish, guard DB writes on
database.is_configured(), `[tag]` print logging.
"""

import json
from pathlib import Path

from .. import database
from ..kafka_client import (
    publish,
    TOPIC_AGENT_FINDINGS,
    TOPIC_THREAT_ASSESSMENT,
    TOPIC_VOICE_BRIEFING,
)
from . import fallback_outputs

# Repo root: <repo>/backend/app/agent_workflow/tools.py -> parents[3] == <repo>
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SAMPLE_VOICE = _REPO_ROOT / "demo_assets" / "sample_voice.mp3"


# --------------------------------------------------------------------------- #
# READ tools (DEMO: canned; TODO live at H5+)
# --------------------------------------------------------------------------- #
def get_suspicion_event(suspicion_id: str | None = None) -> dict:
    """Return the suspicion to investigate. DEMO: the canned Eagle S event."""
    # TODO live (H5+): SELECT ... FROM suspicion_events WHERE suspicion_id=...
    return fallback_outputs.SAMPLE_SUSPICION


def get_recent_track(mmsi: str) -> list[dict]:
    """Return recent positions for a vessel. DEMO: a canned slow-drift track."""
    # TODO live (H5+): SELECT lat,lon,speed,course,ts FROM tracks WHERE mmsi=...
    return [
        {"lat": 59.66, "lon": 24.90, "speed": 3.4, "course": 18},
        {"lat": 59.69, "lon": 24.91, "speed": 2.2, "course": 25},
        {"lat": 59.71, "lon": 24.92, "speed": 1.6, "course": 30},
        {"lat": 59.73, "lon": 24.93, "speed": 1.9, "course": 35},
    ]


def get_vessel_identity(mmsi: str, imo: str | None = None) -> dict:
    """Return vessel identity. DEMO: canned Eagle S identity."""
    # TODO live (H5+): identity lookup / AIS static data
    return {
        "mmsi": mmsi,
        "imo": imo,
        "name": "Eagle S",
        "type": "Oil/chemical tanker",
        "flag": "Cook Islands",
    }


def lookup_sanctions(name: str, imo: str | None = None) -> dict:
    """Return sanctions/watchlist status. DEMO: canned listed result."""
    # TODO live (H5+): OpenSanctions API / web search
    return {
        "listed": True,
        "source": "OpenSanctions (demo)",
        "note": "Linked to the sanctioned Russian shadow fleet.",
    }


def check_gps_environment(lat: float, lon: float) -> dict:
    """Return GNSS-trust context for a location. DEMO: canned elevated risk."""
    # TODO live (H5+): space-weather / jamming feeds
    return {
        "gnss_interference": "elevated",
        "confidence": 0.6,
        "note": "Independent position verification recommended.",
    }


def get_cable_context(cable: str) -> dict:
    """Return context about a cable corridor. DEMO: static Estlink 2 facts."""
    # TODO live (H5+): cable registry
    return {
        "cable": cable,
        "kind": "HVDC power interconnector",
        "operator": "Fingrid / Elering",
        "note": "Critical cross-border infrastructure.",
    }


# --------------------------------------------------------------------------- #
# ACTION tools (publish to Kafka; persist if Postgres is configured)
# --------------------------------------------------------------------------- #
def write_finding(finding: dict) -> None:
    """Publish one agent finding and persist it (if Postgres is configured)."""
    publish(TOPIC_AGENT_FINDINGS, finding)
    if not database.is_configured():
        return
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_findings "
                "(suspicion_id, agent, severity, finding, evidence) "
                "VALUES (%s,%s,%s,%s,%s)",
                (
                    finding["suspicion_id"],
                    finding["agent"],
                    finding["severity"],
                    finding["finding"],
                    json.dumps(finding.get("evidence", [])),
                ),
            )
        conn.commit()


def save_assessment(assessment: dict, voice_path: str | None = None) -> None:
    """Publish the final assessment and upsert it (if Postgres is configured)."""
    publish(TOPIC_THREAT_ASSESSMENT, assessment)
    if not database.is_configured():
        return
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO assessments "
                "(suspicion_id, level, confidence, summary, reasoning, "
                "recommended_action, voice_script, voice_path) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (suspicion_id) DO UPDATE SET "
                "level=EXCLUDED.level, confidence=EXCLUDED.confidence, "
                "summary=EXCLUDED.summary, reasoning=EXCLUDED.reasoning, "
                "recommended_action=EXCLUDED.recommended_action, "
                "voice_script=EXCLUDED.voice_script, voice_path=EXCLUDED.voice_path",
                (
                    assessment["suspicion_id"],
                    assessment["level"],
                    assessment["confidence"],
                    assessment["summary"],
                    json.dumps(assessment.get("reasoning", [])),
                    assessment["recommended_action"],
                    assessment["voice_script"],
                    voice_path,
                ),
            )
        conn.commit()


def create_voice_briefing(voice_script: str, suspicion_id: str) -> dict:
    """Create the spoken briefing. DEMO: no ElevenLabs — point at the fallback mp3.

    Signature locked at (voice_script, suspicion_id) now: the real ElevenLabs
    impl (H13, in voice.py) needs suspicion_id for the voice.briefing message
    and the assessments.voice_path link, so the orchestrator call site won't change.
    Never fails when the mp3 is missing — the done-when is a confirmation, not a file.
    """
    path = str(_SAMPLE_VOICE)
    exists = _SAMPLE_VOICE.exists()
    print(f"[voice:stub] would create voice briefing -> {path} ({len(voice_script)} chars)")
    publish(
        TOPIC_VOICE_BRIEFING,
        {"suspicion_id": suspicion_id, "voice_path": path, "voice_script": voice_script},
    )
    return {"voice_path": path, "exists": exists}
