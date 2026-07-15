"use client";

import { useState } from "react";
import type { CSSProperties } from "react";
import { SourceIntelligence } from "./SourceIntelligence";
import { sourceLabel, useSources } from "./useEnterprise";

/**
 * SourceIntelligencePanel — a project-level surface for E1 (trust) + E3
 * (insight): pick a registry source and inspect its advisory signals. Used by
 * the bridge island so these per-source features are reachable without hooking
 * the legacy registry render loop (that wiring lands in the SPA migration).
 */
export function SourceIntelligencePanel({ projectId }: { projectId: string }) {
  const sources = useSources(projectId);
  const [sourceId, setSourceId] = useState<string | null>(null);

  if (sources.loading) return <p style={S.muted}>Loading sources…</p>;
  if (sources.error) return <p style={S.err}>{sources.error}</p>;
  if (!sources.data || sources.data.length === 0)
    return <p style={S.muted}>No sources in the registry yet.</p>;

  const current = sourceId ?? sources.data[0].id;

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
    </div>
  );
}

const S: Record<string, CSSProperties> = {
  wrap: { fontFamily: "Inter, system-ui, sans-serif" },
  select: { width: "100%", boxSizing: "border-box", fontFamily: "inherit", fontSize: 12.5, border: "1px solid #e7e3db", background: "#fff", borderRadius: 7, padding: "8px", marginBottom: 12 },
  muted: { color: "#6b7688", fontSize: 12.5 },
  err: { color: "#d64545", fontSize: 12.5 },
};
