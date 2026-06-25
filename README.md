# 🛰️ Baltic Sentinel

**An AI watch console for detecting threats to undersea cables in the Baltic Sea.**

Baltic Sentinel ingests live ship traffic, scores vessels for suspicious behavior near
critical undersea power and telecom cables, and lets an operator launch a team of Claude
agents that investigate a vessel and deliver a calibrated threat assessment — read aloud
as a watch-officer voice briefing.

🔴 **Live demo:** https://baltic-sentinel-production.up.railway.app

---

## Why

In December 2024 the *Eagle S*, a Cook-Islands-flagged shadow-fleet tanker, dragged its
anchor across **Estlink 2** and cut the power cable between Finland and Estonia. The Baltic
has seen a string of these incidents. The hard part isn't reacting — it's spotting the one
suspicious ship among thousands *before* the cable is cut, and giving a watch officer the
evidence to act.

Baltic Sentinel is that early-warning console: live maritime picture, automated suspicion
scoring along the cable corridors, and an agentic investigation that assembles the case.

---

## What it does

1. **Live maritime picture.** Streams real AIS positions from Finnish Digitraffic into the
   Gulf of Finland map, ~hundreds of vessels updating in near real time.
2. **Suspicion scoring.** Every vessel is continuously scored for cable-threat signals —
   loitering / slow drift over a cable, AIS gaps ("going dark"), presence in a GPS-jamming
   zone, and sanctioned / shadow-fleet identity.
3. **Agentic investigation.** An operator clicks a vessel and launches a team of Claude
   agents: a Maritime Analyst, an Aiven Evidence Librarian (queries the data layer through
   the **Aiven MCP**), and an OSINT Researcher. A Watch Officer agent synthesizes their
   findings into a single calibrated verdict.
4. **Voice briefing.** The verdict is spoken aloud via **ElevenLabs** — a hands-free
   watch-officer briefing.
5. **Autonomous Sentinel.** Vessels that warrant follow-up land on a watchlist the Sentinel
   monitors on its own, surfacing changes back to the operator.

---

## Architecture

```text
DATA PLANE (live picture)
  Digitraffic AIS ──▶ ingest ──▶ Aiven Kafka (ais.raw) ──▶ state_builder ──▶ Aiven Postgres
                                                            (score + track)    (vessels, tracks)
                                                                                     │
                                              FastAPI  /vessels /track /candidates ◀──┘
                                                   │
                                          MapLibre watch console  (served at  / )

INVESTIGATION PLANE (on operator demand)
  operator ─▶ POST /agent/investigate ─▶ orchestrator
                                            ├─ Maritime Analyst
                                            ├─ Aiven Evidence Librarian ─▶ Aiven MCP ─▶ Postgres
                                            └─ OSINT Researcher        ─▶ web search
                                            ▼
                                       Watch Officer (synthesis) ─▶ threat assessment
                                            ▼
                                   ElevenLabs voice  +  Postgres  +  console dossier
```

The Kafka topic names and message shapes are the shared contract between the two halves of
the system — see [contracts.md](contracts.md).

---

## Tech stack

| Layer | Tech |
|---|---|
| API + console host | FastAPI / Uvicorn (single container) |
| Streaming | Aiven for Apache Kafka (`confluent-kafka`) |
| Storage | Aiven for PostgreSQL (`psycopg` 3 + connection pool) |
| Agents | Claude (Anthropic) + the **Aiven MCP** connector |
| Voice | ElevenLabs |
| Map UI | MapLibre GL (globe projection), vanilla JS console |
| Deploy | Docker → Railway |

---

## Repository layout

