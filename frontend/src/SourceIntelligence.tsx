"use client";

import type { CSSProperties } from "react";
import { StatusBadge } from "./StatusBadge";
import { useInsight, useSourceTrust } from "./useEnterprise";

/**
 * SourceIntelligence — journal/source trust (E1) + paper insight (E3) for one
 * registry source. Everything here is advisory: a "reputable" verdict or a TLDR
 * is a signal, never a verification. An unknown journal is shown as UNKNOWN, not
 * as a negative; a retracted source is surfaced in red and never softened.
 */
export function SourceIntelligence({
  projectId,
  sourceId,
}: {
  projectId: string;
  sourceId: string;
}) {
  const trust = useSourceTrust(projectId, sourceId);
  const insight = useInsight(projectId, sourceId);

  return (
    <div style={S.wrap}>
      <div style={S.advisory}>
        Advisory signals from open scholarly data — not a verification of this source.
      </div>

      {/* ---- Trust (E1) ---- */}
      <section style={S.card}>
        <div style={S.head}>
          <span style={S.title}>Journal &amp; source trust</span>
          {trust.data?.retracted ? (
            <StatusBadge status="retracted" />
          ) : (
            <VerdictChip verdict={trust.data?.verdict} />
          )}
        </div>
        {trust.loading && <p style={S.muted}>Checking…</p>}
        {trust.error && <p style={S.err}>{trust.error}</p>}
        {trust.data && (
          <>
            {trust.data.retracted && (
              <p style={S.retract}>
                ⚠ This source is flagged retracted. It must not be used as reliable support.
              </p>
            )}
            <ul style={S.signals}>
              <Signal on={trust.data.is_in_doaj} label="Indexed in DOAJ" />
              <Signal on={trust.data.is_open_access} label="Open access" />
              {trust.data.h_index != null && <li>h-index: {trust.data.h_index}</li>}
              {trust.data.cited_by_count != null && (
                <li>{trust.data.cited_by_count.toLocaleString()} citations</li>
              )}
            </ul>
            {trust.data.reasons?.length > 0 && (
              <p style={S.muted}>{trust.data.reasons.join(" · ")}</p>
            )}
          </>
        )}
      </section>

      {/* ---- Insight (E3) ---- */}
      <section style={S.card}>
        <div style={S.head}>
          <span style={S.title}>Research insight</span>
          {insight.data && (
            <span style={S.src}>Semantic Scholar</span>
          )}
        </div>
        {insight.loading && <p style={S.muted}>Loading…</p>}
        {insight.error && <p style={S.err}>{insight.error}</p>}
        {insight.data && !insight.data.found && (
          <p style={S.muted}>No insight found for this source.</p>
        )}
        {insight.data?.found && (
          <>
            {insight.data.tldr && <p style={S.tldr}>{insight.data.tldr}</p>}
            {insight.data.citation_count != null && (
              <p style={S.muted}>{insight.data.citation_count.toLocaleString()} citations</p>
            )}
            {insight.data.references?.length > 0 && (
              <RelatedList title="Key references" items={insight.data.references.map((r) => r.title)} />
            )}
          </>
        )}
      </section>
    </div>
  );
}

function VerdictChip({ verdict }: { verdict?: string }) {
  const map: Record<string, { label: string; fg: string; bg: string }> = {
    reputable: { label: "REPUTABLE", fg: "#7DE8A8", bg: "rgba(125,232,168,0.14)" },
    caution: { label: "CAUTION", fg: "#FFC46E", bg: "rgba(255,196,110,0.14)" },
    unknown: { label: "UNKNOWN", fg: "rgba(255,255,255,0.55)", bg: "rgba(255,255,255,0.09)" },
  };
  const s = map[verdict ?? "unknown"] ?? map.unknown;
  return (
    <span style={{ ...S.chip, color: s.fg, background: s.bg }}>{s.label}</span>
  );
}

function Signal({ on, label }: { on: boolean | null; label: string }) {
  if (!on) return null;
  return <li>✓ {label}</li>;
}

function RelatedList({ title, items }: { title: string; items: string[] }) {
  return (
    <div style={{ marginTop: 8 }}>
      <div style={S.relTitle}>{title}</div>
      <ul style={S.rel}>
        {items.slice(0, 5).map((t, i) => (
          <li key={i}>{t}</li>
        ))}
      </ul>
    </div>
  );
}

const S: Record<string, CSSProperties> = {
  wrap: { fontFamily: "'Inter', system-ui, sans-serif", color: "rgba(255,255,255,0.96)" },
  advisory: { fontSize: 11, color: "rgba(255,255,255,0.55)", background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.13)", borderRadius: 8, padding: "6px 9px", marginBottom: 12 },
  card: { border: "1px solid rgba(255,255,255,0.13)", borderRadius: 11, padding: "12px 13px", marginBottom: 10 },
  head: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  title: { fontSize: 13, fontWeight: 700 },
  src: { fontSize: 10.5, color: "rgba(255,255,255,0.55)", fontWeight: 600 },
  chip: { padding: "3px 9px", borderRadius: 999, fontSize: 11, fontWeight: 700 },
  signals: { listStyle: "none", margin: "4px 0", padding: 0, display: "flex", flexWrap: "wrap", gap: "4px 14px", fontSize: 12.5 },
  muted: { color: "rgba(255,255,255,0.55)", fontSize: 12.5, margin: "4px 0" },
  err: { color: "#FF7A76", fontSize: 12.5 },
  retract: { color: "#FF7A76", background: "rgba(255,122,118,0.14)", borderRadius: 8, padding: "7px 9px", fontSize: 12, fontWeight: 600, margin: "2px 0 8px" },
  tldr: { fontSize: 13, lineHeight: 1.55, margin: "2px 0 6px" },
  relTitle: { fontSize: 11, fontWeight: 700, color: "rgba(255,255,255,0.55)", textTransform: "uppercase", letterSpacing: 0.4 },
  rel: { margin: "5px 0 0", paddingLeft: 18, fontSize: 12.5, lineHeight: 1.5 },
};
