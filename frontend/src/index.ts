/**
 * Acadensia frontend kit — production React drop-ins wired to the real API.
 *
 * Integrity surfaces (Phases 1–4, MF1/MF4): TrustPanel, StatusBadge.
 * Enterprise features (E1–E7): the components and hooks below.
 */

// Core / integrity
export { ApiError, apiGet, apiPost, v1 } from "./api";
export { StatusBadge, toStatus, type Status } from "./StatusBadge";
export { TrustPanel } from "./TrustPanel";

// Enterprise surfaces
export { EnterprisePanel } from "./EnterprisePanel";
export { SourceIntelligence } from "./SourceIntelligence";
export { AutoVerifyButton } from "./AutoVerifyButton";
export { BibliographyPanel } from "./BibliographyPanel";
export { IdentityLookup } from "./IdentityLookup";
export { ExportMenu } from "./ExportMenu";
export { WritingPanel } from "./WritingPanel";

// Hooks + actions
export * from "./useEnterprise";
