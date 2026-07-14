"use client";

import { useCallback, useState } from "react";
import { CitationStylePicker } from "./CitationStylePicker";

export interface ReferencesPanelProps {
  /** Project id used to build the .bib endpoint URL. */
  projectId: string;
  /** Current citation style key for this project. */
  styleKey: string;
  /** Persists a style change (parent wires this to the metadata command). */
  onStyleChange: (newKey: string) => Promise<void>;
}

export function ReferencesPanel({
  projectId,
  styleKey,
  onStyleChange,
}: ReferencesPanelProps) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);

  const fetchBib = useCallback(async (): Promise<string> => {
    const res = await fetch(
      `/projects/${encodeURIComponent(projectId)}/references.bib`,
      {
        method: "GET",
        credentials: "include",
        headers: { Accept: "text/x-bibtex, text/plain" },
      }
    );
    if (!res.ok) {
      throw new Error(`Failed to fetch references (HTTP ${res.status})`);
    }
    return res.text();
  }, [projectId]);

  const handleDownload = useCallback(async () => {
    setDownloading(true);
    setError(null);
    try {
      const text = await fetchBib();
      setPreview(text);

      const blob = new Blob([text], { type: "text/x-bibtex" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${projectId}-references.bib`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed");
    } finally {
      setDownloading(false);
    }
  }, [fetchBib, projectId]);

  const handlePreview = useCallback(async () => {
    setError(null);
    try {
      setPreview(await fetchBib());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load preview");
    }
  }, [fetchBib]);

  return (
    <section
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        padding: 16,
        border: "1px solid #e0e0e0",
        borderRadius: 8,
        maxWidth: 720,
      }}
    >
      <h2 style={{ margin: 0, fontSize: 18 }}>References</h2>

      <CitationStylePicker
        value={styleKey}
        onChange={onStyleChange}
        disabled={downloading}
      />

      <div style={{ display: "flex", gap: 8 }}>
        <button
          type="button"
          onClick={handleDownload}
          disabled={downloading}
          style={{
            fontSize: 14,
            padding: "6px 12px",
            borderRadius: 6,
            border: "1px solid #ccc",
            cursor: downloading ? "default" : "pointer",
            opacity: downloading ? 0.6 : 1,
          }}
        >
          {downloading ? "Preparing…" : "Download .bib"}
        </button>
        <button
          type="button"
          onClick={handlePreview}
          disabled={downloading}
          style={{
            fontSize: 14,
            padding: "6px 12px",
            borderRadius: 6,
            border: "1px solid #ccc",
            background: "transparent",
            cursor: downloading ? "default" : "pointer",
          }}
        >
          Refresh preview
        </button>
      </div>

      {error && (
        <p style={{ margin: 0, fontSize: 13, color: "#b00020" }}>{error}</p>
      )}

      {preview !== null && (
        <pre
          style={{
            margin: 0,
            maxHeight: 240,
            overflow: "auto",
            padding: 12,
            background: "#f6f8fa",
            border: "1px solid #e0e0e0",
            borderRadius: 6,
            fontSize: 12,
            fontFamily:
              "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {preview.trim().length > 0
            ? preview
            : "(registry is empty — no references yet)"}
        </pre>
      )}
    </section>
  );
}
