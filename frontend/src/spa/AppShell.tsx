import { useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useMe } from "./domain";
import { FloatingGuide } from "../FloatingGuide";
import { PresenceDots } from "../PresenceDots";
import { ENV_BG, T, overline } from "../theme";

/**
 * AppShell — spatial glass. A dusk-aurora environment behind everything, a
 * frosted glass rail on desktop that becomes a floating bottom dock on small
 * screens, glow-on-gaze hovers, pill controls. UI is Inter; manuscript prose
 * elsewhere stays serif.
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

// Compact stroke icon paths (24px grid).
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
  { to: "/supervise", label: "Supervision desk", icon: I.supervision },
  { to: "/identity", label: "Identity lookup", icon: I.identity },
  { to: "/keys", label: "API keys & security", icon: I.keys },
  { to: "/institution", label: "Institution", icon: I.deposit },
];

/** Warm orb monogram — the same glow as the guide fox. */
function Crest({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <defs>
        <radialGradient id="crestOrb" cx="0.32" cy="0.28" r="1.1">
          <stop offset="0" stopColor="#FFD9A8" />
          <stop offset="0.45" stopColor="#F09B5F" />
          <stop offset="1" stopColor="#7A4AC8" />
        </radialGradient>
      </defs>
      <circle cx="20" cy="20" r="18" fill="url(#crestOrb)" />
      <text x="20" y="26.5" textAnchor="middle"
        fontFamily="'Source Serif 4', Georgia, serif" fontSize="19" fontWeight="600"
        fill="#FFF6EA">A</text>
    </svg>
  );
}

// Deterministic star field (fixed coords so renders are stable).
const STARS = [
  [4, 8], [11, 22], [17, 6], [23, 15], [29, 3], [34, 19], [41, 9], [47, 24],
  [53, 5], [59, 14], [64, 27], [70, 7], [76, 18], [82, 4], [88, 12], [94, 21],
  [8, 34], [21, 30], [37, 33], [51, 36], [66, 31], [79, 35], [91, 29], [97, 38],
].map(([x, y], i) => `${x}vw ${y}vh 0 ${i % 3 === 0 ? "1px" : "0"} rgba(255,255,255,${0.25 + (i % 4) * 0.12})`).join(",");

