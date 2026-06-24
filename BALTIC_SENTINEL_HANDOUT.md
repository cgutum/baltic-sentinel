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
- Running the Claude agent workflow.
- Identity Agent.
- Behavior Agent.
- Sanctions/Record Agent.
- GPS Environment Agent.
- Final synthesis agent.
- ElevenLabs voice generation.
- Saving agent findings and final assessments into Postgres.

Person B should **not** build ship data ingest or tripwire rules.

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

Person B:

- Build a fake/manual consumer for `vessel.suspicion`.
- Manually test with a fake suspicion JSON.
- Start writing fallback agent outputs.

Done when:

- Person A can publish ship events.
- Person B can consume a fake suspicion event.

---

## H5–H7: Person A tripwire, Person B agents

Person A:

- Build tripwire worker.
- Read `ais.raw`.
- If ship is slow near cable, publish `vessel.suspicion`.

Person B:

- Build Identity Agent.
- Build Behavior Agent.
- Make both return short JSON.

Done when:

- Eagle S replay creates a suspicion event.
- Fake suspicion can create two agent findings.

---

## H7–H10: Agent workflow

Person A:

- Improve tripwire reliability.
- Add simple GPS/cable risk fields.
- Save suspicion events properly.

Person B:

- Add Sanctions/Record Agent.
- Add GPS Environment Agent.
- Publish all four findings to `agent.findings`.

Done when:

- One suspicion event creates four agent findings.

---

## H10–H13: Final synthesis

Person A:

- Add helpful context to suspicion messages.
- Make sure replay always triggers.
- Add demo logs.

Person B:

- Build synthesis agent.
- Publish `threat.assessment`.
- Save assessment to Postgres.
- Make `/assessment/latest` return the latest result.

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

- Add ElevenLabs voice generation.
- Make `/voice/latest` return the audio URL.
- Add fallback `sample_voice.mp3`.

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

Build the agent workflow:
1. Listen to Kafka topic vessel.suspicion.
2. Run four Claude agents: Identity, Behavior, Sanctions Record, GPS Environment.
3. Publish each finding to Kafka topic agent.findings.
4. Save findings to Postgres.
5. Run a synthesis agent to create a final threat assessment.
6. Publish the final assessment to Kafka topic threat.assessment.
7. Save the assessment to Postgres.
8. Generate an ElevenLabs voice briefing from the voice_script.
9. Add fallback outputs for Eagle S if Claude or ElevenLabs fails.

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
3. four agent.findings
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
