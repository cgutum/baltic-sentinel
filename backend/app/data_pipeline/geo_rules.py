"""Cable-corridor / geo helpers — Person A.

Undersea-cable routes are stylized/approximate (real seabed paths are classified),
so we detect proximity to a buffered CORRIDOR, never an exact line. Geometry below
uses the real public landing points of each link.

  cable_near(lat, lon)    -> name of the cable corridor containing the point, else None
  nearest_cable(lat, lon) -> (name, distance_km) of the closest corridor (any distance)
  port_near(lat, lon)     -> True if within a major port/anchorage (harbour traffic)
  CABLES                  -> {name: {"kind","coords"}} for the frontend / data export
"""
import math

from shapely.geometry import Point, LineString

# Real landing points (lon, lat). Power = interconnectors/pipeline, telecom = data.
CABLES = {
    "Estlink 2":       {"kind": "power",   "coords": [(25.55, 60.43), (26.0, 60.10), (26.5, 59.80), (26.99, 59.36)]},  # Anttila/Porvoo FI – Püssi EE
    "Estlink 1":       {"kind": "power",   "coords": [(24.557, 60.203), (24.56, 59.80), (24.561, 59.396)]},            # Espoo FI – Harku EE
    "Balticconnector": {"kind": "power",   "coords": [(23.92, 60.045), (23.98, 59.70), (24.03, 59.35)]},               # Inkoo FI – Paldiski EE (gas)
    "C-Lion1":         {"kind": "telecom", "coords": [(25.00, 60.15), (24.30, 59.70), (23.50, 59.40)]},                # Helsinki FI – Rostock DE (GoF segment)
}

_BUFFER_DEG = 0.045  # ~5 km
_LINES = {n: LineString(c["coords"]) for n, c in CABLES.items()}
_CORRIDORS = {n: line.buffer(_BUFFER_DEG) for n, line in _LINES.items()}

# Major Gulf-of-Finland ports / anchorages (lon, lat). A slow vessel here is normal
# harbour traffic, NOT a cable threat — used to suppress false positives.
_PORTS = [
    ("Helsinki", 24.95, 60.15), ("Vuosaari", 25.19, 60.21), ("Kantvik/Inkoo", 24.0, 60.04),
    ("Hanko", 22.97, 59.82), ("Sköldvik/Porvoo", 25.55, 60.30), ("Kotka", 26.95, 60.47),
    ("Hamina", 27.18, 60.55), ("Tallinn", 24.78, 59.44), ("Muuga", 24.95, 59.50),
    ("Paldiski", 24.05, 59.35), ("Sillamäe", 27.74, 59.42), ("Ust-Luga", 28.38, 59.67),
    ("Primorsk", 28.61, 60.34), ("Vysotsk/Vyborg", 28.6, 60.62), ("St Petersburg", 29.7, 59.93),
]
_PORT_RADIUS_KM = 7.0


def _km(lon1, lat1, lon2, lat2) -> float:
    """Fast local-plane distance in km (fine at Baltic latitudes)."""
    dx = (lon2 - lon1) * 111.320 * math.cos(math.radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * 110.574
    return math.hypot(dx, dy)


def cable_near(lat: float, lon: float):
    """Return the name of the cable corridor containing (lat, lon), or None."""
    pt = Point(lon, lat)  # shapely is (x=lon, y=lat)
    for name, corridor in _CORRIDORS.items():
        if corridor.contains(pt):
            return name
    return None


def nearest_cable(lat: float, lon: float):
    """Return (name, distance_km) of the closest cable corridor centreline."""
    pt = Point(lon, lat)
    best, bestd = None, 1e9
    for name, line in _LINES.items():
        # shapely distance is in degrees; convert roughly via the point/projection
        npt = line.interpolate(line.project(pt))
        dkm = _km(lon, lat, npt.x, npt.y)
        if dkm < bestd:
            best, bestd = name, dkm
    return best, round(bestd, 1)


def port_near(lat: float, lon: float, radius_km: float = _PORT_RADIUS_KM) -> bool:
    """True if (lat, lon) is within a major port/anchorage (normal harbour traffic)."""
    return any(_km(lon, lat, plon, plat) <= radius_km for _, plon, plat in _PORTS)
