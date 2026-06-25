"""State builder — Person A.

Consumes `ais.raw`, upserts each vessel's latest state into Postgres `vessels`,
and recomputes its suspicion score. A periodic `sweep()` re-scores known vessels
against the current time to catch AIS gaps (a silent vessel emits no message, so
the gap can only be found by scanning, not reactively).

Run as a worker:  python -m app.data_pipeline.state_builder
"""
import datetime
import threading
import time
from collections import defaultdict, deque

from .. import database, scoring
from ..kafka_client import consume, TOPIC_AIS_RAW

SWEEP_SEC = 30
_REQUIRED = ("mmsi", "lat", "lon", "speed", "timestamp")

# Per-vessel rolling position buffer for the anchor-drag signature.
_tracks: dict[str, deque] = defaultdict(lambda: deque(maxlen=8))


def _valid(msg: dict) -> bool:
    return all(k in msg and msg[k] is not None for k in _REQUIRED)


def _state_from_msg(msg: dict) -> dict:
    nav = msg.get("nav_status")
    return {
        "mmsi": str(msg["mmsi"]), "imo": msg.get("imo"), "name": msg.get("name"),
        "ship_type": msg.get("ship_type", "other"), "flag": msg.get("flag"),
        "last_lat": msg["lat"], "last_lon": msg["lon"],
        "last_speed": msg["speed"], "last_course": msg.get("course"),
        "nav_status": str(nav) if nav is not None else None,
        "last_seen": msg["timestamp"],
    }


def _append_track(st: dict) -> None:
    """Persist this position to the `tracks` table (best-effort).

    Gives Person B's agents a REAL movement history per vessel instead of a mock
    track. Best-effort: a write failure must not stop the consumer.
    """
    if not database.is_configured():
        return
    try:
        with database.get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tracks (mmsi,imo,name,lat,lon,speed,course,ts,source) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (st["mmsi"], st.get("imo"), st.get("name"), st["last_lat"], st["last_lon"],
                 st.get("last_speed"), st.get("last_course"), st.get("last_seen"), "digitraffic"),
            )
            conn.commit()
    except Exception as e:  # noqa: BLE001 — a bad track write must not kill the worker
        print(f"[state_builder] track write failed: {e}")


def handle(msg: dict) -> dict | None:
    """Process one ais.raw message: score + upsert + append track. Returns the record."""
    if not _valid(msg):
        return None
    st = _state_from_msg(msg)
    _tracks[st["mmsi"]].append({"lat": st["last_lat"], "lon": st["last_lon"],
                                "speed": st["last_speed"], "course": st["last_course"]})
    score, reasons, _ = scoring.score_vessel(st, track=list(_tracks[st["mmsi"]]))
    st["suspicion_score"] = score
    st["suspicion_reasons"] = reasons
    st["is_candidate"] = scoring.is_candidate(score)
    database.upsert_vessel(st)
    _append_track(st)
    return st


def sweep() -> int:
    """Re-score known vessels with the current time to catch AIS gaps. Returns #changed."""
    if not database.is_configured():
        return 0
    now = datetime.datetime.now(datetime.timezone.utc)
    changed = 0
    for v in database.get_vessels(limit=1000):
        score, reasons, _ = scoring.score_vessel(v, now=now)
        if score != v.get("suspicion_score") or scoring.is_candidate(score) != v.get("is_candidate"):
            v["suspicion_score"] = score
            v["suspicion_reasons"] = reasons
            v["is_candidate"] = scoring.is_candidate(score)
            database.upsert_vessel(v)
            changed += 1
    return changed


def _sweep_loop() -> None:
    while True:
        time.sleep(SWEEP_SEC)
        try:
            n = sweep()
            if n:
                print(f"[state_builder] sweep updated {n} vessels (AIS-gap re-score)")
        except Exception as e:  # noqa: BLE001
            print(f"[state_builder] sweep error: {e}")


def run() -> None:
    print("[state_builder] consuming ais.raw ...")
    database.init_tables()  # ensure vessels/tracks tables + indexes exist before writing
    threading.Thread(target=_sweep_loop, daemon=True).start()
    for msg in consume(TOPIC_AIS_RAW, group_id="state_builder-v2", offset_reset="latest"):
        try:
            handle(msg)
        except Exception as e:  # noqa: BLE001 — a bad message must not kill the worker
            print(f"[state_builder] handle error: {e}")


if __name__ == "__main__":
    run()
