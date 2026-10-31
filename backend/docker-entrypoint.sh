#!/bin/sh
# Image entrypoint: migrate once, then serve with one Uvicorn worker per CPU (at most 8).
set -e

python -m app.wait_for_services
aerich upgrade

if [ -z "${WORKERS:-}" ]; then
    WORKERS=$(nproc)
    if [ "$WORKERS" -gt 8 ]; then
        WORKERS=8
    fi
fi

# Workers must sign and verify logins with the same key; unset means a new key per container start.
if [ -z "${SECRET_KEY:-}" ]; then
    SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')
fi

# Metric files belong to worker PIDs of this start only.
rm -rf "$PROMETHEUS_MULTIPROC_DIR"
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"

export WORKERS SECRET_KEY
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "$WORKERS" --timeout-graceful-shutdown 30
