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
import os
from pathlib import Path

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
    """Kafka client config with two auth modes.

    - SSL/mTLS when the Aiven Application integration injects cert env vars
      (KAFKA_ACCESS_CERT / KAFKA_ACCESS_KEY [/ KAFKA_CA_CERT]). The values may be
      raw PEM contents or file paths — we detect and handle both.
    - SASL_SSL / SCRAM-SHA-256 otherwise (local dev + the current live service).
    """
    bootstrap = (os.getenv("KAFKA_SERVICE_URI") or os.getenv("KAFKA_BOOTSTRAP_SERVERS")
                 or settings.aiven_kafka_bootstrap)
    cert, key = os.getenv("KAFKA_ACCESS_CERT"), os.getenv("KAFKA_ACCESS_KEY")
    if cert and key:
        conf = {"bootstrap.servers": bootstrap, "security.protocol": "SSL"}
        # confluent-kafka takes either an inline PEM (*.pem) or a file path (*.location).
        for val, pem_key, loc_key in (
            (cert, "ssl.certificate.pem", "ssl.certificate.location"),
            (key, "ssl.key.pem", "ssl.key.location"),
            (os.getenv("KAFKA_CA_CERT"), "ssl.ca.pem", "ssl.ca.location"),
        ):
            if val:
                conf[loc_key if os.path.exists(val) else pem_key] = val
        return conf
    sasl = {
        "bootstrap.servers": bootstrap,
        "security.protocol": "SASL_SSL",
        "sasl.mechanisms": "SCRAM-SHA-256",
        "sasl.username": settings.aiven_kafka_username,
        "sasl.password": settings.aiven_kafka_password,
    }
    ca = _ca_path()
    if os.path.exists(ca):
        sasl["ssl.ca.location"] = ca
    else:
        # Deploy/demo fallback: no CA file shipped (it's gitignored). Encrypt but skip
        # CA verification so the container can still reach the broker. Set KAFKA_CA_PEM
        # (written to a file by start.sh) to restore full verification.
        sasl["enable.ssl.certificate.verification"] = False
        print("[kafka] CA file not found; SSL cert verification disabled (deploy fallback)")
    return sasl


def _producer_conf() -> dict:
    return _conf_base()


def _consumer_conf(group_id: str, offset_reset: str = "earliest") -> dict:
    return {**_conf_base(), "group.id": group_id, "auto.offset.reset": offset_reset}


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


def consume(topic: str, group_id: str | None = None, offset_reset: str = "earliest"):
    """Yield decoded dict messages from a Kafka topic (blocking generator).

    group_id defaults to one per topic so each worker reads independently.
    Logs partition assignment + a periodic poll/msg heartbeat so a silent
    consumer (no assignment / no messages) is diagnosable in the deploy logs.
    Usage:  for msg in consume(TOPIC_VESSEL_SUSPICION): ...
    """
    if not is_configured():
        print(f"[kafka:stub] consume({topic}) — no broker configured yet")
        return
    from confluent_kafka import Consumer
    gid = group_id or f"bsentinel-{topic}"
    c = Consumer(_consumer_conf(gid, offset_reset))

    def _on_assign(_c, partitions):
        desc = ", ".join(f"{p.topic}[{p.partition}]@{p.offset}" for p in partitions) or "(none)"
        print(f"[kafka] {topic} group={gid} assigned: {desc}", flush=True)

    c.subscribe([topic], on_assign=_on_assign)
    polls = got = 0
    try:
        while True:
            msg = c.poll(1.0)
            polls += 1
            if polls % 30 == 0:
                print(f"[kafka] {topic} group={gid}: {polls} polls, {got} msgs", flush=True)
            if msg is None:
                continue
            if msg.error():
                print(f"[kafka] {topic} poll error: {msg.error()}", flush=True)
                continue
            got += 1
            yield json.loads(msg.value().decode("utf-8"))
    finally:
        c.close()