```text
baltic-sentinel/
├─ Dockerfile               Single-container image: API + console + (gated) workers
├─ contracts.md             Shared Kafka topic / message contract (source of truth)
├─ backend/
│  ├─ requirements.txt
│  ├─ start.sh              Entrypoint: uvicorn + workers (gated by RUN_WORKERS)
│  ├─ ca.pem                Aiven Kafka CA (public cert)
│  └─ app/
│     ├─ main.py            FastAPI app
│     ├─ api/routes.py      All HTTP routes; serves the console at /
│     ├─ config.py          Settings (reads .env)
│     ├─ database.py        Postgres helpers (pooled)
│     ├─ kafka_client.py    Kafka producer/consumer helpers
│     ├─ scoring.py         Vessel suspicion scoring
│     ├─ models.py          Pydantic message models (from contracts.md)
│     ├─ data_pipeline/     AIS ingest, scoring sweep, geo rules, data loaders   (Person A)
│     │  ├─ ingest.py            ais.raw producer (Digitraffic)
│     │  ├─ state_builder.py     consumer: score + upsert vessels/tracks + sweep
│     │  ├─ geo_rules.py         cable-proximity rules
│     │  └─ loaders/             sanctions (OpenSanctions), GPS-jamming zones
│     └─ agent_workflow/    Claude agent team + voice                            (Person B)
│        ├─ orchestrator.py      runs the agent team, synthesizes the verdict
│        ├─ analyst.py, osint_researcher.py, evidence_librarian.py
│        ├─ synthesis_agent.py   the Watch Officer
│        ├─ sentinel.py          autonomous watchlist monitor
│        ├─ tools.py             agent tools (DB, watchlist, voice)
│        └─ voice.py             ElevenLabs synthesis
├─ frontend/
│  └─ prototype.html        The watch console (the served UI)
├─ demo_assets/             Sample payloads for demo mode
└─ docs/                    Design + planning docs, pitch handoff
```

---

## Running locally

Requires Python 3.11 and Aiven Kafka + Postgres credentials.

```bash
cd backend
pip install -r requirements.txt

# configure: copy the template and fill in real keys
cp ../.env.example ../.env        # ANTHROPIC_API_KEY, ELEVENLABS_API_KEY, AIVEN_* ...
```

Run the three processes (each in its own terminal):

```bash
python -m app.data_pipeline.ingest          # 1. AIS producer  → Kafka
python -m app.data_pipeline.state_builder   # 2. consumer: score + write to Postgres
uvicorn app.main:app --port 8000            # 3. API + console at http://localhost:8000
```

Open http://localhost:8000 for the console. Configuration lives in
[`.env.example`](.env.example); `config.py` reads `.env` (or `../.env`).

---

## Deployment

The repo builds into one Docker image (`Dockerfile`, built from the repo root so both
`backend/` and `frontend/` are in the context) and runs on Railway.

**Operating model — single writer, shared database.** The Aiven Postgres + Kafka services
are the shared source of truth. To avoid two writers fighting over the data:

- **Railway runs serve-only** — it serves the console + API and *reads* the database. The
  `start.sh` gate keeps the data workers off unless `RUN_WORKERS=true` (which Railway does
  not set), so the deployed site never double-writes.
- **One designated host runs the workers** — `ingest` + `state_builder` run on a single
  machine (a laptop or one cloud box), producing AIS into Kafka and writing the scored
  vessel state into Postgres that the Railway site then serves.

Required environment variables (see `.env.example`): `ANTHROPIC_API_KEY`,
`ELEVENLABS_API_KEY`, `AIVEN_POSTGRES_URL`, `AIVEN_KAFKA_BOOTSTRAP`,
`AIVEN_KAFKA_USERNAME`, `AIVEN_KAFKA_PASSWORD`, and `DEMO_MODE=false` for live data.

---

## Data sources

- **[Digitraffic](https://www.digitraffic.fi/en/marine-traffic/)** — live Finnish AIS vessel positions.
- **[OpenSanctions](https://www.opensanctions.org/)** — sanctioned / shadow-fleet vessel identities.
- **[GPSJAM](https://gpsjam.org/)** — daily GPS-interference zones.
- Submarine cable + landing-point geodata for the Baltic corridors.

---

## Team

- **Person A** — Data pipeline: AIS ingestion, scoring, geo rules (`backend/app/data_pipeline/`)
- **Person B** — Agent workflow: Claude agent team + voice (`backend/app/agent_workflow/`)

Built for a hackathon, focused on Aiven (Kafka + Postgres + MCP), Anthropic Claude, and ElevenLabs.
