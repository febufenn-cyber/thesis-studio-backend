# Provider Readiness — Malware Scanning (ClamAV)

Date: 2026-07-12 · Commit `7397fdc`

## Validated (real, local — all in the 173/0/0/0 suite run)

- **Protocol handling** (`app/services/malware_service.py`, INSTREAM over TCP):
  - clean response accepted — `test_clamd_clean_response`
  - detection rejected — `test_clamd_detected_response_is_rejected`
    (EICAR-signature response fixture)
  - scanner error / unknown response **fails closed** —
    `test_clamd_error_and_unknown_response_fail_closed`
- **Production fail-closed config**: `PRODUCTION_REQUIRE_MALWARE_SCAN` +
  `MALWARE_SCAN_MODE!=clamav` refuses to boot —
  `test_production_requires_clamav` / `test_production_accepts_configured_clamav`
  (made hermetic on this branch; validator unchanged).
- **Upload integration**: `app/ingest/preflight.py` scans before any DOCX parse;
  scanner-unavailable raises `MalwareScannerUnavailableError` (503 handler in
  `app/core/exceptions.py`) — uploads are blocked, never scanned-open.
- **Readiness**: `malware_scanner_ready()` PING/PONG probe; a required-but-down
  scanner fails `/readyz`.
- **Deployment model**: `deploy/compose.phase5.yml` runs ClamAV internal-only
  (no published port), image pinned via `CLAMAV_IMAGE`.

## Blocked (staging)

| Item | Unblock |
|---|---|
| Live EICAR upload rejection through a real scanner | Deploy staging stack; upload EICAR fixture via the app; retain the 4xx rejection + audit row as evidence |
| Scanner-outage readiness flip (real) | Stop the ClamAV container in staging; verify `/readyz` 503 and upload 503 |
| Signature-DB freshness policy | Record freshclam cadence once the container runs |

Note: local execution used `MALWARE_SCAN_MODE=disabled` (recorded in every
local evidence artifact); no local result claims live-scanner behavior.
