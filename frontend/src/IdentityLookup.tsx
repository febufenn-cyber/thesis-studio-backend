"use client";

import { useState } from "react";
import type { CSSProperties } from "react";
import {
  lookupOrcid,
  lookupOrganizations,
  type OrcidIdentity,
  type Organization,
} from "./useEnterprise";

/**
 * IdentityLookup — E2 verified identity. Resolve an institution against ROR or a
 * person against the ORCID public registry, to attach a canonical id to metadata.
 * Read-only lookups; the user chooses what to apply. Nothing is auto-filled.
 */
export function IdentityLookup() {
  const [mode, setMode] = useState<"org" | "orcid">("org");
  return (
    <div style={S.wrap}>
      <div style={S.tabs}>
        <button style={tab(mode === "org")} onClick={() => setMode("org")}>
          Institution (ROR)
        </button>
        <button style={tab(mode === "orcid")} onClick={() => setMode("orcid")}>
          Person (ORCID)
        </button>
      </div>
      {mode === "org" ? <OrgLookup /> : <OrcidLookup />}
    </div>
  );
}

function OrgLookup() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Organization[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function search() {
    if (!q.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await lookupOrganizations(q.trim());
      setRows(r.organizations);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lookup failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <SearchRow value={q} onChange={setQ} onSubmit={search} placeholder="University name…" busy={busy} />
      {error && <p style={S.err}>{error}</p>}
      {rows?.length === 0 && <p style={S.muted}>No organizations found.</p>}
      {rows?.map((o) => (
        <div key={o.ror} style={S.card}>
          <div style={S.name}>{o.name}</div>
          <div style={S.meta}>
            {[o.city, o.country].filter(Boolean).join(", ")}
          </div>
          <a style={S.rorLink} href={o.ror} target="_blank" rel="noreferrer">
            {o.ror.replace("https://", "")}
          </a>
        </div>
      ))}
    </>
  );
}

function OrcidLookup() {
  const [orcid, setOrcid] = useState("");
  const [row, setRow] = useState<OrcidIdentity | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function resolve() {
    if (!orcid.trim()) return;
    setBusy(true);
    setError(null);
    setRow(null);
    try {
      setRow(await lookupOrcid(orcid.trim()));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lookup failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <SearchRow value={orcid} onChange={setOrcid} onSubmit={resolve} placeholder="0000-0002-1825-0097" busy={busy} />
      {error && <p style={S.err}>{error}</p>}
      {row && (
        <div style={S.card}>
          <div style={S.name}>{row.name}</div>
          <a style={S.rorLink} href={`https://orcid.org/${row.orcid}`} target="_blank" rel="noreferrer">
            orcid.org/{row.orcid}
          </a>
        </div>
      )}
    </>
  );
}

function SearchRow({
  value,
  onChange,
  onSubmit,
  placeholder,
  busy,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  placeholder: string;
  busy: boolean;
}) {
  return (
    <div style={S.searchRow}>
      <input
        style={S.input}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onSubmit()}
      />
      <button style={S.btn} onClick={onSubmit} disabled={busy}>
        {busy ? "…" : "Search"}
      </button>
    </div>
  );
}

const tab = (active: boolean): CSSProperties => ({
  flex: 1,
  padding: "8px 4px",
  border: 0,
  borderBottom: `2px solid ${active ? "#1F4D3A" : "transparent"}`,
  background: "transparent",
  color: active ? "#1F4D3A" : "#6E655A",
  fontWeight: 600,
  fontSize: 12.5,
  cursor: "pointer",
});

const S: Record<string, CSSProperties> = {
  wrap: { fontFamily: "'Source Sans 3', 'Inter', system-ui, sans-serif", color: "#1C1917" },
  tabs: { display: "flex", gap: 4, borderBottom: "1px solid #DCD3C5", marginBottom: 12 },
  searchRow: { display: "flex", gap: 8, marginBottom: 10 },
  input: { flex: 1, fontFamily: "inherit", fontSize: 13, border: "1px solid #DCD3C5", borderRadius: 8, padding: "8px 10px" },
  btn: { padding: "8px 14px", borderRadius: 8, border: "1px solid #1F4D3A", background: "#1F4D3A", color: "#fff", fontWeight: 600, fontSize: 12.5, cursor: "pointer" },
  card: { border: "1px solid #DCD3C5", borderRadius: 11, padding: "11px 12px", marginBottom: 9 },
  name: { fontSize: 13.5, fontWeight: 700 },
  meta: { fontSize: 12, color: "#6E655A", marginTop: 2 },
  rorLink: { fontSize: 11.5, color: "#1F4D3A", fontFamily: "'IBM Plex Mono', ui-monospace, monospace", textDecoration: "none", display: "inline-block", marginTop: 5 },
  muted: { color: "#6E655A", fontSize: 12.5 },
  err: { color: "#B3362C", fontSize: 12.5 },
};
