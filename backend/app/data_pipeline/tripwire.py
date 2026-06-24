"""Tripwire detector — Person A (H5-H7).

Consumes `ais.raw`; when a vessel is slow inside a cable corridor it publishes a
`vessel.suspicion` message (which Person B's agents wake up on) and saves it to
Postgres `suspicion_events`.

Run as a worker:  python -m app.data_pipeline.tripwire
"""
import datetime
import uuid

from .. import database
from ..kafka_client import publish, consume, TOPIC_AIS_RAW, TOPIC_VESSEL_SUSPICION
from . import geo_rules

# Rule threshold: "loiter over cable" = slow speed inside a corridor.
SLOW_KN = 3.0

# Fire at most one suspicion per vessel per process lifetime (avoids spamming on
# every slow position). Reset by restarting the worker.
_flagged: set[str] = set()

_REQUIRED = ("mmsi", "lat", "lon", "speed", "timestamp")


def _valid(msg: dict) -> bool:
    return all(k in msg and msg[k] is not None for k in _REQUIRED)


def detect(msg: dict):
    """Return a suspicion dict if the message trips a rule, else None.

    Pure: no side effects, no dedup — safe to call in tests.
    """
    if not _valid(msg):
        return None
    cable = geo_rules.cable_near(msg["lat"], msg["lon"])
    if cable and msg["speed"] < SLOW_KN:
        return {
            "suspicion_id": "sus_" + uuid.uuid4().hex[:8],
            "mmsi": msg["mmsi"],
            "imo": msg.get("imo"),
            "name": msg.get("name"),
            "rule": "slow_near_cable",
            "cable": cable,
            "severity": 0.85,
            "summary": f"Vessel moving below {SLOW_KN} knots inside {cable} cable corridor.",
            "timestamp": msg.get("timestamp") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    return None


def _save(s: dict) -> None:
    if not database.is_configured():
        return
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO suspicion_events "
                "(suspicion_id,mmsi,imo,name,rule,cable,severity,summary,ts) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (suspicion_id) DO NOTHING",
                (s["suspicion_id"], s["mmsi"], s.get("imo"), s.get("name"), s["rule"],
                 s["cable"], s["severity"], s["summary"], s["timestamp"]),
            )
        conn.commit()


def handle(msg: dict):
    """Process one ais.raw message: fire + persist a suspicion if warranted.

    Returns the suspicion dict if one was fired, else None. Skips malformed
    messages and dedups per vessel.
    """
    if not _valid(msg):
        print(f"[tripwire] skip malformed message: {msg!r:.80}")
        return None
    if msg["mmsi"] in _flagged:
        return None
    s = detect(msg)
    if s:
        _flagged.add(msg["mmsi"])
        publish(TOPIC_VESSEL_SUSPICION, s)
        _save(s)
        print(f"[tripwire] SUSPICION {s['suspicion_id']} {s.get('name')} near {s['cable']}")
        return s
    return None


def run() -> None:
    print("[tripwire] listening on ais.raw ...")
    for msg in consume(TOPIC_AIS_RAW, group_id="tripwire"):
        try:
            handle(msg)
        except Exception as e:  # noqa: BLE001 — a bad message must not kill the worker
            print(f"[tripwire] error handling message: {e}")


if __name__ == "__main__":
    run()
