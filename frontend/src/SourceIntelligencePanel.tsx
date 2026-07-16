"use client";

import { useState } from "react";
import type { CSSProperties } from "react";
import { AutoVerifyButton } from "./AutoVerifyButton";
import { SourceIntelligence } from "./SourceIntelligence";
import { sourceLabel, useQuotes, useSources } from "./useEnterprise";

/**
 * SourceIntelligencePanel — a project-level surface for E1 (trust) + E3
 * (insight) + E4 (auto-verify): pick a registry source, inspect its advisory
 * signals, and one-click verify its quotations against open-access full text.
 * Used by the bridge island so these per-source/per-quote features are reachable
 * without hooking the legacy registry render loop (that lands in the SPA).
 */
export function SourceIntelligencePanel({ projectId }: { projectId: string }) {
  const sources = useSources(projectId);
  const quotes = useQuotes(projectId);
  const [sourceId, setSourceId] = useState<string | null>(null);

  if (sources.loading) return <p style={S.muted}>Loading sources…</p>;
  if (sources.error) return <p style={S.err}>{sources.error}</p>;
  if (!sources.data || sources.data.length === 0)
    return <p style={S.muted}>No sources in the registry yet.</p>;

  const current = sourceId ?? sources.data[0].id;
  const sourceQuotes = (quotes.data ?? []).filter((q) => q.source_id === current);

  return (
    <div style={S.wrap}>
      <select style={S.select} value={current} onChange={(e) => setSourceId(e.target.value)}>
        {sources.data.map((s) => (
          <option key={s.id} value={s.id}>
            {sourceLabel(s)}
          </option>
        ))}
      </select>
      <SourceIntelligence projectId={projectId} sourceId={current} />

      <section style={S.quotes}>
        <div style={S.qHead}>Quotations from this source</div>
        {sourceQuotes.length === 0 ? (
          <p style={S.muted}>No quotations recorded for this source.</p>
        ) : (
          sourceQuotes.map((q) => (
            <div key={q.id} style={S.quote}>
              <blockquote style={S.qText}>“{q.text}”</blockquote>
              {q.page_or_loc && <div style={S.qLoc}>{q.page_or_loc}</div>}
              <AutoVerifyButton projectId={projectId} quoteId={q.id} />
            </div>
          ))
        )}
      </section>
    </div>
  );
}

const S: Record<string, CSSProperties> = {
  wrap: { fontFamily: "'Source Sans 3', 'Inter', system-ui, sans-serif" },
  select: { width: "100%", boxSizing: "border-box", fontFamily: "inherit", fontSize: 12.5, border: "1px solid #DCD3C5", background: "#fff", borderRadius: 7, padding: "8px", marginBottom: 12 },
  muted: { color: "#6E655A", fontSize: 12.5 },
  err: { color: "#B3362C", fontSize: 12.5 },
  quotes: { marginTop: 14 },
  qHead: { fontSize: 11, fontWeight: 700, color: "#6E655A", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 8 },
  quote: { border: "1px solid #DCD3C5", borderRadius: 11, padding: "11px 12px", marginBottom: 9 },
  qText: { margin: "0 0 6px", fontSize: 13, lineHeight: 1.5, color: "#1C1917", fontStyle: "italic" },
  qLoc: { fontSize: 11, color: "#6E655A", marginBottom: 8 },
};
