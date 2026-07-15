import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { queryClient } from "./queryClient";
import { AuthGate, HomeView, ProjectBibliography, ProjectExport, ProjectLibrary, ProjectTrust, ProjectWriting } from "./views";

/**
 * SPA entry (FRONTEND_LLD Phase B). React Router + TanStack Query. Served at
 * /app; the router basename matches so deep links like /app/projects/:id/library
 * resolve. Read-only surfaces first; authoring journeys port next.
 */
const router = createBrowserRouter(
  [
    { path: "/", element: <HomeView /> },
    { path: "/projects/:projectId", element: <Navigate to="library" replace /> },
    { path: "/projects/:projectId/library", element: <ProjectLibrary /> },
    { path: "/projects/:projectId/bibliography", element: <ProjectBibliography /> },
    { path: "/projects/:projectId/export", element: <ProjectExport /> },
    { path: "/projects/:projectId/writing", element: <ProjectWriting /> },
    { path: "/projects/:projectId/trust", element: <ProjectTrust /> },
    { path: "*", element: <Navigate to="/" replace /> },
  ],
  { basename: "/app" },
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthGate>
        <RouterProvider router={router} />
      </AuthGate>
    </QueryClientProvider>
  </StrictMode>,
);
