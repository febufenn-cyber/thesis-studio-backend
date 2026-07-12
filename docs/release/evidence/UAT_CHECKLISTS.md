# UAT Role Checklists — Human Judgement Items

Companion to `scripts/run_uat_flows.py`. The script automates every journey in
`docs/release/STAGING_ACCEPTANCE.md` that a machine can verify end-to-end and
emits `manual` or `requires-staging` rows pointing here. This document holds
only the judgements a human must make: visual fidelity, email UX, watermark
visibility, and what a role can *see* in the UI. Complete each checklist on
staging against one exact release SHA, in the same run as the script report.

Rules for evidence:

- Every item is a verifiable assertion. Mark it `[x]` only after observing it
  yourself; never from memory or from a previous release.
- The Evidence field takes a link or path (screenshot, mail-log line id,
  script report step id) — no thesis prose, no full recipient addresses, no
  tokens.
- Attach the script report (`--out` JSON) beside this file when signing off.

Run identity:

- Release SHA:
- Staging URL:
- Script report file:
- Date and operator:

---

## 1. Student

- [ ] The OTP login email arrives within 60 seconds, is addressed from the
      institutional sender domain, states the 10-minute expiry, and contains
      no tracking pixels or third-party links.
      Evidence:
- [ ] After a second-device login, the sessions screen shows both devices
      with distinguishable labels, and revoking one signs that device out on
      its next action without affecting the other.
      Evidence:
- [ ] The manuscript import review screen presents each import issue in plain
      language a non-technical MA student can act on, and resolving an issue
      visibly updates the open-issue count.
      Evidence:
- [ ] The rendered PDF preview is visually faithful to the institutional
      format: 1.5" left / 1" top-right-bottom margins, Times New Roman 12pt,
      1.5 line spacing, correct page numbering, hanging-indent works cited.
      Evidence:
- [ ] While a support-access grant is active, the student-visible banner
      states that support can see metadata only, and it disappears when the
      grant expires or is revoked.
      Evidence:
- [ ] The account data export downloaded from the UI opens, and its contents
      are limited to the student's own projects and identity.
      Evidence:

## 2. Supervisor

- [ ] The review snapshot shown in the UI is the version the student
      submitted: edits the student makes after submission do not change the
      open snapshot view.
      Evidence:
- [ ] Comments and suggestions render anchored to the exact selected text,
      and an accepted suggestion is visibly attributed as accepted by the
      student (not silently applied as supervisor text).
      Evidence:
- [ ] The supervisor UI offers no control that directly edits student prose —
      only comment, suggest, instruct, approve and request-changes actions.
      Evidence:
- [ ] The student's private AI conversation history is not visible anywhere
      in the supervisor's view of the project.
      Evidence:
- [ ] The approval screen distinguishes a snapshot-only approval (stale) from
      an active approval of the current version, using the wording the
      academic senate signed off.
      Evidence:

## 3. Operator

- [ ] The formatting console permits metadata and structure corrections but
      renders prose blocks read-only; attempting a prose change surfaces the
      "create a structured suggestion" refusal, not a silent failure.
      Evidence:
- [ ] A formatting correction (e.g. submission year) is visible in the
      project audit timeline attributed to the operator with role `operator`.
      Evidence:
- [ ] The exported DOCX opened in Microsoft Word shows no tracked changes, no
      comments, and no operator identity in document properties.
      Evidence:
- [ ] The operator cannot open the student's AI history, sources notes, or
      private comments from any screen reachable in the operator role.
      Evidence:

## 4. Department admin

- [ ] The admin project list shows metadata (title, state, deadlines,
      approvals) but offers no route to open manuscript chapter text.
      Evidence:
- [ ] Role assignment and queue screens only list projects within the
      admin's own department.
      Evidence:
- [ ] The student's private AI history and prose are invisible in every
      admin screen, including the audit timeline detail view.
      Evidence:
- [ ] The sealed submission package view presents the package checksum and
      the exact "authenticated workflow approval" wording — no claim of a
      legally certified signature anywhere in the UI or PDF.
      Evidence:
- [ ] After revoking a staff member, that member's pending invitation links
      show an opaque not-found page (no hint the invitation ever existed).
      Evidence:

## 5. External reviewer

- [ ] The access link requires entering the bound recipient email; a typo'd
      or different address shows an opaque not-found response.
      Evidence:
- [ ] The sealed reading view displays the watermark text on screen and shows
      no download control when downloads are disabled.
      Evidence:
- [ ] When a download grant is issued, the downloaded file arrives through
      the short-lived link, and (redirect path) the artifact is the sealed
      version — compare its checksum against the package manifest.
      Evidence:
- [ ] The watermark is visibly rendered on the pages of the downloaded or
      previewed PDF, not only in HTTP headers or on-screen chrome.
      Evidence:
- [ ] After expiry or revocation, the same link and email show the same
      opaque not-found response with no distinguishable error wording.
      Evidence:

## 6. Support

- [ ] The support console shows a visible banner naming the consent grant,
      its expiry, and the granting student, on every support screen for the
      project.
      Evidence:
- [ ] The diagnostic bundle rendered in the console contains job states,
      counts, checksums and identifiers only — visually confirm no chapter
      text, quotation text, source titles, or student email bodies appear.
      Evidence:
- [ ] Retrying a failed job from the console shows the new queued attempt and
      an audit entry with the support justification; the console never
      displays document content while doing so.
      Evidence:
- [ ] When the grant expires, the project disappears from the support
      console with an opaque not-found response.
      Evidence:

---

## Sign-off

| Role checklist | Completed by | Date | Result (pass / defects) |
|---|---|---|---|
| Student | | | |
| Supervisor | | | |
| Operator | | | |
| Department admin | | | |
| External reviewer | | | |
| Support | | | |

Blocking defects found:

Non-blocking defects found:

Decision input for `docs/release/STAGING_ACCEPTANCE.md`: `pass | conditional | fail`
