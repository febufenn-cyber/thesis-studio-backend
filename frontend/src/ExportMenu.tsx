"use client";

import { useState } from "react";
import type { CSSProperties } from "react";
import { downloadConverted, exportPandoc, useInteropFormats } from "./useEnterprise";

/**
 * ExportMenu — E6 pandoc export. Convert the rendered manuscript to any
 * allow-listed format and download it. Falls back gracefully: when pandoc is not
 * available on the deployment the menu is disabled with an explanation, never a
 * broken button.
 */
const EXT: Record<string, string> = {
  docx: "docx", odt: "odt", epub: "epub", rtf: "rtf", latex: "tex",
  html: "html", rst: "rst", markdown: "md", gfm: "md", org: "org",
  plain: "txt", asciidoc: "adoc", mediawiki: "wiki", textile: "textile",
  jats: "xml", docbook: "xml", commonmark: "md",
};

export function ExportMenu({ projectId }: { projectId: string }) {
  const formats = useInteropFormats();
  const [to, setTo] = useState("odt");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const available = formats.data?.available ?? false;

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const payload = await exportPandoc(projectId, to);
      downloadConverted(payload, `manuscript.${EXT[to] ?? to}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setBusy(false);
    }
  }

  if (formats.loading) return <p style={S.muted}>Loading formats…</p>;
  if (!available) {
    return (
      <p style={S.muted}>
        Document conversion isn’t enabled on this deployment. Ask an admin to install pandoc.
      </p>
    );
  }

  return (
    <div style={S.wrap}>
      <div style={S.row}>
        <select style={S.select} value={to} onChange={(e) => setTo(e.target.value)}>
          {formats.data?.output_formats.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
        <button style={S.btn} onClick={run} disabled={busy}>
          {busy ? "Converting…" : "Export & download"}
        </button>
      </div>
      {error && <p style={S.err}>{error}</p>}
      <p style={S.hint}>Rendered from the manuscript, then converted with pandoc.</p>
    </div>
  );
}

const S: Record<string, CSSProperties> = {
  wrap: { fontFamily: "Inter, system-ui, sans-serif", color: "#1b2733" },
  row: { display: "flex", gap: 8 },
  select: { flex: 1, fontFamily: "inherit", fontSize: 12.5, border: "1px solid #e7e3db", background: "#fff", borderRadius: 7, padding: "8px" },
  btn: { padding: "8px 14px", borderRadius: 8, border: "1px solid #4b4bd6", background: "#4b4bd6", color: "#fff", fontWeight: 600, fontSize: 12.5, cursor: "pointer", whiteSpace: "nowrap" },
  hint: { fontSize: 11, color: "#6b7688", marginTop: 8 },
  muted: { color: "#6b7688", fontSize: 12.5 },
  err: { color: "#d64545", fontSize: 12.5, marginTop: 8 },
};
