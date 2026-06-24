# Baltic Sentinel — 2-Person Backend Handoff

**Goal:** build the backend first in 20 hours, then spend 4 hours on storyline, UI, and pitch.

This handout is written for a **non-technical 2-person team**. Follow it like an operations checklist.

---

## 1. The project in one sentence

**Baltic Sentinel** is a voice-first maritime incident system: ship events flow through **Aiven Kafka**, suspicious behavior is detected, **Claude agents** investigate, results are stored in **Aiven Postgres**, and **ElevenLabs** speaks the final watch-officer briefing.

---

## 2. What we are optimizing for

We are now optimizing for the **Aiven challenge**.

Use:

- **Aiven Kafka** = the event pipe between system parts.
- **Aiven Postgres** = the memory/database.
- **Claude** = the agent investigators.
- **ElevenLabs** = the spoken watch officer.
- **Vercel** = frontend later.
- **Laptop + tunnel** = backend hosting for demo, unless deployment is already easy.

Do **not** spend time on AWS unless everything else is already working. AWS is no longer a judged challenge for us.

---

## 3. Simple mental model

```text
Ship event
  ↓
Kafka topic: ais.raw
  ↓
Tripwire detector
  ↓
Kafka topic: vessel.suspicion
  ↓
Claude agent workflow
  ↓
Kafka topic: agent.findings
  ↓
Final synthesis
  ↓
Kafka topic: threat.assessment
  ↓
Postgres stores result + ElevenLabs creates voice briefing
```

The frontend is only the screen. The backend is the machine.

---

## 4. Team split

## Person A — Data Pipeline Lead

Person A owns everything up to the suspicious event.

Person A builds:

```text
Replay / ship data
  ↓
Kafka topic: ais.raw
  ↓
Tripwire detector
  ↓
Kafka topic: vessel.suspicion
  ↓
Postgres storage for tracks and suspicions
```

Person A is responsible for:

- Eagle S replay.
- Ship event format.
- Optional live ship API ingest.
- Kafka producer for `ais.raw`.
- Tripwire detector.
- Kafka producer for `vessel.suspicion`.
- Saving ship tracks and suspicion events into Postgres.

Person A should **not** build Claude agents.

---

## Person B — Agent Workflow Lead

Person B owns everything after a suspicious event exists.

Person B builds:

```text
Kafka topic: vessel.suspicion
  ↓
Claude agents
  ↓
Kafka topic: agent.findings
  ↓
Final synthesis
  ↓
Kafka topic: threat.assessment
  ↓
ElevenLabs voice briefing
  ↓
Postgres storage for findings and assessments
```

Person B is responsible for:

- Listening for `vessel.suspicion` messages.
- Running the Claude agent workflow (see §4.1 — **one Investigator agent doing
  multi-step tool calls**, not four single-shot agents).
- Investigator agent: identity, behavior, sanctions (mock), GPS/cable context,
  plus real online research via Claude's built-in web search.
- Watch Officer agent: final synthesis → threat assessment.
- ElevenLabs voice generation + a drafted human alert.
- Saving agent findings and final assessments into Postgres.
- (Stretch) Shadow Tracker agent on a schedule.

Person B should **not** build ship data ingest or tripwire rules.

---

## 4.1 Agent Architecture (Updated — supersedes the four-mini-agent list above)

After review, we are **not** building four separate single-shot agents
(Identity / Behavior / Sanctions / GPS). The Anthropic challenge explicitly
penalizes "a single prompt in a wrapper," and four single-shot agents read as
exactly that. Instead, **one Investigator agent does multi-step tool calling** —
that is what scores on "agentic depth." It still produces several finding cards
(one per tool result), so the UI stays rich.

### Recommended architecture (if things go well)

