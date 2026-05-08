#!/usr/bin/env bash
#
# Deploy thesis-studio-backend to the Oracle Cloud VM.
#
# Idempotent: first run installs everything; subsequent runs just pull code,
# install new deps if requirements.txt changed, run new migrations, restart pm2.
#
# Prerequisites on the dev machine:
#   - Working tree clean (committed)
#   - `git remote get-url origin` resolves; `git push origin main` works
#   - SSH to ${VM_USER}@${VM_HOST} works using the key at ${SSH_KEY}
#     (default ~/.ssh/oracle_key; override with SSH_KEY=...)
#
# Prerequisites on the GitHub repo:
#   - A read-only deploy key registered on the repo whose private half
#     lives at /home/ubuntu/.ssh/thesis_deploy_key on the VM. The script
#     uses this via GIT_SSH_COMMAND when cloning/pulling.
#
# Prerequisites on the VM (first run):
#   - Ubuntu 22.04+, ubuntu user with passwordless sudo
#   - /opt/thesis-studio-backend/.env exists with production values
#     (scp it manually before first deploy — see SETUP-CLOUDFLARE-TUNNEL.md
#     for the env-vars list)
#
# After first successful deploy, the chat endpoint will fail until you also:
#   1. ssh ubuntu@<VM> and run `claude /login` interactively
#   2. ssh ubuntu@<VM> and `pm2 restart thesis-api` to reload the auth state
#
# Usage:
#   scripts/deploy_to_oracle.sh
#
# Override defaults via env vars:
#   VM_HOST=1.2.3.4 VM_USER=ubuntu scripts/deploy_to_oracle.sh
#   SSH_KEY=~/.ssh/other_key scripts/deploy_to_oracle.sh
#   REPO_URL_SSH=git@github.com:org/repo.git scripts/deploy_to_oracle.sh

set -euo pipefail

VM_USER="${VM_USER:-ubuntu}"
VM_HOST="${VM_HOST:-68.233.116.11}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/oracle_key}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/thesis-studio-backend}"
PM2_NAME="${PM2_NAME:-thesis-api}"
APP_PORT="${APP_PORT:-8000}"
REPO_URL_SSH="${REPO_URL_SSH:-git@github.com:febufenn-cyber/thesis-studio-backend.git}"
VM_DEPLOY_KEY="${VM_DEPLOY_KEY:-/home/ubuntu/.ssh/thesis_deploy_key}"

SSH_OPTS=(-i "${SSH_KEY}" -o BatchMode=yes)

echo "==> Pre-flight checks"

if [[ ! -f "${SSH_KEY}" ]]; then
    echo "ERROR: SSH key not found at ${SSH_KEY}." >&2
    echo "       Override with: SSH_KEY=~/.ssh/other_key $0" >&2
    exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
    echo "ERROR: working tree is dirty. Commit or stash before deploying." >&2
    git status --short
    exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
    echo "ERROR: no 'origin' remote configured. Set one with:" >&2
    echo "  git remote add origin git@github.com:<you>/thesis-studio-backend.git" >&2
    exit 1
fi

if ! ssh "${SSH_OPTS[@]}" -o ConnectTimeout=5 "${VM_USER}@${VM_HOST}" true 2>/dev/null; then
    echo "ERROR: cannot SSH to ${VM_USER}@${VM_HOST} with key ${SSH_KEY}." >&2
    echo "       Confirm the public half is in ~/.ssh/authorized_keys on the VM," >&2
    echo "       or set SSH_KEY=<path> to point at the right key." >&2
    exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "==> Pushing ${CURRENT_BRANCH} to origin"
git push origin "${CURRENT_BRANCH}"

echo "==> Running remote bootstrap on ${VM_USER}@${VM_HOST}"
ssh "${SSH_OPTS[@]}" -T "${VM_USER}@${VM_HOST}" bash -s -- \
    "${REPO_URL_SSH}" \
    "${DEPLOY_PATH}" \
    "${PM2_NAME}" \
    "${APP_PORT}" \
    "${CURRENT_BRANCH}" \
    "${VM_DEPLOY_KEY}" <<'REMOTE_SCRIPT'
