import type { CSSProperties } from "react";
import { Link, useParams } from "react-router-dom";
import { useMe, useProjects } from "./domain";
import { AppShell } from "./AppShell";
import { BibliographyPanel } from "../BibliographyPanel";
import { ExportMenu } from "../ExportMenu";
import { SourceIntelligencePanel } from "../SourceIntelligencePanel";
import { TrustPanel } from "../TrustPanel";
import { WritingPanel } from "../WritingPanel";

/** Signed-out gate: /me 401 → point users at the main app to sign in. */
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
    <AppShell>
      <h1 style={h1}>Your projects</h1>
      {projects.isLoading && <p style={muted}>Loading projects…</p>}
      {projects.isError && <p style={err}>Couldn’t load projects.</p>}
      {projects.data?.length === 0 && <p style={muted}>No projects yet.</p>}
      <div style={grid}>
        {projects.data?.map((p) => (
          <Link key={p.id} to={`/projects/${p.id}/library`} style={card}>
            <div style={{ fontWeight: 700, fontSize: 15 }}>{p.title}</div>
            {p.document_type && <div style={muted}>{p.document_type}</div>}
          </Link>
        ))}
      </div>
    </AppShell>
  );
}

export function ProjectLibrary() {
  const { projectId = "" } = useParams();
  return (
    <AppShell>
      <h1 style={h1}>Library</h1>
      <p style={muted}>Registry sources with advisory trust, insight and quote verification.</p>
      <SourceIntelligencePanel projectId={projectId} />
    </AppShell>
  );
}

export function ProjectBibliography() {
  const { projectId = "" } = useParams();
  return <AppShell><h1 style={h1}>Bibliography</h1><BibliographyPanel projectId={projectId} /></AppShell>;
}

export function ProjectExport() {
  const { projectId = "" } = useParams();
  return <AppShell><h1 style={h1}>Export</h1><ExportMenu projectId={projectId} /></AppShell>;
}

export function ProjectWriting() {
  const { projectId = "" } = useParams();
  return <AppShell><h1 style={h1}>Writing polish</h1><WritingPanel projectId={projectId} /></AppShell>;
}

export function ProjectTrust() {
  const { projectId = "" } = useParams();
  return <AppShell><h1 style={h1}>Integrity</h1><TrustPanel projectId={projectId} /></AppShell>;
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div style={center}>{children}</div>;
}

const center: CSSProperties = { minHeight: "60vh", display: "grid", placeItems: "center", textAlign: "center", fontFamily: "Inter, system-ui, sans-serif", color: "#1b2733" };
const h1: CSSProperties = { fontSize: 20, fontWeight: 700, margin: "0 0 12px" };
const muted: CSSProperties = { color: "#6b7688", fontSize: 13, margin: "4px 0 14px" };
const err: CSSProperties = { color: "#d64545", fontSize: 13 };
const grid: CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(240px,1fr))", gap: 12 };
const card: CSSProperties = { border: "1px solid #e7e3db", borderRadius: 12, padding: "14px 15px", background: "#fff", textDecoration: "none", color: "#1b2733" };
const link: CSSProperties = { color: "#4b4bd6", fontWeight: 600, textDecoration: "none" };
