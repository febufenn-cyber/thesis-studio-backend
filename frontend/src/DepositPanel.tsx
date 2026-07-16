"use client";

import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import {
  connectOrcid,
  createDeposit,
  disconnectOrcid,
  listDeposits,
  listExports,
  type Deposit,
  type ExportRow,
} from "./useFeatures";

/**
 * DepositPanel — MF3: deposit a completed export to Zenodo (DOI minting) and
 * connect an ORCID iD. Partner-gated server-side: without a ZENODO_TOKEN the
 * API fails closed with 503 and this panel says so honestly.
 */
export function DepositPanel({ projectId }: { projectId: string }) {
  const [deposits, setDeposits] = useState<Deposit[] | null>(null);
  const [exports, setExports] = useState<ExportRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const reload = useCallback(() => {
    listDeposits(projectId).then((d) => setDeposits(d.deposits)).catch((e) => setError(e.message));
    listExports(projectId).then(setExports).catch(() => setExports([]));
  }, [projectId]);
  useEffect(reload, [reload]);

  async function deposit(exportId: string) {
    setBusyId(exportId); setError(null);
    try {
      await createDeposit(projectId, exportId);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Deposit failed");
    } finally { setBusyId(null); }
  }

  const depositable = (exports ?? []).filter((e) => e.status === "completed");

  return (
    <div style={S.wrap}>
      <section style={S.card}>
        <div style={S.h}>Deposit to Zenodo</div>
        <p style={S.muted}>Mints a DOI for a completed export. Runs against the Zenodo sandbox until a production token is configured.</p>
        {exports === null ? <p style={S.muted}>Loading exports…</p> : depositable.length === 0 ? (
          <p style={S.muted}>No completed exports yet — generate one from the Export page first.</p>
        ) : (
          depositable.map((e) => (
            <div key={e.id} style={S.rowLine}>
              <span style={S.mono}>{e.format.toUpperCase()} · {new Date(e.created_at).toLocaleDateString()}</span>
              <button style={S.btn} disabled={busyId === e.id} onClick={() => deposit(e.id)}>
                {busyId === e.id ? "Depositing…" : "Deposit"}
              </button>
            </div>
          ))
        )}
      </section>

      <section style={S.card}>
        <div style={S.h}>Deposits</div>
        {deposits === null ? <p style={S.muted}>Loading…</p> : deposits.length === 0 ? (
          <p style={S.muted}>No deposits yet.</p>
        ) : (
          deposits.map((d) => (
            <div key={d.id} style={S.depRow}>
              <span style={{ ...S.chip, ...(d.status === "published" ? S.chipGood : d.status === "failed" ? S.chipBad : {}) }}>{d.status}</span>
              <span style={S.mono}>{d.doi ?? "no DOI yet"}</span>
              {d.sandbox && <span style={S.chip}>sandbox</span>}
              {d.landing_url && <a style={S.link} href={d.landing_url} target="_blank" rel="noreferrer">open ↗</a>}
              {d.error_message && <span style={S.err}>{d.error_message}</span>}
            </div>
          ))
        )}
      </section>

      <OrcidCard />
      {error && <p style={S.err}>{error}</p>}
    </div>
  );
}

function OrcidCard() {
  const [orcid, setOrcid] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function connect() {
    setBusy(true); setMsg(null);
    try {
      const r = await connectOrcid(orcid.trim());
      setMsg(`Connected ${r.orcid}.`);
    } catch (e) { setMsg(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(false); }
  }
  async function disconnect() {
    setBusy(true); setMsg(null);
    try { await disconnectOrcid(); setMsg("ORCID disconnected."); }
    catch (e) { setMsg(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(false); }
  }

  return (
    <section style={S.card}>
      <div style={S.h}>ORCID iD</div>
      <p style={S.muted}>Attach your ORCID so deposits and exports carry your verified researcher identity.</p>
      <div style={S.rowLine}>
        <input style={S.input} placeholder="0000-0002-1825-0097" value={orcid} onChange={(e) => setOrcid(e.target.value)} />
        <button style={S.btn} onClick={connect} disabled={busy || !orcid.trim()}>Connect</button>
        <button style={S.btnGhost} onClick={disconnect} disabled={busy}>Disconnect</button>
      </div>
      {msg && <p style={S.hint}>{msg}</p>}
    </section>
  );
}

const S: Record<string, CSSProperties> = {
  wrap: { fontFamily: "'Source Sans 3', 'Inter', system-ui, sans-serif", color: "#1C1917" },
  card: { border: "1px solid #DCD3C5", borderRadius: 11, padding: "13px 14px", marginBottom: 10, background: "#fff" },
  h: { fontSize: 13.5, fontWeight: 700, marginBottom: 4 },
  muted: { color: "#6E655A", fontSize: 12.5, margin: "4px 0 10px" },
  rowLine: { display: "flex", alignItems: "center", gap: 9, marginBottom: 8, flexWrap: "wrap" },
  depRow: { display: "flex", alignItems: "center", gap: 9, padding: "7px 0", borderTop: "1px solid #EFE9DD", flexWrap: "wrap" },
  chip: { fontSize: 10.5, fontWeight: 700, color: "#6E655A", background: "#EFE9DD", borderRadius: 999, padding: "3px 9px", textTransform: "uppercase" },
  chipGood: { color: "#1F7A4D", background: "#E4F1E9" },
  chipBad: { color: "#B3362C", background: "#F8E7E4" },
  mono: { fontFamily: "'IBM Plex Mono', ui-monospace, monospace", fontSize: 12 },
  link: { color: "#1F4D3A", fontSize: 12, fontWeight: 600, textDecoration: "none" },
  input: { flex: 1, minWidth: 180, fontFamily: "inherit", fontSize: 13, border: "1px solid #DCD3C5", borderRadius: 8, padding: "8px 10px" },
  btn: { padding: "8px 13px", borderRadius: 8, border: "1px solid #1F4D3A", background: "#1F4D3A", color: "#fff", fontWeight: 600, fontSize: 12.5, cursor: "pointer" },
  btnGhost: { padding: "8px 13px", borderRadius: 8, border: "1px solid #DCD3C5", background: "#fff", color: "#1C1917", fontWeight: 600, fontSize: 12.5, cursor: "pointer" },
  err: { color: "#B3362C", fontSize: 12.5 },
  hint: { fontSize: 11.5, color: "#6E655A", marginTop: 6 },
};
