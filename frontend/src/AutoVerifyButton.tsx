"use client";

import { useState } from "react";
import type { CSSProperties } from "react";
import { StatusBadge, toStatus } from "./StatusBadge";
import { verifyQuoteAuto, type AutoVerifyResult } from "./useEnterprise";

/**
 * AutoVerifyButton — E4 one-click quote verification against open-access full
 * text (no upload). Advisory only: it never flips the human-verified bit. If no
 * OA text is found the result is "unverifiable", shown honestly — never green.
 */
export function AutoVerifyButton({
  projectId,
  quoteId,
  onResult,
}: {
  projectId: string;
  quoteId: string;
  onResult?: (r: AutoVerifyResult) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AutoVerifyResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const r = await verifyQuoteAuto(projectId, quoteId);
      setResult(r);
      onResult?.(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Verification failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={S.wrap}>
      <button style={S.btn} onClick={run} disabled={busy}>
        {busy ? "Checking source…" : "⚡ Verify against source"}
      </button>
      {result && (
        <span style={S.res}>
          <StatusBadge status={toStatus(result.status)} />
          {result.fulltext_provider && (
            <span style={S.prov}>via {result.fulltext_provider}</span>
          )}
        </span>
      )}
      {result && result.status === "unverifiable" && (
        <p style={S.note}>No open-access full text was found — this is not a failure of the quote.</p>
      )}
      {error && <p style={S.err}>{error}</p>}
    </div>
  );
}

const S: Record<string, CSSProperties> = {
  wrap: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 9, fontFamily: "'Source Sans 3', 'Inter', system-ui, sans-serif" },
  btn: { display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 12px", borderRadius: 9, border: "1px solid #1F4D3A", background: "#1F4D3A", color: "#fff", fontWeight: 600, fontSize: 12.5, cursor: "pointer" },
  res: { display: "inline-flex", alignItems: "center", gap: 7 },
  prov: { fontSize: 11, color: "#6E655A" },
  note: { width: "100%", fontSize: 11.5, color: "#6E655A", margin: "2px 0 0" },
  err: { width: "100%", fontSize: 12, color: "#B3362C", margin: "2px 0 0" },
};
