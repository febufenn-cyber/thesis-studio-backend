import type { CSSProperties, ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useMe } from "./domain";
import { FloatingGuide } from "../FloatingGuide";
import { T, overline } from "../theme";

/**
 * AppShell — the scholar's desk. Familiar workspace skeleton (left nav, slim
 * topbar) in an academic skin: warm paper, hairline book-rules, serif brand
 * and headings, engraved stroke icons, laurel accent. No emoji, no purple.
 */

function Icon({ d, size = 15 }: { d: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" style={{ flexShrink: 0 }}>
      <path d={d} />
    </svg>
  );
}

// Compact engraved-stroke icon paths (24px grid).
const I = {
  home: "M3 11.5 12 4l9 7.5M5.5 10v9h13v-9",
  library: "M4 19.5V5a1 1 0 0 1 1-1h3v16H5a1 1 0 0 1-1-.5ZM8 4h4v16H8ZM14.5 5.2l4.6-1.2 2 15.5-4.6 1.2Z",
  import: "M12 3v10m0 0 3.5-3.5M12 13 8.5 9.5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4",
  bibliography: "M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1Z",
  integrity: "M12 3l7 3v5c0 4.5-3 8.5-7 10-4-1.5-7-5.5-7-10V6ZM9 12l2 2 4-4.5",
  supervision: "M8 8a3 3 0 1 0 0-.01M16.5 9.5a2.5 2.5 0 1 0 0-.01M3.5 20c.5-3 2.5-5 4.5-5s4 2 4.5 5M14 20c.3-2 1.5-3.6 3-3.6s2.7 1.6 3 3.6",
  writing: "M4 20l1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L8 19l-4 1ZM13.5 7.5l3 3",
  export: "M12 15V4m0 0L8.5 7.5M12 4l3.5 3.5M6 12v6a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2v-6",
  deposit: "M4 10l8-6 8 6M5.5 10v8.5M18.5 10v8.5M3 20h18M9 13v4M15 13v4M12 13v4",
  settings: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Zm8 3-.9 2.2 1.2 2-1.8 1.8-2-1.2L14.2 18l-.7 2.2h-3l-.7-2.2-2.3-1.2-2 1.2L3.7 16.2l1.2-2L4 12l.9-2.2-1.2-2 1.8-1.8 2 1.2L9.8 6l.7-2.2h3l.7 2.2 2.3 1.2 2-1.2 1.8 1.8-1.2 2Z",
  identity: "M4 6h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1Zm3.5 8.5c.4-1.4 1.4-2.3 2.5-2.3s2.1.9 2.5 2.3M10 9.6a1.6 1.6 0 1 0 0 .01M15 10h4M15 13h3",
  keys: "M14.5 4a5.5 5.5 0 1 0 1.7 10.7L18 16.5V19h2.5v-2.5H23l-6.3-6.3A5.5 5.5 0 0 0 14.5 4Zm-1 4.5a1.5 1.5 0 1 1 0 .01",
};

const PROJECT_NAV = [
  { to: "library", label: "Library", icon: I.library },
  { to: "import", label: "Import", icon: I.import },
  { to: "bibliography", label: "Bibliography", icon: I.bibliography },
  { to: "trust", label: "Integrity", icon: I.integrity },
  { to: "supervision", label: "Supervision", icon: I.supervision },
  { to: "writing", label: "Writing", icon: I.writing },
  { to: "export", label: "Export", icon: I.export },
  { to: "deposit", label: "Deposit & DOI", icon: I.deposit },
  { to: "settings", label: "Settings", icon: I.settings },
];

const GLOBAL_NAV = [
  { to: "/identity", label: "Identity lookup", icon: I.identity },
  { to: "/keys", label: "API keys", icon: I.keys },
];

/** Laurel monogram: an engraved A between laurel sprigs. */
function Crest({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <rect x="1" y="1" width="38" height="38" rx="7" fill={T.laurel} />
      <text x="20" y="26.5" textAnchor="middle"
        fontFamily="'Source Serif 4', Georgia, serif" fontSize="19" fontWeight="600"
        fill="#F3EFE6">A</text>
      <path d="M8 27c2-1 3.4-3 3.8-5M32 27c-2-1-3.4-3-3.8-5"
        stroke="#B08A3E" strokeWidth="1.4" fill="none" strokeLinecap="round" />
      <circle cx="10.5" cy="21" r="1" fill="#B08A3E" />
      <circle cx="29.5" cy="21" r="1" fill="#B08A3E" />
    </svg>
  );
}

