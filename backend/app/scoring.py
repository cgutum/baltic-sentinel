"""Suspicion scoring — Person A.

Transparent, weighted, rule-based score. Each feature adds points AND a
human-readable reason, so every flag is explainable (that explainability is the
product). No black-box ML.

    score, reasons, top_cable = score_vessel(state, track=None, now=None)

- state: dict with mmsi, imo, name, flag, last_lat, last_lon, last_speed,
         last_course, last_seen (datetime or ISO str)
- track: optional list of recent positions [{lat,lon,speed,course,ts}, ...]
         used only for the anchor-drag signature
- now:   optional datetime; when given, enables the AIS-gap feature (used by
         state_builder.sweep() — a silent vessel emits no message, so the gap
         can only be detected by a periodic scan, not reactively)

is_candidate when score >= THRESHOLD. Score is capped at 100.
"""
import datetime
import math

from .data_pipeline import geo_rules
from .data_pipeline.loaders import sanctions, gpsjam

WEIGHTS = {
    "slow_near_cable": 35,
    "sanctions": 30,
    "ais_gap": 25,
    "anchor_drag": 20,
    "jammed": 15,
    "foc": 10,
}
THRESHOLD = 50
SLOW_KN = 3.0
# A vessel at exactly 0 kn is docked/anchored (often in port zones that overlap our
# corridors). Loiter / anchor-drag is SLOW BUT MOVING. Require movement to flag.
MOVING_MIN_KN = 0.2
AIS_GAP_MIN = 15
ANCHOR_DRAG_MAX_KN = 4.0
ANCHOR_DRAG_SPREAD_DEG = 60

FLAGS_OF_CONVENIENCE = {
    "Cook Islands", "Gabon", "Comoros", "Palau", "Panama", "Liberia",
    "Marshall Islands", "Cameroon", "Barbados", "Togo", "Sierra Leone", "Djibouti",
}


def _parse_ts(ts) -> datetime.datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime.datetime):
        return ts
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _heading_spread(courses: list[float]) -> float:
    """Circular spread of headings, 0 (aligned) .. 180 (erratic)."""
    if not courses:
        return 0.0
    xs = sum(math.cos(math.radians(c)) for c in courses) / len(courses)
    ys = sum(math.sin(math.radians(c)) for c in courses) / len(courses)
    r = math.hypot(xs, ys)  # 1 = consistent heading, 0 = all over the place
    return (1 - r) * 180


def score_vessel(state: dict, track: list[dict] | None = None,
                 now: datetime.datetime | None = None):
    score = 0
    reasons: list[str] = []
    lat, lon = state.get("last_lat"), state.get("last_lon")
    spd = state.get("last_speed")
    cable = geo_rules.cable_near(lat, lon) if lat is not None and lon is not None else None

    # 1. Slow but MOVING over a cable corridor (excludes docked/anchored 0-kn ships)
    if cable and spd is not None and MOVING_MIN_KN <= spd < SLOW_KN:
        score += WEIGHTS["slow_near_cable"]
        reasons.append(f"Slow ({spd:.1f} kn) inside {cable} corridor")

    # 2. Sanctions / detention record
    hit = sanctions.lookup(imo=state.get("imo"), name=state.get("name"))
    if hit and (hit.get("risk") or "").strip():
        score += WEIGHTS["sanctions"]
        reasons.append(f"Sanctions/detention record: {hit['risk']}")

    # 3. AIS gap (silent vessel near a cable) — only when `now` is supplied
    last_seen = _parse_ts(state.get("last_seen"))
    if cable and now and last_seen:
        gap_min = (now - last_seen).total_seconds() / 60
        if gap_min >= AIS_GAP_MIN:
            score += WEIGHTS["ais_gap"]
            reasons.append(f"AIS silent {gap_min:.0f} min near {cable}")

    # 4. Anchor-drag signature: slow + erratic heading over a corridor
    if cable and track and len(track) >= 3:
        speeds = [p["speed"] for p in track if p.get("speed") is not None]
        courses = [p["course"] for p in track if p.get("course") is not None]
        if speeds and courses and max(speeds) < ANCHOR_DRAG_MAX_KN:
            spread = _heading_spread(courses)
            if spread >= ANCHOR_DRAG_SPREAD_DEG:
                score += WEIGHTS["anchor_drag"]
                reasons.append(f"Erratic heading ({spread:.0f} deg) while slow over {cable}")

    # 5. Inside a GPS-jamming zone near a cable
    if cable and lat is not None and gpsjam.in_jammed_zone(lat, lon):
        score += WEIGHTS["jammed"]
        reasons.append("Inside GPS-jamming zone; AIS unreliable here")

    # 6. Flag of convenience
    flag = state.get("flag")
    if flag in FLAGS_OF_CONVENIENCE:
        score += WEIGHTS["foc"]
        reasons.append(f"Flag of convenience: {flag}")

    return min(score, 100), reasons, cable


def is_candidate(score: int) -> bool:
    return score >= THRESHOLD
