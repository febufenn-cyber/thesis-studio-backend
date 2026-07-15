# Acadensia Frontend — Low-Level Design

Status: proposed · Owner: frontend · Scope: the whole client application
Companion to `docs/LLD.md` (backend) and `docs/LLD_MISSING_FEATURES.md`.

This document analyzes the current frontend, states the problems precisely, and
specifies a target architecture with a phased, non-breaking migration. It is
written to be executable: every section ends in a decision, not an opinion.

---

## 1. Method

The analysis was done bottom-up against the actual repository, not from memory:
the served HTML shells (`app/static/index.html`, `app/static/v2.html`), the
`phase*.js` / `phase*.css` bundles they load, the parallel React `frontend-kit/`,
the `acadensia-studio-v2.html` prototype, and the live route table (265 routes
across `app/api/*.py`). Every endpoint named in the component map in §13 was
grep-verified to exist. Where this document asserts a gap, it is a gap observed
in the tree today, not a hypothetical.

---

## 2. Current state (as-built)

**Two disconnected frontends exist, and only one is served.**

The **served app** is vanilla JavaScript with no build step. `v2.html` (mounted
at `/`) and `index.html` (mounted at `/legacy`) load a set of classic
`<script src="/static/phaseN-*.js">` tags. State is a single module-global
mutable object (`const S = {user, projects, project, sources, quotes, …}`) in
`phase1-core.js`; the DOM is updated imperatively through a hand-rolled
`h(tag,text,cls)` element factory and `document.getElementById` lookups; views
are switched by toggling a `hidden` attribute across three top-level `<div>`s.
There is no module system, no bundler, no dependency management, no client
router, and no test harness. CSS is hand-authored and split by phase
(`phase1.css`…`phase4.css`).

The **React kit** (`frontend-kit/`) is a separate, newer track: `api.ts` (typed
fetch helpers), `StatusBadge.tsx` (the status vocabulary), `TrustPanel.tsx`
(Phases 1–4 + MF1/MF4), and the enterprise drop-ins added for E1–E7
(`SourceIntelligence`, `AutoVerifyButton`, `BibliographyPanel`, `IdentityLookup`,
`ExportMenu`, `WritingPanel`, `EnterprisePanel`, `useEnterprise.ts`). It
type-checks under `tsc --strict` but **is not integrated into the served app** —
it has no host page, no build, and no route. It is design capital sitting on the
shelf.

A third artifact, `acadensia-studio-v2.html`, is a single-file redesigned
prototype (command palette, readiness ring, dark mode) that is neither served
nor wired to the API.

**Design-system state.** The served app uses Syne + IBM Plex; the kit and the
prototype use Inter. The validated colorblind-safe palette (from the `dataviz`
work) is enforced only inside the React `StatusBadge`, not in the vanilla app.
The status vocabulary — the product's core integrity signal — therefore has two
implementations that can drift, and until this LLD's fix, the React one mapped
`resolved → green VERIFIED`, contradicting AI-safety rule 11.

The referenced `docs/UI_UX_LLD.md` does not exist; component comments point at a
document that was never committed.

---

## 3. Problems, prioritized

| # | Problem | Consequence | Severity |
|---|---------|-------------|----------|
| P1 | Two parallel frontends (vanilla served, React shelved) | Duplicated logic, guaranteed drift, E1–E7 invisible to real users | Critical |
| P2 | Global mutable state + manual DOM sync | State/UI desync bugs, untestable, no reactivity | High |
| P3 | No build/module system | No code-splitting, no deps, no typing in the served path | High |
| P4 | Integrity vocabulary implemented twice | The *one* thing that must never be wrong (verified vs resolved) can diverge | Critical |
| P5 | Design tokens inconsistent (fonts, colors) | Incoherent product; palette guarantees unenforced | Medium |
| P6 | No standardized loading/empty/error/fail-closed states | Advisory/unavailable features can look broken or, worse, falsely positive | High |
| P7 | No routing, no deep links | Can't link to a project tab, no back-button, poor shareability | Medium |
| P8 | No a11y layer, no tests, no error boundaries | Regressions ship silently; keyboard/SR users blocked | High |
| P9 | Unsanitized HTML injection surface | `BibliographyPanel` renders citeproc HTML via `dangerouslySetInnerHTML` | High (security) |

