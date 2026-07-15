"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "./api";

/* ---------- response types (mirror the FastAPI endpoints) ---------- */

export interface ProvenanceRollup {
  origin_counts: Record<string, number>;
  total_blocks: number;
  ai_block_count: number;
  assisted: boolean;
  accepted_proposals: number;
  accepted_operations: number;
  human_edited_operations: number;
  models: string[];
}

export interface ProvenanceSummary {
  document_version: number;
  rollup: ProvenanceRollup;
  templates: { key: string; label: string; policy_ref: string }[];
}

export interface AIUseStatement {
  id: string;
  template_key: string;
  body_text: string;
  content_hash: string;
  document_version: number;
  document_checksum: string;
}

export interface QuoteResult {
  quote_id: string;
  kind: string;
  status: string;
  score: number | null;
  matched_locator: string | null;
  advisory: boolean;
}

export interface QuoteReport {
  advisory: boolean;
  counts: Record<string, number>;
  results: QuoteResult[];
}

export interface Finding {
  validator: string;
  severity: "block" | "warn" | "info";
  code: string;
  message: string;
  locator: Record<string, unknown>;
}

export interface Compliance {
  profile: string | null;
  enforced: boolean;
  ready: boolean;
  page_limit?: number | null;
  findings: Finding[];
  checklist: string[];
}

export interface IntegrityReport {
  document_version: number;
  document_checksum: string;
  assertion: string;
  ai_provenance: ProvenanceRollup;
  references: { counts: Record<string, number>; ready: boolean };
  quote_verification: { checked: number; counts: Record<string, number>; ready: boolean };
  open_markers: { total: number; kinds: Record<string, number>; ready: boolean };
  ready: boolean;
}

export interface Candidate {
  title: string;
  authors: string[];
  year: number | null;
  container: string | null;
  doi: string | null;
  identifier: string;
  authority: string;
  score: number;
}

/* ---------- generic fetch-on-mount hook ---------- */

interface Async<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

function useResource<T>(path: string): Async<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiGet<T>(path, controller.signal)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Request failed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [path, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, loading, error, reload };
}

/* ---------- feature hooks ---------- */

export const useProvenance = (projectId: string) =>
  useResource<ProvenanceSummary>(`/projects/${projectId}/provenance/summary`);

export const useCompliance = (projectId: string) =>
  useResource<Compliance>(`/projects/${projectId}/compliance`);

export const useQuoteReport = (projectId: string) =>
  useResource<QuoteReport>(`/projects/${projectId}/quote-verification/report`);

export const useIntegrityReport = (projectId: string) =>
  useResource<IntegrityReport>(`/projects/${projectId}/integrity-report`);

/* ---------- actions ---------- */

export function generateAIUseStatement(projectId: string, templateKey: string) {
  return apiPost<AIUseStatement>(`/projects/${projectId}/ai-use-statement`, {
    template_key: templateKey,
  });
}

export interface ResolveResult {
  source_id: string;
  applied_fields: string[];
  resolution_status: string | null;
  retraction_status: string | null;
  still_missing: string[];
}

export function resolveSource(projectId: string, sourceId: string, minConfidence = 0.75) {
  return apiPost<ResolveResult>(`/projects/${projectId}/sources/${sourceId}/resolve`, {
    min_confidence: minConfidence,
  });
}

export function discoverSearch(projectId: string, query: string, limit = 10) {
  const q = encodeURIComponent(query);
  return apiGet<{ candidates: Candidate[] }>(
    `/projects/${projectId}/references/search?q=${q}&limit=${limit}`,
  );
}

export function addDiscoveredSource(projectId: string, identifier: string) {
  return apiPost<ResolveResult>(`/projects/${projectId}/references/search/add`, {
    identifier,
  });
}
