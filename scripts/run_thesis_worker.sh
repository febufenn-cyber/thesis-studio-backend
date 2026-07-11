#!/usr/bin/env bash
# Durable ingestion/export worker with a hard virtual-memory ceiling inherited
# by LibreOffice subprocesses. Override only after measuring the VM.
set -euo pipefail
cd /opt/thesis-studio-backend
ulimit -v "${THESIS_WORKER_VMEM_KB:-900000}"
exec /opt/thesis-studio-backend/venv/bin/python -m app.services.job_queue
