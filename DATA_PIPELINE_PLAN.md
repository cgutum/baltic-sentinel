# Baltic Sentinel — Data Foundation Plan (Person A)

> Locked via `/plan-eng-review` (2026-06-24). Builds the real data foundation on top of the H1–H7 spine. Person B builds the agents against the contract boundary below.

## Locked decisions
1. **Map data path:** backend from Postgres (`Digitraffic → Kafka → consumer → Postgres → API`). Browser-direct Digitraffic is fallback only. → Aiven is the system of record for the whole live picture.
2. **Ingest spine:** poll Digitraffic every ~60s → `ais.raw`. AISStream = stretch.
3. **Trigger model:** continuous scoring flags **candidates**; operator clicks **Launch Investigation** → backend publishes `vessel.suspicion` (with feature dossier) → Person B's agents. Human-in-the-loop.
4. **Scoring:** transparent weighted rule score with a human-readable reason per feature. No ML clustering (explainability is the pitch).

## Data flow
```
              ┌──────────────────────────── AIVEN ────────────────────────────┐
              │ Kafka:  ais.raw · vessel.suspicion · agent.findings ·          │
              │         threat.assessment · voice.briefing                     │
              │ Postgres: vessels · tracks · suspicion_events · agent_findings │
              │           · assessments                                        │
              └────────────────────────────────────────────────────────────────┘
 Digitraffic ─poll 60s─►[ingest]─► ais.raw ─►[state_builder consumer]
 (whole Baltic,no key)                           │ upsert vessels (score+reasons[], is_candidate)
 replay Eagle S ──────► ais.raw ─────────────────┤ append tracks
                                                 │ uses (in-mem, cached at boot):
                                                 │   cables · gpsjam hexes · sanctions
                                                 ▼
 Browser ◄─ GET /vessels  GET /candidates ─[FastAPI]
 (Vercel)     operator clicks "Launch Investigation"
              └─ POST /investigate/{mmsi} ─► publish vessel.suspicion (+dossier)
                                                 │
   ═════════════════════ contract boundary → Person B ═════════════════════
                                                 ▼
            [orchestrator] consume vessel.suspicion → Investigator → agent.findings
              → Watch Officer → threat.assessment → ElevenLabs → voice.briefing
                                                 │
 Browser ◄─ SSE /stream · GET /assessment/{mmsi} · GET /voice/{mmsi}
```

## ⚠️ Contract change to coordinate with Person B
`vessel.suspicion` is now **operator-triggered** and carries a `dossier` (backward compatible — extra field):
```json
{
  "suspicion_id": "sus_xxxx", "mmsi": "518998000", "imo": "9329760", "name": "Eagle S",
  "rule": "operator_launch", "cable": "Estlink 2", "severity": 0.9,
  "summary": "Operator launched investigation. Score 90/100 near Estlink 2.",
  "timestamp": "...",
  "dossier": {
    "score": 90,
    "reasons": ["Slow (1.6 kn) inside Estlink 2 corridor", "Sanctions/detention record: mare.detained", "Inside GPS-jamming zone; AIS unreliable", "Flag of convenience: Cook Islands"],
    "track_summary": {"points": 6, "min_speed": 1.6, "near_cable_minutes": 4},
    "flag": "Cook Islands", "gps_jammed": true,
    "sanctions_hit": {"risk": "mare.detained", "flag": "ck"}
  }
}
```
B's Investigator uses `dossier` as starting context, then does its own tool calls + web search on top.

