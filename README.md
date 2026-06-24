# Baltic Sentinel

Voice-first maritime incident system. Ship events flow through **Aiven Kafka**,
suspicious behavior is detected, **Claude agents** investigate, results are
stored in **Aiven Postgres**, and **ElevenLabs** speaks the final watch-officer
briefing.

```text
Ship event → ais.raw → tripwire → vessel.suspicion → Claude agents
→ agent.findings → synthesis → threat.assessment → Postgres + ElevenLabs voice
```

See [contracts.md](contracts.md) for the shared message formats and the
[handout](BALTIC_SENTINEL_HANDOUT.md) for the full plan.

## Quick start (backend)

```bash
conda activate st
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env   # then fill in real keys
uvicorn app.main:app --reload --port 8000
```

Verify it is alive:

```bash
curl http://localhost:8000/health
# -> {"ok": true}
```

## Team

- **Person A** — Data Pipeline Lead (`backend/app/data_pipeline/`)
- **Person B** — Agent Workflow Lead (`backend/app/agent_workflow/`)

| Where | Port |
|---|---|
| Backend | http://localhost:8000 |
| Frontend | http://localhost:3000 |
