#!/usr/bin/env bash
# Single-container launcher for the Aiven Application service.
# Runs the two always-on workers (auto-restarting) in the background and
# uvicorn in the foreground as PID 1. The 60s ingest poll is also the Kafka
# heartbeat, so keeping it alive keeps the free-tier broker warm.
set -uo pipefail

# Write the Kafka CA from an env var (the cert is gitignored, not baked into the image),
# so SSL verification works in the container. Optional: kafka_client falls back to
# skipping verification if neither a CA file nor KAFKA_CA_PEM is present.
if [ -n "${KAFKA_CA_PEM:-}" ]; then
  printf '%s\n' "$KAFKA_CA_PEM" > /app/ca.pem
  export AIVEN_KAFKA_CA=/app/ca.pem
  echo "[start] wrote Kafka CA from KAFKA_CA_PEM -> /app/ca.pem"
fi

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