```text
Tripwire Worker (cheap code, Person A — NOT a Claude agent)
  → Kafka vessel.suspicion + Postgres row

[Scheduled trigger — native Managed Agent schedule, NOT an agent]
  ↓
Investigator Agent (Claude Managed Agent)   ← multi-step, tool-using
  - reads suspicion + track + identity + GPS + cable + sanctions (mock)
  - does real online research with Claude's built-in web search
  - writes 3-5 findings → Postgres + Kafka agent.findings
  ↓
Watch Officer Agent (Claude Managed Agent)
  - reads all findings → LOW/MEDIUM/HIGH + reasoning + voice_script
  - saves assessment → Postgres + Kafka threat.assessment
  - creates ElevenLabs voice briefing
  - drafts a human alert (Slack/email)   ← human-in-the-loop + connector points
  ↓
(Stretch) Shadow Tracker Agent — re-checks the vessel over time, escalates
```

### Minimum viable architecture (guaranteed floor)

```text
ONE Claude Managed Agent, triggered live:
  claim suspicion → investigate (tools) → write findings (Postgres+Kafka)
  → synthesize assessment → publish (Postgres+Kafka) → voice briefing
+ Full fallback path (canned findings/assessment/voice) behind DEMO_MODE
```

If only the MVP works, we still have a complete, defensible autonomous agent.
Everything else is an upgrade.

### Number of agents — decisions

- **Scheduler is NOT a Claude agent.** Managed Agents give us scheduling for
  free. Use the native schedule/trigger; don't spend an LLM on polling Postgres.
- **Two Claude agents is the target** (Investigator + Watch Officer). The split
  gives us a natural human-escalation handoff, which the judges reward.
- **One agent is the safe floor.** Build the whole loop as one agent first,
  split into two only if time allows.
- **A 3rd agent (Shadow Tracker) only if we are ahead.** It maps exactly onto
  the challenge line "runs on a schedule without watching it" — build it as a
  **scheduled deployment** that re-checks each vessel on a cadence and escalates
  if risk rises. For the demo, simulate time passing (feed a second, worse
  position) so it visibly escalates on stage.

### How the agent loop runs — decide at H5 (lean semi-autonomous + HITL)

The Investigator's "brain" can run two ways, and BOTH plug into the same
orchestrator + tools (Option A), so the H3-H5 fallback work is unaffected:

- **Claude Managed Agent** — Anthropic runs the loop; free scheduling/state; the
  challenge nudges toward it. Risk = the cloud→Aiven connectivity.
- **Our own harness** — a raw Claude API tool-calling loop we run on the laptop
  (a "workflow"). More control, keys stay local, easiest to make bulletproof
  live. Smaller "Managed Agents" scoring nudge.

Either way the system is **semi-autonomous with a human at the end**: the agent
investigates and *recommends*; a human decides and acts. We do NOT build
automatic enforcement (see §16). Pick the loop-runner at H5; nothing before then
depends on it.

### What is real vs mock

| Info | Source | Real or mock |
|---|---|---|
| Suspicion event, recent track, vessel identity | Aiven Postgres (Person A) | Real (our own data) |
| Online research about the vessel | Claude built-in web search | Real — Eagle S is a real sanctioned tanker; keep a canned fallback |
| Sanctions / watchlist | Static JSON (or web search) | Mock — cheap, good story |
| GPS-degraded region, cable corridor | Rule from lat/lon | Mock |
| "Following the vessel over time" | Scheduled re-check (3rd agent) | Real schedule, simulated time for demo |

---

## 4.2 Connectivity — how the agent reaches Aiven (DECISION: Option A)

The Managed Agent runs in Anthropic's cloud, **not** on our laptop, so it cannot
see Aiven Postgres/Kafka by magic. We bridge it with **Option A**.

### ✅ Option A — Custom tools, executed on our laptop (CHOSEN)

We declare tools (`get_recent_track`, `lookup_sanctions`, `publish_finding`,
`create_voice_briefing`, ...) as **custom tools** on the agent. When the agent
calls one, it emits an event; our laptop orchestrator (holding the agent's event
stream open) runs the real code against Aiven / ElevenLabs with our local keys
and sends the result back.

- **Why:** simplest reliable path; Aiven and ElevenLabs keys **never leave our
  laptop**; matches the laptop + tunnel demo plan; reuses our FastAPI code;
  trivial to mock (`DEMO_MODE` returns canned data); no public server to host.
