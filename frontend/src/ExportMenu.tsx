"use client";

import { useState } from "react";
import type { CSSProperties } from "react";
import { downloadConverted, exportPandoc, useInteropFormats } from "./useEnterprise";
import { downloadText, fetchInterchange, type InterchangeKind } from "./useFeatures";

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

  return (
    <div style={S.wrap}>
      {available ? (
        <>
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
        </>
      ) : (
        <p style={S.muted}>
          Document conversion isn’t enabled on this deployment. Ask an admin to install pandoc.
          Scholarly formats below still work.
        </p>
      )}
      <InterchangeRow projectId={projectId} />
    </div>
  );
}

/** JATS / LaTeX / CSL-JSON — publisher interchange, rendered server-side (3.5). */
function InterchangeRow({ projectId }: { projectId: string }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const KINDS: { kind: InterchangeKind; label: string; file: string }[] = [
    { kind: "jats", label: "JATS XML", file: "manuscript.jats.xml" },
    { kind: "latex", label: "LaTeX", file: "manuscript.tex" },
    { kind: "csl", label: "CSL-JSON", file: "references.csl.json" },
  ];
  async function grab(kind: InterchangeKind, file: string) {
    setBusy(kind); setError(null);
    try {
      downloadText(file, await fetchInterchange(projectId, kind));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally { setBusy(null); }
  }
  return (
    <div style={{ marginTop: 14 }}>
      <div style={S.subHead}>Scholarly interchange</div>
      <div style={S.rowWrap}>
        {KINDS.map((k) => (
          <button key={k.kind} style={S.btnGhost} disabled={busy === k.kind} onClick={() => grab(k.kind, k.file)}>
            {busy === k.kind ? "Rendering…" : `↓ ${k.label}`}
          </button>
        ))}
      </div>
      {error && <p style={S.err}>{error}</p>}
      <p style={S.hint}>JATS for publisher submission, LaTeX for Overleaf, CSL-JSON for Zotero and citeproc.</p>
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
  subHead: { fontSize: 11, fontWeight: 700, color: "#6b7688", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 8 },
  rowWrap: { display: "flex", gap: 8, flexWrap: "wrap" },
  btnGhost: { padding: "7px 12px", borderRadius: 8, border: "1px solid #e7e3db", background: "#fff", color: "#1b2733", fontWeight: 600, fontSize: 12.5, cursor: "pointer" },
};
