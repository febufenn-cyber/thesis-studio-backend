"use client";

import { useState } from "react";
import type { CSSProperties } from "react";
import { ApiKeysPanel } from "./ApiKeysPanel";
import { BibliographyPanel } from "./BibliographyPanel";
import { DepositPanel } from "./DepositPanel";
import { DomainReadiness } from "./DomainReadiness";
import { ExportMenu } from "./ExportMenu";
import { IdentityLookup } from "./IdentityLookup";
import { ImportPanel } from "./ImportPanel";
import { SettingsPanel } from "./SettingsPanel";
import { SourceIntelligencePanel } from "./SourceIntelligencePanel";
import { SupervisionPanel } from "./SupervisionPanel";
import { WritingPanel } from "./WritingPanel";

/**
 * EnterprisePanel — the island bridge surface inside the classic workspace.
 * Groups every project tool: sources trust/insight/auto-verify (E1/E3/E4),
 * import (MF5), bibliography (E5), export + interchange (E6/3.5), deposit &
 * ORCID (MF3), writing polish (E7), identity (E2), supervision (3.6), API keys
 * (MF6) and settings (3.7/3.8).
 */
type Tab =
  | "sources" | "import" | "bibliography" | "export" | "deposit"
  | "writing" | "identity" | "supervision" | "readiness" | "keys" | "settings";

const TABS: { key: Tab; label: string }[] = [
  { key: "sources", label: "Sources" },
  { key: "import", label: "Import" },
  { key: "bibliography", label: "Bibliography" },
  { key: "export", label: "Export" },
  { key: "deposit", label: "Deposit" },
  { key: "writing", label: "Writing" },
  { key: "identity", label: "Identity" },
  { key: "supervision", label: "Supervision" },
  { key: "readiness", label: "Readiness" },
  { key: "keys", label: "API keys" },
  { key: "settings", label: "Settings" },
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
        {tab === "import" && <ImportPanel projectId={projectId} />}
        {tab === "bibliography" && <BibliographyPanel projectId={projectId} />}
        {tab === "export" && <ExportMenu projectId={projectId} />}
        {tab === "deposit" && <DepositPanel projectId={projectId} />}
        {tab === "writing" && <WritingPanel projectId={projectId} />}
        {tab === "identity" && <IdentityLookup />}
        {tab === "supervision" && <SupervisionPanel projectId={projectId} />}
        {tab === "readiness" && <DomainReadiness projectId={projectId} />}
        {tab === "keys" && <ApiKeysPanel />}
        {tab === "settings" && <SettingsPanel projectId={projectId} />}
      </div>
    </section>
  );
}

const S: Record<string, CSSProperties> = {
  panel: {
    width: "100%", maxWidth: 860, margin: "0 auto",
    border: "1px solid rgba(255,255,255,0.13)", borderRadius: 10, background: "rgba(255,255,255,0.07)",
    boxShadow: "0 1px 2px rgba(28,25,23,.06), 0 10px 30px rgba(28,25,23,.08)",
    overflow: "hidden", fontFamily: "'Inter', system-ui, sans-serif",
  },
  tabs: { display: "flex", flexWrap: "wrap", gap: 2, padding: "10px 14px 0", borderBottom: "1px solid rgba(255,255,255,0.13)", position: "sticky", top: 0, background: "rgba(255,255,255,0.07)", zIndex: 5 },
  tab: { padding: "8px 10px", border: 0, background: "transparent", borderBottom: "2px solid transparent", fontWeight: 600, fontSize: 12.5, color: "rgba(255,255,255,0.55)", cursor: "pointer" },
  tabActive: { color: "#A5B8FF", borderBottomColor: "#A5B8FF" },
  body: { padding: "18px 20px 20px" },
};
