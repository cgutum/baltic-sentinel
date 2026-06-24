"""Investigation team runner — Person B.

Runs the specialist agents IN PARALLEL and merges their findings:
  - Identity & Records   (web search + sanctions record + ID validation)
  - Behavior & History   (real track + prior incidents)
  - Environment & Proximity (GPS trust + nearby vessels / the wider scene)

Each specialist genuinely fetches new information via its own tools, so the
findings are investigation, not paraphrase. Falls back to canned findings if the
API key is missing or the whole team comes back empty (demo never breaks).

run(suspicion) -> list[dict]   # AgentFinding-shaped, from all specialists
"""

from concurrent.futures import ThreadPoolExecutor

from ..config import settings
from . import behavior_agent, fallback_outputs, gps_environment_agent, identity_agent

_TEAM = [identity_agent, behavior_agent, gps_environment_agent]


def run(suspicion: dict) -> list[dict]:
    if not settings.anthropic_api_key:
        print("[investigator] no ANTHROPIC_API_KEY — using fallback findings")
        return fallback_outputs.findings(suspicion)

    findings: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(_TEAM)) as ex:
        futures = {ex.submit(m.run, suspicion): m.AGENT for m in _TEAM}
        for fut, name in futures.items():
            try:
                fs = fut.result()
                findings.extend(fs)
                print(f"[investigator] {name}: {len(fs)} finding(s)")
            except Exception as e:  # noqa: BLE001 — one specialist failing must not sink the rest
                print(f"[investigator] {name} failed: {e}")

    if not findings:
        print("[investigator] team produced no findings — using fallback")
        return fallback_outputs.findings(suspicion)
    return findings
