# Architecture

How Baltic Sentinel works end to end, with emphasis on **where Aiven Kafka and the Aiven
MCP are actually invoked** in the codebase. Two planes:

- **Data plane** — continuous: live AIS in → Kafka → scored vessel state in Postgres → console.
- **Investigation plane** — on demand: an operator launches a Claude agent team that
  investigates a vessel and produces a spoken verdict; an autonomous Sentinel then monitors
  the watchlist.

> GitHub renders the Mermaid diagrams below inline. To edit them, paste into
> [mermaid.live](https://mermaid.live).

---

## Where Kafka & the MCP actually fire

**Kafka is both the data spine and a telemetry bus.** Only `ais.raw` is consumed by the
app; the other five topics are *produced but never consumed* (the UI reads results over
HTTP, not Kafka — see [kafka_client.py:121](../backend/app/kafka_client.py#L121)).

| Topic | Produced by | Consumed by |
|---|---|---|
| `ais.raw` | `ingest` ([ingest.py:21](../backend/app/data_pipeline/ingest.py#L21)) | `state_builder` ([:110](../backend/app/data_pipeline/state_builder.py#L110)), `tripwire` ([:92](../backend/app/data_pipeline/tripwire.py#L92)) |
| `vessel.suspicion` | `tripwire` ([:83](../backend/app/data_pipeline/tripwire.py#L83)), `/investigate` ([routes.py:121](../backend/app/api/routes.py#L121)) | — (telemetry) |
| `agent.findings` | `write_finding` ([tools.py:272](../backend/app/agent_workflow/tools.py#L272)) | — (telemetry) |
| `threat.assessment` | `save_assessment` ([tools.py:289](../backend/app/agent_workflow/tools.py#L289)) | — (telemetry) |
| `voice.briefing` | `create_voice_briefing` ([tools.py:361](../backend/app/agent_workflow/tools.py#L361)) | — (telemetry) |
| `vessel.watch` | `record_watch` ([tools.py:401](../backend/app/agent_workflow/tools.py#L401)) | — (telemetry) |

**The Aiven MCP fires in exactly two agents**, server-side through the Anthropic beta MCP
connector ([agent_base.py:113](../backend/app/agent_workflow/agent_base.py#L113),
[:141](../backend/app/agent_workflow/agent_base.py#L141)), and only when a real token is set.
Everywhere else, Aiven Postgres is accessed directly via psycopg.

| MCP caller | When | What it does over the MCP |
|---|---|---|
| Evidence Librarian | once per investigation ([evidence_librarian.py:104](../backend/app/agent_workflow/evidence_librarian.py#L104)) | pipeline health / data freshness, to judge how much to trust the evidence |
| Sentinel | once per autonomous cycle ([sentinel.py:176](../backend/app/agent_workflow/sentinel.py#L176), [:231](../backend/app/agent_workflow/sentinel.py#L231)) | pipeline health + manages its own `sentinel_memory` table via `aiven_pg_read`/`aiven_pg_write` |

Analyst, OSINT, and Watch Officer never touch the MCP. MCP tool calls are recorded to a ring
buffer ([agent_base.py:166](../backend/app/agent_workflow/agent_base.py#L166)) and surfaced
at `GET /mcp/activity`.

---

## Diagram 1 — System architecture

```mermaid
flowchart TD
  classDef ext fill:#1f2933,stroke:#8593AB,color:#dce3ee
  classDef aiven fill:#0b3a53,stroke:#4CC9E6,color:#eaf6fb
  classDef wrk fill:#2a2140,stroke:#b59cff,color:#f0eaff
  classDef svc fill:#10261a,stroke:#5fd08a,color:#e7f7ec

  DT["Digitraffic AIS"]:::ext
  ANT["Anthropic API<br/>Claude + web_search"]:::ext
  ELV["ElevenLabs TTS"]:::ext

  subgraph AIVEN["Aiven"]
    K[("Kafka")]:::aiven
    PG[("Postgres")]:::aiven
    MCP{{"Aiven MCP server"}}:::aiven
  end

  subgraph HOST["Data workers — single designated host"]
    ING["ingest"]:::wrk
    SB["state_builder + sweep"]:::wrk
    TW["tripwire"]:::wrk
  end

  subgraph RAIL["FastAPI service — Railway, serve-only"]
    API["routes + MapLibre console"]:::svc
    ORC["investigation orchestrator"]:::svc
    SEN["Sentinel — autonomous"]:::svc
  end

  DT -->|poll 60s| ING
  ING ==>|"produce ais.raw"| K
  K ==>|"consume ais.raw"| SB
  K ==>|"consume ais.raw"| TW
  SB -->|"write vessels, tracks"| PG
  TW -->|"write suspicion_events"| PG
  TW -.->|"vessel.suspicion (telemetry, unconsumed)"| K
  PG -->|read| API

  API -->|"POST /agent/investigate"| ORC
  ORC -->|"Analyst · Librarian · OSINT · Watch Officer"| ANT
  ORC -->|"gather + write findings/assessment"| PG
  ORC -->|"voice briefing"| ELV
  ORC -.->|"agent.findings · threat.assessment<br/>voice.briefing · vessel.watch (telemetry)"| K

  SEN -->|"Sentinel agent (Sonnet)"| ANT
  SEN -->|"check_changes · watchlist R/W"| PG

  ANT ==>|"MCP connector — Librarian & Sentinel ONLY"| MCP
  MCP -->|"service health/metrics +<br/>sentinel_memory R/W"| PG
```

---

## Diagram 2 — Lifecycle sequence (*when* Kafka and the MCP are called)

```mermaid
sequenceDiagram
  autonumber
  participant DT as Digitraffic
  participant W as Workers (ingest/state_builder/tripwire)
  participant K as Aiven Kafka
  participant PG as Aiven Postgres
  participant UI as Console (browser)
  participant SVC as FastAPI (API + orchestrator + sentinel)
  participant CL as Anthropic API (Claude)
  participant MCP as Aiven MCP
  participant EL as ElevenLabs

  Note over DT,PG: 1 — LIVE DATA LOOP (continuous, every 60s) ▸ Kafka here
  loop every 60s
    W->>DT: fetch AIS positions
    W->>K: produce ais.raw
    K->>W: consume ais.raw
    W->>PG: upsert vessels + tracks (scored)
    W-->>K: produce vessel.suspicion (telemetry only)
    W->>PG: insert suspicion_events
  end

  Note over UI,PG: 2 — MAP (console polls over HTTP, not Kafka)
  loop every ~20s
    UI->>SVC: GET /vessels
    SVC->>PG: SELECT vessels (active_only filter)
    SVC-->>UI: GeoJSON
  end

  Note over UI,EL: 3 — INVESTIGATION (operator-triggered) ▸▸ Aiven MCP FIRES
  UI->>SVC: POST /agent/investigate/{mmsi}
  SVC->>PG: gather raw evidence (track, sanctions, GPS, cable)
  par Maritime Analyst (Sonnet, no tools)
    SVC->>CL: messages.create
  and Evidence Librarian (Sonnet) — the MCP user
    SVC->>CL: beta.messages.create (mcp_servers=aiven)
    SVC->>PG: aiven_query (direct read-only SQL)
    CL->>MCP: aiven_* (pipeline health / freshness)
    MCP->>PG: read service state
  and OSINT Researcher (Sonnet)
    SVC->>CL: messages.create + web_search (server-side)
  end
  SVC->>CL: Watch Officer (Opus) — synthesize verdict
  SVC->>PG: write_finding + save_assessment
  SVC->>EL: create_voice_briefing -> MP3
  SVC-->>K: produce agent.findings / threat.assessment / voice.briefing (telemetry)
  SVC->>PG: record_watch (if MEDIUM/HIGH -> watchlist)
  UI->>SVC: GET /agent/result/{mmsi} (poll until done)
  SVC-->>UI: verdict + spoken briefing

  Note over PG,MCP: 4 — SENTINEL (autonomous, every 120s or /sentinel/run) ▸▸ MCP FIRES AGAIN
  loop every 120s
    SVC->>PG: read ACTIVE watchlist
    SVC->>CL: Sentinel agent (Sonnet, tool loop)
    CL->>MCP: aiven_* health + sentinel_memory read/write
    MCP->>PG: read/write sentinel_memory
    SVC->>PG: check_changes / update_watch
    Note right of CL: material change -> reinvestigate (re-runs phase 3)
  end
```

---

## Notes

- **Single-writer model.** The data workers run on one designated host; Railway runs
  serve-only. See the deployment section of the [README](../README.md).
- **Telemetry topics.** `vessel.suspicion`, `agent.findings`, `threat.assessment`,
  `voice.briefing`, and `vessel.watch` are emitted to Kafka as a streaming record of the
  system's activity (the Aiven "nervous system"), but the console reads everything it
  displays over HTTP. Closing those loops via Kafka consumers is a natural extension.
- **MCP vs direct SQL.** Most Aiven Postgres access is direct psycopg (fast, in-process).
  The MCP is used specifically where an *agent* needs to reason about the data layer itself
  (is the pipeline healthy? how fresh is the ingest?) and for the Sentinel's self-managed
  long-term memory.