function ReleaseBadge() {
  const [rel, setRel] = useState<string | null>(null);
  useEffect(() => {
    fetch("/meta/release", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => j && setRel(String(j.release ?? j.version ?? j.sha ?? "").slice(0, 12)))
      .catch(() => undefined);
  }, []);
  if (!rel) return null;
  return <div style={{ fontSize: 10, color: "rgba(255,255,255,0.32)", marginTop: 6, fontFamily: T.mono }}>build {rel}</div>;
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
      <Icon d={icon} />
      <span className="lbl">{label}</span>
    </Link>
  );

  return (
    <div style={S.app} className="shell">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=IBM+Plex+Mono:wght@400;500&display=swap');
        html { color-scheme: dark; }
        body { background: ${T.envTop}; background-image: ${ENV_BG}; background-attachment: fixed; }
        ::selection { background: ${T.laurelWash}; }
        a:focus-visible, button:focus-visible { outline: 2px solid ${T.laurel}; outline-offset: 2px; }
        a, button { transition: background-color .16s ease, border-color .16s ease, color .16s ease, box-shadow .16s ease, transform .16s ease; }
        button:active { transform: translateY(1px); }
        .stars { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
        .stars::before { content: ""; position: absolute; width: 2px; height: 2px; border-radius: 50%;
          box-shadow: ${STARS}; animation: twinkle 5s ease-in-out infinite; }
        @keyframes twinkle { 0%,100% { opacity: .35; } 50% { opacity: .9; } }
        .nav-x { transition: background-color .15s ease, color .15s ease, box-shadow .15s ease; }
        .nav-x:not(.on):hover { background: rgba(255,255,255,.10); color: ${T.ink};
          box-shadow: inset 0 1px 0 rgba(255,255,255,.16); }
        .mcard { transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease, background .16s ease; }
        .mcard:hover { border-color: rgba(255,255,255,.30); transform: translateY(-2px) scale(1.008);
          background: rgba(255,255,255,.11) !important;
          box-shadow: 0 14px 40px rgba(4,6,16,.5), 0 0 0 5px rgba(255,255,255,.06), inset 0 1px 0 rgba(255,255,255,.3); }
        .rail-x { scrollbar-width: none; }
        @media (max-width: 760px) {
          .shell { flex-direction: column; }
          .rail-x { position: fixed !important; left: 12px !important; right: 12px !important;
            top: auto !important; bottom: 12px !important; width: auto !important; height: auto !important;
            flex-direction: row !important; align-items: center; overflow-x: auto; z-index: 60;
            border-radius: 999px !important; border: 1px solid rgba(255,255,255,.16) !important;
            padding: 8px 12px !important; gap: 2px;
            background: rgba(19,23,44,.62) !important;
            backdrop-filter: blur(30px) saturate(160%); -webkit-backdrop-filter: blur(30px) saturate(160%);
            box-shadow: 0 18px 50px rgba(4,6,16,.55), inset 0 1px 0 rgba(255,255,255,.2) !important; }
          .rail-x .brandword, .rail-x .navsec, .rail-x .railfoot, .rail-x .brandrule, .rail-x .lbl { display: none; }
          .rail-x nav { flex-direction: row !important; padding: 0 !important; gap: 2px !important; }
          .rail-x .nav-x { padding: 10px !important; border-radius: 999px !important; }
          .shell main { padding-bottom: 90px !important; }
          .rf-root { bottom: 86px !important; right: 14px !important; }
        }
        @media (prefers-reduced-motion: reduce) {
          a, button, .nav-x, .mcard, .stars::before { transition: none !important; animation: none !important; }
          .mcard:hover, button:active { transform: none; }
        }
      `}</style>
      <div className="stars" aria-hidden="true" />
      <aside style={S.sidebar} className="rail-x">
        <Link to="/" style={S.brand}>
          <Crest />
          <span style={S.brandWord} className="brandword">Acadensia</span>
        </Link>
        <div style={S.brandRule} className="brandrule" />

        <nav style={S.nav} aria-label="Workspace">
          {navItem("/", "Home", I.home, location.pathname === "/")}

          {projectId && (
            <>
              <div style={S.navSection} className="navsec">This manuscript</div>
              {PROJECT_NAV.map((n) =>
                navItem(`/projects/${projectId}/${n.to}`, n.label, n.icon, isActive(n.to)),
              )}
            </>
          )}

          <div style={S.navSection} className="navsec">Account</div>
          {GLOBAL_NAV.map((n) => navItem(n.to, n.label, n.icon, isActive(n.to)))}
        </nav>

        <div style={S.sidebarFoot} className="railfoot">
          <a href="/" style={S.legacyLink}>Classic workspace ↗</a>
          <ReleaseBadge />
        </div>
      </aside>

      <div style={S.mainCol}>
        <header style={S.topbar}>
          <span style={S.crumb}>{title ?? ""}</span>
          <span style={{ display: "inline-flex", alignItems: "center" }}>
            {projectId && <PresenceDots projectId={projectId} />}
            <span style={S.user}>{me.data?.email ?? ""}</span>
          </span>
        </header>
        <main style={S.main}>{children}</main>
      </div>
      <FloatingGuide getProjectId={() => projectId ?? null} />
    </div>
  );
}

const S: Record<string, CSSProperties> = {
  app: { display: "flex", minHeight: "100vh", background: "transparent", color: T.ink, fontFamily: T.sans, position: "relative", zIndex: 1 },
  sidebar: {
    width: 232, flexShrink: 0, display: "flex", flexDirection: "column",
    position: "sticky", top: 0, height: "100vh", overflowY: "auto",
    background: "linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.02))",
    borderRight: `1px solid ${T.line}`,
    backdropFilter: "blur(30px) saturate(160%)", WebkitBackdropFilter: "blur(30px) saturate(160%)",
    boxShadow: "inset 0 1px 0 rgba(255,255,255,.10)",
  },
  brand: { display: "flex", alignItems: "center", gap: 10, padding: "18px 16px 12px", textDecoration: "none" },
  brandWord: { fontFamily: T.sans, fontSize: 17.5, fontWeight: 600, color: T.ink, letterSpacing: "-0.015em" },
  brandRule: { height: 1, background: T.line, margin: "0 16px 6px" },
  nav: { display: "flex", flexDirection: "column", gap: 2, padding: "6px 10px", flex: 1 },
  navSection: { ...overline, padding: "16px 12px 6px" },
  navItem: { display: "flex", alignItems: "center", gap: 11, padding: "8px 12px", borderRadius: T.radius, fontSize: 13.5, fontWeight: 500, color: T.inkSoft, textDecoration: "none" },
  navActive: { background: "rgba(255,255,255,.15)", color: T.ink, boxShadow: "inset 0 1px 0 rgba(255,255,255,.24), 0 2px 10px rgba(0,0,0,.18)" },
  sidebarFoot: { padding: "12px 16px", borderTop: `1px solid ${T.line}` },
  legacyLink: { fontSize: 11.5, color: T.muted, textDecoration: "none", fontWeight: 500 },
  mainCol: { flex: 1, display: "flex", flexDirection: "column", minWidth: 0 },
  topbar: {
    display: "flex", alignItems: "baseline", justifyContent: "space-between",
    padding: "13px 26px", borderBottom: `1px solid ${T.line}`,
    background: "rgba(12,15,32,.35)",
    backdropFilter: "blur(24px) saturate(160%)", WebkitBackdropFilter: "blur(24px) saturate(160%)",
    position: "sticky", top: 0, zIndex: 10,
  },
  crumb: { ...overline, color: T.laurel },
  user: { fontSize: 12, color: T.muted },
  main: { maxWidth: 880, width: "100%", margin: "0 auto", padding: "30px 26px", boxSizing: "border-box" },
};
