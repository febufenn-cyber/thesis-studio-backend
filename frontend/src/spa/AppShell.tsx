import type { CSSProperties, ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

/**
 * AppShell — persistent frame for the SPA: brand, project context, and the
 * project tab rail. Read-only surfaces (Library + enterprise panels) ship first
 * per the migration plan; authoring journeys are ported next.
 */
const PROJECT_TABS = [
  { to: "library", label: "Library" },
  { to: "bibliography", label: "Bibliography" },
  { to: "export", label: "Export" },
  { to: "writing", label: "Writing" },
  { to: "trust", label: "Integrity" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { projectId } = useParams();
  return (
    <div style={S.app}>
      <header style={S.bar}>
        <Link to="/" style={S.brand}>
          Acadensia <strong>Studio</strong>
        </Link>
        <span style={S.badge}>preview · /app</span>
      </header>
      {projectId && (
        <nav style={S.tabs} aria-label="Project sections">
          {PROJECT_TABS.map((t) => (
            <Link key={t.to} to={`/projects/${projectId}/${t.to}`} style={S.tab}>
              {t.label}
            </Link>
          ))}
        </nav>
      )}
      <main style={S.main}>{children}</main>
    </div>
  );
}

const S: Record<string, CSSProperties> = {
  app: { minHeight: "100vh", background: "#faf9f6", color: "#1b2733", fontFamily: "Inter, system-ui, sans-serif" },
  bar: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 20px", borderBottom: "1px solid #e7e3db", background: "#fff", position: "sticky", top: 0, zIndex: 10 },
  brand: { fontSize: 16, fontWeight: 600, color: "#1b2733", textDecoration: "none" },
  badge: { fontSize: 10.5, fontWeight: 700, color: "#4b4bd6", background: "#ecebfb", borderRadius: 999, padding: "3px 9px" },
  tabs: { display: "flex", gap: 4, padding: "8px 20px 0", borderBottom: "1px solid #e7e3db", background: "#fff", flexWrap: "wrap" },
  tab: { padding: "8px 12px", fontSize: 13, fontWeight: 600, color: "#4b4bd6", textDecoration: "none" },
  main: { maxWidth: 1080, margin: "0 auto", padding: "22px 20px" },
};
