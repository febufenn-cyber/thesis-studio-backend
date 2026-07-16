"use client";

import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { createApiKey, listApiKeys, revokeApiKey, type ApiKeyRow } from "./useFeatures";

const SCOPES = ["read", "export", "resolve", "import"] as const;

/**
 * ApiKeysPanel — MF6: bearer keys for Word/Overleaf and other non-browser
 * clients. The plaintext key is shown exactly once at creation; after that only
 * the prefix is visible. Revocation is immediate.
 */
export function ApiKeysPanel() {
  const [rows, setRows] = useState<ApiKeyRow[] | null>(null);
  const [label, setLabel] = useState("");
  const [scopes, setScopes] = useState<string[]>(["read"]);
  const [fresh, setFresh] = useState<ApiKeyRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    listApiKeys()
      .then((r) => {
        const anyR = r as { api_keys?: ApiKeyRow[]; keys?: ApiKeyRow[] } | ApiKeyRow[];
        setRows(Array.isArray(anyR) ? anyR : (anyR.api_keys ?? anyR.keys ?? []));
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(reload, [reload]);

  async function create() {
    setBusy(true); setError(null); setFresh(null);
    try {
      const row = await createApiKey(label.trim(), scopes);
      setFresh(row); setLabel(""); reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Create failed"); }
    finally { setBusy(false); }
  }

  async function revoke(id: string) {
    try { await revokeApiKey(id); reload(); }
    catch (e) { setError(e instanceof Error ? e.message : "Revoke failed"); }
  }

  function toggleScope(s: string) {
    setScopes((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]));
  }

  return (
    <div style={S.wrap}>
      <section style={S.card}>
        <div style={S.h}>Create a key</div>
        <input style={S.input} placeholder="Label (e.g. Word add-in on my laptop)" value={label} onChange={(e) => setLabel(e.target.value)} />
        <div style={S.scopes}>
          {SCOPES.map((s) => (
            <label key={s} style={S.scopeLabel}>
              <input type="checkbox" checked={scopes.includes(s)} onChange={() => toggleScope(s)} /> {s}
            </label>
          ))}
        </div>
        <button style={S.btn} onClick={create} disabled={busy || scopes.length === 0}>
          {busy ? "Creating…" : "Create key"}
        </button>
        {fresh?.key && (
          <div style={S.freshBox}>
            <div style={S.freshHead}>Copy this key now — it is shown only once.</div>
            <code style={S.freshKey}>{fresh.key}</code>
          </div>
        )}
      </section>

      <section style={S.card}>
        <div style={S.h}>Your keys</div>
        {rows === null ? <p style={S.muted}>Loading…</p> : rows.length === 0 ? (
          <p style={S.muted}>No API keys yet.</p>
        ) : (
          rows.map((k) => (
            <div key={k.id} style={S.row}>
              <code style={S.prefix}>{k.prefix}…</code>
              <span style={S.label}>{k.label || "unlabelled"}</span>
              <span style={S.scopesText}>{(k.scopes ?? []).join(", ") || "—"}</span>
              {k.revoked_at ? (
                <span style={S.revoked}>revoked</span>
              ) : (
                <button style={S.btnDanger} onClick={() => revoke(k.id)}>Revoke</button>
              )}
            </div>
          ))
        )}
      </section>
      {error && <p style={S.err}>{error}</p>}
      <p style={S.hint}>
        Use as <code>Authorization: Bearer ak_…</code>. Scopes are enforced server-side:
        <em> read</em> = any GET; <em>export</em>, <em>resolve</em>, <em>import</em> unlock their
        endpoints. Keys can never manage keys or mutate projects.
      </p>
    </div>
  );
}

const S: Record<string, CSSProperties> = {
  wrap: { fontFamily: "'Source Sans 3', 'Inter', system-ui, sans-serif", color: "#1C1917" },
  card: { border: "1px solid #DCD3C5", borderRadius: 11, padding: "13px 14px", marginBottom: 10, background: "#fff" },
  h: { fontSize: 13.5, fontWeight: 700, marginBottom: 8 },
  input: { width: "100%", boxSizing: "border-box", fontFamily: "inherit", fontSize: 13, border: "1px solid #DCD3C5", borderRadius: 8, padding: "8px 10px", marginBottom: 8 },
  scopes: { display: "flex", gap: 14, marginBottom: 10, flexWrap: "wrap" },
  scopeLabel: { fontSize: 12.5, display: "inline-flex", alignItems: "center", gap: 5 },
  btn: { padding: "8px 14px", borderRadius: 8, border: "1px solid #1F4D3A", background: "#1F4D3A", color: "#fff", fontWeight: 600, fontSize: 12.5, cursor: "pointer" },
  btnDanger: { padding: "5px 10px", borderRadius: 7, border: "1px solid #B3362C", background: "#fff", color: "#B3362C", fontWeight: 600, fontSize: 11.5, cursor: "pointer" },
  freshBox: { marginTop: 10, border: "1px solid #9A6A00", background: "#F7EEDA", borderRadius: 9, padding: "9px 11px" },
  freshHead: { fontSize: 11.5, fontWeight: 700, color: "#9A6A00", marginBottom: 5 },
  freshKey: { fontFamily: "'IBM Plex Mono', ui-monospace, monospace", fontSize: 12, wordBreak: "break-all" },
  row: { display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderTop: "1px solid #EFE9DD", flexWrap: "wrap" },
  prefix: { fontFamily: "'IBM Plex Mono', ui-monospace, monospace", fontSize: 12 },
  label: { fontSize: 12.5, fontWeight: 600, flex: 1 },
  scopesText: { fontSize: 11.5, color: "#6E655A" },
  revoked: { fontSize: 11, fontWeight: 700, color: "#6E655A", textTransform: "uppercase" },
  muted: { color: "#6E655A", fontSize: 12.5 },
  err: { color: "#B3362C", fontSize: 12.5 },
  hint: { fontSize: 11.5, color: "#6E655A", background: "#F4EFE6", border: "1px solid #DCD3C5", borderRadius: 8, padding: "7px 10px", marginTop: 4 },
};
