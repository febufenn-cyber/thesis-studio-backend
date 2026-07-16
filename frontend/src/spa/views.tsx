import type { CSSProperties } from "react";
import { Link, useParams } from "react-router-dom";
import { useMe, useProjects } from "./domain";
import { AppShell } from "./AppShell";
import { ApiKeysPanel } from "../ApiKeysPanel";
import { BibliographyPanel } from "../BibliographyPanel";
import { DepositPanel } from "../DepositPanel";
import { ExportMenu } from "../ExportMenu";
import { IdentityLookup } from "../IdentityLookup";
import { ImportPanel } from "../ImportPanel";
import { SettingsPanel } from "../SettingsPanel";
import { SourceIntelligencePanel } from "../SourceIntelligencePanel";
import { SupervisionPanel } from "../SupervisionPanel";
import { TrustPanel } from "../TrustPanel";
import { WritingPanel } from "../WritingPanel";
import { T, display, overline } from "../theme";

/** Signed-out gate: /auth/me 401 → point users at the main app to sign in. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const me = useMe();
  if (me.isLoading) return <Centered>Loading…</Centered>;
  if (me.isError || !me.data)
    return (
      <Centered>
        <p style={{ marginBottom: 12 }}>You’re signed out.</p>
        <a href="/" style={link}>Go to sign in →</a>
      </Centered>
    );
  return <>{children}</>;
}

export function HomeView() {
  const me = useMe();
  const projects = useProjects(!!me.data);
  return (
    <AppShell title="Home">
      <h1 style={h1}>Your projects</h1>
      <p style={muted}>Pick a project to open its library, integrity checks and tools.</p>
      {projects.isLoading && <p style={muted}>Loading projects…</p>}
      {projects.isError && <p style={err}>Couldn’t load projects.</p>}
      {projects.data?.length === 0 && <p style={muted}>No projects yet — create one in the classic workspace.</p>}
      <div style={grid}>
        {projects.data?.map((p) => (
          <Link key={p.id} to={`/projects/${p.id}/library`} style={card}>
            {p.doc_type && <div style={cardOverline}>{p.doc_type.replace(/_/g, " ")}</div>}
            <div style={cardTitle}>{p.title}</div>
            <div style={cardFoot}>Open manuscript →</div>
          </Link>
        ))}
      </div>
    </AppShell>
  );
}

function projectView(title: string, blurb: string, Body: (p: { projectId: string }) => JSX.Element) {
  return function View() {
    const { projectId = "" } = useParams();
    return (
      <AppShell title={title}>
        <h1 style={h1}>{title}</h1>
        <p style={muted}>{blurb}</p>
        <Body projectId={projectId} />
      </AppShell>
    );
  };
}

export const ProjectLibrary = projectView(
  "Library",
  "Registry sources with advisory trust, insight and one-click quote verification.",
  (p) => <SourceIntelligencePanel projectId={p.projectId} />,
);

export const ProjectImport = projectView(
  "Import",
  "Bring references in from BibTeX, RIS, CSL-JSON or a Zotero library.",
  (p) => <ImportPanel projectId={p.projectId} />,
);

export const ProjectBibliography = projectView(
  "Bibliography",
  "Render your registry in any of 10,000+ citation styles via citeproc.",
  (p) => <BibliographyPanel projectId={p.projectId} />,
);

export const ProjectExport = projectView(
  "Export",
  "Convert the manuscript to other formats, plus JATS / LaTeX / CSL-JSON interchange.",
  (p) => <ExportMenu projectId={p.projectId} />,
);

export const ProjectDeposit = projectView(
  "Deposit & DOI",
  "Send a finished export to Zenodo for a DOI, and connect your ORCID iD.",
  (p) => <DepositPanel projectId={p.projectId} />,
);

export const ProjectWriting = projectView(
  "Writing polish",
  "Advisory grammar and style suggestions — nothing is rewritten for you.",
  (p) => <WritingPanel projectId={p.projectId} />,
);

export const ProjectTrust = projectView(
  "Integrity",
  "Provenance, quote verification, compliance and the integrity report.",
  (p) => <TrustPanel projectId={p.projectId} />,
);

export const ProjectSupervision = projectView(
  "Supervision",
  "Committee roster and semantic version comparison.",
  (p) => <SupervisionPanel projectId={p.projectId} />,
);

export const ProjectSettings = projectView(
  "Settings",
  "Language & script policy, and optional anonymized research donation.",
  (p) => <SettingsPanel projectId={p.projectId} />,
);

export function IdentityView() {
  return (
    <AppShell title="Identity lookup">
      <h1 style={h1}>Identity lookup</h1>
      <p style={muted}>Resolve institutions against ROR and people against ORCID.</p>
      <IdentityLookup />
    </AppShell>
  );
}

export function ApiKeysView() {
  return (
    <AppShell title="API keys">
      <h1 style={h1}>API keys</h1>
      <p style={muted}>Bearer keys for Word, Overleaf and other non-browser clients.</p>
      <ApiKeysPanel />
    </AppShell>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div style={center}>{children}</div>;
}

const center: CSSProperties = { minHeight: "60vh", display: "grid", placeItems: "center", textAlign: "center", fontFamily: "'Source Sans 3', 'Inter', system-ui, sans-serif", color: "#1C1917" };
const h1: CSSProperties = { ...display(26), margin: "0 0 6px" };
const muted: CSSProperties = { color: T.muted, fontSize: 13.5, margin: "0 0 20px", lineHeight: 1.55 };
const err: CSSProperties = { color: T.bad, fontSize: 13 };
const grid: CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(250px,1fr))", gap: 14 };
const card: CSSProperties = { border: `1px solid ${T.line}`, borderTop: `3px solid ${T.laurel}`, borderRadius: T.radiusLg, padding: "16px 17px 13px", background: T.card, textDecoration: "none", color: T.ink, boxShadow: T.shadow };
const cardOverline: CSSProperties = { ...overline, marginBottom: 7 };
const cardTitle: CSSProperties = { fontFamily: T.serif, fontSize: 16.5, fontWeight: 600, lineHeight: 1.35, marginBottom: 12 };
const cardFoot: CSSProperties = { fontSize: 12, fontWeight: 700, color: T.laurel };
const link: CSSProperties = { color: T.laurel, fontWeight: 600, textDecoration: "none" };
