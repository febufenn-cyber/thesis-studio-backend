"use client";

import { apiGet, apiPost } from "./api";

/**
 * Hooks/actions for the previously UI-less features: reference import (BibTeX/
 * RIS/CSL + Zotero, MF5), interchange exports (JATS/LaTeX/CSL, 3.5), batch
 * resolve (3.2), deposits + ORCID (MF3), API keys (MF6), locales (3.7),
 * research consent (3.8), committee + semantic diff (3.6). All owner-guarded
 * and fail-closed server-side; the UI mirrors errors honestly.
 */

async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(path, {
    method: "DELETE",
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch { /* non-JSON */ }
    throw new Error(detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "PATCH",
    credentials: "include",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const b = (await res.json()) as { detail?: string };
      if (b?.detail) detail = b.detail;
    } catch { /* non-JSON */ }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

/* ============ reference import (BibTeX / RIS / CSL-JSON) ============ */

export interface ImportResult {
  imported: number;
  kinds: Record<string, number>;
}

export const importReferences = (
  projectId: string,
  format: "bibtex" | "ris" | "csl",
  content: string,
) => apiPost<ImportResult>(`/projects/${projectId}/references/import`, { format, content });

export interface ZoteroImportRequest {
  api_key: string;
  library_id: string;
  library_type: "user" | "group";
}

export const importZotero = (projectId: string, body: ZoteroImportRequest) =>
  apiPost<ImportResult>(`/projects/${projectId}/references/zotero/import`, body);

/* ============ batch resolve ============ */

export interface BatchResolveResult {
  resolved: number;
  unresolved: number;
  results: { query?: string; status: string }[];
}

export const resolveBatch = (projectId: string, queries: string[]) =>
  apiPost<BatchResolveResult>(`/projects/${projectId}/references/resolve-batch`, { queries });

/* ============ interchange exports (JATS / LaTeX / CSL-JSON) ============ */

export type InterchangeKind = "jats" | "latex" | "csl";

export async function fetchInterchange(projectId: string, kind: InterchangeKind): Promise<string> {
  const data = await apiGet<{ content?: string; items?: unknown }>(
    `/projects/${projectId}/export/${kind}`,
  );
  return kind === "csl" ? JSON.stringify(data.items ?? [], null, 2) : (data.content ?? "");
}

/* ============ exports list + deposits + ORCID (MF3) ============ */

export interface ExportRow {
  id: string;
  format: string;
  status: string;
  created_at: string;
}

export const listExports = (projectId: string) =>
  apiGet<ExportRow[]>(`/projects/${projectId}/exports`);

export interface Deposit {
  id: string;
  target: string;
  status: string;
  doi: string | null;
  landing_url: string | null;
  error_message: string | null;
  sandbox: boolean;
}

export const listDeposits = (projectId: string) =>
  apiGet<{ deposits: Deposit[] }>(`/projects/${projectId}/deposits`);

export const createDeposit = (projectId: string, exportId: string) =>
  apiPost<Deposit>(`/projects/${projectId}/deposits`, { export_id: exportId, target: "zenodo" });

export const connectOrcid = (orcid: string) =>
  apiPost<{ orcid: string; verified: boolean }>(`/orcid`, { orcid });

export const disconnectOrcid = () => apiDelete<{ orcid: null }>(`/orcid`);

/* ============ API keys (MF6) ============ */

export interface ApiKeyRow {
  id: string;
  prefix: string;
  label: string;
  scopes: string[];
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string | null;
  key?: string; // present only in the create response, once
}

export const listApiKeys = () => apiGet<{ keys: ApiKeyRow[] } | ApiKeyRow[]>(`/api-keys`);
export const createApiKey = (label: string, scopes: string[]) =>
  apiPost<ApiKeyRow>(`/api-keys`, { label, scopes });
export const revokeApiKey = (id: string) => apiDelete<unknown>(`/api-keys/${id}`);

/* ============ locales (3.7) ============ */

export interface LocaleInfo {
  key?: string;
  code?: string;
  label?: string;
  name?: string;
  [k: string]: unknown;
}

export const listLocales = () => apiGet<Record<string, unknown>>(`/locales`);
export const patchProjectLocale = (projectId: string, locale: string) =>
  apiPatch<Record<string, unknown>>(`/projects/${projectId}/locale`, { locale });

/* ============ research consent (3.8) ============ */

export const getResearchConsent = () => apiGet<Record<string, unknown>>(`/research/consent`);
export const grantResearchConsent = (scope: string) =>
  apiPost<Record<string, unknown>>(`/research/consent`, { scope });
export const revokeResearchConsent = (scope: string) =>
  apiDelete<Record<string, unknown>>(`/research/consent/${encodeURIComponent(scope)}`);

/* ============ supervision: committee + semantic diff (3.6) ============ */

export interface CommitteeMember {
  user_id: string;
  committee_role: string;
  voting: boolean;
  content_access: boolean;
  position: number;
  [k: string]: unknown;
}

export const getCommittee = (projectId: string) =>
  apiGet<{ committee?: CommitteeMember[]; members?: CommitteeMember[] } | CommitteeMember[]>(
    `/projects/${projectId}/committee`,
  );

export const runSemanticDiff = (projectId: string, baseDocument: unknown) =>
  apiPost<Record<string, unknown>>(`/projects/${projectId}/diff`, { base_document: baseDocument });

/* ============ tiny download helper ============ */

export function downloadText(filename: string, text: string): void {
  const a = document.createElement("a");
  a.href = `data:text/plain;charset=utf-8,${encodeURIComponent(text)}`;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
