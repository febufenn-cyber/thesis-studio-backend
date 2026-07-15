"use client";

import { useState } from "react";
import type { CSSProperties } from "react";
import { renderBibliography, useBibliographyStyles, type RenderedBibliography } from "./useEnterprise";

/**
 * BibliographyPanel — E5 CSL rendering. Pick a style (friendly alias or any CSL
 * repo id) and render the project's registry sources in it via citeproc. A
 * formatter, not a fact source: it renders only registered fields. An
 * unresolvable style surfaces the server's 422 message rather than a substitute.
 */
export function BibliographyPanel({ projectId }: { projectId: string }) {
  const styles = useBibliographyStyles();
  const [style, setStyle] = useState("harvard1");
  const [custom, setCustom] = useState("");
  const [output, setOutput] = useState<"html" | "text">("html");
  const [result, setResult] = useState<RenderedBibliography | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function render() {
    const chosen = custom.trim() || style;
    setBusy(true);
    setError(null);
    try {
      setResult(await renderBibliography(projectId, chosen, output));
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : "Render failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={S.wrap}>
      <div style={S.row}>
        <select style={S.select} value={style} onChange={(e) => setStyle(e.target.value)}>
          <option value="harvard1">harvard1 (offline)</option>
          {styles.data?.aliases.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <select style={S.select} value={output} onChange={(e) => setOutput(e.target.value as "html" | "text")}>
          <option value="html">HTML</option>
          <option value="text">Plain text</option>
        </select>
      </div>
      <input
        style={S.input}
        placeholder="…or any CSL style id, e.g. american-political-science-association"
        value={custom}
        onChange={(e) => setCustom(e.target.value)}
      />
      <button style={S.btn} onClick={render} disabled={busy}>
        {busy ? "Rendering…" : "Render bibliography"}
      </button>

      {error && <p style={S.err}>{error}</p>}
      {result && (
        <div style={S.out}>
          <div style={S.outHead}>
            {result.count} entr{result.count === 1 ? "y" : "ies"} · {result.style}
          </div>
          <ol style={S.list}>
            {result.entries.map((e, i) =>
              result.output === "html" ? (
                <li key={i} style={S.entry} dangerouslySetInnerHTML={{ __html: e }} />
              ) : (
                <li key={i} style={S.entry}>
                  {e}
                </li>
              ),
            )}
          </ol>
        </div>
      )}
    </div>
  );
}

const S: Record<string, CSSProperties> = {
  wrap: { fontFamily: "Inter, system-ui, sans-serif", color: "#1b2733" },
  row: { display: "flex", gap: 8, marginBottom: 8 },
  select: { flex: 1, fontFamily: "inherit", fontSize: 12.5, border: "1px solid #e7e3db", background: "#fff", borderRadius: 7, padding: "7px 8px" },
  input: { width: "100%", boxSizing: "border-box", fontFamily: "inherit", fontSize: 12.5, border: "1px solid #e7e3db", borderRadius: 7, padding: "7px 9px", marginBottom: 8 },
  btn: { display: "inline-flex", alignItems: "center", gap: 6, padding: "8px 13px", borderRadius: 9, border: "1px solid #4b4bd6", background: "#4b4bd6", color: "#fff", fontWeight: 600, fontSize: 12.5, cursor: "pointer" },
  err: { color: "#d64545", fontSize: 12.5, marginTop: 9 },
  out: { marginTop: 12, border: "1px solid #e7e3db", borderRadius: 11, padding: "12px 14px" },
  outHead: { fontSize: 11, color: "#6b7688", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 8 },
  list: { margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 9 },
  entry: { fontSize: 13, lineHeight: 1.55 },
};