export function AppShell({ children, title }: { children: ReactNode; title?: string }) {
  const { projectId } = useParams();
  const location = useLocation();
  const me = useMe();

  const isActive = (path: string) =>
    location.pathname.endsWith(`/${path}`) || location.pathname === path;

  const navItem = (to: string, label: string, icon: string, active: boolean) => (
    <Link key={to} to={to} className={active ? "nav-x on" : "nav-x"}
      style={{ ...S.navItem, ...(active ? S.navActive : {}) }}>
      <span style={{ ...S.navRule, background: active ? T.gilt : "transparent" }} />
      <Icon d={icon} />
      {label}
    </Link>
  );

  return (
    <div style={S.app}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&family=Source+Sans+3:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
        ::selection { background: ${T.giltWash}; }
        a:focus-visible, button:focus-visible { outline: 2px solid ${T.laurel}; outline-offset: 2px; }
        a, button { transition: background-color .14s ease, border-color .14s ease, color .14s ease, box-shadow .14s ease; }
        button:active { transform: translateY(1px); }
        .nav-x { transition: background-color .12s ease, color .12s ease; }
        .nav-x:not(.on):hover { background: rgba(255,255,255,.75); color: ${T.ink}; }
        .mcard { transition: border-color .14s ease, box-shadow .14s ease, transform .14s ease; }
        .mcard:hover { border-color: ${T.laurel}; box-shadow: 0 2px 4px rgba(28,25,23,.08), 0 14px 34px rgba(28,25,23,.12); transform: translateY(-1px); }
        @media (prefers-reduced-motion: reduce) {
          a, button, .nav-x, .mcard { transition: none !important; }
          .mcard:hover { transform: none; }
          button:active { transform: none; }
        }
      `}</style>
      <aside style={S.sidebar}>
        <Link to="/" style={S.brand}>
          <Crest />
          <span style={S.brandWord}>Acadensia</span>
        </Link>
        <div style={S.brandRule} />

        <nav style={S.nav} aria-label="Workspace">
          {navItem("/", "Home", I.home, location.pathname === "/")}

          {projectId && (
            <>
              <div style={S.navSection}>This manuscript</div>
              {PROJECT_NAV.map((n) =>
                navItem(`/projects/${projectId}/${n.to}`, n.label, n.icon, isActive(n.to)),
              )}
            </>
          )}

          <div style={S.navSection}>Account</div>
          {GLOBAL_NAV.map((n) => navItem(n.to, n.label, n.icon, isActive(n.to)))}
        </nav>

        <div style={S.sidebarFoot}>
          <a href="/" style={S.legacyLink}>Classic workspace ↗</a>
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
  app: { display: "flex", minHeight: "100vh", background: T.paper, color: T.ink, fontFamily: T.sans },
  sidebar: { width: 230, flexShrink: 0, background: T.wash, borderRight: `1px solid ${T.line}`, display: "flex", flexDirection: "column", position: "sticky", top: 0, height: "100vh", overflowY: "auto" },
  brand: { display: "flex", alignItems: "center", gap: 10, padding: "18px 16px 12px", textDecoration: "none" },
  brandWord: { fontFamily: T.serif, fontSize: 19, fontWeight: 600, color: T.ink, letterSpacing: "0.005em" },
  brandRule: { height: 1, background: T.lineStrong, margin: "0 16px 6px" },
  nav: { display: "flex", flexDirection: "column", gap: 1, padding: "6px 10px", flex: 1 },
  navSection: { ...overline, padding: "16px 10px 6px" },
  navItem: { position: "relative", display: "flex", alignItems: "center", gap: 10, padding: "7px 10px 7px 14px", borderRadius: T.radius, fontSize: 13, fontWeight: 600, color: T.inkSoft, textDecoration: "none" },
  navActive: { background: T.laurelWash, color: T.laurel },
  navRule: { position: "absolute", left: 0, top: 6, bottom: 6, width: 3, borderRadius: 2 },
  sidebarFoot: { padding: "12px 16px", borderTop: `1px solid ${T.line}` },
  legacyLink: { fontSize: 11.5, color: T.muted, textDecoration: "none", fontWeight: 600 },
  mainCol: { flex: 1, display: "flex", flexDirection: "column", minWidth: 0 },
  topbar: { display: "flex", alignItems: "baseline", justifyContent: "space-between", padding: "12px 26px", borderBottom: `1px solid ${T.line}`, background: T.card, position: "sticky", top: 0, zIndex: 10 },
  crumb: { ...overline, color: T.laurel },
  user: { fontSize: 12, color: T.muted },
  main: { maxWidth: 880, width: "100%", margin: "0 auto", padding: "30px 26px", boxSizing: "border-box" },
};
