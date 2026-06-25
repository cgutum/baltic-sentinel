# Baltic Sentinel — Deployment Plan

> **What this is:** where every moving part actually *runs* — Aiven, Vercel, Anthropic cloud — and why. Written against the live system as built (FastAPI + always-on workers + Aiven Kafka/Postgres + Claude agents + ElevenLabs), and scoped to the three challenges we're judged on. Decisions are made, not surveyed — see §8 for the one-line answer and §9 for the demo-day runbook.
>
> **v2 (2026-06-25):** dropped the laptop + Cloudflare-tunnel plan. Two things changed it: (1) Aiven has **managed application hosting** we can deploy to **via the MCP** (`aiven_application_deploy`), so the workers run *on Aiven* with a public URL — no laptop, no tunnel; (2) the Aiven **remote MCP** lets a **Claude Managed Agent reach Aiven directly**, so the agents run fully in Anthropic's cloud with no bridge. Both upgrades also *strengthen* the challenge story. Live services confirmed: project `baltic-sentinel`, `baltic-kafka` + `baltic-pg`, both RUNNING.

---

## 0. TL;DR

- **Data plane → Aiven, already live & managed.** Kafka (`baltic-kafka`) + Postgres (`baltic-pg`), RUNNING in `google-europe-north1` (Finland). We don't host these — that's the Aiven pitch. We just keep traffic flowing.
- **Compute plane → an Aiven Application service, deployed via MCP.** Our existing Dockerfile, pulled from GitHub, run by Aiven, with Kafka + Postgres credentials **auto-injected**. Public URL, no laptop, no tunnel — and it makes the Aiven story stronger (compute *and* data on Aiven, stood up through MCP). Vercel still **cannot** run it (no WebSockets/workers, 300s cap). See §4.
- **Agents → Claude Managed Agents, reaching Aiven directly via the remote Aiven MCP.** No laptop bridge. Scheduled (autonomy) + live-triggerable (works live) + Slack/Gmail HITL connectors. The deterministic ingest stays plain code on the Aiven app — *not* an LLM. See §6.
- **Presentation plane → Vercel** (public URL), with the Aiven app also serving the console at `/` as a zero-CORS fallback.
- **AWS → skip.** Not judged for us; an AWS host (ECS/App Runner) would just duplicate the Aiven app, and MSK/RDS would shadow Aiven. See §7.
- **Break-glass → the in-app `orchestrator` + `DEMO_MODE`** so conference wifi can't kill the demo. See §6.

---

## 1. The three planes (mental model)

Think of the system as three planes that deploy independently. Most of the confusion in the handoffs comes from treating it as one "backend."

```
┌─ PRESENTATION PLANE ──────────────────────────────────────────────┐
│  MapLibre watch console (frontend/prototype.html + prototype_data) │
│  → Vercel (public URL)   ·   also served by the Aiven app at GET / │
└────────────────────────────────────────────────────────────────────┘
                              │ polls /vessels /candidates, POSTs /investigate
                              ▼
┌─ COMPUTE PLANE — deterministic data pipeline (plain code) ────────┐
│  FastAPI (api/routes.py)        ← REST + serves the console        │
│  ingest worker                  ← Digitraffic poll → ais.raw       │
│  state_builder worker           ← ais.raw → vessels/tracks + score │
│  orchestrator (BREAK-GLASS)     ← local agent fallback / DEMO_MODE  │
│  → Aiven Application service (deployed via MCP; Kafka+PG injected) │
└────────────────────────────────────────────────────────────────────┘
        │ produce / consume / SQL                  ▲ pg_read/write,
        ▼                                          │ kafka produce (via MCP)
┌─ DATA PLANE (Aiven — managed, do not host) ──┐   │
│  Kafka  baltic-kafka   (Finland, RUNNING)    │   │
│  Postgres baltic-pg    (PG 17, RUNNING)      │   │
└──────────────────────────────────────────────┘   │
        ▲ remote MCP (mcp.aiven.live/mcp)           │
        │                                           │
┌─ AGENT PLANE — Claude Managed Agents (Anthropic cloud) ───────────┐
│  Investigator + Watch Officer   ← scheduled + live-triggerable     │
│  reach Aiven DIRECTLY via the remote Aiven MCP (no bridge)         │
│  call ElevenLabs (voice) · Slack/Gmail connectors (HITL)          │
└────────────────────────────────────────────────────────────────────┘
```