set -euo pipefail

REPO_URL="$1"
DEPLOY_PATH="$2"
PM2_NAME="$3"
APP_PORT="$4"
GIT_BRANCH="$5"
VM_DEPLOY_KEY="$6"

# Tell git to authenticate to GitHub via the deploy key only.
export GIT_SSH_COMMAND="ssh -i ${VM_DEPLOY_KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

if ! sudo -n true 2>/dev/null; then
    echo "ERROR: ubuntu user does not have passwordless sudo on this VM." >&2
    echo "       Configure /etc/sudoers.d/ubuntu with 'ubuntu ALL=(ALL) NOPASSWD:ALL'" >&2
    echo "       or run this deploy as a user that does have it." >&2
    exit 1
fi

echo "[remote] Updating apt cache"
sudo apt-get update -qq

echo "[remote] Installing system packages (idempotent)"
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    git curl ca-certificates build-essential \
    python3.11 python3.11-venv python3.11-dev \
    postgresql postgresql-client \
    >/dev/null

if ! command -v node >/dev/null 2>&1 || [[ "$(node -v 2>/dev/null | cut -d. -f1 | tr -d v)" -lt 20 ]]; then
    echo "[remote] Installing Node.js 20 via NodeSource"
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - >/dev/null
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs >/dev/null
fi

if ! command -v pm2 >/dev/null 2>&1; then
    echo "[remote] Installing pm2 globally"
    sudo npm install -g pm2 >/dev/null
fi

if ! command -v claude >/dev/null 2>&1; then
    echo "[remote] Installing Claude Code CLI globally"
    sudo npm install -g @anthropic-ai/claude-code >/dev/null
fi

echo "[remote] Ensuring Postgres is running"
sudo systemctl enable --now postgresql >/dev/null

if [[ ! -d "${DEPLOY_PATH}" ]]; then
    echo "[remote] First deploy — cloning repo to ${DEPLOY_PATH}"
    sudo mkdir -p "${DEPLOY_PATH}"
    sudo chown "$(id -un):$(id -gn)" "${DEPLOY_PATH}"
    git clone "${REPO_URL}" "${DEPLOY_PATH}"
fi

cd "${DEPLOY_PATH}"
echo "[remote] git pull"
git fetch origin
git reset --hard "origin/${GIT_BRANCH}"

if [[ ! -f "${DEPLOY_PATH}/.env" ]]; then
    echo "ERROR: ${DEPLOY_PATH}/.env does not exist." >&2
    echo "       scp your production .env to the VM before the first deploy:" >&2
    echo "         scp .env.production ${USER}@<vm>:${DEPLOY_PATH}/.env" >&2
    exit 1
fi

echo "[remote] Creating venv if needed"
if [[ ! -d "${DEPLOY_PATH}/venv" ]]; then
    python3.11 -m venv "${DEPLOY_PATH}/venv"
fi

echo "[remote] pip install (only refetches if requirements.txt changed)"
"${DEPLOY_PATH}/venv/bin/pip" install -q --upgrade pip
"${DEPLOY_PATH}/venv/bin/pip" install -q -r "${DEPLOY_PATH}/requirements.txt"

echo "[remote] Ensuring Postgres role + database exist (parsing .env DATABASE_URL)"
DATABASE_URL_LINE="$(grep -E '^DATABASE_URL=' "${DEPLOY_PATH}/.env" | head -1 | cut -d= -f2-)"
if [[ -z "${DATABASE_URL_LINE}" ]]; then
    echo "ERROR: DATABASE_URL not set in ${DEPLOY_PATH}/.env" >&2
    exit 1