- **Cost:** the orchestrator process must stay running during the demo (fine),
  and we write the tool-dispatch glue ourselves.

### 📝 Option B — Our own MCP server (note only, not building now)

Build a small MCP server wrapping the same tools; the agent connects via
`mcp_toolset` with credentials in an Anthropic vault. Cleaner "MCP-native" story,
but we must host the server publicly (HTTPS via tunnel) + set up vault auth —
more setup and more to break live. Revisit only if well ahead.

### 📝 Option C — Aiven MCP, agent queries the data layer directly (note only)

If Aiven offers an MCP server, the agent could query Postgres/Kafka directly —
the strongest *Aiven-challenge narrative* ("the agent controls Aiven via MCP").
But it runs raw SQL (riskier), still needs voice + Kafka-publish handled
elsewhere, and is hardest to mock. Consider as a **read-only flourish** on top of
Option A if we are ahead — not as the core.

---

## 5. The shared agreement: `contracts.md`

Before splitting, both people must create and agree on one file:

```text
contracts.md
```

This file is the agreement between Person A and Person B.

**Rule:** once agreed, do not change it casually. If it changes, both people must pull the change and update their code.

---

# 5.1 Kafka topics

Create these Aiven Kafka topics:

```text
ais.raw
vessel.suspicion
agent.findings
threat.assessment
voice.briefing
```

Plain meaning:

| Topic | Meaning | Owner |
|---|---|---|
| `ais.raw` | Raw ship events | Person A |
| `vessel.suspicion` | Danger detected | Person A produces, Person B consumes |
| `agent.findings` | Claude agent outputs | Person B |
| `threat.assessment` | Final report | Person B |
| `voice.briefing` | Audio briefing created | Person B |

---

# 5.2 Message format: `ais.raw`

Person A sends this into Kafka topic `ais.raw`.

```json
{
  "mmsi": "518998000",
  "imo": "9329760",
  "name": "Eagle S",
  "lat": 59.7,
  "lon": 24.9,
  "speed": 1.8,
  "course": 270,
  "timestamp": "2026-06-24T12:00:00Z",
  "source": "replay"
}
```

---

# 5.3 Message format: `vessel.suspicion`

Person A sends this into Kafka topic `vessel.suspicion`.

Person B starts work from this message.

```json
{
  "suspicion_id": "sus_001",
  "mmsi": "518998000",
  "imo": "9329760",
  "name": "Eagle S",
  "rule": "slow_near_cable",
  "cable": "Estlink 2",
  "severity": 0.85,
  "summary": "Vessel moving below 3 knots inside Estlink 2 cable corridor.",
  "timestamp": "2026-06-24T12:01:00Z"
}
```

---

# 5.4 Message format: `agent.findings`

Person B sends one of these for each Claude agent.

```json
{
  "suspicion_id": "sus_001",
  "agent": "Behavior Agent",
  "severity": 0.9,
  "finding": "The vessel is moving slowly inside a cable corridor.",
  "evidence": [
    "Speed below 3 knots",
    "Position overlaps Estlink 2 corridor"
  ]
}
```

---

# 5.5 Message format: `threat.assessment`

Person B sends this after all agents finish.

```json
{
  "suspicion_id": "sus_001",
  "level": "HIGH",
  "confidence": 0.86,
  "summary": "Suspicious vessel movement detected near Estlink 2.",
  "reasoning": [
    "Slow movement inside cable corridor",
    "Infrastructure at risk",
    "AIS/GPS trust may be degraded in the region"
  ],
  "recommended_action": "Escalate to a human operator and notify the cable operator.",
  "voice_script": "High risk alert. Suspicious vessel movement detected near Estlink 2. Recommend human escalation and independent verification."
}
```

---

## 6. Repository structure

Use this folder structure.

