# Staging Execution Package — ARM64 (OCI A1)

Date: 2026-07-12 · Companion to `OCI_A1_STAGING_SPEC.md`, `POSTGRES_STAGING_SPEC.md`,
`R2_STAGING_SPEC.md`, `STAGING_PROVISIONING.md`.

**The official path is the release workflow** (step 9's dispatch runs verify →
multi-arch build/push → env verify → migrate → up → smoke). Every manual
command below is a recovery/debug path or a post-deploy exercise, not the
normal deployment method. Placeholders: `$DB_URL` = staging DATABASE_URL,
`$ACC` = R2 account id. Never echo secrets; use stdin/files.

## 1. Host bootstrap (once, after VM launch per OCI_A1_STAGING_SPEC)

```bash
uname -m                                   # expect: aarch64
sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg nginx postgresql-client-16
# Docker (official repo, arm64) + cloudflared: exact commands in OCI_A1_STAGING_SPEC §10
docker info --format '{{.Architecture}}'   # expect: aarch64
sudo install -m 700 -d /opt/thesis-staging && cd /opt/thesis-staging
git clone --depth 1 https://github.com/febufenn-cyber/thesis-studio-backend.git repo
sudo install -m 600 /dev/null /opt/thesis-staging/.env   # then fill from .env.staging.example
sudo cp repo/deploy/nginx-staging.conf /etc/nginx/sites-available/thesis-staging
sudo ln -sf ../sites-available/thesis-staging /etc/nginx/sites-enabled/ && sudo nginx -t && sudo systemctl reload nginx
```

## 2. GHCR authentication (read-only PAT with `read:packages`)

```bash
docker login ghcr.io -u febufenn-cyber --password-stdin   # paste PAT, Ctrl-D
```

## 3. Pull the digest-addressed image

```bash
# manifest digest comes from the release run's release-image-manifest-<sha> artifact
docker pull ghcr.io/febufenn-cyber/thesis-studio-backend@sha256:<MANIFEST_DIGEST>
docker image inspect ghcr.io/febufenn-cyber/thesis-studio-backend@sha256:<MANIFEST_DIGEST> \
  --format '{{.Architecture}} {{index .Config.Env 3}}'   # arm64 + RELEASE_SHA=...
```

## 4. Environment file

```bash
python3 repo/scripts/verify_phase5_environment.py --target staging   # with .env exported
# fails closed on CHANGE_ME leftovers, missing TLS, missing providers
```

## 5. Database connectivity (TLS)

```bash
PGSSLMODE=require psql "<libpq form of $DB_URL>" -c "select version(), current_user;"
```

## 6. R2 permission test (per R2_STAGING_SPEC §validation)

```bash
aws s3api put-object --bucket thesis-staging --key temp/permcheck --body /etc/hostname --endpoint-url https://$ACC.r2.cloudflarestorage.com
aws s3api get-object --bucket thesis-staging --key temp/permcheck /tmp/permcheck --endpoint-url https://$ACC.r2.cloudflarestorage.com
aws s3api list-objects-v2 --bucket some-other-bucket --endpoint-url https://$ACC.r2.cloudflarestorage.com && echo "FAIL: token too broad" || echo "scoped ok"
```

## 7. ClamAV readiness

```bash
docker compose -f repo/deploy/compose.phase5.yml up -d clamav && sleep 60
docker compose -f repo/deploy/compose.phase5.yml exec clamav clamdscan --version
printf 'PING' | docker compose -f repo/deploy/compose.phase5.yml exec -T clamav nc 127.0.0.1 3310   # PONG
```

## 8. Email connectivity

```bash
# Resend key already proven working in production v1; staging check is config-only:
grep -c '^RESEND_API_KEY=re_' /opt/thesis-staging/.env   # 1, value never printed
```

## 9. Migration + 10. web/worker startup — THE OFFICIAL PATH

```bash
gh workflow run phase5-release.yml \
  -f environment=staging \
  -f expected_sha=$(python scripts/latest_attested_release.py)
gh run watch
# The workflow: verifies attestation + rejects attestation-only SHAs, builds and
# pushes the amd64+arm64 manifest, records digests, then on the host: pull →
# verify_phase5_environment → alembic upgrade head → up -d → smoke.
```

Manual recovery equivalents (debug only): `docker compose -f deploy/compose.phase5.yml
run --rm --no-deps web-a alembic upgrade head` then `up -d --remove-orphans`.

## 11. Cloudflare Tunnel

```bash
cloudflared tunnel create thesis-staging
sudo cp repo/deploy/cloudflared-staging.example.yml /etc/cloudflared/config.yml  # fill tunnel id
cloudflared tunnel route dns thesis-staging thesis-staging.robofox.online
sudo systemctl enable --now cloudflared
```

## 12. Health / readiness / status / release

```bash
python repo/scripts/phase5_smoke.py --base-url https://thesis-staging.robofox.online \
  --expected-release $(python repo/scripts/latest_attested_release.py)
```

## 13. UAT driver + 14. EICAR rejection

```bash
python repo/scripts/run_uat_flows.py --base-url https://thesis-staging.robofox.online \
  --out docs/release/evidence/UAT_STAGING_RAW.json
# EICAR (fixture string, not malware): upload via the app; expect 422 + audit row
python3 - <<'PY'
eicar = r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
open("/tmp/eicar.docx", "w").write(eicar)
PY
# upload /tmp/eicar.docx through POST /projects/{id}/manuscript → expect rejection evidence
```

## 15. PDF worker crash / lease recovery

```bash
# queue an export, then kill the pdf worker mid-job:
docker compose -f repo/deploy/compose.phase5.yml kill worker-pdf
sleep 130   # > JOB_LEASE_SECONDS=120
docker compose -f repo/deploy/compose.phase5.yml up -d worker-pdf
# assert: job completed exactly once (jobs table idempotency_key), no duplicate export object
```

## 16. Backup / 17. Restore drill

Backup commands: `STAGING_PROVISIONING.md §6`. Restore drill (isolated DB on
the DB host, never the live database):

```bash
PGSSLMODE=require python repo/scripts/run_restore_drill.py \
  --source-db thesis_staging --restore-db thesis_staging_drill \
  --pg-host <db-host> --pg-user thesis_staging \
  --evidence-out docs/release/evidence/RESTORE_DRILL_STAGING_$(date +%F).json
# then set BACKUP_EVIDENCE_PATH in the host .env to the produced evidence file
```

## 18. Evidence collection

Retain: release-image-manifest artifact, smoke output, UAT JSON, EICAR
rejection response + audit row id, lease-recovery job rows, restore-drill
JSON, `docs/release/STAGING_ACCEPTANCE.md` filled in. Label everything
`staging` with the deployed manifest digest.

## 19. Rollback

```bash
# redeploy the previous attested SHA through the SAME workflow:
gh workflow run phase5-release.yml -f environment=staging -f expected_sha=<previous attested sha>
# data: expand-migrate discipline means the previous app runs against the newer schema;
# if a migration must be reverted: alembic downgrade <rev> per docs/runbooks/backup-restore.md
```

## 20. Full teardown

```bash
docker compose -f repo/deploy/compose.phase5.yml down --remove-orphans
cloudflared tunnel delete thesis-staging   # after removing the DNS route
# OCI: terminate instance (console or oci compute instance terminate) — boot volume too
# R2: empty + delete thesis-staging bucket; revoke the staging tokens
# GitHub: gh secret delete <NAME> --env staging  (for each)
```
