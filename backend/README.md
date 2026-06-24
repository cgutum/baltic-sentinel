# Baltic Sentinel — Backend

FastAPI backend. Runs at `http://localhost:8000`.

## Run

```bash
conda activate st
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Health check

```bash
curl http://localhost:8000/health   # -> {"ok": true}
```

## Layout

```text
app/
  main.py          FastAPI app + router wiring (shared)
  config.py        env settings (shared)
  models.py        Pydantic message models from contracts.md (shared)
  kafka_client.py  Aiven Kafka helpers (shared)
  database.py      Aiven Postgres helpers (shared)
  data_pipeline/   Person A
  agent_workflow/  Person B
  api/             routes (shared)
```
