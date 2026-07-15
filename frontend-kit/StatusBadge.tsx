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
  verified: { label: "VERIFIED", fg: "#1f9d6b", bg: "#e5f4ee" },
  // Resolved is advisory (a machine match / score), not human verification, so
  // it is shown in neutral slate — never the earned green. See AI safety rule 11.
  resolved: { label: "RESOLVED", fg: "#4b4bd6", bg: "#ecebfb" },
  verify: { label: "[VERIFY]", fg: "#c98a1a", bg: "#fbf1dc" },
  retracted: { label: "RETRACTED", fg: "#d64545", bg: "#fbe7e7" },
  resolving: { label: "RESOLVING", fg: "#4b4bd6", bg: "#ecebfb" },
  unverifiable: { label: "UNVERIFIABLE", fg: "#6b7688", bg: "#eef0f3" },
  drift: { label: "DRIFT", fg: "#c98a1a", bg: "#fbf1dc" },
  not_found: { label: "NOT FOUND", fg: "#c98a1a", bg: "#fbf1dc" },
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
    fontFamily: "Inter, system-ui, sans-serif",
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
