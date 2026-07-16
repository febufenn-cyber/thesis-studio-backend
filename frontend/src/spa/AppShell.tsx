import type { CSSProperties, ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useMe } from "./domain";
import { FloatingGuide } from "../FloatingGuide";

/**
 * AppShell — familiar workspace layout: fixed left sidebar (project navigation,
 * like Notion/Drive), slim top bar (brand · breadcrumb · account), scrollable
 * content. Every shipped capability has exactly one obvious home in the nav.
 */

const PROJECT_NAV: { to: string; label: string; icon: string }[] = [
  { to: "library", label: "Library", icon: "📚" },
  { to: "import", label: "Import", icon: "📥" },
  { to: "bibliography", label: "Bibliography", icon: "🔖" },
  { to: "trust", label: "Integrity", icon: "🛡" },
  { to: "supervision", label: "Supervision", icon: "🧑‍🏫" },
  { to: "writing", label: "Writing", icon: "✍️" },
  { to: "export", label: "Export", icon: "📤" },
  { to: "deposit", label: "Deposit & DOI", icon: "🏛" },
  { to: "settings", label: "Settings", icon: "⚙️" },
];

const GLOBAL_NAV: { to: string; label: string; icon: string }[] = [
  { to: "/identity", label: "Identity lookup", icon: "🪪" },
  { to: "/keys", label: "API keys", icon: "🔑" },
];

export function AppShell({ children, title }: { children: ReactNode; title?: string }) {
  const { projectId } = useParams();
  const location = useLocation();
  const me = useMe();

  const isActive = (path: string) => location.pathname.endsWith(`/${path}`) || location.pathname === path;

  return (
    <div style={S.app}>
      <aside style={S.sidebar}>
        <Link to="/" style={S.brand}>
          <span style={S.brandMark}>A</span> Acadensia
        </Link>

        <nav style={S.nav} aria-label="Workspace">
          <Link to="/" style={{ ...S.navItem, ...(location.pathname === "/" ? S.navActive : {}) }}>
            <span style={S.icon}>🏠</span> Home
          </Link>

          {projectId && (
            <>
              <div style={S.navSection}>This project</div>
              {PROJECT_NAV.map((n) => (
                <Link
                  key={n.to}
                  to={`/projects/${projectId}/${n.to}`}
                  style={{ ...S.navItem, ...(isActive(n.to) ? S.navActive : {}) }}
                >
                  <span style={S.icon}>{n.icon}</span> {n.label}
                </Link>
              ))}
            </>
          )}

          <div style={S.navSection}>Account</div>
          {GLOBAL_NAV.map((n) => (
            <Link key={n.to} to={n.to} style={{ ...S.navItem, ...(isActive(n.to) ? S.navActive : {}) }}>
              <span style={S.icon}>{n.icon}</span> {n.label}
            </Link>
          ))}
        </nav>

        <div style={S.sidebarFoot}>
          <a href="/" style={S.legacyLink}>← Classic workspace</a>
        </div>
      </aside>

      <div style={S.mainCol}>
        <header style={S.topbar}>
          <span style={S.crumb}>{title ?? ""}</span>
          <span style={S.user}>{me.data?.email ?? ""}</span>
        </header>
        <main style={S.main}>{children}</main>
      </div>
      <FloatingGuide getProjectId={() => projectId ?? null} />
    </div>
  );
}

const S: Record<string, CSSProperties> = {
  app: { display: "flex", minHeight: "100vh", background: "#faf9f6", color: "#1b2733", fontFamily: "Inter, system-ui, sans-serif" },
  sidebar: { width: 224, flexShrink: 0, background: "#f5f3ee", borderRight: "1px solid #e7e3db", display: "flex", flexDirection: "column", position: "sticky", top: 0, height: "100vh", overflowY: "auto" },
  brand: { display: "flex", alignItems: "center", gap: 9, padding: "16px 16px 12px", fontSize: 15, fontWeight: 700, color: "#1b2733", textDecoration: "none" },
  brandMark: { width: 26, height: 26, borderRadius: 8, background: "#4b4bd6", color: "#fff", display: "grid", placeItems: "center", fontSize: 14, fontWeight: 800 },
  nav: { display: "flex", flexDirection: "column", gap: 1, padding: "4px 8px", flex: 1 },
  navSection: { fontSize: 10.5, fontWeight: 700, color: "#6b7688", textTransform: "uppercase", letterSpacing: 0.5, padding: "14px 10px 5px" },
  navItem: { display: "flex", alignItems: "center", gap: 9, padding: "7px 10px", borderRadius: 8, fontSize: 13, fontWeight: 500, color: "#1b2733", textDecoration: "none" },
  navActive: { background: "#ecebfb", color: "#4b4bd6", fontWeight: 600 },
  icon: { width: 18, textAlign: "center", fontSize: 13 },
  sidebarFoot: { padding: "10px 16px", borderTop: "1px solid #e7e3db" },
  legacyLink: { fontSize: 11.5, color: "#6b7688", textDecoration: "none" },
  mainCol: { flex: 1, display: "flex", flexDirection: "column", minWidth: 0 },
  topbar: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 24px", borderBottom: "1px solid #e7e3db", background: "#fff", position: "sticky", top: 0, zIndex: 10 },
  crumb: { fontSize: 13, fontWeight: 600, color: "#6b7688" },
  user: { fontSize: 12, color: "#6b7688" },
  main: { maxWidth: 860, width: "100%", margin: "0 auto", padding: "26px 24px", boxSizing: "border-box" },
};