## New / changed files (build order)
| # | File | Purpose | Owner |
|---|---|---|---|
| 1 | `data_pipeline/sources/digitraffic.py` | fetch + normalize Digitraffic → ais.raw dicts; filter stale by `timestampExternal` | A |
| 2 | `data_pipeline/loaders/sanctions.py` | download+cache maritime.csv; `lookup(imo,name)->risk` | A |
| 3 | `data_pipeline/loaders/gpsjam.py` | download+cache day CSV; `in_jammed_zone(lat,lon)` | A |
| 4 | `data_pipeline/geo_rules.py` (extend) | load telecom cables (TeleGeography GeoJSON, cached) + hardcoded power corridors; `cable_near`, `nearest_cable` | A |
| 5 | `scoring.py` | `score_vessel(state, track, ctx) -> (score, reasons[], top_cable)`; reuses `tripwire.detect` as the slow-near-cable feature | A |
| 6 | `data_pipeline/ingest.py` | worker: poll Digitraffic 60s → diff → publish ais.raw (Kafka heartbeat) | A |
| 7 | `data_pipeline/state_builder.py` | consumer: ais.raw → upsert vessels + append tracks → recompute score → set is_candidate | A |
| 8 | `database.py` (extend, **shared**) | add `vessels` table to `init_tables`; `upsert_vessel`, `get_vessels`, `get_candidates` | A (tell B) |
| 9 | `api/routes.py` (extend, **shared**) | `GET /vessels`, `GET /candidates`, `POST /investigate/{mmsi}` (publish vessel.suspicion+dossier) | A (tell B) |
| 10 | `config.py` (extend, **shared**) | scoring weights/threshold, poll interval, jam box, cache paths | A (tell B) |

## `vessels` table
```sql
CREATE TABLE IF NOT EXISTS vessels (
  mmsi text PRIMARY KEY, imo text, name text, ship_type text, flag text,
  last_lat double precision, last_lon double precision,
  last_speed double precision, last_course double precision, nav_status text,
  last_seen timestamptz,
  suspicion_score double precision DEFAULT 0,
  suspicion_reasons jsonb DEFAULT '[]',
  is_candidate boolean DEFAULT false,
  updated_at timestamptz DEFAULT now()
);
```

## Scoring spec (weighted, explainable). Candidate if score ≥ 50. Cap 100.
| Feature | Condition | Pts | Reason string |
|---|---|---|---|
| slow_near_cable | speed<3kn AND in corridor | 35 | `Slow ({sog} kn) inside {cable} corridor` |
| sanctions/detention | imo/name in maritime.csv w/ risk | 30 | `Sanctions/detention record: {risk}` |
| ais_gap | gap > 15 min while last near corridor | 25 | `AIS silent {min} min near {cable}` |
| anchor_drag | slow + heading variance high over corridor | 20 | `Erratic heading while slow over {cable}` |
| in_jammed_zone | in bad GPSJam hex AND near corridor | 15 | `Inside GPS-jamming zone; AIS unreliable here` |
| flag_of_convenience | flag in FoC list | 10 | `Flag of convenience: {flag}` |

Eagle S replay → 35+30+15+10 = **90** → top candidate, deterministically.

## Flag of convenience list (seed)
Cook Islands, Gabon, Comoros, Palau, Panama, Liberia, Marshall Islands, Cameroon, Barbados, Togo, Sierra Leone, Djibouti.

## Workers to run (laptop / tunnel)
```
uvicorn app.main:app --port 8000              # API (serves /vessels, /candidates, /investigate)
python -m app.data_pipeline.ingest            # Digitraffic poll -> ais.raw
python -m app.data_pipeline.state_builder     # ais.raw -> vessels + score
python -m app.agent_workflow.orchestrator     # Person B: vessel.suspicion -> agents
```
Eagle S replay (`POST /replay/eagle-s`) injects into ais.raw alongside live traffic → flows through the same scorer → becomes the obvious candidate on stage.

## NOT in scope (deferred)
- AISStream live ingest — Digitraffic covers the Baltic with no key; stretch only.
- ML clustering — replaced by explainable weighted score.
- ClickHouse / analytics store — Postgres is enough for the demo.
- Second region, OpenSky live ADS-B — stretch.
- Auth / multi-user — not judged.
- Real seabed cable geometry — corridors only (routes are classified; that's a pitch point).

## Failure modes (mitigation in plan)
- Digitraffic 406 (needs `Accept-Encoding: gzip`) → set header; test.
- Stale ghost vessels → filter `timestampExternal` < 15 min; if 0 fresh, keep last state + flag "feed degraded" (don't wipe map).
- maritime.csv / GeoJSON download fails at boot → fall back to cached local copy; if none, feature returns no-hit (degrade, never crash).
- GPSJam today not yet published (404) → use yesterday's file.
- Kafka free-tier idle power-off → the 60s poll is the heartbeat.
- /investigate double-click → dedup vessel.suspicion per mmsi within a short window.