```text
baltic-sentinel/
  README.md
  contracts.md
  .gitignore
  .env.example

  backend/
    README.md
    requirements.txt
    Dockerfile

    app/
      main.py
      config.py
      models.py
      kafka_client.py
      database.py

      data_pipeline/
        replay_eagle_s.py
        ship_ingest.py
        tripwire.py
        geo_rules.py

      agent_workflow/
        orchestrator.py
        identity_agent.py
        behavior_agent.py
        sanctions_agent.py
        gps_environment_agent.py
        synthesis_agent.py
        voice.py
        fallback_outputs.py

      api/
        routes.py
        events.py

  frontend/
    README.md
    package.json
    src/
      App.jsx
      api.js
      components/
        EventTimeline.jsx
        AgentCards.jsx
        AssessmentPanel.jsx
        VoicePlayer.jsx

  demo_assets/
    sample_events.jsonl
    sample_assessment.json
    sample_voice.mp3
```

---

## 7. File ownership

This is important so Git does not become chaos.

## Person A owns these files

```text
backend/app/data_pipeline/replay_eagle_s.py
backend/app/data_pipeline/ship_ingest.py
backend/app/data_pipeline/tripwire.py
backend/app/data_pipeline/geo_rules.py
```

Person A can also edit:

```text
backend/app/models.py
backend/app/kafka_client.py
backend/app/database.py
```

But if Person A changes shared files, Person B must be told immediately.

---

## Person B owns these files

```text
backend/app/agent_workflow/orchestrator.py
backend/app/agent_workflow/identity_agent.py
backend/app/agent_workflow/behavior_agent.py
backend/app/agent_workflow/sanctions_agent.py
backend/app/agent_workflow/gps_environment_agent.py
backend/app/agent_workflow/synthesis_agent.py
backend/app/agent_workflow/voice.py
backend/app/agent_workflow/fallback_outputs.py
```

Person B can also edit:

```text
backend/app/models.py
backend/app/kafka_client.py
backend/app/database.py
```

But if Person B changes shared files, Person A must be told immediately.

---

## Shared files: edit carefully

These files are shared. Do not both edit them at the same time.

```text
contracts.md
backend/app/models.py
backend/app/kafka_client.py
backend/app/database.py
backend/app/main.py
backend/app/api/routes.py
.env.example
README.md
```

Before editing a shared file, say in chat:

```text
I am editing backend/app/models.py now.
```

When done, commit and push.

---

## 8. Git workflow

Use GitHub.

Assume the main branch is called:

```text
main
```

Do not both work directly on `main`.

---

# 8.1 Branch names

Use exactly these branches:

```text
person-a-data-pipeline
person-b-agent-workflow
integration-demo
```

Plain meaning:

| Branch | Who uses it | Purpose |
|---|---|---|
| `main` | Everyone, but only stable code | Working version |
| `person-a-data-pipeline` | Person A | Data ingest, replay, tripwire |
| `person-b-agent-workflow` | Person B | Claude agents, synthesis, voice |
| `integration-demo` | Both, later | Combine both sides for demo |

---

# 8.2 First-time setup

Both people run:

```bash
git clone <YOUR_GITHUB_REPO_URL>
cd baltic-sentinel
```

Then:

Person A runs:

```bash
git checkout -b person-a-data-pipeline
```

Person B runs:

```bash
git checkout -b person-b-agent-workflow
```

---

# 8.3 How to save work

Every time you complete a small piece, run:

```bash
git status
git add .
git commit -m "clear message of what changed"
git push origin YOUR_BRANCH_NAME
```

Examples:

Person A:

```bash
git add .
git commit -m "add Eagle S replay producer"
git push origin person-a-data-pipeline
```

Person B:

```bash
git add .
git commit -m "add behavior agent fallback output"
git push origin person-b-agent-workflow
```

---

# 8.4 How to get the latest stable code

Before starting a new work session, run:

```bash
git checkout main
git pull origin main
```

Then go back to your branch.

Person A:

```bash
git checkout person-a-data-pipeline
git merge main
```

Person B:

```bash
git checkout person-b-agent-workflow
git merge main
```

If Git asks you about conflicts, stop and ask Claude Code:

```text
I have a Git merge conflict. Explain it simply and help me resolve it without losing work.
```

---

# 8.5 How to merge finished work safely

Use Pull Requests on GitHub.

Person A opens PR:

```text
person-a-data-pipeline → main
```

