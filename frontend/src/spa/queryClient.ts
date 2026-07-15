import { QueryClient } from "@tanstack/react-query";

/**
 * Server-state cache (FRONTEND_LLD ADR-2). Configured fail-closed: bounded
 * retries, and stale-but-cached data is refetched rather than trusted as fresh.
 * This replaces the vanilla app's hand-synced global mutable state.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
});
