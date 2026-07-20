"use client";

import type { CSSProperties } from "react";

/**
 * The single status vocabulary for the whole product. Green is *earned*
 * (verified); slate ("unknown"/"unverifiable") is deliberately neutral and is
 * NEVER shown in green — that is the never-guess discipline made visible.
 */
export type Status =
  | "verified"
  | "resolved" // machine-resolved / advisory — NEVER green
  | "verify" // [VERIFY] / needs attention
  | "retracted"
  | "resolving"
  | "unverifiable"
  | "drift"
  | "not_found";

const STYLES: Record<Status, { label: string; fg: string; bg: string }> = {
  verified: { label: "VERIFIED", fg: "#7DE8A8", bg: "rgba(125,232,168,0.14)" },
  // Resolved is advisory (a machine match / score), not human verification, so
  // it is shown in neutral slate — never the earned green. See AI safety rule 11.
  resolved: { label: "RESOLVED", fg: "#A5B8FF", bg: "rgba(165,184,255,0.16)" },
  verify: { label: "[VERIFY]", fg: "#FFC46E", bg: "rgba(255,196,110,0.14)" },
  retracted: { label: "RETRACTED", fg: "#FF7A76", bg: "rgba(255,122,118,0.14)" },
  resolving: { label: "RESOLVING", fg: "#A5B8FF", bg: "rgba(165,184,255,0.16)" },
  unverifiable: { label: "UNVERIFIABLE", fg: "rgba(255,255,255,0.55)", bg: "rgba(255,255,255,0.09)" },
  drift: { label: "DRIFT", fg: "#FFC46E", bg: "rgba(255,196,110,0.14)" },
  not_found: { label: "NOT FOUND", fg: "#FFC46E", bg: "rgba(255,196,110,0.14)" },
};

/** Map a verbatim/verification status string to a badge Status. */
export function toStatus(raw: string | null | undefined): Status {
  switch (raw) {
    case "verified":
      return "verified";
    case "drift":
      return "drift";
    case "not_found":
      return "not_found";
    case "unverifiable":
      return "unverifiable";
    case "resolved":
      // Resolved is advisory, NOT verified — it must not render in green.
      return "resolved";
    case "retracted":
      return "retracted";
    default:
      return "verify";
  }
}

export function StatusBadge({ status, label }: { status: Status; label?: string }) {
  const s = STYLES[status];
  const wrap: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "3px 9px",
    borderRadius: 999,
    fontSize: 11.5,
    fontWeight: 700,
    color: s.fg,
    background: s.bg,
    fontFamily: "'Inter', system-ui, sans-serif",
  };
  const dot: CSSProperties = {
    width: 7,
    height: 7,
    borderRadius: "50%",
    background: s.fg,
    animation: status === "resolving" ? "acad-pulse 1s infinite" : undefined,
  };
  return (
    <span style={wrap}>
      <span style={dot} />
      {label ?? s.label}
    </span>
  );
}
