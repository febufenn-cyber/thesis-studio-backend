import { StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { EnterprisePanel } from "./EnterprisePanel";
import { TrustPanel } from "./TrustPanel";
import { SourceIntelligence } from "./SourceIntelligence";
import { AutoVerifyButton } from "./AutoVerifyButton";
import { FloatingGuide } from "./FloatingGuide";

/**
 * Island bridge (FRONTEND_LLD §19, Phase A).
 *
 * The served vanilla app (app/static/v2.html) loads this IIFE bundle and calls
 * window.AcadensiaKit.mount*() to render React components into its own DOM. This
 * makes the E1–E7 work reachable by real users today, and is the first
 * increment of the strangler-fig migration to a full SPA. Each mount returns a
 * handle; the host calls unmount() (or mount again on the same element) to
 * tear it down — roots are tracked per element so re-mounting is safe.
 */

const ROOTS = new WeakMap<Element, Root>();

function render(el: Element, node: React.ReactNode): void {
  let root = ROOTS.get(el);
  if (!root) {
    root = createRoot(el);
    ROOTS.set(el, root);
  }
  root.render(<StrictMode>{node}</StrictMode>);
}

export function mountEnterprise(el: Element, opts: { projectId: string }): void {
  render(el, <EnterprisePanel projectId={opts.projectId} />);
}

export function mountTrustPanel(el: Element, opts: { projectId: string }): void {
  render(el, <TrustPanel projectId={opts.projectId} />);
}

export function mountSourceIntelligence(
  el: Element,
  opts: { projectId: string; sourceId: string },
): void {
  render(el, <SourceIntelligence projectId={opts.projectId} sourceId={opts.sourceId} />);
}

export function mountAutoVerify(
  el: Element,
  opts: { projectId: string; quoteId: string },
): void {
  render(el, <AutoVerifyButton projectId={opts.projectId} quoteId={opts.quoteId} />);
}

export function mountGuide(
  el: Element,
  opts: { getProjectId?: () => string | null } = {},
): void {
  render(el, <FloatingGuide getProjectId={opts.getProjectId} />);
}

/** Tear down a previously mounted island. */
export function unmount(el: Element): void {
  const root = ROOTS.get(el);
  if (root) {
    root.unmount();
    ROOTS.delete(el);
  }
}
