"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { apiGet } from "./coverageApi";
import { T } from "./theme";

/**
 * InstitutionConsole — read-only administrator visibility for the
 * institutional endpoints that had no UI: analytics, operations posture,
 * billing/usage, reliability dashboard and entitlements. Shown only to
 * accounts the API authorises (anything else 403s and the console says so).
 * Mutating admin actions (incidents, rollouts, backups, restore drills)
 * stay API-first deliberately — they are runbook operations.
 */

const TABS = [
  { key: "analytics", label: "Analytics", path: (id: string) => `/institutions/${id}/analytics` },
  { key: "operations", label: "Operations", path: (id: string) => `/institutions/${id}/operations` },
  { key: "billing", label: "Billing", path: (id: string) => `/institutions/${id}/commercial/billing` },
  { key: "usage", label: "Usage", path: (id: string) => `/institutions/${id}/commercial/usage` },
  { key: "reliability", label: "Reliability", path: (id: string) => `/institutions/${id}/reliability/dashboard` },
  { key: "entitlements", label: "Entitlements", path: (id: string) => `/institutions/${id}/commercial/entitlements` },
  { key: "onboarding", label: "Onboarding", path: (id: string) => `/institutions/${id}/onboarding` },
];

export function InstitutionConsole({ institutionId }: { institutionId: string }) {
  const [tab, setTab] = useState(TABS[0]);
  const [data, setData] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true); setError(null); setData(null);
    apiGet(tab.path(institutionId))
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tab, institutionId]);

  return (
    <div>
      <div style={S.tabs}>
        {TABS.map((t) => (
          <button key={t.key} style={{ ...S.tab, ...(tab.key === t.key ? S.tabOn : {}) }}
            onClick={() => setTab(t)}>{t.label}</button>
        ))}
      </div>
      {loading && <p style={S.muted}>Loading…</p>}
      {error && (
        <p style={S.err}>
          {error.includes("403") || /denied|permission|forbidden/i.test(error)
            ? "Your account isn't authorised for this console section."
            : error}
        </p>
      )}
      {data !== null && <Rendered value={data} />}
      <p style={S.foot}>
        Read-only visibility. Incident, rollout, backup and restore-drill actions are
        deliberately API-first (runbook operations) — see the operations documentation.
      </p>
    </div>
  );
}

/** Render nested API payloads as legible cards, not raw JSON. */
function Rendered({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) return <span style={S.dim}>—</span>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <span style={S.dim}>none</span>;
    return (
      <div style={{ display: "grid", gap: 8 }}>
        {value.slice(0, 40).map((v, i) => (
          <div key={i} style={depth === 0 ? S.card : undefined}><Rendered value={v} depth={depth + 1} /></div>
        ))}
      </div>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    return (
      <div style={depth === 0 ? S.card : undefined}>
        {entries.map(([k, v]) => (
          <div key={k} style={S.kv}>
            <span style={S.k}>{k.replace(/_/g, " ")}</span>
            <span style={S.v}>
              {typeof v === "object" && v !== null ? <Rendered value={v} depth={depth + 1} /> : String(v ?? "—")}
            </span>
          </div>
        ))}
      </div>
    );
  }
  return <span style={S.v}>{String(value)}</span>;
}

const S: Record<string, CSSProperties> = {
  tabs: { display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 14 },
  tab: { fontFamily: "inherit", fontSize: 12.5, fontWeight: 600, padding: "7px 14px", borderRadius: 999, border: `1px solid ${T.line}`, background: "rgba(255,255,255,0.05)", color: T.muted, cursor: "pointer" },
  tabOn: { background: "rgba(255,255,255,0.14)", color: T.ink, borderColor: T.lineStrong },
  card: { border: `1px solid ${T.line}`, borderRadius: 14, padding: "12px 14px", marginBottom: 10, background: T.card },
  kv: { display: "flex", gap: 12, padding: "4px 0", fontSize: 12.5, alignItems: "baseline" },
  k: { color: T.muted, minWidth: 160, textTransform: "capitalize" as const, flexShrink: 0 },
  v: { color: T.ink, wordBreak: "break-word" as const },
  dim: { color: T.faint, fontSize: 12.5 },
  muted: { color: T.muted, fontSize: 12.5 },
  err: { color: T.warn, fontSize: 12.5 },
  foot: { color: T.faint, fontSize: 11.5, lineHeight: 1.5, marginTop: 16, borderTop: `1px solid ${T.line}`, paddingTop: 10 },
};
