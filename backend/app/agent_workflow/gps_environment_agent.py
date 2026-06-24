"""Environment & Proximity specialist — Person B.

Answers "can we trust the picture, and what else is around this vessel?"
- get_nearby_vessels -> the live maritime scene (a second loitering vessel, a
  cluster, an escort near the cable) — the "wider picture" no single-vessel view has
- get_cable_context  -> what the threatened cable actually is

This is the agent that looks beyond the one suspect to the situation around it.
"""

from . import agent_base, tools

AGENT = "Environment & Proximity"

_SYSTEM = (
    "You are the Environment & Proximity analyst for Baltic Sentinel. Assess two "
    "things: (1) GPS/AIS TRUST in this area — if the vessel is in a GPS-jamming zone "
    "or has AIS gaps, reported positions and speeds must be treated with low "
    "confidence; (2) the maritime SCENE around the vessel via get_nearby_vessels — is "
    "there a second slow/loitering vessel, an unusual cluster, or an escort near the "
    "cable that changes the picture? Use get_cable_context for what the cable is and "
    "why it matters. If no vessels are nearby or no position is available, say so "
    "plainly. Finish by calling submit_findings with 1-2 findings."
)

_TOOLS = [
    {"name": "get_nearby_vessels",
     "description": "Other live vessels within radius_nm of a point: mmsi,name,flag,ship_type,speed,nav_status,score,is_candidate,distance_nm.",
     "input_schema": {"type": "object", "properties": {
         "lat": {"type": "number"}, "lon": {"type": "number"},
         "radius_nm": {"type": "number", "description": "default 10"}}}},
    {"name": "get_cable_context",
     "description": "Context about the cable corridor (kind, operator, role).",
     "input_schema": {"type": "object", "properties": {"cable": {"type": "string"}}}},
]


def run(suspicion: dict) -> list[dict]:
    lp = suspicion.get("last_position") or {}
    lat, lon = lp.get("lat"), lp.get("lon")
    user = (
        f"Vessel mmsi={suspicion.get('mmsi')} name={suspicion.get('name')!r} at "
        f"lat={lat} lon={lon}, cable={suspicion.get('cable')}.\n"
        f"Scoring reasons (may flag GPS jamming / AIS gaps): {suspicion.get('reasons')}\n\n"
        "Call get_nearby_vessels around its position and get_cable_context, then "
        "submit_findings about GPS/AIS trust and the surrounding scene."
    )
    dispatch = {
        "get_nearby_vessels": lambda inp: tools.get_nearby_vessels(
            inp.get("lat", lat), inp.get("lon", lon),
            radius_nm=float(inp.get("radius_nm", 10)),
            exclude_mmsi=suspicion.get("mmsi")),
        "get_cable_context": lambda inp: tools.get_cable_context(
            inp.get("cable") or suspicion.get("cable")),
    }
    return agent_base.run_specialist(
        agent_name=AGENT, system=_SYSTEM, user=user, suspicion=suspicion,
        tool_defs=_TOOLS, dispatch=dispatch, max_steps=4)
