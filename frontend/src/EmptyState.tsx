import type { CSSProperties, ReactNode } from "react";
import { T } from "./theme";

/**
 * EmptyState — the scholar's-desk empty moment: a gilt engraved glyph, one
 * serif line, one muted sentence, an optional action. Shared by the SPA and
 * the island panels so every "nothing here yet" reads as designed, not shrugged.
 */

export const GLYPHS = {
  book: "M12 5.5C10.5 4 8.2 3.4 5.5 3.4c-.8 0-1.5.06-2.5.2V19c1-.14 1.7-.2 2.5-.2 2.7 0 5 .6 6.5 2.1 1.5-1.5 3.8-2.1 6.5-2.1.8 0 1.5.06 2.5.2V3.6c-1-.14-1.7-.2-2.5-.2-2.7 0-5 .6-6.5 2.1Zm0 0V21",
  shelf: "M4 19.5V5a1 1 0 0 1 1-1h3v16H5a1 1 0 0 1-1-.5ZM8 4h4v16H8ZM14.5 5.2l4.6-1.2 2 15.5-4.6 1.2Z",
  quill: "M4 20l1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L8 19l-4 1ZM13.5 7.5l3 3",
  seal: "M12 3l7 3v5c0 4.5-3 8.5-7 10-4-1.5-7-5.5-7-10V6ZM9 12l2 2 4-4.5",
};

export function EmptyState({
  glyph = GLYPHS.book,
  title,
  hint,
  action,
}: {
  glyph?: string;
  title: string;
  hint: string;
  action?: ReactNode;
}) {
  return (
    <div style={S.wrap}>
      <svg width={34} height={34} viewBox="0 0 24 24" fill="none" stroke="#F0B472"
        strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
        aria-hidden="true" style={{ opacity: 0.85 }}>
        <path d={glyph} />
      </svg>
      <p style={S.title}>{title}</p>
      <p style={S.hint}>{hint}</p>
      {action && <div style={{ marginTop: 6 }}>{action}</div>}
    </div>
  );
}

const S: Record<string, CSSProperties> = {
  wrap: {
    display: "grid",
    justifyItems: "center",
    gap: 7,
    padding: "44px 20px",
    textAlign: "center",
  },
  title: { fontFamily: T.serif, fontSize: 17.5, color: T.ink, margin: 0 },
  hint: { fontSize: 13, color: T.muted, margin: 0, maxWidth: 360, lineHeight: 1.55 },
};