fi
DB_USER="$(echo "${DATABASE_URL_LINE}" | sed -E 's|.*://([^:]+):.*|\1|')"
DB_PASS="$(echo "${DATABASE_URL_LINE}" | sed -E 's|.*://[^:]+:([^@]+)@.*|\1|')"
DB_NAME="$(echo "${DATABASE_URL_LINE}" | sed -E 's|.*/([^?]+).*|\1|')"

sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASS}'"

sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}"

echo "[remote] Running alembic migrations"
cd "${DEPLOY_PATH}"
PYTHONPATH="${DEPLOY_PATH}" "${DEPLOY_PATH}/venv/bin/alembic" upgrade head

echo "[remote] Bootstrapping institutions if table empty"
INSTITUTION_COUNT="$(sudo -u postgres psql -tAc "SELECT COUNT(*) FROM ${DB_NAME}.public.institutions" 2>/dev/null || echo 0)"
if [[ "${INSTITUTION_COUNT}" == "0" ]]; then
    PYTHONPATH="${DEPLOY_PATH}" "${DEPLOY_PATH}/venv/bin/python" \
        "${DEPLOY_PATH}/scripts/create_institution.py" \
        --name "Madras Christian College (Autonomous)" \
        --short-name "MCC" \
        --domains "mcc.edu.in,students.mcc.edu.in" \
        --address "Tambaram, Chennai – 600 059." \
        --short-address "Tambaram, Chennai – 59" \
        --university "University of Madras" \
        --department "PG & Research Department of English" \
        --aided

    PYTHONPATH="${DEPLOY_PATH}" "${DEPLOY_PATH}/venv/bin/python" \
        "${DEPLOY_PATH}/scripts/create_institution.py" \
        --name "The American College (Autonomous)" \
        --short-name "AMC" \
        --domains "theamericancollege.edu.in,students.theamericancollege.edu.in" \
        --address "Tallakulam, Madurai – 625 002." \
        --short-address "Madurai – 625 002" \
        --university "Madurai Kamaraj University" \
        --department "PG & Research Department of English" \
        --aided
else
    echo "[remote] Skipping bootstrap — ${INSTITUTION_COUNT} institutions already exist"
fi

echo "[remote] Ensuring run wrapper is executable"
chmod +x "${DEPLOY_PATH}/scripts/run_thesis_api.sh"

echo "[remote] Starting / restarting pm2 process '${PM2_NAME}' from ecosystem.config.js"
cd "${DEPLOY_PATH}"
if pm2 describe "${PM2_NAME}" >/dev/null 2>&1; then
    APP_PORT="${APP_PORT}" pm2 restart "${DEPLOY_PATH}/ecosystem.config.js" --update-env
else
    APP_PORT="${APP_PORT}" pm2 start "${DEPLOY_PATH}/ecosystem.config.js"
    pm2 save
fi

if ! systemctl is-enabled pm2-"$(id -un)" >/dev/null 2>&1; then
    echo "[remote] Enabling pm2 startup on boot"
    PM2_STARTUP_CMD="$(pm2 startup systemd -u "$(id -un)" --hp "$HOME" | tail -1)"
    if [[ "${PM2_STARTUP_CMD}" == sudo* ]]; then
        eval "${PM2_STARTUP_CMD}"
        pm2 save
    fi
fi

echo
echo "==> pm2 status"
pm2 status

echo
echo "==> Last 50 log lines"
pm2 logs "${PM2_NAME}" --lines 50 --nostream || true

echo
echo "==> Healthcheck"
sleep 2
curl -fsS "http://127.0.0.1:${APP_PORT}/healthz" && echo
REMOTE_SCRIPT

echo
echo "==> Deploy complete."
echo
echo "If this was the first deploy, you still need to authenticate Claude Code on the VM:"
echo "  ssh ${VM_USER}@${VM_HOST}"
echo "  claude /login         # follow the URL → browser → paste code back"
echo "  claude -p 'say hello' # verify"
echo "  pm2 restart ${PM2_NAME}"
