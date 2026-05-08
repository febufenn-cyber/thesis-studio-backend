#!/usr/bin/env bash
#
# pm2 invokes this wrapper so we can set a virtual-memory cap before exec'ing
# uvicorn. Both uvicorn and any subprocess it spawns (notably `claude -p`)
# inherit the cap, bounding worst-case memory pressure on the 1GB VM.
#
# 716800 KB ≈ 700 MB. Tune with: edit and `pm2 restart thesis-api`.

set -euo pipefail

ulimit -v 716800

exec /opt/thesis-studio-backend/venv/bin/uvicorn \
    app.main:app \
    --host 127.0.0.1 \
    --port "${APP_PORT:-8000}"
