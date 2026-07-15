import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../api";

/**
 * Shell-level server-state hooks via TanStack Query (ADR-2). Project-scoped
 * feature data still flows through the kit's own hooks for now; those migrate to
 * Query incrementally. These establish the pattern at the shell.
 */

export interface Me {
  id: string;
  email: string;
  name?: string | null;
}

export interface ProjectSummary {
  id: string;
  title: string;
  document_type?: string | null;
  updated_at?: string | null;
}

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => apiGet<Me>("/me"),
    retry: false, // a 401 must surface immediately as "signed out", not retry
  });
}

export function useProjects(enabled: boolean) {
  return useQuery({
    queryKey: ["projects"],
    queryFn: () => apiGet<ProjectSummary[]>("/projects"),
    enabled,
  });
}
