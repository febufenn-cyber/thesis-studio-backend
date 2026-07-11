#!/usr/bin/env bash
# Deploy Robofox Thesis Studio to the Oracle VM.
#
# Phase 1 runtime requirements:
# - PostgreSQL migrations
# - API + durable worker under PM2
# - LibreOffice Writer and Times New Roman for deterministic PDF output
# - swap protection on the small shared VM
# - liveness and readiness verification

set -euo pipefail

VM_USER="${VM_USER:-ubuntu}"
VM_HOST="${VM_HOST:-68.233.116.11}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/oracle_key}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/thesis-studio-backend}"
APP_PORT="${APP_PORT:-8000}"
REPO_URL_SSH="${REPO_URL_SSH:-git@github.com:febufenn-cyber/thesis-studio-backend.git}"
VM_DEPLOY_KEY="${VM_DEPLOY_KEY:-/home/ubuntu/.ssh/thesis_deploy_key}"
SWAP_SIZE="${SWAP_SIZE:-2G}"
SSH_OPTS=(-i "${SSH_KEY}" -o BatchMode=yes)

echo "==> Local preflight"
[[ -f "${SSH_KEY}" ]] || { echo "ERROR: SSH key missing: ${SSH_KEY}" >&2; exit 1; }
[[ -z "$(git status --porcelain)" ]] || { echo "ERROR: working tree is dirty" >&2; git status --short; exit 1; }
git remote get-url origin >/dev/null 2>&1 || { echo "ERROR: origin remote missing" >&2; exit 1; }
ssh "${SSH_OPTS[@]}" -o ConnectTimeout=8 "${VM_USER}@${VM_HOST}" true 2>/dev/null || {
  echo "ERROR: cannot SSH to ${VM_USER}@${VM_HOST} with ${SSH_KEY}" >&2
  exit 1
}

CURRENT_BRANCH="$(git branch --show-current)"
echo "==> Pushing ${CURRENT_BRANCH}"
git push origin "${CURRENT_BRANCH}"

echo "==> Deploying ${CURRENT_BRANCH} to ${VM_HOST}"
ssh "${SSH_OPTS[@]}" -T "${VM_USER}@${VM_HOST}" bash -s -- \
  "${REPO_URL_SSH}" "${DEPLOY_PATH}" "${APP_PORT}" "${CURRENT_BRANCH}" \
  "${VM_DEPLOY_KEY}" "${SWAP_SIZE}" <<'REMOTE_SCRIPT'
set -euo pipefail

REPO_URL="$1"
DEPLOY_PATH="$2"
APP_PORT="$3"
GIT_BRANCH="$4"
VM_DEPLOY_KEY="$5"
SWAP_SIZE="$6"
export GIT_SSH_COMMAND="ssh -i ${VM_DEPLOY_KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

sudo -n true 2>/dev/null || {
  echo "ERROR: deployment user needs passwordless sudo" >&2
  exit 1
}

echo "[remote] Installing system runtime"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  git curl ca-certificates build-essential software-properties-common \
  python3.11 python3.11-venv python3.11-dev \
  postgresql postgresql-client \
  libreoffice-writer fontconfig cabextract \
  >/dev/null

if ! command -v node >/dev/null 2>&1 || [[ "$(node -v 2>/dev/null | cut -d. -f1 | tr -d v)" -lt 20 ]]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - >/dev/null
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs >/dev/null
fi
command -v pm2 >/dev/null 2>&1 || sudo npm install -g pm2 >/dev/null
command -v claude >/dev/null 2>&1 || sudo npm install -g @anthropic-ai/claude-code >/dev/null

# The renderer and readiness probe intentionally require the actual family.
if ! fc-list | grep -qi "Times New Roman"; then
  echo "[remote] Installing Microsoft core fonts"
  sudo add-apt-repository -y multiverse >/dev/null 2>&1 || true
  echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | \
    sudo debconf-set-selections
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ttf-mscorefonts-installer >/dev/null
  sudo fc-cache -f >/dev/null
fi
fc-list | grep -qi "Times New Roman" || {
  echo "ERROR: Times New Roman is still unavailable; refusing an inaccurate production deploy" >&2
  exit 1
}
command -v soffice >/dev/null 2>&1 || {
  echo "ERROR: LibreOffice soffice is unavailable" >&2
  exit 1
}

