# Phase 4 Completion — Collaborative Academic Workspace

Phase 4 turns Robofox Thesis Studio into a governed institutional workspace. It does not make collaboration equivalent to shared unrestricted editing. It separates authorship, advising, reviewing, formatting, evidence verification, approval, administration, external examination, and support access.

## Completion principle

The student remains the author. Supervisors review and suggest. Formatting operators correct structure and presentation. Departments govern workflow metadata and institutional requirements. Institution administrators manage versioned policy, profiles, retention, onboarding, and aggregate operations. Robofox remains an assistant. No role silently acquires every authority.

## Canonical authority

- `Project` remains the canonical thesis source of truth.
- Existing student owners retain their Phase 1–3 project access.
- Shared access is represented through organization and project memberships rather than a single supervisor column.
- Identity, claimed affiliation, verified affiliation, project membership, and capability are separate records.
- A selected/default institution does not create administrator privileges.
- Cross-tenant and unauthorized object access returns opaque `404` responses.

## Roles and capabilities

Phase 4 evaluates explicit capabilities such as:

- `project.read_metadata`
- `project.read_content`
- `project.read_sources`
- `project.read_ai_history`
- `project.edit_content`
- `project.edit_structure`
- `project.edit_metadata`
- `project.comment`
- `project.suggest`
- `project.accept_suggestion`
- `project.approve_chapter`
- `project.approve_academic`
- `project.approve_formatting`
- `source.verify`
- `project.transition_submission`
- `profile.manage_department`
- `profile.manage_institution`
- `template.manage`
- `policy.manage`
- `retention.manage`
- `analytics.read_aggregate`

Default authority boundaries:

| Role | Default authority |
|---|---|
| Student | Author, edit canonical content, manage evidence, use governed AI, submit reviews, accept/reject suggestions, make authorship attestation |
| Supervisor | Read assigned thesis/evidence, comment, suggest, issue instructions, approve academic content; no silent prose mutation |
| Formatting operator | Correct metadata and structure, prepare and approve formatting; no academic approval or prose rewriting |
| Department administrator | Assign work, operate queues, govern department workflow/profile, see operational metadata; no default thesis-content or AI-chat access |
| Institution administrator | Govern policies, templates, retention, onboarding, aggregate analytics and audit metadata; no default thesis-content or AI-chat access |
| External reviewer | Time-limited access to one sealed version with explicit permissions and recipient binding |
| Support | Explicit, consent-bound, time-limited capabilities with audit visibility |

## Multi-tenant foundation

New relational entities include:

- departments
- organization memberships
- project memberships
- membership invitations
- review assignments
- project handoffs
- notification preferences and notifications
- lifecycle requests
- support-access grants
- limited project presence

Every shared project request resolves institution, department, active verified affiliation, active project membership, capability, expiry, content/source/AI-history flags, and revocation state.

## Asynchronous review collaboration

Phase 4 deliberately does not implement Google Docs–style concurrent editing or live cursors.

The supported workflow is:

1. Student edits a canonical version.
2. Student submits a project/chapter/front-matter scope.
3. Robofox creates an immutable review snapshot with version and checksum.
4. Reviewer comments or proposes structured changes against that snapshot.
5. Student accepts, rejects, partially incorporates, or resolves suggestions manually.
6. Approved decisions remain attached to the exact reviewed snapshot.
7. Later canonical changes require reconciliation or resubmission.

Comments support project, chapter, block, selected-text range, source, quote, review issue, metadata, and preview-page anchors. Range anchors retain selected-text snapshots and can become current, moved successfully, possibly outdated, or orphaned.

Suggestions are separate from comments and store author, target block, original block, document version, structured command, explanation, student decision, response, and applied command ID. Accepted suggestions pass through the existing Phase 2 command engine.

## Review cycles and state machine

Review cycles record:

- immutable snapshot
- scope and stable ID
- submitted document version and checksum
- student submitter
- assigned reviewer
- deadline
- decision and note
- current version when decided
- resubmission lineage

High-level states:

- draft
- imported
- student review
- supervisor review
- changes requested
- academically approved
- formatting review
- submission ready
- submitted
- post-viva corrections
- final archived

Transitions are server-side capability checks. Frontend visibility never substitutes for backend authority.

## Independent approval dimensions

Approvals are version/checksum-bound records with separate dimensions:

- content
- citation
- formatting
- institutional
- submission

Every Phase 2 canonical command triggers central dependency-aware invalidation in the same transaction. Prose changes invalidate relevant content/citation/submission approvals. Metadata and official front-matter changes invalidate formatting/institutional/submission approvals. Chapter-scoped content changes preserve unrelated chapter approvals when the command identifies its scope.

## Supervisor instructions and AI policy

Supervisor instructions are first-class, scoped, prioritised, versioned records. Mandatory active instructions are incorporated into the governed Phase 3 AI policy context. Robofox must expose conflicts rather than silently override recorded supervisor authority.

Private AI history remains separate from canonical thesis access. Supervisors and administrators do not receive it by default. Accepted AI provenance and disclosure summaries remain available where institutional policy requires accountability.

## Evidence review

Assigned collaborators need `project.read_sources` to inspect the source and quotation registry. Human verification requires the separate `source.verify` capability.

- A source must be verified before a linked exact quotation can be verified.
- Revoking source verification automatically revokes dependent quote verification.
- Every decision records verifier, time, method, note, project and document version.
- Deterministic review findings are resynchronised after shared verification changes.
- Verification is described honestly as internal traceability and human comparison, not universal truth or interpretive correctness.

## Institutional profile, policy and template governance

