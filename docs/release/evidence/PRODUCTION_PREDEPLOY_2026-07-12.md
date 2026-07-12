# Production Pre-Deploy State — thesis.robofox.online — 2026-07-12

Captured before any change. No secrets, no thesis content. Companion:
`PRODUCTION_PREDEPLOY_2026-07-12.json`.

## What the domain serves today

`https://thesis.robofox.online` currently serves the **legacy v1 Thesis
Studio**, not a Phase 1–5 release. Confirmed, not assumed:

- `/healthz` → 200 `{"status":"ok"}` (v1 shape; the Phase 5 app returns a
  release-identity object)
- `/readyz` → **404** (endpoint does not exist in v1)
- `/meta/release` → **404** (endpoint does not exist in v1)
- root `/` → 200

## Edge and origin

| Property | Value |
|---|---|
| DNS | `thesis.robofox.online` → `172.67.173.228`, `104.21.30.225` (Cloudflare) |
| Edge | Cloudflare proxy (server: cloudflare, cf-ray …-SIN); TLS valid at edge |
| Origin path | Cloudflare → nginx (Certbot TLS) → `proxy_pass http://127.0.0.1:8000` |
| Origin host | Oracle VM `68.233.116.11`, Ubuntu 22.04, **x86_64**, 2 vCPU |
| App process | PM2 `thesis-api` (online, 7 restarts, ~14 MB RSS) |

## v1 application facts

| Property | Value |
|---|---|
| Deploy dir | `/opt/thesis-studio-backend` |
| Source commit | `2b11a09df1dd122d762d5dc57572b30a080d56b1` |
| `ENV` | production |
| Database | `postgresql://…@localhost:5432/thesis_studio` (**on-host PostgreSQL 14.23**) |
| **Alembic revision** | **`0006`** |
| Storage backend | **`local`** |
| Email | Resend key present |
| ClamAV | **none** (no container, no binary) |
| Worker topology | none separate (v1 uses in-process background tasks) |
| Backups | **none existed** before this mission (see PRODUCTION_BACKUP evidence) |

## Host capacity (shared, multi-tenant)

- RAM: **956 MB total, ~318 MB available** (476 MB used)
- Disk: 29 GB free of 49 GB
- Co-tenant production services on the same host (must stay healthy):
  LeadFinder (`leads`/`api`), NetPrep (`netprep`, Streamlit :8503), FoxLabel,
  RoboFox Voice, RoboFox clothing site, the marketing site, and the
  separately-authorised **E2 demo stack** (thesis-demo-*, ~56 MB total).

## Release under consideration

- Eligible attested application SHA: `69d5333c059731d8b040171bc0754df951407171`
  (PR #9 merge; derived by `scripts/latest_attested_release.py`, not hand-copied)
- Multi-arch image available (from the PR #8 build; PR #9 changed only
  workflow/demo/docs, no app runtime): amd64
  `sha256:d023b02c963201865d5bb932e58096bd5c7729d30c9461b2f4a479132a31a46c`
- Release schema target: `0018` (app 0.7.0)

## Immediate consequence for the plan

The live production schema is **0006**; the release is **0018**. A production
cutover would require a **12-step, five-phase forward migration** (0007→0018)
across real user data — outside the safe scope of a single reversible canary
and requiring its own staged migration plan. This compounds the
infrastructure blockers in `PRODUCTION_BLOCKERS.md`.
