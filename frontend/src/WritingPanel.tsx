"use client";

import { useState } from "react";
import type { CSSProperties } from "react";
import { checkWriting, useWritingStatus, type WritingMatch } from "./useEnterprise";

/**
 * WritingPanel — E7 private writing polish (LanguageTool). Advisory grammar /
 * style suggestions with positions; the user applies them, nothing is rewritten
 * automatically. Disabled deployments show an honest notice, not a dead button.
 */
export function WritingPanel({ projectId }: { projectId: string }) {
  const status = useWritingStatus();
  const [text, setText] = useState("");
  const [matches, setMatches] = useState<WritingMatch[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enabled = status.data?.enabled && status.data?.configured;

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const r = await checkWriting(projectId, text);
      setMatches(r.available ? r.matches : []);
      if (!r.available) setError("The writing service is currently unreachable.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Check failed");
    } finally {
      setBusy(false);
    }
  }

  if (status.loading) return <p style={S.muted}>Loading…</p>;
  if (!enabled) {
    return (
      <p style={S.muted}>
        Private writing checks aren’t configured on this deployment. Set a
        LanguageTool server URL to enable grammar &amp; style suggestions.
      </p>
    );
  }

  return (
    <div style={S.wrap}>
      <textarea
        style={S.area}
        placeholder="Paste a paragraph to check…"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={5}
      />
      <div style={S.actions}>
        <button style={S.btn} onClick={run} disabled={busy || !text.trim()}>
          {busy ? "Checking…" : "Check writing"}
        </button>
        {matches && (
          <span style={S.count}>
            {matches.length === 0 ? "No issues found" : `${matches.length} suggestion${matches.length === 1 ? "" : "s"}`}
          </span>
        )}
      </div>
      {error && <p style={S.err}>{error}</p>}
      <div>
        {matches?.map((m, i) => (
          <div key={i} style={S.match}>
            <div style={S.matchHead}>
              <span style={S.cat}>{m.category || m.issue_type || "Style"}</span>
              {m.replacements.length > 0 && (
                <span style={S.fix}>→ {m.replacements.slice(0, 3).join(", ")}</span>
              )}
            </div>
            <div style={S.msg}>{m.message}</div>
            <div style={S.pos}>at character {m.offset}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

const S: Record<string, CSSProperties> = {
  wrap: { fontFamily: "'Source Sans 3', 'Inter', system-ui, sans-serif", color: "#1C1917" },
  area: { width: "100%", boxSizing: "border-box", fontFamily: "inherit", fontSize: 13, lineHeight: 1.5, border: "1px solid #DCD3C5", borderRadius: 9, padding: "10px 11px", resize: "vertical" },
  actions: { display: "flex", alignItems: "center", gap: 12, margin: "9px 0" },
  btn: { padding: "8px 14px", borderRadius: 8, border: "1px solid #1F4D3A", background: "#1F4D3A", color: "#fff", fontWeight: 600, fontSize: 12.5, cursor: "pointer" },
  count: { fontSize: 12, color: "#6E655A", fontWeight: 600 },
  match: { border: "1px solid #DCD3C5", borderRadius: 10, padding: "9px 11px", marginBottom: 8 },
  matchHead: { display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline", marginBottom: 3 },
  cat: { fontSize: 11, fontWeight: 700, color: "#9A6A00", textTransform: "uppercase", letterSpacing: 0.3 },
  fix: { fontSize: 12, color: "#1F7A4D", fontWeight: 600 },
  msg: { fontSize: 12.5, lineHeight: 1.45 },
  pos: { fontSize: 10.5, color: "#6E655A", fontFamily: "'IBM Plex Mono', ui-monospace, monospace", marginTop: 3 },
  muted: { color: "#6E655A", fontSize: 12.5, lineHeight: 1.5 },
  err: { color: "#B3362C", fontSize: 12.5, marginBottom: 8 },
};
