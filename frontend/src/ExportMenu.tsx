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
      <SubmissionPackCard projectId={projectId} />
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

/**
 * SubmissionPackCard — THE deliverable: one click, one zip (thesis PDF +
 * integrity report + AI-use statement + quote verification + provenance log,
 * with a checksummed manifest). Review packs say so honestly.
 */
function SubmissionPackCard({ projectId }: { projectId: string }) {
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function download() {
    setBusy(true); setError(null); setState(null);
    try {
      const res = await fetch(`/projects/${projectId}/submission-pack`, {
        method: "POST", credentials: "include",
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { const b = (await res.json()) as { detail?: string }; if (b?.detail) detail = b.detail; } catch { /* */ }
        throw new Error(detail);
      }
      const packState = res.headers.get("X-Pack-State");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `submission-pack-${packState ?? "draft"}.zip`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      setState(packState);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pack failed");
    } finally { setBusy(false); }
  }

  return (
    <div style={S.packCard}>
      <div>
        <div style={S.packTitle}>Submission Pack</div>
        <div style={S.packDesc}>
          Thesis PDF · integrity report · AI-use statement · quote verification ·
          provenance log — one zip with a checksummed manifest.
        </div>
      </div>
      <button style={S.packBtn} onClick={download} disabled={busy}>
        {busy ? "Building…" : "⬇ Download pack"}
      </button>
      {state === "review" && (
        <p style={S.packNote}>
          Review pack: open items remain visibly marked [UNVERIFIED]. Resolve the
          Integrity blockers to produce a final pack.
        </p>
      )}
      {state === "final" && <p style={S.packOk}>Final pack downloaded.</p>}
      {error && <p style={S.err}>{error}</p>}
    </div>
  );
}

const S: Record<string, CSSProperties> = {
  packCard: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12, border: "1px solid #A5B8FF", background: "rgba(165,184,255,0.16)", borderRadius: 12, padding: "14px 15px", marginBottom: 16 },
  packTitle: { fontSize: 14.5, fontWeight: 800, color: "#A5B8FF" },
  packDesc: { fontSize: 12, color: "rgba(255,255,255,0.96)", marginTop: 3, maxWidth: 420, lineHeight: 1.5 },
  packBtn: { marginLeft: "auto", padding: "10px 16px", borderRadius: 10, border: "1px solid #A5B8FF", background: "#A5B8FF", color: "#fff", fontWeight: 700, fontSize: 13, cursor: "pointer", whiteSpace: "nowrap" },
  packNote: { width: "100%", fontSize: 11.5, color: "#FFC46E", margin: 0 },
  packOk: { width: "100%", fontSize: 11.5, color: "#7DE8A8", fontWeight: 600, margin: 0 },
  wrap: { fontFamily: "'Inter', system-ui, sans-serif", color: "rgba(255,255,255,0.96)" },
  row: { display: "flex", gap: 8 },
  select: { flex: 1, fontFamily: "inherit", fontSize: 12.5, border: "1px solid rgba(255,255,255,0.13)", background: "rgba(255,255,255,0.07)", borderRadius: 7, padding: "8px" },
  btn: { padding: "8px 14px", borderRadius: 8, border: "1px solid #A5B8FF", background: "#A5B8FF", color: "#fff", fontWeight: 600, fontSize: 12.5, cursor: "pointer", whiteSpace: "nowrap" },
  hint: { fontSize: 11, color: "rgba(255,255,255,0.55)", marginTop: 8 },
  muted: { color: "rgba(255,255,255,0.55)", fontSize: 12.5 },
  err: { color: "#FF7A76", fontSize: 12.5, marginTop: 8 },
  subHead: { fontSize: 11, fontWeight: 700, color: "rgba(255,255,255,0.55)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 8 },
  rowWrap: { display: "flex", gap: 8, flexWrap: "wrap" },
  btnGhost: { padding: "7px 12px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.13)", background: "rgba(255,255,255,0.07)", color: "rgba(255,255,255,0.96)", fontWeight: 600, fontSize: 12.5, cursor: "pointer" },
};