Institutional configuration is immutable and versioned:

- policy versions
- formatting profile versions
- official template versions
- retention policy versions

Profiles/policies move through draft and staging before publication. Official wording moves through draft, under review, approved, published, and deprecated states. Published versions are never mutated in place.

Projects pin a published profile/policy version. Profile impact analysis identifies changed fields, preview regeneration, formatting reapproval, and active projects affected. Upgrades are never automatic. Pinning a published profile creates an immutable renderer override for the project, preserving the published institutional version while using the existing deterministic renderer.

Institution onboarding readiness requires departments, published policy/profile/template versions, verified members, and a pilot project. Production configuration is not tested directly on active student theses.

## Queues, notifications and handoffs

Workflow-derived queues support reviewer/operator/admin assignments, priorities, due dates, status and handoff history. Handoffs retain prior reviewer history and outstanding work.

Notifications are event driven and metadata only. Email/in-app messages may state that a comment or review event occurred; they do not include thesis prose by default. Preferences support immediate, daily, weekly, and muted delivery.

## Limited presence

Presence heartbeats expire after 90 seconds and expose only role, activity and stable scope IDs. Allowed activities are viewing, editing, reviewing and formatting. Unauthorized activity claims downgrade to viewing. Presence never stores selected prose, prompts, cursor positions or unsaved text and does not provide concurrent merging.

## Sealed submissions

Submission readiness requires configured approval dimensions, student/supervisor attestations, and final DOCX/PDF exports for the current document version.

Sealing creates an immutable package containing:

- canonical snapshot
- document version and checksum
- final DOCX/PDF IDs and checksums
- active approval records
- profile and policy version IDs
- attestation records
- verification/provenance manifest
- package checksum
- authenticated workflow-approval notice

A sealed project is protected below every API by an ORM guard. Canonical metadata, chapters, front matter, Works Cited, schema/version and active manuscript revision cannot change until a governed withdrawal or post-submission revision clears the lock. Withdrawal records an event and never deletes the original package.

Workflow approval is never represented as a legally certified digital signature.

## External examination

External review access is:

- tied to one sealed package
- bound to recipient email
- protected by a random token stored only as a hash
- expiring and revocable
- permission scoped
- optionally download-disabled
- watermarked
- audited without recording plaintext tokens

Access requires both token and bound recipient email. The public manifest omits internal storage keys. Download is a POST-only request and returns only the exact final export captured in the sealed package.

## Privacy, retention and portability

Operational metadata and thesis content are separate permissions. Aggregate analytics contain workflow states, deadlines, assignments and export operations; they do not rank students, score academic quality or expose private chats.

Project/account portability endpoints provide structured exports. Canonical content is included only for a requester with content access. Private AI history is included only after an explicit request by a user who already has that capability.

Lifecycle requests support export, deletion and institution-exit workflows with soft-delete timing, legal-hold fields, and honest backup-retention notices. Support access requires explicit consent, limited capabilities, expiry and an audit trail.

## User interface

The shared workspace adds:

- owned and assigned project cards
- role/capability summary
- metadata-only privacy banner
- workflow rail and immutable review snapshots
- people, invitations and queue panels
- anchored comments and structured suggestions
- supervisor instructions
- independent approval dimensions and submission readiness
- attestations, sealing and examiner grants
- governance summary
- notifications
- human-readable audit timeline

Shared users use capability-aware read models. Metadata-only administrators never download chapter JSON. Student owners retain the complete editor, review, evidence, AI, preview and history tools.

## Migrations

Phase 4 relational revisions:

- `0012_phase4_collaborative_workspace`
- `0013_phase4_project_tenant_default`
- `0014_phase4_attestation_submission_fk`
- `0015_phase4_presence`
- `0016_phase4_profile_renderer_bridge`

The migration gate validates `head → 0011 → head`.

## Release gate

Phase 4 CI requires:

- Python compilation and application import
- six workspace JavaScript syntax checks
- full relational rollback/upgrade round-trip
- capability/state/anchor/approval/seal invariants
- tenant, department, revocation, affiliation and invitation adversarial tests
- presence, portability, governance and evidence-authority tests
- the complete institutional acceptance demonstration
- the full inherited Phase 1–3 regression suite

## Acceptance demonstration encoded in tests

The end-to-end acceptance test performs:

1. student project creation
2. department/supervisor/operator/admin assignment
3. Chapter III snapshot submission
4. supervisor range comment and structured suggestion
5. student acceptance through an undoable command
6. approval restricted to the older reviewed snapshot after an edit
7. current-version resubmission and academic approval
8. operator prose-rewrite rejection and metadata correction
9. separate citation, formatting and institutional approvals
10. student and supervisor attestations
11. final version-bound DOCX/PDF records
12. readiness calculation
13. immutable sealed package creation
14. wrong-recipient external-access rejection
15. correct-recipient sealed-version access with sanitized manifest
16. post-seal canonical-edit rejection
17. human-readable audit verification
18. confirmation that department metadata access does not expose private AI history

## Explicit exclusions

Phase 4 does not add:

- real-time collaborative text editing, CRDTs or live cursors
- autonomous AI grading
- legal digital-signature claims
- plagiarism detection
- AI-detection enforcement or evasion
- public thesis URLs/repositories
- surveillance analytics or institution-wide student rankings
- unlimited custom workflows
- complex billing or national integrations

## Deployment status

This phase is implemented on the isolated branch `agent/phase-4-collaborative-workspace` and pull request #4. It is not merged and not deployed. Production remains unchanged until stacked Phase 1–4 review and an explicit deployment decision.