#!/usr/bin/env bash
# Single-container launcher. uvicorn runs in the foreground as PID 1 (serves the
# console/API/agents). The ingest + state_builder workers run ONLY when this host is
# the designated single writer (RUN_WORKERS=true) — see the gate below — so two hosts
# never double-ingest or fight over the Kafka partition.
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

# Single-writer gate: run ingest + state_builder ONLY on the one host designated with
# RUN_WORKERS=true. Everywhere else (e.g. Railway serving the console) stays serve-only.
case "${RUN_WORKERS:-false}" in
  1|true|TRUE|yes|YES|on)
    echo "[start] RUN_WORKERS=$RUN_WORKERS -> launching ingest + state_builder"
    run_forever python -m app.data_pipeline.ingest &
    run_forever python -m app.data_pipeline.state_builder &
    ;;
  *)
    echo "[start] RUN_WORKERS off -> serve-only (no ingest/state_builder)"
    ;;
esac

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