# Protect the shared VM from simultaneous Python/LibreOffice memory pressure.
if [[ -z "$(swapon --show --noheadings 2>/dev/null)" ]]; then
  echo "[remote] Creating ${SWAP_SIZE} swapfile"
  sudo fallocate -l "${SWAP_SIZE}" /swapfile || \
    sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

sudo systemctl enable --now postgresql >/dev/null

if [[ ! -d "${DEPLOY_PATH}/.git" ]]; then
  echo "[remote] Cloning repository"
  sudo mkdir -p "${DEPLOY_PATH}"
  sudo chown "$(id -un):$(id -gn)" "${DEPLOY_PATH}"
  git clone "${REPO_URL}" "${DEPLOY_PATH}"
fi
cd "${DEPLOY_PATH}"
git fetch origin
git reset --hard "origin/${GIT_BRANCH}"

[[ -f "${DEPLOY_PATH}/.env" ]] || {
  echo "ERROR: ${DEPLOY_PATH}/.env is missing" >&2
  exit 1
}

[[ -d "${DEPLOY_PATH}/venv" ]] || python3.11 -m venv "${DEPLOY_PATH}/venv"
"${DEPLOY_PATH}/venv/bin/pip" install -q --upgrade pip
"${DEPLOY_PATH}/venv/bin/pip" install -q -r "${DEPLOY_PATH}/requirements.txt"

DATABASE_URL_LINE="$(grep -E '^DATABASE_URL=' "${DEPLOY_PATH}/.env" | head -1 | cut -d= -f2-)"
[[ -n "${DATABASE_URL_LINE}" ]] || { echo "ERROR: DATABASE_URL missing" >&2; exit 1; }
DB_USER="$(echo "${DATABASE_URL_LINE}" | sed -E 's|.*://([^:]+):.*|\1|')"
DB_PASS="$(echo "${DATABASE_URL_LINE}" | sed -E 's|.*://[^:]+:([^@]+)@.*|\1|')"
DB_NAME="$(echo "${DATABASE_URL_LINE}" | sed -E 's|.*/([^?]+).*|\1|')"

sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASS}'"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}"

cd "${DEPLOY_PATH}"
PYTHONPATH="${DEPLOY_PATH}" "${DEPLOY_PATH}/venv/bin/alembic" upgrade head

INSTITUTION_COUNT="$(sudo -u postgres psql -d "${DB_NAME}" -tAc 'SELECT COUNT(*) FROM public.institutions' 2>/dev/null || echo 0)"
if [[ "${INSTITUTION_COUNT//[[:space:]]/}" == "0" ]]; then
  PYTHONPATH="${DEPLOY_PATH}" "${DEPLOY_PATH}/venv/bin/python" scripts/create_institution.py \
    --name "Madras Christian College (Autonomous)" --short-name "MCC" \
    --domains "mcc.edu.in,students.mcc.edu.in" --address "Tambaram, Chennai – 600 059." \
    --short-address "Tambaram, Chennai – 59" --university "University of Madras" \
    --department "PG & Research Department of English" --aided
  PYTHONPATH="${DEPLOY_PATH}" "${DEPLOY_PATH}/venv/bin/python" scripts/create_institution.py \
    --name "The American College (Autonomous)" --short-name "AMC" \
    --domains "theamericancollege.edu.in,students.theamericancollege.edu.in" \
    --address "Tallakulam, Madurai – 625 002." --short-address "Madurai – 625 002" \
    --university "Madurai Kamaraj University" \
    --department "PG & Research Department of English" --aided
fi

chmod +x scripts/run_thesis_api.sh
rm -f /tmp/robofox-thesis-worker.heartbeat
APP_PORT="${APP_PORT}" pm2 startOrRestart ecosystem.config.js --update-env
pm2 save

if ! systemctl is-enabled pm2-"$(id -un)" >/dev/null 2>&1; then
  STARTUP_CMD="$(pm2 startup systemd -u "$(id -un)" --hp "$HOME" | tail -1)"
  [[ "${STARTUP_CMD}" == sudo* ]] && eval "${STARTUP_CMD}"
  pm2 save
fi

sleep 5
echo "[remote] PM2 status"
pm2 status
curl -fsS "http://127.0.0.1:${APP_PORT}/healthz" && echo
curl -fsS "http://127.0.0.1:${APP_PORT}/readyz" && echo
REMOTE_SCRIPT

echo "==> Deploy complete and readiness verified"
