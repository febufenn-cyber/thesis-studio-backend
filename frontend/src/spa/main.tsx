import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { queryClient } from "./queryClient";
import {
  ApiKeysView,
  AuthGate,
  HomeView,
  IdentityView,
  InstitutionView,
  SupervisorDeskView,
  ProjectBibliography,
  ProjectDeposit,
  ProjectExport,
  ProjectImport,
  ProjectLibrary,
  ProjectSettings,
  ProjectSupervision,
  ProjectTrust,
  ProjectWriting,
} from "./views";

/**
 * SPA entry (FRONTEND_LLD Phase B). Familiar sidebar workspace; every shipped
 * capability has a route. Served at /app; deep links resolve via the FastAPI
 * catch-all.
 */
const router = createBrowserRouter(
  [
    { path: "/", element: <HomeView /> },
    { path: "/identity", element: <IdentityView /> },
    { path: "/keys", element: <ApiKeysView /> },
    { path: "/supervise", element: <SupervisorDeskView /> },
    { path: "/institution", element: <InstitutionView /> },
    { path: "/projects/:projectId", element: <Navigate to="library" replace /> },
    { path: "/projects/:projectId/library", element: <ProjectLibrary /> },
    { path: "/projects/:projectId/import", element: <ProjectImport /> },
    { path: "/projects/:projectId/bibliography", element: <ProjectBibliography /> },
    { path: "/projects/:projectId/export", element: <ProjectExport /> },
    { path: "/projects/:projectId/deposit", element: <ProjectDeposit /> },
    { path: "/projects/:projectId/writing", element: <ProjectWriting /> },
    { path: "/projects/:projectId/trust", element: <ProjectTrust /> },
    { path: "/projects/:projectId/supervision", element: <ProjectSupervision /> },
    { path: "/projects/:projectId/settings", element: <ProjectSettings /> },
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