P1 and P4 are the reasons this LLD exists. Everything else is downstream of them.

---

## 4. Design goals & principles

1. **One frontend.** A single source of truth for state, components, and the
   integrity vocabulary. The vanilla app is retired, not forked again.
2. **Integrity is a UI contract, not a coat of paint.** The never-guess
   discipline the backend enforces (fail-closed, advisory ≠ verified,
   resolved ≠ verified, retraction always visible) is encoded as typed,
   test-guarded UI invariants (§9). The UI can never render a claim greener than
   the data supports.
3. **Server state is borrowed, not owned.** The client caches server truth; it
   does not keep a shadow copy it mutates by hand (kills P2).
4. **Every async surface has four states** — loading, empty, error, and *stale/
   unavailable* — and "unavailable" is designed, honest, and never mistaken for
   a negative result (kills P6).
5. **Typed edge to edge.** The API contract is TypeScript types mirrored from the
   FastAPI responses; a wrong field name fails at build, not in production.
6. **Progressive, non-breaking migration.** The new app coexists with the legacy
   one behind a route flag until parity is reached; no big-bang cutover.
7. **Accessible and colorblind-safe by construction** — status is never
   color-alone; the validated palette is the only source of hue.

---

## 5. Target architecture — decisions (ADRs)

### ADR-1 · Stack: React 18 + TypeScript + Vite
Adopt the stack the kit already commits to. React + TS gives us the existing
type-checked components for free; Vite gives fast dev, code-splitting, and a
single static build FastAPI can serve from `app/static/app/`. **Rejected:**
(a) continuing vanilla JS — fails P2/P3 and cannot absorb the kit; (b) Next.js/SSR
— the app is a cookie-authenticated, behind-login workspace with no SEO surface,
so SSR adds server complexity for no benefit; a SPA is the right shape.

### ADR-2 · Server state via TanStack Query; UI state via Zustand
Server data (projects, sources, trust, reports) is cached, invalidated, and
re-fetched by **TanStack Query** — this is the structural fix for P2: no global
mutable `S`, no manual re-render. Ephemeral UI state (open tab, palette
visibility, theme) lives in a tiny **Zustand** store. **Rejected:** Redux
(ceremony out of proportion to needs); a single global context (re-render
storms, reinvents Query poorly).

### ADR-3 · Routing via React Router, URL-addressable
Journeys and project tabs become real routes (`/projects/:id/verify`), so state
is deep-linkable and the back button works (P7). **Rejected:** the current
hidden-div toggling.

### ADR-4 · Design tokens are the single source of hue and type
One `tokens.ts` (+ CSS custom properties) defines color, type scale, spacing,
radius, and the status palette, derived from the validated `dataviz` palette.
Components read tokens only; no literal hex outside the token file. Fonts
consolidate on **Inter** (UI) + a single serif for manuscript preview. This
kills P5 and makes the palette guarantee enforceable by a lint rule.

### ADR-5 · The status vocabulary is one typed module
`StatusBadge` + `toStatus` is the *only* place a verification/resolution state
becomes a color and label (kills P4). Its mapping is unit-tested against the
invariants in §9. There is no second implementation anywhere.

### ADR-6 · All server HTML is sanitized before render
Any server-provided HTML (citeproc bibliography entries, previews) passes through
DOMPurify with a strict allowlist before `dangerouslySetInnerHTML` (fixes P9).
Prefer the `output: "text"` API variant where the rich form is not required.

---

## 6. Layered architecture

```
┌───────────────────────────────────────────────────────────┐
│ app shell         routing, auth gate, theme, error boundary │
├───────────────────────────────────────────────────────────┤
│ feature modules   journey + integrity + enterprise surfaces │  ← composed of primitives
├───────────────────────────────────────────────────────────┤
│ domain hooks      useProject, useTrust, useInsight, …       │  ← TanStack Query wrappers
├───────────────────────────────────────────────────────────┤
│ api client        typed fetch, error model, auth headers    │  ← api.ts (exists)
├───────────────────────────────────────────────────────────┤
│ ui primitives     Button, Badge, Card, Tabs, Field, Empty…  │  ← token-driven, a11y-baked
├───────────────────────────────────────────────────────────┤
│ design tokens     color / type / spacing / status palette   │  ← single source of truth
└───────────────────────────────────────────────────────────┘
```

