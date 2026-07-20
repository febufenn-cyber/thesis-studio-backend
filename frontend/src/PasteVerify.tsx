"use client";

import { useState } from "react";
import type { CSSProperties } from "react";
import { apiSend } from "./coverageApi";
import { T } from "./theme";

/**
 * PasteVerify — verify a quotation against source text YOU provide
 * (POST /quotes/{id}/verify-source). For sources with no open-access full
 * text: paste the passage from your own copy and get the advisory match.
 * Never sets verified — that judgment stays human.
 */
export function PasteVerify({ projectId, quoteId }: { projectId: string; quoteId: string }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      const r = await apiSend<Record<string, unknown>>(
        "POST",
        `/projects/${projectId}/quotes/${quoteId}/verify-source`,
        { source_text: text, run_alignment: true },
      );
      const status = (r.status ?? r.result ?? r.match ?? "checked") as string;
      const score = r.similarity ?? r.score;
      setResult(`Advisory result: ${String(status)}${score !== undefined ? ` (similarity ${String(score)})` : ""}. Verified stays your call.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!open)
    return (
      <button style={S.link} onClick={() => setOpen(true)}>
        Verify against pasted source text
      </button>
    );

  return (
    <div style={S.box}>
      <textarea
        style={S.ta}
        rows={4}
        placeholder="Paste the passage (or full page) from your copy of the source…"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div style={{ display: "flex", gap: 8 }}>
        <button style={S.primary} disabled={busy || text.trim().length < 20} onClick={run}>
          {busy ? "Checking…" : "Check quote"}
        </button>
        <button style={S.ghost} onClick={() => setOpen(false)}>Close</button>
      </div>
      {result && <p style={S.ok}>{result}</p>}
      {error && <p style={S.err}>{error}</p>}
    </div>
  );
}

const S: Record<string, CSSProperties> = {
  link: { border: 0, background: "none", padding: 0, marginTop: 6, fontFamily: "inherit", fontSize: 11.5, fontWeight: 600, color: T.laurel, cursor: "pointer", textDecoration: "underline" },
  box: { marginTop: 8, borderTop: `1px dashed ${T.line}`, paddingTop: 8 },
  ta: { width: "100%", boxSizing: "border-box", fontFamily: T.serif, fontSize: 13, lineHeight: 1.6, border: `1px solid ${T.line}`, background: "rgba(255,255,255,0.07)", color: T.ink, borderRadius: 10, padding: "8px 10px", resize: "vertical", marginBottom: 8 },
  primary: { fontFamily: "inherit", fontSize: 12, fontWeight: 600, padding: "7px 14px", borderRadius: 999, border: 0, background: T.pillBg, color: T.pillInk, cursor: "pointer" },
  ghost: { fontFamily: "inherit", fontSize: 12, fontWeight: 600, padding: "7px 13px", borderRadius: 999, border: `1px solid ${T.lineStrong}`, background: "transparent", color: T.ink, cursor: "pointer" },
  ok: { color: T.good, fontSize: 12, marginTop: 8 },
  err: { color: T.bad, fontSize: 12, marginTop: 8 },
};
