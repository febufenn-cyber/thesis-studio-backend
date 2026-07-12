# Provider Readiness — Email (Resend)

Date: 2026-07-12 · Commit `7397fdc`

## Validated (real)

- **Verified sender domain**: `robofox.online` verified in Resend
  (2026-07-11, account `febufenn`). API key is **sending-only**, named
  `thesis-studio`, stored only in the v1 VM `.env` (0 occurrences in tracked
  files — secret scan passed).
- **Live delivery**: OTP email to a real mailbox showed **Delivered** in the
  Resend dashboard on 2026-07-11 (production login flow at
  `thesis.robofox.online`).
- **DNS posture (queried 2026-07-12)**:
  - DKIM: `resend._domainkey.robofox.online` TXT present (RSA key published)
  - SPF: `send.robofox.online` TXT `v=spf1 include:amazonses.com ~all`
    (Resend envelope subdomain; MX `feedback-smtp.us-east-1.amazonses.com`)
  - DMARC: `_dmarc.robofox.online` TXT `v=DMARC1; p=quarantine; adkim=r;
    aspf=r; rua=mailto:…` — relaxed alignment, quarantine policy, aggregate
    reports enabled
- **No manuscript content in email**: `app/services/email_service.py` sends
  only magic-link URLs and 6-digit OTP codes; no thesis fields are passed in.
- **Dev fallback**: with no API key the service logs the link/OTP instead of
  sending — no silent failure.

## Blocked / gaps (honest)

| Item | Status |
|---|---|
| Invitation delivery template | `membership_invitations` exist server-side; a dedicated invitation email function is not present in `email_service.py` — invitations currently rely on link distribution. Needs either a template or an explicit product decision before institutional onboarding. |
| Bounce/complaint handling | No bounce webhook endpoint is implemented; failures surface only as Resend API errors. Acceptable for staging; production should register a Resend webhook and record bounce policy. |
| Provider rate limits | Resend free-tier limits (100/day) apply to the current key; a paid plan or institution SMTP is required before cohort-scale sends. |
| Staging recipient policy | `STAGING_ACCEPTANCE.md` requires a staging-safe recipient policy (no real student emails) — enforced operationally, not yet in code. |