Person B opens PR:

```text
person-b-agent-workflow → main
```

Before merging, the other person should review:

- Does the app still run?
- Did it change `contracts.md` unexpectedly?
- Did it break the agreed message format?

After merging a PR, both people run:

```bash
git checkout main
git pull origin main
```

Then update your personal branch:

```bash
git checkout YOUR_BRANCH_NAME
git merge main
```

---

# 8.6 Git rules to avoid breaking things

1. Do not commit `.env`.
2. Do not put real API keys in GitHub.
3. Do not both edit shared files at the same time.
4. Commit small changes often.
5. Pull before starting work.
6. If something works, commit it immediately.
7. If something breaks, do not panic. Use `git status` first.

---

## 9. `.env` and secrets

Create this file locally:

```text
.env
```

Never commit it.

Create this file in GitHub:

```text
.env.example
```

`.env.example` should contain fake placeholders:

```text
ANTHROPIC_API_KEY=your_anthropic_key_here
ELEVENLABS_API_KEY=your_elevenlabs_key_here
AIVEN_KAFKA_BOOTSTRAP=your_kafka_bootstrap_here
AIVEN_KAFKA_USERNAME=your_kafka_username_here
AIVEN_KAFKA_PASSWORD=your_kafka_password_here
AIVEN_POSTGRES_URL=your_postgres_url_here
DEMO_MODE=true
```

Add this to `.gitignore`:

```text
.env
*.pem
*.key
__pycache__/
.venv/
node_modules/
```

---

## 10. Localhost setup

During development:

```text
Backend runs at:  http://localhost:8000
Frontend runs at: http://localhost:3000
```

Plain meaning:

- `localhost` = your own laptop.
- Backend = the worker machine.
- Frontend = the screen.

The frontend calls the backend.

Example:

```text
Click Replay button
  ↓
POST http://localhost:8000/replay/eagle-s
  ↓
Backend starts replay
```

---

## 11. Backend routes

Create these backend routes:

| Route | Type | Meaning |
|---|---|---|
| `/health` | GET | Check backend is alive |
| `/replay/eagle-s` | POST | Start the Eagle S replay |
| `/assessment/latest` | GET | Return latest final report |
| `/voice/latest` | GET | Return latest voice briefing |
| `/events` | GET | Stream live events for UI |

Plain meaning:

- `GET` = give me information.
- `POST` = do an action.

---

## 12. 20-hour backend plan

## H0–H1: Together — setup

Do together:

- Create repo.
- Create folder structure.
- Create `contracts.md`.
- Create `.env.example`.
- Create `.gitignore`.
- Create basic FastAPI backend.
- Test `/health`.

Done when:

```text
http://localhost:8000/health returns {"ok": true}
```

---

## H1–H3: Together — Aiven foundation

Do together:

- Connect Aiven MCP.
- Create/connect Aiven Kafka.
- Create/connect Aiven Postgres.
- Create Kafka topics.
- Create Postgres tables.

Done when:

- You can send one test Kafka message.
- You can read one test Kafka message.
- You can insert one test Postgres row.

---

## H3–H5: Split starts

Person A:

- Build `replay_eagle_s.py`.
- Publish fake Eagle S ship events to `ais.raw`.
- Save track rows to Postgres.

Person B (see §4.1 / §4.2 for the architecture):

- **Build the fallback path FIRST** — hardcoded Eagle S suspicion → mock tools →
  canned findings + assessment, printed to console. This is the demo safety net.
- Load a fake `vessel.suspicion` JSON to drive it.
- Spike **Option A** connectivity: confirm a local orchestrator can run one
  custom tool (even a stub) and hand its result back.

Done when:

- Person A can publish ship events.
- Person B can run the whole fake investigation end-to-end in `DEMO_MODE`
  (findings + assessment printed, no external services needed).

---

## H5–H7: Person A tripwire, Person B agents

Person A:

- Build tripwire worker.
- Read `ais.raw`.
- If ship is slow near cable, publish `vessel.suspicion`.

Person B:

- Build the **Investigator agent** (one Claude Managed Agent) wired through
  **Option A** (custom tools executed by the laptop orchestrator).
