"""Aiven Kafka helpers (shared).

Wired in H1-H3 to the real Aiven Kafka service over SASL_SSL (SCRAM-SHA-256).
Public names kept stable so both owners can import them:
  - TOPIC_* constants, ALL_TOPICS
  - is_configured()
  - publish(topic, message)
  - consume(topic[, group_id])  -> generator yielding decoded dict messages

If Kafka isn't configured (DEMO with empty .env), publish/consume degrade to a
print-only stub so the app still boots locally.
"""

import json
from pathlib import Path

from app.config import settings

# Topic names — single source of truth (matches contracts.md).
TOPIC_AIS_RAW = "ais.raw"
TOPIC_VESSEL_SUSPICION = "vessel.suspicion"
TOPIC_AGENT_FINDINGS = "agent.findings"
TOPIC_THREAT_ASSESSMENT = "threat.assessment"
TOPIC_VOICE_BRIEFING = "voice.briefing"
TOPIC_VESSEL_WATCH = "vessel.watch"  # investigation -> Sentinel monitoring hand-off

ALL_TOPICS = [
    TOPIC_AIS_RAW,
    TOPIC_VESSEL_SUSPICION,
    TOPIC_AGENT_FINDINGS,
    TOPIC_THREAT_ASSESSMENT,
    TOPIC_VOICE_BRIEFING,
    TOPIC_VESSEL_WATCH,
]


def is_configured() -> bool:
    return bool(settings.aiven_kafka_bootstrap)


def _ca_path() -> str:
    """Resolve the CA cert path no matter the working directory.

    .env stores AIVEN_KAFKA_CA as 'backend/ca.pem' (relative to the repo root),
    but the app may run from backend/. Try a few sensible locations.
    """
    p = settings.aiven_kafka_ca
    repo_root = Path(__file__).resolve().parents[2]   # <repo>/backend/app/config.. -> <repo>
    candidates = [
        Path(p),                       # relative to cwd
        repo_root / p,                 # <repo>/backend/ca.pem
        repo_root / "backend" / Path(p).name,
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return p


def _conf_base() -> dict:
    return {
        "bootstrap.servers": settings.aiven_kafka_bootstrap,
        "security.protocol": "SASL_SSL",
        "sasl.mechanisms": "SCRAM-SHA-256",
        "sasl.username": settings.aiven_kafka_username,
        "sasl.password": settings.aiven_kafka_password,
        "ssl.ca.location": _ca_path(),
    }


def _producer_conf() -> dict:
    return _conf_base()


def _consumer_conf(group_id: str) -> dict:
    return {**_conf_base(), "group.id": group_id, "auto.offset.reset": "earliest"}


_producer = None


def _get_producer():
    global _producer
    if _producer is None:
        from confluent_kafka import Producer
        _producer = Producer(_producer_conf())
    return _producer


def publish(topic: str, message: dict) -> None:
    """Publish a JSON message to a Kafka topic."""
    payload = json.dumps(message)
    if not is_configured():
        print(f"[kafka:stub] would publish to {topic}: {payload}")
        return
    p = _get_producer()
    p.produce(topic, payload.encode("utf-8"))
    p.flush(5)


def consume(topic: str, group_id: str | None = None):
    """Yield decoded dict messages from a Kafka topic (blocking generator).

    group_id defaults to one per topic so each worker reads independently.
    Usage:  for msg in consume(TOPIC_VESSEL_SUSPICION): ...
    """
    if not is_configured():
        print(f"[kafka:stub] consume({topic}) — no broker configured yet")
        return
    from confluent_kafka import Consumer
    c = Consumer(_consumer_conf(group_id or f"bsentinel-{topic}"))
    c.subscribe([topic])
    try:
        while True:
            msg = c.poll(1.0)
            if msg is None or msg.error():
                continue
            yield json.loads(msg.value().decode("utf-8"))
    finally:
        c.close()