Dependencies point downward only. A feature never calls `fetch` directly (it uses
a domain hook); a primitive never imports a feature; nothing outside `tokens`
names a color.

---

## 7. Module & directory structure

```
frontend/
  index.html                 # Vite entry; single mount node
  src/
    main.tsx                 # bootstrap: QueryClient, Router, ThemeProvider, ErrorBoundary
    app/
      routes.tsx             # route table
      AppShell.tsx           # nav rail, header, journey outlet
      AuthGate.tsx           # redirect to login when /me is 401
    tokens/
      tokens.ts              # color/type/space/status — the only hex in the app
      global.css             # CSS custom properties + resets
    lib/
      api.ts                 # (from kit) typed fetch + ApiError + v1()
      queryClient.ts         # TanStack config: staleness, retry=fail-closed
      sanitize.ts            # DOMPurify wrapper (ADR-6)
    ui/                       # primitives — no domain knowledge
      Button.tsx Badge.tsx Card.tsx Tabs.tsx Field.tsx
      Async.tsx              # the loading/empty/error/unavailable wrapper (§10)
      StatusBadge.tsx        # THE status vocabulary (from kit, hardened)
    domain/                  # typed server-state hooks (TanStack Query)
      useProject.ts useSources.ts useTrust.ts useEnterprise.ts …
    features/
      journey/               # Home, Write, Ready, Library, Submit
      integrity/             # TrustPanel + Provenance/Verify/Comply/Integrity tabs
      enterprise/            # E1–E7 surfaces (from kit)
      auth/
    test/
      setup.ts  msw/handlers.ts   # mock API for tests
  vite.config.ts   tsconfig.json   .eslintrc  (token-hex lint rule)
```

The existing `frontend-kit/*` files migrate into `src/ui`, `src/domain`, and
`src/features/*` largely unchanged — they were written to these conventions.

---

## 8. Component hierarchy & routing

```
<AppShell>                         route: /
  <NavRail/>                       journeys: Home Write Ready Library Submit
  <Outlet/>
    /                    → <Home/>
    /projects/:id        → <ProjectShell> (loads project, sets query context)
       /write            → <WriteView/>   manuscript editor + <TrustPanel/>
       /ready            → <ReadyView/>   readiness ring + <IntegrityTab/>
       /library          → <LibraryView/> sources + per-source <SourceIntelligence/>
       /bibliography     → <BibliographyPanel/>            (E5)
       /export           → <ExportMenu/> + <SubmitView/>   (E6)
       /polish           → <WritingPanel/>                 (E7)
    /identity            → <IdentityLookup/>               (E2)
```

`ProjectShell` fetches the project once and provides its id via route param; all
child tabs read server state through domain hooks keyed by that id, so tabs are
independently cached and never share a mutable object. `TrustPanel` and the
enterprise panels are the components already built; they slot in as route
elements or docked asides.

---

## 9. Integrity UX invariants (the core of this design)

These are **typed, tested contracts**, not guidelines. Each maps to a backend
rule and a test in `ui/StatusBadge.test.tsx` / feature tests.

- **INV-1 · Green is earned.** Only a human-`verified` status renders green.
  `resolved`, `aligned`, `scored`, `found` render in neutral/advisory slate.
  (`toStatus("resolved") !== "verified"` — regression-guarded; this was a real
  bug fixed in this cycle.)
- **INV-2 · Retraction is never hidden or softened.** Any `retracted` /
  concern-flagged source renders the red RETRACTED badge and an explicit "must
  not be used as reliable support" line, in every surface it appears.
- **INV-3 · Advisory is labeled.** Trust verdicts, insights, alignment, and
  auto-verify results carry a visible "advisory — not a verification" note.
- **INV-4 · Fail-closed reads as unavailable, not negative.** When a feature is
  disabled/unreachable (E4 no-OA-text, E6 no pandoc, E7 no server), the UI shows
  a designed "unavailable / not found here" state that is visually distinct from
  a *failed* or *negative* result. An empty result never implies a problem with
  the user's work.
- **INV-5 · The verified bit is read-only in the UI.** No advisory action
  (auto-verify, trust check, alignment) exposes a control that could set
  `verified`; that transition exists only on the explicit human-review path.
- **INV-6 · Unknown is neutral.** An unknown journal/source is UNKNOWN (slate),
  never styled as predatory or negative (mirrors the E1 backend verdict).