**Why this split matters for deployment:** the data plane is managed (Aiven); the compute plane is deterministic code that needs an always-on host (now the **Aiven app**, not a laptop); the agent plane is LLM work that runs best as a hosted, scheduled **Managed Agent**. The old "where does the backend live?" question dissolves: deterministic code → Aiven app; agents → Anthropic cloud; data → Aiven. Nothing runs on a laptop except the break-glass fallback.

---

## 2. What Aiven is actually doing (and why it's *managed*, not hosted by us)

This is the Aiven challenge in one section. The point of the challenge — "the Autonomous Data Operator" — is that **we never wrote backend infra boilerplate; the agents/system orchestrate managed services via the Aiven MCP.** So the right mental frame is: *Aiven is the operating system for our data; we are a tenant.*

### 2.1 Kafka (`baltic-kafka`) — the nervous system

Kafka is the **event bus that decouples every part of the pipeline** so each can run as a separate process (even on a separate host) and they still talk. It's not a queue we could swap for a Python list — it's what makes the multi-agent fan-out *real* rather than function calls in one process.

| Topic | What flows through it | Producer → Consumer | Why it's on Kafka and not in-memory |
|---|---|---|---|
| `ais.raw` | Normalized ship positions (Digitraffic poll + Eagle S replay) | ingest → state_builder | Replay and live feed publish to the **same** topic, so the staged incident runs the identical path as real traffic. |
| `vessel.suspicion` | Operator-launched investigation + dossier | FastAPI `/investigate` → orchestrator | This is the **contract boundary** between Person A (data) and Person B (agents). Decoupling here is what lets the agent loop run as its own process / Managed Agent. |
| `agent.findings` | One message per agent finding (tagged with agent name) | orchestrator → UI | Drives the **swarm animation** — the UI subscribes to findings as they land, which is only legible because they're discrete events on a stream. |
| `threat.assessment` | Synthesized verdict + recommended action | synthesis → UI/Postgres | The "done" signal; also the trigger for the voice briefing. |
| `voice.briefing` | Audio-ready signal | synthesis → voice | Lets voice synthesis run async without blocking the verdict. |

> **Deployment-critical gotcha:** Aiven **free-tier Kafka auto-powers-off when idle.** The 60s Digitraffic poll in `ingest.py` is our **heartbeat** — it must be running during judging or the broker sleeps and the demo stalls on a cold start. Provision and warm Kafka *first*, never at hour 20.

### 2.2 Postgres (`baltic-pg`) — the memory

Postgres is the **system of record and the agent's long-term memory.** Per the locked data plan, the map reads from Postgres (not browser-direct Digitraffic) — so Aiven *is* the live picture, which is exactly the narrative the Aiven judges want.

| Table | Role in deployment | Who writes |
|---|---|---|
| `vessels` | Latest position + suspicion score per vessel — **the map's source of truth** (`GET /vessels`). | state_builder |
| `tracks` | Rolling position history — feeds the route trail (`GET /track/{mmsi}`) and the behavior agent. | state_builder |
| `suspicion_events` | Every operator-launched investigation — the audit trail. | FastAPI `/investigate` |
| `agent_findings` | Per-agent outputs — explainability evidence, survives restarts. | orchestrator |
| `assessments` | Final verdicts + voice path — what `/assessment/latest` serves. | synthesis |

**The pitch-able point:** because state lives in managed Postgres, the agent has memory *across* runs ("have we flagged this hull before?"), and the whole investigation is reconstructable after the fact. That's the difference between "a prompt in a wrapper" and "a stateful operator." If we add the **pgvector** extension for similarity over past `agent_findings`, that directly hits the Aiven rubric's "long-term memory" line — a high-leverage stretch (§10).

### 2.3 The Aiven MCP angle (the 34% "Depth of MCP Integration")

