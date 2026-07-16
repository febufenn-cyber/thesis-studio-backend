/**
 * Acadensia design language — "spatial glass".
 *
 * One token source for every surface (SPA, islands, guide). The aesthetic is
 * spatial: a dusk-aurora environment behind everything, frosted-glass panes
 * with specular top edges, pill controls, gaze-glow hovers, soft depth. UI
 * type is Inter; manuscript prose stays a real serif; status colors are the
 * on-dark accessible family and identity is never color-alone.
 */

export const T = {
  // environment (the world behind the glass)
  envTop: "#070A16",
  envMid: "#1B2148",
  envGlow: "#59414F",
  // glass surfaces
  paper: "rgba(255,255,255,0.04)", // page ground inside a pane
  card: "rgba(255,255,255,0.07)", // raised pane
  cardSolid: "rgba(19,23,44,0.72)", // near-opaque pane for dense reading
  wash: "rgba(255,255,255,0.05)", // recessed panels / sidebars
  line: "rgba(255,255,255,0.13)", // hairline
  lineStrong: "rgba(255,255,255,0.24)",
  // ink (on glass)
  ink: "rgba(255,255,255,0.96)",
  inkSoft: "rgba(255,255,255,0.80)",
  muted: "rgba(255,255,255,0.55)",
  faint: "rgba(255,255,255,0.38)",
  // brand
  laurel: "#A5B8FF", // primary accent — links, active, rings
  laurelDeep: "#C6D2FF", // hover / emphasis
  laurelWash: "rgba(165,184,255,0.16)", // selected/active wash
  gilt: "#F0B472", // warm highlight (fox, achievement)
  giltWash: "rgba(240,180,114,0.16)",
  // pills (primary action = bright pill, dark text)
  pillBg: "rgba(255,255,255,0.92)",
  pillInk: "#141A38",
  // status (on-dark family; icon+label always)
  good: "#7DE8A8",
  goodWash: "rgba(125,232,168,0.14)",
  warn: "#FFC46E",
  warnWash: "rgba(255,196,110,0.14)",
  bad: "#FF7A76",
  badWash: "rgba(255,122,118,0.14)",
  info: "#7FC8E8",
  infoWash: "rgba(127,200,232,0.14)",
  // type
  serif: "'Source Serif 4', 'Iowan Old Style', Georgia, 'Times New Roman', serif",
  sans: "'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
  mono: "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace",
  // shape
  radius: 14, // glass is soft
  radiusLg: 22,
  shadow: "0 4px 18px rgba(4,6,16,.28), inset 0 1px 0 rgba(255,255,255,.18)",
  shadowLg: "0 30px 80px rgba(4,6,16,.45), 0 4px 18px rgba(4,6,16,.28), inset 0 1px 0 rgba(255,255,255,.28)",
  // material
  blur: "blur(36px) saturate(160%)",
} as const;

/** Overline label: tracked caps, quiet. */
export const overline = {
  fontFamily: T.sans,
  fontSize: 10.5,
  fontWeight: 600,
  letterSpacing: "0.14em",
  textTransform: "uppercase" as const,
  color: T.muted,
};

/** Display heading — Inter tight on glass. */
export const display = (size = 24) => ({
  fontFamily: T.sans,
  fontSize: size,
  fontWeight: 600,
  color: T.ink,
  letterSpacing: "-0.02em",
  lineHeight: 1.15,
});

export const bodyText = {
  fontFamily: T.sans,
  fontSize: 13.5,
  color: T.inkSoft,
  lineHeight: 1.6,
};

export const btnPrimary = {
  fontFamily: T.sans,
  padding: "9px 18px",
  borderRadius: 999,
  border: "0",
  background: T.pillBg,
  color: T.pillInk,
  fontWeight: 600,
  fontSize: 13,
  cursor: "pointer",
  letterSpacing: "-0.005em",
  boxShadow: "0 6px 20px rgba(0,0,0,.25), inset 0 -1px 0 rgba(0,0,0,.08)",
};

export const btnGhost = {
  fontFamily: T.sans,
  padding: "8px 16px",
  borderRadius: 999,
  border: `1px solid ${T.lineStrong}`,
  background: "rgba(255,255,255,0.06)",
  color: T.ink,
  fontWeight: 600,
  fontSize: 13,
  cursor: "pointer",
};

export const card = {
  border: `1px solid ${T.line}`,
  borderRadius: T.radiusLg,
  background: T.card,
  padding: "14px 16px",
  boxShadow: T.shadow,
};

export const input = {
  fontFamily: T.sans,
  fontSize: 13.5,
  color: T.ink,
  border: `1px solid ${T.line}`,
  borderRadius: T.radius,
  padding: "10px 13px",
  background: "rgba(255,255,255,0.07)",
  outlineColor: T.laurel,
};

/** The dusk-aurora environment, shared by every surface. */
export const ENV_BG = `
  radial-gradient(120% 90% at 78% 108%, rgba(255,166,87,.30) 0%, rgba(255,120,90,.14) 26%, transparent 55%),
  radial-gradient(90% 70% at 12% 112%, rgba(94,140,255,.22) 0%, transparent 55%),
  radial-gradient(70% 55% at 55% -8%, rgba(120,90,220,.28) 0%, transparent 60%),
  linear-gradient(178deg, #070A16 0%, #101632 34%, #1B2148 58%, #33305E 76%, #4A3A5E 90%, #59414F 100%)`;

/** Global CSS for SPA/guide contexts: environment, selection, focus. */
export const GLOBAL_CSS = `
body { background: ${T.envTop}; background-image: ${ENV_BG}; background-attachment: fixed; color: ${T.ink}; }
::selection { background: ${T.laurelWash}; color: ${T.ink}; }
:focus-visible { outline: 2px solid ${T.laurel}; outline-offset: 2px; }
`;
