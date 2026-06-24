"""Aiven Kafka helpers (shared).

H0 stub. Real producer/consumer wiring happens in H1-H3 once Aiven Kafka is
connected. Keep the public function names stable so both owners can import them.
"""

import json

from app.config import settings

# Topic names — single source of truth (matches contracts.md).
TOPIC_AIS_RAW = "ais.raw"
TOPIC_VESSEL_SUSPICION = "vessel.suspicion"
TOPIC_AGENT_FINDINGS = "agent.findings"
TOPIC_THREAT_ASSESSMENT = "threat.assessment"
TOPIC_VOICE_BRIEFING = "voice.briefing"

ALL_TOPICS = [
    TOPIC_AIS_RAW,
    TOPIC_VESSEL_SUSPICION,
    TOPIC_AGENT_FINDINGS,
    TOPIC_THREAT_ASSESSMENT,
    TOPIC_VOICE_BRIEFING,
]


def is_configured() -> bool:
    return bool(settings.aiven_kafka_bootstrap)


def publish(topic: str, message: dict) -> None:
    """Publish a JSON message to a Kafka topic.

    TODO (H1-H3): use confluent_kafka.Producer with the Aiven SASL_SSL config.
    For now this is a no-op-ish stub that just prints, so the app runs locally
    before Kafka exists.
    """
    payload = json.dumps(message)
    if not is_configured():
        print(f"[kafka:stub] would publish to {topic}: {payload}")
        return
    raise NotImplementedError("Real Kafka producer not wired yet (H1-H3).")


def consume(topic: str):
    """Yield messages from a Kafka topic.

    TODO (H1-H3): use confluent_kafka.Consumer. Stub yields nothing for now.
    """
    if not is_configured():
        print(f"[kafka:stub] consume({topic}) — no broker configured yet")
        return
    raise NotImplementedError("Real Kafka consumer not wired yet (H1-H3).")