The challenge's biggest scoring slice is *how natively the agent uses the Aiven MCP.* In the v2 architecture the MCP isn't a flourish bolted on — it's the **main path** for both compute and agents. Three levels, all in play:

1. **Provisioning via MCP:** the Kafka service, topics, and Postgres tables were created through the Aiven MCP rather than hand-rolled Terraform/CLI. "No backend boilerplate — the data layer was stood up by tool calls."
2. **Compute deployed via MCP:** the whole data pipeline (FastAPI + ingest + state_builder) is shipped to **Aiven Application hosting** through `aiven_application_deploy` — *our compute runs on Aiven, deployed by an MCP tool call.* This is the "abstract away manual backend coding" slice (33%) made literal.
3. **Agents operate the data layer via MCP at runtime:** the Managed Agents **read candidates (`aiven_pg_read`), write findings/assessments (`aiven_pg_write`), and produce to Kafka (`aiven_kafka_topic_message_produce`) — all through the Aiven MCP.** This is the strongest possible "the agent natively controls the infrastructure" narrative (34%), and it's now the primary agent path, not a read-only add-on.

---

## 3. Component → host matrix

Every runnable process, where it can live, and the call.

| Process | Vercel | Aiven App | Fly/Railway | AWS | Anthropic cloud | **Recommendation** |
|---|:--:|:--:|:--:|:--:|:--:|---|
| MapLibre console (static) | ✅ | ✅ (served at `/`) | ✅ | ✅ | — | **Vercel** public + Aiven app `/` fallback |
| FastAPI REST | ❌ (no long-run) | ✅ | ✅ | ✅ | — | **Aiven App** |
| `ingest` worker (poll loop) | ❌ | ✅ | ✅ | ✅ | ⚠️ don't (LLM-as-poller) | **Aiven App** |
| `state_builder` (Kafka consumer) | ❌ | ✅ | ✅ | ✅ | ⚠️ don't | **Aiven App** |
| Investigator + Watch Officer agents | ❌ | ✅ (break-glass) | ✅ (break-glass) | ✅ | ✅ native | **Managed Agents** (in-app orchestrator = fallback) |
| Kafka broker | — | (is Aiven) | ❌ | (MSK ❌) | — | **Aiven** (already live) |
| Postgres | — | (is Aiven) | ❌ | (RDS ❌) | — | **Aiven** (already live) |
| ElevenLabs TTS | — | (call) | (call) | (call) | (call) | **External SaaS** — called by the Watch Officer agent |
| Claude inference | — | (call) | (call) | (call) | (native) | **External SaaS** / native to Managed Agents |

**Why Vercel can't host the backend (settled):** no persistent WebSocket/consumer connections, no background workers, and a 300s function ceiling. `ingest` and `state_builder` are infinite loops; a Kafka consumer holds a long-lived connection. None of that survives serverless. Vercel is presentation-only. ✔

**Why not Managed Agents for `ingest`/`state_builder`:** those are cheap deterministic loops. Running an LLM to poll an HTTP endpoint every 60s is wasteful, slow, and exactly what Anthropic's own brief warns against ("the scheduler is not a Claude agent"). Keep them as plain code on the Aiven app; reserve Managed Agents for the actual reasoning (investigation + synthesis).

---

## 4. The recommended topology (and the fallbacks)

