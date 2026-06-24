"""GPSJam loader — Person A.

Downloads the most recent available daily GPS-interference file (H3 resolution-4
hexes), caches it under backend/data/, builds the set of "bad" hexes, and offers
in_jammed_zone(lat, lon). Degrades to False if no data is available.

CSV columns: hex, count_good_aircraft, count_bad_aircraft
A hex is "bad" if >=10% of aircraft were degraded AND >=3 aircraft sampled.
"""
import csv
import datetime
from pathlib import Path

import h3
import requests

_DIR = Path(__file__).resolve().parents[3] / "data"  # backend/data/
_URL = "https://gpsjam.org/data/{date}-h3_4.csv"
_MIN_PCT = 0.10
_MIN_AIRCRAFT = 3

_bad_hexes: set[str] = set()
_loaded = False


def _candidate_dates() -> list[datetime.date]:
    # today's file is usually not published until the day completes
    today = datetime.date.today()
    return [today - datetime.timedelta(days=d) for d in (1, 2, 3)]


def _ensure_file() -> Path | None:
    for d in _candidate_dates():
        p = _DIR / f"gpsjam-{d.isoformat()}.csv"
        if p.exists():
            return p
        try:
            r = requests.get(_URL.format(date=d.isoformat()), timeout=30)
            if r.status_code == 200 and r.content:
                _DIR.mkdir(parents=True, exist_ok=True)
                p.write_bytes(r.content)
                return p
        except Exception as e:  # noqa: BLE001
            print(f"[gpsjam] fetch {d} failed: {e}")
    return None


def load(force: bool = False) -> None:
    global _loaded
    if _loaded and not force:
        return
    p = _ensure_file()
    if not p:
        print("[gpsjam] no data; in_jammed_zone() -> False")
        _loaded = True
        return
    with open(p, encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or row[0] == "hex":
                continue
            try:
                hx, good, bad = row[0], int(row[1]), int(row[2])
            except (ValueError, IndexError):
                continue
            total = good + bad
            if total >= _MIN_AIRCRAFT and bad / total >= _MIN_PCT:
                _bad_hexes.add(hx)
    _loaded = True
    print(f"[gpsjam] {len(_bad_hexes)} bad hexes from {p.name}")


def in_jammed_zone(lat: float, lon: float) -> bool:
    if not _loaded:
        load()
    if not _bad_hexes:
        return False
    try:
        return h3.latlng_to_cell(lat, lon, 4) in _bad_hexes
    except Exception:  # noqa: BLE001
        return False
