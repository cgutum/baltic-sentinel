"""Ingest worker — Person A.

Polls the Digitraffic open AIS API and produces normalized positions to the
`ais.raw` Kafka topic. This is the ingest spine AND the Kafka heartbeat (keeps the
free-tier broker from idling off).

Run as a worker:  python -m app.data_pipeline.ingest
"""
import time

from ..kafka_client import publish, TOPIC_AIS_RAW
from .sources import digitraffic

POLL_SEC = 60


def poll_once() -> int:
    """Fetch one snapshot and produce it to ais.raw. Returns count produced."""
    positions = digitraffic.fetch_positions()
    for p in positions:
        publish(TOPIC_AIS_RAW, p)
    return len(positions)


def run(poll_sec: int = POLL_SEC) -> None:
    print(f"[ingest] polling Digitraffic -> ais.raw every {poll_sec}s")
    while True:
        try:
            n = poll_once()
            print(f"[ingest] produced {n} positions")
        except Exception as e:  # noqa: BLE001 — a bad poll must not kill the worker
            print(f"[ingest] poll error: {e}")
        time.sleep(poll_sec)


if __name__ == "__main__":
    run()
