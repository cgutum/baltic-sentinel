"""Digitraffic AIS source — Person A.

Polls the Finnish Digitraffic open AIS API (no key, whole Baltic, CORS-open) and
normalizes to `ais.raw` message dicts. This is the ingest spine.

Gotchas handled here:
- `Accept-Encoding: gzip` header is REQUIRED (else HTTP 406).
- The bulk feed includes stale "ghost" vessels going back years — filter by
  `timestampExternal` (epoch ms) to keep only fresh fixes.
- /locations (dynamic) and /vessels (static) are separate; join on mmsi.
"""
import datetime
from typing import Iterable

import requests

_LOCATIONS = "https://meri.digitraffic.fi/api/ais/v1/locations"
_VESSELS = "https://meri.digitraffic.fi/api/ais/v1/vessels"
_HEADERS = {"Accept-Encoding": "gzip", "Digitraffic-User": "baltic-sentinel-hackathon"}

# Gulf of Finland focus box (lat_min, lat_max, lon_min, lon_max).
GOF_BBOX = (59.0, 60.7, 22.0, 30.0)
FRESH_MIN = 15          # drop fixes older than this
DEFAULT_CAP = 400       # max vessels returned per poll (keeps the map sane)

# MMSI MID (first 3 digits) -> flag. Small map: flags-of-convenience + Baltic states.
_MID_FLAG = {
    "518": "Cook Islands", "636": "Liberia", "637": "Liberia", "538": "Marshall Islands",
    "616": "Comoros", "626": "Gabon", "511": "Palau", "671": "Togo", "667": "Sierra Leone",
    "613": "Cameroon", "314": "Barbados", "621": "Djibouti",
    "351": "Panama", "352": "Panama", "353": "Panama", "354": "Panama", "355": "Panama",
    "356": "Panama", "357": "Panama", "370": "Panama", "371": "Panama", "372": "Panama",
    "373": "Panama", "374": "Panama",
    "230": "Finland", "265": "Sweden", "266": "Sweden", "276": "Estonia",
    "275": "Latvia", "277": "Lithuania", "273": "Russia", "211": "Germany", "219": "Denmark",
}


def mmsi_to_flag(mmsi: str) -> str | None:
    return _MID_FLAG.get(str(mmsi)[:3])


def _ship_type(code) -> str:
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "other"
    if 80 <= c <= 89:
        return "tanker"
    if 70 <= c <= 79:
        return "cargo"
    if 60 <= c <= 69:
        return "passenger"
    if 50 <= c <= 59:
        return "service"
    if c == 30:
        return "fishing"
    return "other"


def _in_bbox(lat, lon, bbox) -> bool:
    lo_lat, hi_lat, lo_lon, hi_lon = bbox
    return lo_lat <= lat <= hi_lat and lo_lon <= lon <= hi_lon


def fetch_static() -> dict[str, dict]:
    """mmsi -> {name, imo, type} from the /vessels endpoint."""
    r = requests.get(_VESSELS, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    out = {}
    for v in r.json():
        mmsi = str(v.get("mmsi"))
        imo = v.get("imo")
        out[mmsi] = {
            "name": (v.get("name") or "").strip() or None,
            "imo": str(imo) if imo else None,
            "type": _ship_type(v.get("shipType")),
        }
    return out


def fetch_positions(bbox=GOF_BBOX, fresh_min: int = FRESH_MIN,
                    cap: int = DEFAULT_CAP, static: dict | None = None) -> list[dict]:
    """Return normalized ais.raw dicts for fresh vessels inside bbox."""
    if static is None:
        try:
            static = fetch_static()
        except Exception as e:  # noqa: BLE001 — static is best-effort enrichment
            print(f"[digitraffic] static fetch failed: {e}")
            static = {}
    r = requests.get(_LOCATIONS, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    geo = r.json()
    cutoff_ms = (datetime.datetime.now(datetime.timezone.utc).timestamp() - fresh_min * 60) * 1000

    out: list[dict] = []
    for feat in geo.get("features", []):
        p = feat.get("properties", {})
        coords = (feat.get("geometry") or {}).get("coordinates") or [None, None]
        lon, lat = coords[0], coords[1]
        ts_ext = p.get("timestampExternal")
        if lat is None or lon is None or ts_ext is None:
            continue
        if ts_ext < cutoff_ms:                 # stale ghost
            continue
        if not _in_bbox(lat, lon, bbox):
            continue
        mmsi = str(p.get("mmsi"))
        s = static.get(mmsi, {})
        out.append({
            "mmsi": mmsi,
            "imo": s.get("imo"),
            "name": s.get("name"),
            "ship_type": s.get("type", "other"),
            "flag": mmsi_to_flag(mmsi),
            "lat": lat, "lon": lon,
            "speed": p.get("sog"), "course": p.get("cog"),
            "nav_status": p.get("navStat"),
            "timestamp": datetime.datetime.fromtimestamp(
                ts_ext / 1000, datetime.timezone.utc).isoformat(),
            "source": "digitraffic",
        })
    out.sort(key=lambda v: v["timestamp"], reverse=True)
    return out[:cap]
