#!/usr/bin/env bash
# Single-container launcher for the Aiven Application service.
# Runs the two always-on workers (auto-restarting) in the background and
# uvicorn in the foreground as PID 1. The 60s ingest poll is also the Kafka
# heartbeat, so keeping it alive keeps the free-tier broker warm.
set -uo pipefail

run_forever () {
  while true; do
    echo "[start] launching: $*"
    "$@" || echo "[start] '$*' exited ($?); restarting in 3s"
    sleep 3
  done
}

run_forever python -m app.data_pipeline.ingest &
run_forever python -m app.data_pipeline.state_builder &

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
