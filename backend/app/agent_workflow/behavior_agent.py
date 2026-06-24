"""Behavior & History specialist — Person B.

Answers "how is this vessel actually moving, and has it done this before?"
- get_recent_track   -> the REAL recorded track (may be empty)
- get_vessel_history -> prior suspicion events for this MMSI

Honest about movement: if the track is empty it must say so, not invent loitering.
"""

from . import agent_base, tools

AGENT = "Behavior & History"

_SYSTEM = (
    "You are the Behavior & History analyst for Baltic Sentinel. Use get_recent_track "
    "to examine how the vessel has actually moved, and get_vessel_history for prior "
    "incidents involving this MMSI. Rules: if get_recent_track returns an EMPTY list, "
    "state that movement history is unavailable — do NOT invent or describe movement. "
    "Carefully distinguish a STOPPED/anchored vessel (~0 kn) from SLOW LOITERING "
    "(moving below 3 kn): they mean different things over a cable. Note repeat behavior "
    "if prior suspicions exist. Finish by calling submit_findings with 1-2 findings."
)

_TOOLS = [
    {"name": "get_recent_track",
     "description": "Recent positions for the vessel (lat,lon,speed,course,ts), oldest first. MAY BE EMPTY.",
     "input_schema": {"type": "object", "properties": {"mmsi": {"type": "string"}}}},
    {"name": "get_vessel_history",
     "description": "Prior suspicion events for this MMSI + how many track points are on record.",
     "input_schema": {"type": "object", "properties": {"mmsi": {"type": "string"}}}},
]


def run(suspicion: dict) -> list[dict]:
    mmsi = suspicion.get("mmsi")
    last = suspicion.get("last_position") or {}
    user = (
        f"Vessel mmsi={mmsi} name={suspicion.get('name')!r} near cable={suspicion.get('cable')}.\n"
        f"Last reported position/speed: {last}\n"
        f"Scoring reasons so far: {suspicion.get('reasons')}\n\n"
        "Call get_recent_track and get_vessel_history, then submit_findings about its "
        "movement behavior and history."
    )
    dispatch = {
        "get_recent_track": lambda inp: tools.get_recent_track(inp.get("mmsi") or mmsi),
        "get_vessel_history": lambda inp: tools.get_vessel_history(inp.get("mmsi") or mmsi),
    }
    return agent_base.run_specialist(
        agent_name=AGENT, system=_SYSTEM, user=user, suspicion=suspicion,
        tool_defs=_TOOLS, dispatch=dispatch, max_steps=4)
