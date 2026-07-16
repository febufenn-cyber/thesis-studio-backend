"use client";

import { useState } from "react";
import type { CSSProperties } from "react";
import { importReferences, importZotero, resolveBatch, type ImportResult } from "./useFeatures";

/**
 * ImportPanel — bring references in: paste BibTeX / RIS / CSL-JSON, or pull a
 * Zotero library (MF5). Imports create UNVERIFIED registry sources — the panel
 * says so plainly and offers an advisory batch-resolve pass afterwards (3.2).
 */
export function ImportPanel({ projectId }: { projectId: string }) {
  const [mode, setMode] = useState<"paste" | "zotero">("paste");
  return (
    <div style={S.wrap}>
      <div style={S.tabs}>
        <button style={tab(mode === "paste")} onClick={() => setMode("paste")}>Paste BibTeX / RIS / CSL</button>
        <button style={tab(mode === "zotero")} onClick={() => setMode("zotero")}>Zotero library</button>
      </div>
      {mode === "paste" ? <PasteImport projectId={projectId} /> : <ZoteroImport projectId={projectId} />}
      <p style={S.note}>
        Imported entries join the registry as <strong>unverified</strong> sources — verification
        stays a human decision.
      </p>
    </div>
  );
}

function ResultLine({ r }: { r: ImportResult }) {
  const kinds = Object.entries(r.kinds).map(([k, n]) => `${n} ${k}`).join(", ");
  return (
    <p style={S.ok}>
      Imported {r.imported} source{r.imported === 1 ? "" : "s"}{kinds ? ` (${kinds})` : ""}.
    </p>
  );
}

function PasteImport({ projectId }: { projectId: string }) {
  const [format, setFormat] = useState<"bibtex" | "ris" | "csl">("bibtex");
  const [content, setContent] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true); setError(null); setResult(null);
    try {
      setResult(await importReferences(projectId, format, content));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    } finally { setBusy(false); }
  }

  return (
    <>
      <div style={S.row}>
        <select style={S.select} value={format} onChange={(e) => setFormat(e.target.value as typeof format)}>
          <option value="bibtex">BibTeX (.bib)</option>
          <option value="ris">RIS (.ris)</option>
          <option value="csl">CSL-JSON</option>
        </select>
      </div>
      <textarea
        style={S.area}
        rows={7}
        placeholder={format === "bibtex" ? "@article{key, title={...}, ...}" : format === "ris" ? "TY  - JOUR\nTI  - ..." : '[{"type":"article-journal","title":"..."}]'}
        value={content}
        onChange={(e) => setContent(e.target.value)}
      />
      <button style={S.btn} onClick={run} disabled={busy || !content.trim()}>
        {busy ? "Importing…" : "Import references"}
      </button>
      {result && <ResultLine r={result} />}
      {error && <p style={S.err}>{error}</p>}
    </>
  );
}

function ZoteroImport({ projectId }: { projectId: string }) {
  const [apiKey, setApiKey] = useState("");
  const [libraryId, setLibraryId] = useState("");
  const [libraryType, setLibraryType] = useState<"user" | "group">("user");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true); setError(null); setResult(null);
    try {
      setResult(await importZotero(projectId, { api_key: apiKey.trim(), library_id: libraryId.trim(), library_type: libraryType }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Zotero import failed");
    } finally { setBusy(false); }
  }

  return (
    <>
      <input style={S.input} placeholder="Zotero API key (zotero.org → Settings → Keys)" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
      <div style={S.row}>
        <input style={{ ...S.input, marginBottom: 0, flex: 1 }} placeholder="Library ID" value={libraryId} onChange={(e) => setLibraryId(e.target.value)} />
        <select style={S.select} value={libraryType} onChange={(e) => setLibraryType(e.target.value as "user" | "group")}>
          <option value="user">My library</option>
          <option value="group">Group library</option>
        </select>
      </div>
      <button style={S.btn} onClick={run} disabled={busy || !apiKey.trim() || !libraryId.trim()}>
        {busy ? "Importing from Zotero…" : "Import library"}
      </button>
      {result && <ResultLine r={result} />}
      {error && <p style={S.err}>{error}</p>}
      <p style={S.hint}>Your Zotero key is used for this import only and is never stored.</p>
    </>
  );
}

/** Advisory batch resolve, offered from the Library too. */
export function BatchResolveButton({ projectId, queries }: { projectId: string; queries: string[] }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  async function run() {
    setBusy(true); setMsg(null);
    try {
      const r = await resolveBatch(projectId, queries);
      setMsg(`${r.resolved} resolved, ${r.unresolved} unresolved (advisory — nothing marked verified).`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Resolve failed");
    } finally { setBusy(false); }
  }
  if (queries.length === 0) return null;
  return (
    <span>
      <button style={S.btnGhost} onClick={run} disabled={busy}>
        {busy ? "Resolving…" : `Resolve ${queries.length} against Crossref/OpenAlex`}
      </button>
      {msg && <span style={S.hint}> {msg}</span>}
    </span>
  );
}

const tab = (active: boolean): CSSProperties => ({
  flex: 1, padding: "8px 4px", border: 0,
  borderBottom: `2px solid ${active ? "#A5B8FF" : "transparent"}`,
  background: "transparent", color: active ? "#A5B8FF" : "rgba(255,255,255,0.55)",
  fontWeight: 600, fontSize: 12.5, cursor: "pointer",
});

const S: Record<string, CSSProperties> = {
  wrap: { fontFamily: "'Inter', system-ui, sans-serif", color: "rgba(255,255,255,0.96)" },
  tabs: { display: "flex", gap: 4, borderBottom: "1px solid rgba(255,255,255,0.13)", marginBottom: 12 },
  row: { display: "flex", gap: 8, marginBottom: 8 },
  select: { fontFamily: "inherit", fontSize: 12.5, border: "1px solid rgba(255,255,255,0.13)", background: "rgba(255,255,255,0.07)", borderRadius: 7, padding: "8px" },
  input: { width: "100%", boxSizing: "border-box", fontFamily: "inherit", fontSize: 13, border: "1px solid rgba(255,255,255,0.13)", borderRadius: 8, padding: "8px 10px", marginBottom: 8 },
  area: { width: "100%", boxSizing: "border-box", fontFamily: "'IBM Plex Mono', ui-monospace, monospace", fontSize: 12, lineHeight: 1.5, border: "1px solid rgba(255,255,255,0.13)", borderRadius: 9, padding: "10px 11px", resize: "vertical", marginBottom: 8 },
  btn: { padding: "8px 14px", borderRadius: 8, border: "1px solid #A5B8FF", background: "#A5B8FF", color: "#fff", fontWeight: 600, fontSize: 12.5, cursor: "pointer" },
  btnGhost: { padding: "6px 11px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.13)", background: "rgba(255,255,255,0.07)", color: "rgba(255,255,255,0.96)", fontWeight: 600, fontSize: 12, cursor: "pointer" },
  ok: { color: "#7DE8A8", fontSize: 12.5, fontWeight: 600, marginTop: 9 },
  err: { color: "#FF7A76", fontSize: 12.5, marginTop: 9 },
  note: { fontSize: 11.5, color: "rgba(255,255,255,0.55)", background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.13)", borderRadius: 8, padding: "7px 10px", marginTop: 14 },
  hint: { fontSize: 11, color: "rgba(255,255,255,0.55)" },
};