- Start with 2 tools: `get_suspicion_event` + `get_recent_track`.
- Have it write findings → `agent.findings`.

Done when:

- Eagle S replay creates a suspicion event.
- A fake suspicion makes the Investigator agent produce real agent findings
  (not canned — actual tool calls).

---

## H7–H10: Agent workflow

Person A:

- Improve tripwire reliability.
- Add simple GPS/cable risk fields.
- Save suspicion events properly.

Person B:

- Add the rest of the Investigator's tools: `get_vessel_identity`,
  `lookup_sanctions` (mock list), `check_gps_environment`, `get_cable_context`.
- Add **real online research** using Claude's built-in web search.
- Publish 3-5 findings to `agent.findings`; save them to Postgres.

Done when:

- One suspicion event makes the Investigator produce several findings,
  including one from web research.

---

## H10–H13: Final synthesis

Person A:

- Add helpful context to suspicion messages.
- Make sure replay always triggers.
- Add demo logs.

Person B:

- Build the **Watch Officer agent** (synthesis): read all findings →
  LOW/MEDIUM/HIGH + confidence + reasoning + `voice_script`.
- Publish `threat.assessment`.
- Save assessment to Postgres.
- Make `/assessment/latest` return the latest result.
- Add idempotency (`mark_suspicion_event_processed`) so re-runs don't duplicate.

Done when:

```text
POST /replay/eagle-s
  ↓
final assessment exists
```

---

## H13–H16: Voice

Person A:

- Keep the data pipeline stable.
- Help test full flow.

Person B:

- Watch Officer creates the ElevenLabs voice briefing (via an Option A custom
  tool run on the laptop).
- Make `/voice/latest` return the audio URL.
- Add fallback `sample_voice.mp3`.
- Add the **human alert draft** (Slack/email) — connector + human-in-the-loop
  points the judges reward.
- Make the Investigator a **real scheduled/triggerable Managed Agent** so the
  "runs on a schedule without watching it" story is true, not hypothetical.

Done when:

- Replay creates final assessment.
- Final assessment creates audio briefing.

---

## H16–H18: Integration

Both:

- Merge Person A and Person B work into `integration-demo` branch.
- Run the full flow.
- Fix only connection problems.

Integration branch commands:

```bash
git checkout main
git pull origin main
git checkout -b integration-demo
```

Then merge both branches:

```bash
git merge person-a-data-pipeline
git merge person-b-agent-workflow
```

If conflicts happen, stop and resolve together.

Done when:

```text
POST /replay/eagle-s
  ↓
ais.raw
  ↓
vessel.suspicion
  ↓
agent.findings
  ↓
threat.assessment
  ↓
voice.briefing
```

---

## H18–H20: Freeze backend

Both:

- Stop adding new features.
- Run the backend demo five times.
- Save backup outputs.
- Commit known-good state.

Create:

```text
demo_assets/sample_events.jsonl
demo_assets/sample_assessment.json
demo_assets/sample_voice.mp3
```

Done when:

- Full backend flow works.
- Backup mode works.
- Code is committed.

---

## 13. Final 4-hour story plan

## H20–H21: Story

Write the pitch:

```text
Undersea cables are critical.
AIS data is noisy and sometimes untrustworthy.
Humans cannot watch everything manually.
Baltic Sentinel detects risky behavior near cable corridors.
Claude agents investigate.
Aiven Kafka/Postgres power the event stream and memory.
ElevenLabs speaks the watch-officer briefing.
The system recommends human escalation, not automatic action.
```

---

## H21–H22.5: Simple UI

Use Vercel for frontend.

Build only:

- Replay button.
- Live event timeline.
- Agent cards.
- Final assessment panel.
- Voice briefing player.

Do not build a complex map unless the backend is already stable.

---

## H22.5–H23.5: Sponsor framing

Aiven line:

```text
Aiven is our core data layer. Kafka carries ship events, suspicion events, and agent findings. Postgres stores investigation memory. MCP lets the agent environment control and query the data infrastructure directly.
```

Anthropic line:

