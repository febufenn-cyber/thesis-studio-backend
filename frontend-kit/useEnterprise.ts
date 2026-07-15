"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "./api";

/**
 * Hooks + actions for the enterprise feature set (E1–E7), mirroring the FastAPI
 * endpoints. Every one is advisory / fail-closed server-side: an unavailable or
 * disabled feature returns an explicit "unavailable" shape, never a fabricated
 * positive. UI must render "resolved"/"scored" as advisory, never as verified.
 */

/* ================= shared async hook ================= */

interface Async<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

function useResource<T>(path: string | null): Async<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(path != null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (path == null) return;
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiGet<T>(path, controller.signal)
      .then((d) => !cancelled && setData(d))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : "Request failed"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [path, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, loading, error, reload };
}

/* ================= E1 · Source & Journal Trust ================= */

export interface SourceTrust {
  verdict: "reputable" | "caution" | "unknown" | string;
  reasons: string[];
  is_in_doaj: boolean | null;
  is_open_access: boolean | null;
  h_index: number | null;
  cited_by_count: number | null;
  retracted: boolean;
  advisory: boolean;
}

export const useSourceTrust = (projectId: string, sourceId: string | null) =>
  useResource<SourceTrust>(sourceId ? `/projects/${projectId}/sources/${sourceId}/trust` : null);

/* ================= E2 · Verified identity ================= */

export interface Organization {
  name: string;
  ror: string;
  country: string | null;
  city: string | null;
}
export interface OrcidIdentity {
  orcid: string;
  name: string;
}

export const lookupOrganizations = (q: string) =>
  apiGet<{ organizations: Organization[] }>(`/identity/organizations?q=${encodeURIComponent(q)}`);

export const lookupOrcid = (orcid: string) =>
  apiGet<OrcidIdentity>(`/identity/orcid/${encodeURIComponent(orcid)}`);

/* ================= E3 · Research copilot ================= */

export interface PaperInsight {
  advisory: boolean;
  found: boolean;
  tldr: string | null;
  citation_count: number | null;
  references: { title: string; doi: string | null }[];
  citations: { title: string; doi: string | null }[];
}

export const useInsight = (projectId: string, sourceId: string | null) =>
  useResource<PaperInsight>(sourceId ? `/projects/${projectId}/sources/${sourceId}/insight` : null);

/* ================= E4 · Auto quote-verify ================= */

export interface AutoVerifyResult {
  quote_id: string;
  status: string; // verified | drift | unverifiable | ...
  score: number | null;
  matched_locator: string | null;
  advisory: boolean;
  fulltext_provider: string | null;
}

export const verifyQuoteAuto = (projectId: string, quoteId: string) =>
  apiPost<AutoVerifyResult>(`/projects/${projectId}/quotes/${quoteId}/verify-auto`, {});

/* ================= E5 · CSL bibliography ================= */

export interface BibliographyStyles {
  bundled: string;
  aliases: string[];
  note: string;
}
export interface RenderedBibliography {
  style: string;
  requested_style: string;
  output: "html" | "text";
  count: number;
  entries: string[];
}

export const useBibliographyStyles = () => useResource<BibliographyStyles>(`/bibliography/styles`);

export const renderBibliography = (projectId: string, style: string, output: "html" | "text" = "html") =>
  apiPost<RenderedBibliography>(`/projects/${projectId}/bibliography/render`, { style, output });

/* ================= E6 · Pandoc interop ================= */

export interface InteropFormats {
  available: boolean;
  input_formats: string[];
  output_formats: string[];
  binary_outputs: string[];
}
export interface Converted {
  format?: string;
  from?: string;
  to?: string;
  encoding: "utf-8" | "base64";
  content: string;
}

export const useInteropFormats = () => useResource<InteropFormats>(`/interop/formats`);

export const exportPandoc = (projectId: string, to: string) =>
  apiPost<Converted & { format: string }>(`/projects/${projectId}/export/pandoc`, { to });

/** Trigger a browser download for a converted (possibly binary) payload. */
export function downloadConverted(payload: Converted, filename: string): void {
  const href =
    payload.encoding === "base64"
      ? `data:application/octet-stream;base64,${payload.content}`
      : `data:text/plain;charset=utf-8,${encodeURIComponent(payload.content)}`;
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* ================= E7 · Private writing polish ================= */

export interface WritingStatus {
  enabled: boolean;
  configured: boolean;
  language: string;
}
export interface WritingMatch {
  message: string;
  short_message: string;
  offset: number;
  length: number;
  replacements: string[];
  rule_id: string;
  category: string;
  issue_type: string;
}
export interface WritingResult {
  advisory: boolean;
  available: boolean;
  language: string;
  matches: WritingMatch[];
  truncated: boolean;
}

export const useWritingStatus = () => useResource<WritingStatus>(`/writing/status`);

export const checkWriting = (projectId: string, text: string, language?: string) =>
  apiPost<WritingResult>(`/projects/${projectId}/writing/check`, { text, language });
