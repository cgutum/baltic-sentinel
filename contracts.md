# contracts.md — Baltic Sentinel Shared Agreement

This file is the agreement between **Person A (Data Pipeline Lead)** and
**Person B (Agent Workflow Lead)**.

**Rule:** once agreed, do not change it casually. If it changes, both people
must pull the change and update their code. Before editing this file, say so in
chat first.

---

## 1. Kafka topics

| Topic | Meaning | Owner |
|---|---|---|
| `ais.raw` | Raw ship events | Person A |
| `vessel.suspicion` | Danger detected | Person A produces, Person B consumes |
| `agent.findings` | Claude agent outputs | Person B |
| `threat.assessment` | Final report | Person B |
| `voice.briefing` | Audio briefing created | Person B |

---

## 2. Message format: `ais.raw`

Person A → `ais.raw`

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

## 3. Message format: `vessel.suspicion`

Person A → `vessel.suspicion`. Person B starts work from this message.

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

## 4. Message format: `agent.findings`

Person B → `agent.findings`. One message per Claude agent.

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

## 5. Message format: `threat.assessment`

Person B → `threat.assessment`. Sent after all agents finish.

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

## 6. Backend routes

| Route | Type | Meaning |
|---|---|---|
| `/health` | GET | Check backend is alive → `{"ok": true}` |
| `/replay/eagle-s` | POST | Start the Eagle S replay |
| `/assessment/latest` | GET | Return latest final report |
| `/voice/latest` | GET | Return latest voice briefing |
| `/events` | GET | Stream live events for UI |

---

## 7. File ownership

**Person A owns:**
`backend/app/data_pipeline/replay_eagle_s.py`,
`backend/app/data_pipeline/ship_ingest.py`,
`backend/app/data_pipeline/tripwire.py`,
`backend/app/data_pipeline/geo_rules.py`

**Person B owns:**
`backend/app/agent_workflow/orchestrator.py`,
`identity_agent.py`, `behavior_agent.py`, `sanctions_agent.py`,
`gps_environment_agent.py`, `synthesis_agent.py`, `voice.py`,
`fallback_outputs.py`

**Shared (edit carefully, announce first):**
`contracts.md`, `backend/app/models.py`, `backend/app/kafka_client.py`,
`backend/app/database.py`, `backend/app/main.py`,
`backend/app/api/routes.py`, `.env.example`, `README.md`
