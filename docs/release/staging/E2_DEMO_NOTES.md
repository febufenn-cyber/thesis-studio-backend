# E2.1.Micro Demo — Deviations Register

Date: 2026-07-12 · **DEMO ONLY.** This deployment demonstrates the attested
release on a 1 GB amd64 free-tier host. It is not staging validation, not ARM
validation, and not production readiness. The A1/ARM64 staging pilot remains
a separate, owner-authorised step.

## Deviations from the staging playbook (each deliberate)

| # | Deviation | Staging rule | Demo choice | Reason |
|---|---|---|---|---|
| 1 | Malware scanning | `MALWARE_SCAN_MODE=clamav`, internal scanner | `disabled` | ClamAV needs ~3 GB resident; impossible in 1 GB. `disabled` is the only other supported value in `app/core/config.py`. EICAR test **skipped** — recorded as skipped, never passed. |
| 2 | PostgreSQL location | Off-host, TLS required | Colocated `postgres:16-alpine` container, no TLS, isolated docker network | Explicit demo-only exception in the owner instruction. Settings mandates TLS only via the staging/production verifier, which the demo does not claim to pass. |
| 3 | `ENV` | `staging` | `development` | With no Resend key (production secret, not reusable here) and no scanner, `ENV=staging` fails `/readyz` (email component). `development` is a supported enum whose documented fallbacks (log-based OTP delivery) match what the demo actually is. No validator weakened. |
| 4 | Storage | R2 with scoped token | `local` backend on a dedicated volume | No scoped demo R2 credentials exist; `local` is a supported backend value. |
| 5 | `PRODUCTION_REQUIRE_R2` / `PRODUCTION_REQUIRE_MALWARE_SCAN` | true | false | Demo relaxation; these flags only bind in `ENV=production` anyway. |
| 6 | Postgres `max_connections` | ~20 suggested | 60 | The attested image hardcodes SQLAlchemy `pool_size=10/max_overflow=20` per process; the demo runs two processes (web+worker). 60 covers worst case without deploying unattested code. Demo load ≈ 1 user. |
| 7 | Worker topology | 4 dedicated workers | 1 worker on all queues (`general,ai,pdf,maintenance`) | 1 GB budget; AI queue is inert (`AI_GLOBAL_ENABLED=false`). |
| 8 | Ingress | Cloudflare named tunnel + DNS | Credential-free quick tunnel (`*.trycloudflare.com`) | No demo tunnel credentials exist; quick tunnels need no account, no DNS, no OCI rule changes. URL is ephemeral by design. |
| 9 | Host tenancy | Dedicated staging host | Co-tenant on the owner's E2.1.Micro alongside PM2 services | Owner-authorised demo exception. Isolation: dedicated docker network `thesis-demo-net`, `thesis-demo-*` names/volumes, loopback port 8300, memory caps totalling 832m, co-tenant services untouched. |

## Memory budget (956 MB RAM + 4 GB swap)

postgres 256m · web 192m · worker 320m (LibreOffice conversions) ·
cloudflared 64m → 832m caps; co-tenant PM2 services ~180 MB; swap absorbs
bursts. Burstable 1/8 OCPU means conversions are slow — acceptable for demo.

## What this demo does prove

The attested multi-arch release image (amd64 platform) boots, migrates,
serves, authenticates, and renders DOCX→PDF with correct fonts on the
smallest real host we own, using only supported configuration values, with
zero production resources involved.