### Topology A — Aiven App + Managed Agents *(recommended — no laptop, no tunnel)*
```
Vercel console ──https──► Aiven Application service ───────────────► Aiven Kafka + Postgres
   (or served at /)         FastAPI + ingest + state_builder            (same project, Finland)
                            (deployed via aiven_application_deploy,        ▲
                             Kafka+PG creds auto-injected)                 │ pg_read/write +
                                                                           │ kafka produce
                            Claude Managed Agents ─── remote Aiven MCP ────┘  (all via MCP)
                            (Investigator + Watch Officer;                 
                             scheduled + live-triggerable) ──► ElevenLabs · Slack/Gmail (HITL)
```
- **Pro:** nothing on a laptop; everything has a public URL; compute is co-located with the data; the *whole* story runs through MCP (provision + deploy + operate). Strongest possible Aiven + Anthropic narrative.
- **Con:** two real setup tasks (below) and a cloud round-trip for the agents (mitigated by the break-glass).
- **Setup task 1 — one container, many processes:** the Aiven app runs one `CMD`. Add a tiny `start.sh` entrypoint that launches `uvicorn` + `ingest` + `state_builder` together (background the workers, foreground uvicorn), or deploy them as **separate Aiven app services**. Current [Dockerfile](backend/Dockerfile) only runs uvicorn → add the launcher.
- **Setup task 2 — Kafka auth mapping:** the app integration injects **SSL/mTLS** creds (`KAFKA_ACCESS_CERT`/`KAFKA_ACCESS_KEY`/`KAFKA_CA_CERT`, `KAFKA_SECURITY_PROTOCOL=SSL`), but [kafka_client.py](backend/app/kafka_client.py) currently uses **SASL/SCRAM**. Teach it to use cert-based SSL when those env vars are present (small branch). PG: set the integration's `env_key=AIVEN_POSTGRES_URL` to match `config.py`; mind the injected `PROJECT_CA_CERT` for TLS.
- **Deploy prerequisites:** confirm the GitHub repo URL + branch and public/private (private → connect GitHub in the Aiven console first); enable Kafka REST (`kafka_rest: true`) so agents can produce via MCP.

### Topology B — Fly.io / Railway *(fallback if Aiven app hosting is constrained)*
```
Vercel console ──https──► Fly.io / Railway container (Dockerfile) ──► Aiven Kafka + Postgres
```
- Same one-container-many-processes pattern; same Dockerfile. Use if the Aiven app plan is too small, the repo can't be connected in time, or we hit a build limit. Keeps us off the laptop. **Fly.io** is the pick (always-on, multi-process via `fly.toml`); Railway for fastest DX.

### Topology C — Laptop + tunnel *(break-glass only, was the old plan)*
The original `cloudflared`/laptop setup still works as a last resort if all hosting fails — run the four processes locally and tunnel `:8000`. Documented so we have a floor, **not** the plan. ❌ as primary.

### Topology D — Pure Vercel serverless *(do not pursue)*
Kafka-from-serverless connection churn + cold starts + no always-on ingest = the riskiest path. ❌

---

## 5. Frontend hosting — Vercel, concretely

The console is **static** today: [frontend/prototype.html](frontend/prototype.html) + [frontend/prototype_data.js](frontend/prototype_data.js) (the React scaffold in `src/` is unfinished and not on the demo path). That makes Vercel trivial:

- Deploy `frontend/` as a static project (no build step needed for the prototype; `vercel --prod` on the folder).
- The console's API base needs to point at the backend. Two clean options:
  1. **Same-origin (simplest, no CORS):** the console is already served by the backend at `GET /` ([routes.py](backend/app/api/routes.py)), so hitting the **Aiven app's public URL** gives you UI + API on one origin, zero CORS config.
  2. **Vercel + Aiven app:** host on Vercel for the polished public link, set the API base to the Aiven app URL. CORS is already `allow_origins=["*"]` in [main.py](backend/app/main.py), so this works out of the box.
- **Recommendation:** drive the demo from the **Aiven app `/`** (bulletproof, one origin, on-brand "it all runs on Aiven") and use **Vercel** as the shareable public link. Both serve the identical file.

---

## 6. The agents — fully on Claude Managed Agents, reaching Aiven via MCP

The old plan hedged with a laptop "Option A" bridge. We don't need it: because Aiven publishes a **remote MCP server** (`mcp.aiven.live/mcp`), a **Claude Managed Agent connects to Aiven directly** as an MCP connector — no laptop, no self-hosted bridge.

