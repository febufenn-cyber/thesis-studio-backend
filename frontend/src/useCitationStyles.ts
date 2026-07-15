import { useEffect, useState } from "react";

export type CitationMechanism = "author_page" | "author_date" | "numbered";

export interface CitationStyle {
  key: string;
  edition: string;
  mechanism: CitationMechanism;
}

export interface CitationStylesResponse {
  styles: CitationStyle[];
  default: string;
}

export interface UseCitationStylesResult {
  styles: CitationStyle[];
  default: string | null;
  loading: boolean;
  error: string | null;
}

/**
 * Fetches the available citation styles from GET /citation-styles once on mount.
 * Cookie-authenticated (credentials: "include").
 */
export function useCitationStyles(): UseCitationStylesResult {
  const [styles, setStyles] = useState<CitationStyle[]>([]);
  const [defaultKey, setDefaultKey] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch("/citation-styles", {
          method: "GET",
          credentials: "include",
          headers: { Accept: "application/json" },
          signal: controller.signal,
        });
        if (!res.ok) {
          throw new Error(`Failed to load citation styles (HTTP ${res.status})`);
        }
        const data: CitationStylesResponse = await res.json();
        if (cancelled) return;
        setStyles(Array.isArray(data.styles) ? data.styles : []);
        setDefaultKey(data.default ?? null);
      } catch (err) {
        if (cancelled || (err as Error).name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  return { styles, default: defaultKey, loading, error };
}