```text
Claude is not a chatbot here. Claude agents wake up from Kafka events, investigate in parallel, and synthesize a final operational assessment.
```

ElevenLabs line:

```text
Voice is the watch officer. In a fast multi-agent investigation, voice keeps the human oriented while the system is acting.
```

---

## H23.5–H24: Rehearse

Run the demo script:

1. Open UI.
2. Click Replay Eagle S.
3. Show event timeline.
4. Show agents completing.
5. Show final assessment.
6. Play voice briefing.
7. Explain Aiven Kafka/Postgres.
8. Close with human escalation.

Record a backup video.

---

## 14. Prompts for Claude Code

## Person A prompt

```text
I am Person A, Data Pipeline Lead for Baltic Sentinel.

Use contracts.md exactly.

Build the data pipeline:
1. Publish Eagle S replay events to Kafka topic ais.raw.
2. Save ship tracks to Postgres.
3. Read ais.raw in a tripwire worker.
4. If a vessel is moving below 3 knots near Estlink 2, publish a suspicion event to Kafka topic vessel.suspicion.
5. Save suspicion events to Postgres.

Only edit files in backend/app/data_pipeline unless a shared file is necessary.
Explain every step simply because we are non-technical.
```

---

## Person B prompt

```text
I am Person B, Agent Workflow Lead for Baltic Sentinel.

Use contracts.md exactly.

Build the agent workflow (see §4.1 / §4.2):
1. Listen to Kafka topic vessel.suspicion.
2. Run ONE Investigator agent (Claude Managed Agent) that does multi-step tool
   calls: identity, behavior, sanctions (mock), GPS/cable, and real online
   research via built-in web search. Not four single-shot agents.
3. Wire tools through Option A (custom tools run by a laptop orchestrator, so
   Aiven/ElevenLabs keys never leave the laptop).
4. Publish each finding to Kafka topic agent.findings and save to Postgres.
5. Run a Watch Officer agent to create the final threat assessment.
6. Publish the final assessment to Kafka topic threat.assessment + save it.
7. Make /assessment/latest return it; add idempotency on processed suspicions.
8. Generate an ElevenLabs voice briefing from voice_script + draft a human alert.
9. Add fallback outputs for Eagle S if Claude or ElevenLabs fails (build first).
10. (Stretch) Add a scheduled Shadow Tracker agent that re-checks the vessel.

Only edit files in backend/app/agent_workflow unless a shared file is necessary.
Explain every step simply because we are non-technical.
```

---

## 15. Definition of done

The backend is done when this works:

```bash
curl -X POST http://localhost:8000/replay/eagle-s
```

And then the system creates:

```text
1. ais.raw ship events
2. vessel.suspicion danger event
3. several agent.findings (3-5, from the one Investigator agent)
4. one threat.assessment
5. one voice.briefing
6. latest assessment saved in Postgres
7. latest voice file available
```

If that works, you have the core product.

Everything else is packaging.

---

## 16. What not to build

Do not build these during the first 20 hours:

- User accounts.
- Login.
- Payments.
- Fancy dashboard.
- Complex live map.
- Satellite data.
- Tangled integration.
- AWS deployment.
- Perfect geospatial math.
- Too many agents.
- Automatic enforcement.

Focus only on:

```text
Aiven Kafka/Postgres
+ ship replay
+ tripwire
+ Claude agents
+ ElevenLabs voice
```

---

## 17. Emergency fallback

If something breaks before judging, use fallback mode.

Fallback mode should return:

```text
demo_assets/sample_events.jsonl
demo_assets/sample_assessment.json
demo_assets/sample_voice.mp3
```

Pitch it honestly as:

```text
This is our cached replay path. The architecture is the same; we keep a fallback so the demo remains reliable under hackathon conditions.
```

---

## 18. Final reminder

The winning demo is not about having the most features.

The winning demo is:

```text
A suspicious ship event enters Aiven Kafka.
A tripwire detects risk.
Claude agents investigate.
Aiven Postgres stores the investigation.
ElevenLabs speaks the result.
A human gets a clear recommendation.
```

Build exactly that.
