"""Eagle S replay producer — Person A (H3-H5).

Injects a synthetic Eagle S track into Kafka topic `ais.raw` exactly like a real
ship, so it flows through the SAME tripwire -> agents -> dossier path, and saves
each position to Postgres `tracks`.

The track drifts slowly across the Estlink 2 corridor (speed < 3 kn while inside),
so the tripwire reliably fires. Be transparent in the pitch that it's a
reconstruction of the publicly reported Christmas 2024 incident.

Trigger via:  POST /replay/eagle-s
"""
import datetime
import threading
import time

from .. import database
from ..kafka_client import publish, TOPIC_AIS_RAW

# Eagle S identity (matches contracts.md + a real OpenSanctions entry).
EAGLE_S = {"mmsi": "518998000", "imo": "9329760", "name": "Eagle S"}

# Synthetic drift across the Estlink 2 corridor (lat, lon, speed_kn, course_deg).
# Middle points sit inside the corridor at < 3 kn -> trips "slow_near_cable".
_TRACK = [
    {"lat": 59.62, "lon": 24.88, "speed": 6.0, "course": 15},   # approaching
    {"lat": 59.66, "lon": 24.90, "speed": 3.4, "course": 18},   # slowing
    {"lat": 59.69, "lon": 24.91, "speed": 2.2, "course": 25},   # slow, in corridor
    {"lat": 59.71, "lon": 24.92, "speed": 1.6, "course": 30},   # slow, in corridor
    {"lat": 59.73, "lon": 24.93, "speed": 1.9, "course": 35},   # slow, in corridor
    {"lat": 59.76, "lon": 24.95, "speed": 4.8, "course": 40},   # leaving
]


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _run(interval: float) -> None:
    conn = database.get_connection() if database.is_configured() else None
    try:
        for i, p in enumerate(_TRACK):
            msg = {
                **EAGLE_S,
                "lat": p["lat"], "lon": p["lon"],
                "speed": p["speed"], "course": p["course"],
                "timestamp": _now_iso(),
                "source": "replay",
            }
            publish(TOPIC_AIS_RAW, msg)
            if conn is not None:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO tracks (mmsi,imo,name,lat,lon,speed,course,ts,source) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (msg["mmsi"], msg["imo"], msg["name"], msg["lat"], msg["lon"],
                         msg["speed"], msg["course"], msg["timestamp"], msg["source"]),
                    )
                conn.commit()
            print(f"[replay] {i+1}/{len(_TRACK)} lat={p['lat']} lon={p['lon']} sog={p['speed']}")
            time.sleep(interval)
        print("[replay] Eagle S replay complete")
    finally:
        if conn is not None:
            conn.close()


def start(interval: float = 1.0) -> dict:
    """Start the replay in a background thread so the HTTP call returns fast."""
    threading.Thread(target=_run, args=(interval,), daemon=True).start()
    return {"status": "started", "vessel": EAGLE_S["name"], "points": len(_TRACK)}