**The two agents (Anthropic's Investigator + Watch Officer split, which gives a natural HITL handoff):**

- **Investigator (Managed Agent, scheduled + triggerable):** wakes on a schedule (e.g. every 60s), `aiven_pg_read`s for new candidates, does multi-step tool-using investigation (identity, behavior, sanctions, GPS/cable context, real web search), then `aiven_pg_write`s findings and `aiven_kafka_topic_message_produce`s to `agent.findings` — **all through the Aiven MCP.** Scheduled wake = Anthropic's "runs without you watching"; manual trigger from the operator's "Launch Investigation" = "it works live."
- **Watch Officer (Managed Agent):** reads the findings, synthesizes LOW/MED/HIGH + reasoning + `voice_script`, writes `assessments` + produces `threat.assessment` (via MCP), calls **ElevenLabs** for the briefing (stores audio/path in Postgres), and **drafts a human alert via a Slack/Gmail connector** — the HITL + connector points Anthropic explicitly rewards. We *recommend*, never enforce.

**Why this scores on every Anthropic slice:** agentic depth (multi-step tool calls, not a wrapper) · real-world usefulness (a 24/7 cable-watch you'd run weekly) · autonomy & infra leverage (Managed Agents' native scheduling/state/connectors/sandbox + HITL) · it works live (triggerable from the submission).

**The break-glass (insurance, not the plan):** the in-app **orchestrator** ([orchestrator.py](backend/app/agent_workflow/orchestrator.py)) still runs the same loop locally via the `anthropic` SDK with a `DEMO_MODE` canned fallback. If conference wifi makes the Managed-Agent→MCP round-trip flaky on stage, flip to the in-app path — same findings, same dossier. Managed Agents are the **primary** path and the story; the orchestrator is the floor.

> One caveat to internalize: don't let the *deterministic* pipeline drift onto Managed Agents (see §3). Agents reason; the Aiven app polls and scores.

---

## 7. AWS — the honest answer

AWS is a partner but **not a challenge we're judged on** (confirmed in the team handout: "Do not spend time on AWS"). And now that **Aiven hosts our compute too**, AWS has no role left — it would only be a *third* place to run the same container, and any AWS data service would **shadow Aiven**, which actively weakens our primary prize.

If we were ever forced to put it on AWS (or wanted a one-liner for an AWS mentor):

| AWS service | Maps to | Verdict |
|---|---|---|
| **App Runner** (or ECS Fargate) running the existing Dockerfile | compute plane | The *only* sensible AWS piece — same role as the Aiven app, more setup, weaker story. |
| **MSK** (managed Kafka) | Kafka | ❌ Don't — duplicates Aiven Kafka and kills the Aiven narrative. |
| **RDS Postgres** | Postgres | ❌ Don't — duplicates Aiven Postgres. |
| **Lambda** | agent loop / TTS | ❌ Same serverless limits as Vercel; agents belong on Managed Agents anyway. |

**Verdict: skip AWS.** The compute home is the Aiven app (Fly/Railway as fallback); the data home is Aiven; the agent home is Anthropic. AWS is over-engineering for zero judged upside.

---

## 8. Recommendation (the one-line answer)

> **Frontend → Vercel (Aiven app `/` as same-origin fallback). Compute → the deterministic data pipeline runs on an Aiven Application service, deployed via the Aiven MCP, with Kafka + Postgres auto-injected — no laptop, no tunnel. Data → Aiven Kafka + Postgres, live in Finland, kept warm by the 60s poll. Agents → Claude Managed Agents (scheduled + live-triggerable) that read/write Postgres and produce to Kafka directly through the Aiven MCP, with Slack/Gmail HITL; the in-app `orchestrator` + `DEMO_MODE` is the break-glass. AWS → skip.**

This maximizes all three rubrics at once: Aiven is the managed backbone *and* the compute host *and* the agents' control surface, all driven through MCP — provision + deploy + operate (34% + 33%); the agents are real scheduled/triggerable autonomous monitors with HITL (Anthropic 30/30/20/20); and the demo stays bulletproof because the in-app path + `DEMO_MODE` survives even if cloud connectivity wobbles.

---

## 9. Demo-day runbook

Most of this is **already deployed and running** — the runbook is mostly *verification*, not startup (that's the point of moving off the laptop).

**Day before — deploy once, leave running**
```text
1. aiven_application_deploy → app pulls the repo, builds the Dockerfile, runs
   FastAPI + ingest + state_builder; Kafka + PG creds auto-injected.
2. Register the two Managed Agents (Investigator + Watch Officer); connect the
   Aiven remote MCP (mcp.aiven.live/mcp, bare URL) + ElevenLabs + Slack/Gmail.
3. Set the Investigator's schedule; confirm one scheduled run writes findings.
4. Deploy the Vercel console; API base = Aiven app URL (or just use the app's /).
```

**T-30 min — verify the live system (it's already up)**
```bash
APP=https://<aiven-app-url>
curl $APP/health                       # {"ok": true}
curl $APP/vessels | head              # live vessels present (ingest is flowing = Kafka warm)
# Confirm the Managed Agent's last scheduled run succeeded (Anthropic console).
```

**T-10 min — dry-run the centerpiece**
```bash
curl -X POST $APP/replay/eagle-s       # inject Eagle S
curl $APP/assessment/latest            # verdict exists?
curl $APP/voice/latest                 # voice ready?
```

**Break-glass (if the Managed-Agent→MCP path wobbles live):** set `DEMO_MODE=true` (or flip to the in-app `orchestrator`) — the Eagle S replay still produces the complete dossier from the Aiven app alone. Plus the recorded screen-capture of the §2 north-star demo and cached `demo_assets/`.

---

## 10. Config, secrets & gotchas (deployment-specific)

- **App env vars:** the Aiven app injects service creds automatically — don't paste connection strings. Set `ANTHROPIC_API_KEY` / `ELEVENLABS_API_KEY` as `secret` env vars in the deploy call. Keep `backend/.env` (gitignored) for local; `.env.example` ships placeholders.
- **Kafka auth — the one code change:** the live service uses **SASL_SSL / SCRAM-SHA-256** (what `kafka_client.py` does today, dotted keys `ssl.ca.location` ✔). But the **Aiven app integration injects SSL/mTLS** (`KAFKA_ACCESS_CERT`/`KAFKA_ACCESS_KEY`/`KAFKA_CA_CERT`, `KAFKA_SECURITY_PROTOCOL=SSL`). Add a branch in `_conf_base()`: if the cert env vars are present, use `security.protocol=SSL` + `ssl.certificate.location`/`ssl.key.location`; else fall back to SCRAM. Small, isolated.
- **PG on the app:** set the integration `env_key=AIVEN_POSTGRES_URL` to match [config.py](backend/app/config.py); the app injects `PROJECT_CA_CERT` for TLS — ensure the connection URL keeps `sslmode=require` (psycopg handles it).
- **Aiven MCP:** use the **bare URL** (`https://mcp.aiven.live/mcp`) — `?read_only=true` makes write ops silently no-op (and the agents must write). Enable **Kafka REST** (`kafka_rest: true` via `aiven_service_update`) before agents produce via MCP.
- **CORS:** `allow_origins=["*"]` is set for the demo. Fine for a hackathon; tighten if this ever leaves the venue.
- **Idle power-off:** the #1 demo-killer — the `ingest` poll on the Aiven app is the heartbeat; it runs continuously, so the broker stays warm. Confirm the app is up the morning of.
- **pgvector stretch:** `aiven_pg_service_available_extensions` → enable `vector` on `baltic-pg`, add an embedding column to `agent_findings`, let the Investigator do a similarity lookup over past investigations via MCP. Directly scores the Aiven "long-term memory" line. Only if the core is solid.

---

## 11. Open decisions to lock (don't revisit after)

1. **Compute host:** Aiven app vs Fly/Railway fallback. → *Recommend Aiven app (strongest story); keep Fly ready if the repo can't be connected or the plan is too small.*
2. **One container vs split services** for FastAPI + ingest + state_builder. → *Recommend one container + a `start.sh` launcher for the demo; split later if needed.*
3. **Agent path that drives the live demo:** Managed Agents (via Aiven MCP) vs the in-app orchestrator. → *Recommend Managed Agents drive (it's the story + the autonomy points); in-app orchestrator + `DEMO_MODE` is the break-glass.*
4. **Repo readiness for `aiven_application_deploy`:** confirm `github.com/cgutum/baltic-sentinel` URL + branch + public/private (private → connect GitHub in the Aiven console first). → *Lock at deploy time; the tool refuses to run until these are confirmed.*
