"""Cable-corridor / geo helpers — Person A.

Undersea-cable routes are stylized/approximate (real seabed paths are classified),
so we detect proximity to a buffered CORRIDOR, never an exact line.

`cable_near(lat, lon)` -> name of the cable corridor containing the point, else None.
"""
from shapely.geometry import Point, LineString

# Approximate Gulf-of-Finland cable lines as (lon, lat) pairs.
_CABLES = {
    "Estlink 2": LineString([(24.90, 59.45), (25.00, 60.05)]),
    "Estlink 1": LineString([(25.30, 59.50), (25.40, 60.05)]),
    "Balticconnector": LineString([(23.80, 59.45), (24.10, 60.00)]),
}

# ~5 km buffer in degrees (rough but fine for the demo).
_BUFFER_DEG = 0.05
_CORRIDORS = {name: line.buffer(_BUFFER_DEG) for name, line in _CABLES.items()}


def cable_near(lat: float, lon: float):
    """Return the name of the cable corridor containing (lat, lon), or None."""
    pt = Point(lon, lat)  # shapely is (x=lon, y=lat)
    for name, corridor in _CORRIDORS.items():
        if corridor.contains(pt):
            return name
    return None