A CI test asserts these on the `StatusBadge` mapping and on each enterprise
component's unavailable branch, so an integrity regression fails the build.

---

## 10. Async state model

A single primitive standardizes P6. Every server-backed surface renders through:

```tsx
<Async query={trustQuery}
  loading={<Skeleton/>}
  empty={(d) => d.matches.length === 0 && <EmptyNote>No issues found</EmptyNote>}
  unavailable={(d) => d.available === false && <UnavailableNote>…honest copy…</UnavailableNote>}
  error={(e) => <ErrorNote detail={e.message}/>}>
  {(data) => <TrustCard data={data}/>}
</Async>
```

`unavailable` is a first-class branch distinct from `error` — this is INV-4 made
mechanical. TanStack Query is configured **fail-closed**: on error the last good
data is not silently shown as fresh; retries are bounded; a network failure on an
advisory feature surfaces as unavailable, never as a fabricated positive.

---

## 11. Design system & tokens

- **Color.** Sourced from the validated `dataviz` palette. Status tokens:
  `good #0ca30c`, `warning #fab219`, `serious #ec835a`, `critical #d03b3b`;
  categorical `blue #2a78d6`, `aqua #1baf7a`, `violet #4a3aa7`. Verified green is
  a status token; advisory/resolved is a categorical violet/slate — deliberately
  *not* green. Surfaces defined for light and dark, each validated against its
  own background (dark mode is re-derived, not an inverted flip).
- **Status is icon + label + color, never color alone** (WCAG + CVD): every badge
  ships a shape/label so it survives grayscale and colorblind rendering.
- **Type.** Inter for UI (single family, 4–5 steps); one serif for manuscript
  preview only. Retire Syne/IBM Plex to end P5.
- **Spacing/radius/elevation** on a small fixed scale; components consume tokens,
  never literals. An ESLint rule bans raw hex outside `tokens.ts`.

---

## 12. Data-fetching & API contract

`api.ts` (already typed) stays the transport. Each domain hook wraps a query key
and a response type that mirrors the FastAPI JSON. Types live beside the hook and
are the contract; a backend field rename surfaces as a TS error in CI. The bearer
`ak_` key path (MF6) is supported through `extraHeaders` for non-browser clients;
the browser uses the session cookie (`credentials: "include"`). All reads are
owner-guarded server-side, so the client performs no authorization logic — it
only reflects 401→login and 403/404→not-available.

---

## 13. Component → endpoint map (verified against the live route table)

| Surface | Component | Endpoint(s) |
|---------|-----------|-------------|
| Provenance / AI-use | TrustPanel · Provenance | `GET /projects/{id}/provenance/summary`, `POST …/ai-use-statement` |
| Verify quotes | TrustPanel · Verify | `GET …/quote-verification/report`, `POST …/quotes/{qid}/verify-source` |
| Comply | TrustPanel · Comply | `GET /projects/{id}/compliance` |
| Integrity report | TrustPanel · Integrity | `GET /projects/{id}/integrity-report` |
| Discover / resolve | ReferencesPanel | `GET …/references/search`, `POST …/references/search/add`, `POST …/sources/{sid}/resolve` |
| **E1** trust | SourceIntelligence | `GET /projects/{id}/sources/{sid}/trust` |
| **E2** identity | IdentityLookup | `GET /identity/organizations`, `GET /identity/orcid/{orcid}` |
| **E3** insight | SourceIntelligence | `GET /projects/{id}/sources/{sid}/insight` |
| **E4** auto-verify | AutoVerifyButton | `POST /projects/{id}/quotes/{qid}/verify-auto` |
| **E5** bibliography | BibliographyPanel | `GET /bibliography/styles`, `POST /projects/{id}/bibliography/render` |
| **E6** export/convert | ExportMenu | `GET /interop/formats`, `POST /projects/{id}/export/pandoc`, `POST /interop/convert/preview` |
| **E7** writing | WritingPanel | `GET /writing/status`, `POST /projects/{id}/writing/check` |

Every path above was confirmed present in `app/api/*.py` (265 routes) at the time
of writing. New surfaces must add their row here and a domain hook — no ad-hoc
fetch.

---

## 14. Accessibility

