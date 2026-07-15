"use client";

import { useState } from "react";
import type { CSSProperties } from "react";
import { BibliographyPanel } from "./BibliographyPanel";
import { ExportMenu } from "./ExportMenu";
import { IdentityLookup } from "./IdentityLookup";
import { SourceIntelligencePanel } from "./SourceIntelligencePanel";
import { WritingPanel } from "./WritingPanel";

/**
 * EnterprisePanel — a single surface grouping the enterprise features: source &
 * journal trust + insight (E1/E3), bibliography rendering (E5), universal export
 * (E6), private writing polish (E7) and verified-identity lookup (E2). Per-quote
 * auto-verify (E4) lives next to quotes via <AutoVerifyButton>.
 */
type Tab = "sources" | "bibliography" | "export" | "writing" | "identity";

const TABS: { key: Tab; label: string }[] = [
  { key: "sources", label: "Sources" },
  { key: "bibliography", label: "Bibliography" },
  { key: "export", label: "Export" },
  { key: "writing", label: "Writing" },
  { key: "identity", label: "Identity" },
];

export function EnterprisePanel({ projectId }: { projectId: string }) {
  const [tab, setTab] = useState<Tab>("sources");
  return (
    <section style={S.panel}>
      <div style={S.tabs}>
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{ ...S.tab, ...(tab === t.key ? S.tabActive : {}) }}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div style={S.body}>
        {tab === "sources" && <SourceIntelligencePanel projectId={projectId} />}
        {tab === "bibliography" && <BibliographyPanel projectId={projectId} />}
        {tab === "export" && <ExportMenu projectId={projectId} />}
        {tab === "writing" && <WritingPanel projectId={projectId} />}
        {tab === "identity" && <IdentityLookup />}
      </div>
    </section>
  );
}

const S: Record<string, CSSProperties> = {
  panel: { width: 396, borderLeft: "1px solid #e7e3db", background: "#fff", height: "100%", overflowY: "auto", fontFamily: "Inter, system-ui, sans-serif" },
  tabs: { display: "flex", gap: 2, padding: "10px 12px 0", borderBottom: "1px solid #e7e3db", position: "sticky", top: 0, background: "#fff" },
  tab: { flex: 1, padding: "9px 4px", border: 0, background: "transparent", borderBottom: "2px solid transparent", fontWeight: 600, fontSize: 12.5, color: "#6b7688", cursor: "pointer" },
  tabActive: { color: "#4b4bd6", borderBottomColor: "#4b4bd6" },
  body: { padding: "16px 15px" },
};
