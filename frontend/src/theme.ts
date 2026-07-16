/**
 * Acadensia design language — "the scholar's desk".
 *
 * One token source for every surface (SPA, islands, guide). The aesthetic is
 * academic: warm paper, warm-black ink, laurel green as the trust color, gilt
 * gold for achievement, hairline book-rules instead of puffy cards, a real
 * serif for titles and figures, small-caps overlines like journal front
 * matter. Status colors keep the validated accessible family; identity is
 * never color-alone.
 */

export const T = {
  // ground
  paper: "#FAF7F1", // page ground
  card: "#FFFFFF", // sheet
  wash: "#F4EFE6", // recessed panels / sidebars
  line: "#DCD3C5", // hairline book-rule
  lineStrong: "#C6B99F",
  // ink
  ink: "#1C1917",
  inkSoft: "#44403A",
  muted: "#6E655A",
  faint: "#988D7E",
  // brand
  laurel: "#1F4D3A", // primary — trust, actions
  laurelDeep: "#14352A", // hover / emphasis
  laurelWash: "#E8EFE9", // selected/active wash
  gilt: "#B08A3E", // achievement, highlights
  giltWash: "#F6EFDD",
  // status (validated family, unchanged semantics; icon+label always)
  good: "#1F7A4D",
  goodWash: "#E4F1E9",
  warn: "#9A6A00",
  warnWash: "#F7EEDA",
  bad: "#B3362C",
  badWash: "#F8E7E4",
  info: "#31596B",
  infoWash: "#E7EEF1",
  // type
  serif: "'Source Serif 4', 'Iowan Old Style', Georgia, 'Times New Roman', serif",
  sans: "'Source Sans 3', 'Inter', system-ui, -apple-system, sans-serif",
  mono: "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace",
  // shape
  radius: 6, // restrained; books are not bubbles
  radiusLg: 10,
  shadow: "0 1px 2px rgba(28,25,23,.06), 0 8px 28px rgba(28,25,23,.07)",
  shadowLg: "0 2px 6px rgba(28,25,23,.08), 0 20px 48px rgba(28,25,23,.14)",
} as const;

/** Journal-style overline: small caps, tracked out, muted. */
export const overline = {
  fontFamily: T.sans,
  fontSize: 10.5,
  fontWeight: 700,
  letterSpacing: "0.14em",
  textTransform: "uppercase" as const,
  color: T.muted,
};

/** Serif display heading. */
export const display = (size = 24) => ({
  fontFamily: T.serif,
  fontSize: size,
  fontWeight: 600,
  color: T.ink,
  letterSpacing: "-0.01em",
  lineHeight: 1.2,
});

export const bodyText = {
  fontFamily: T.sans,
  fontSize: 13.5,
  color: T.inkSoft,
  lineHeight: 1.6,
};

export const btnPrimary = {
  fontFamily: T.sans,
  padding: "9px 16px",
  borderRadius: T.radius,
  border: `1px solid ${T.laurel}`,
  background: T.laurel,
  color: "#FDFCF9",
  fontWeight: 600,
  fontSize: 13,
  cursor: "pointer",
  letterSpacing: "0.01em",
};

export const btnGhost = {
  fontFamily: T.sans,
  padding: "8px 14px",
  borderRadius: T.radius,
  border: `1px solid ${T.lineStrong}`,
  background: T.card,
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
};

export const input = {
  fontFamily: T.sans,
  fontSize: 13.5,
  color: T.ink,
  border: `1px solid ${T.lineStrong}`,
  borderRadius: T.radius,
  padding: "9px 11px",
  background: T.card,
  outlineColor: T.laurel,
};

/** Global CSS for SPA/guide contexts: fonts, ground, selection, focus. */
export const GLOBAL_CSS = `
body { background: ${T.paper}; color: ${T.ink}; }
::selection { background: ${T.giltWash}; color: ${T.ink}; }
:focus-visible { outline: 2px solid ${T.laurel}; outline-offset: 2px; }
`;