Target WCAG 2.2 AA. Status never color-alone (§11). All interactive elements are
real buttons/links with focus-visible rings from tokens; tab order follows visual
order; the ⌘K command palette and journey nav are fully keyboard-operable;
async regions announce via `aria-live` (a resolved/verified change is announced,
not just recolored). A tabular/text view exists for any color-encoded summary.
Dark mode is a selected, validated theme, not an auto-invert.

---

## 15. Performance

Route-level code-splitting (`React.lazy` per journey/tab) keeps first load small;
target initial JS < 200 KB gzipped, each lazy route < 100 KB. TanStack Query
dedupes and caches, so tab switches are instant and re-fetch in the background.
Skeletons (not spinners) for perceived speed. The manuscript editor is the one
heavy view and is isolated behind its own chunk. A bundle-size budget is enforced
in CI.

---

## 16. Error handling & resilience

A top-level error boundary catches render faults and shows a recoverable panel
(never a white screen). `ApiError` carries the server `detail`, surfaced in the
`error` branch of `<Async>`. Fail-closed is the default everywhere: a failed
advisory call yields "unavailable," a failed mutation is retryable and never
optimistically shown as succeeded, and a 401 anywhere routes to login without
losing the current URL (restored post-auth).

---

## 17. Testing strategy

- **Unit (Vitest + Testing Library):** primitives and, critically, the §9
  invariants — `StatusBadge` mapping, each unavailable branch.
- **Integration (MSW):** feature components against mocked endpoints, including
  the fail-closed and retracted paths (E1 unknown, E4 no-OA, E6 no-pandoc).
- **A11y (axe):** automated checks in component tests; manual keyboard sweep per
  journey.
- **E2E (Playwright):** the golden path — login → project → write → verify →
  render bibliography → export.
- **Visual/regression:** snapshot the status vocabulary and dark mode.

CI gates: type-check (`tsc --noEmit`, already green for the kit), lint (incl. the
no-raw-hex rule), unit+integration, bundle budget.

---

## 18. Security

DOMPurify on all server HTML (ADR-6) — the citeproc entries in `BibliographyPanel`
are the first consumer. A strict CSP (no inline scripts once bundled; `data:`
limited to the export-download path). Session cookie is HTTP-only server-side; the
SPA never stores tokens in `localStorage` (consistent with the artifact storage
rule). No secret or model detail is ever rendered (mirrors AI-safety rule 3).

---

## 19. Migration plan (strangler-fig, non-breaking)

The legacy app keeps serving `/` until parity; the new app ships behind a flag and
takes routes one journey at a time.

1. **Scaffold.** Vite app under `frontend/`, FastAPI serves its build at
   `/app` (new `frontend_v3` route beside the existing `/` and `/legacy`).
   Move `frontend-kit/*` into `src/ui|domain|features`. No user-facing change.
2. **Read-only surfaces first.** Ship Library + the integrity/enterprise panels
   (E1–E7, TrustPanel) at `/app` — these are additive and low-risk, and they make
   the already-built E1–E7 work finally visible to users.
3. **Journey parity.** Port Home/Write/Ready/Submit; wire the editor. When `/app`
   reaches parity, flip the `/` route to the new app and demote the vanilla app to
   `/legacy2`.
4. **Retire.** Delete `phase*.js/css` and the old shells once telemetry shows no
   `/legacy` traffic. One frontend remains (goal §4.1).

Each step is independently shippable and reversible by route flag.

---

## 20. Open decisions & risks

- **Editor engine.** The manuscript editor (block model, provenance-aware) is the
  largest single build; choosing its core (e.g. a ProseMirror/Lexical-based block
  editor vs. the current custom one) is deferred to its own LLD. It is the main
  schedule risk.
- **Design refresh scope.** This LLD unifies tokens and retires the font split; a
  full visual redesign (beyond the prototype) is a separate track.
- **SSR/SEO.** Explicitly out of scope while the app is behind login; revisit only
  if a public surface (shared read-only manuscripts) is added.

---

## 21. Definition of done

One React+TS application serves `/`; the vanilla `phase*.js` app is deleted; every
E1–E7 and Phase 1–4 surface is reachable, typed, and covered by the §9 invariant
tests; the status vocabulary exists once; no raw hex outside `tokens.ts`; CI gates
(type, lint, unit/integration, a11y, bundle budget) are green; and no async
surface can render an advisory or fail-closed result as a verified positive.
