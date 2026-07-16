"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { T } from "./theme";

/**
 * PresenceDots — who else is on this manuscript right now. Heartbeats
 * PUT /projects/{id}/presence while mounted, polls the roster, and leaves
 * cleanly on unmount. Quiet by design: initials in small glass dots.
 */

type Peer = { user_id?: string; email?: string; full_name?: string; activity?: string };

export function PresenceDots({ projectId }: { projectId: string }) {
  const [peers, setPeers] = useState<Peer[]>([]);

  useEffect(() => {
    let alive = true;
    const beat = () =>
      fetch(`/projects/${projectId}/presence`, {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ activity: "viewing", scope: {} }),
      }).catch(() => undefined);
    const poll = () =>
      fetch(`/projects/${projectId}/presence`, { credentials: "include" })
        .then((r) => (r.ok ? r.json() : null))
        .then((j) => {
          if (!alive || !j) return;
          const list: Peer[] = Array.isArray(j) ? j : (j.presence ?? j.peers ?? []);
          setPeers(list);
        })
        .catch(() => undefined);
    beat().then(poll);
    const h = setInterval(() => { beat(); poll(); }, 45000);
    return () => {
      alive = false;
      clearInterval(h);
      fetch(`/projects/${projectId}/presence`, { method: "DELETE", credentials: "include" }).catch(() => undefined);
    };
  }, [projectId]);

  if (peers.length <= 1) return null; // just you — stay quiet

  return (
    <span style={S.wrap} title={peers.map((p) => p.full_name || p.email || "someone").join(", ")}>
      {peers.slice(0, 4).map((p, i) => (
        <span key={p.user_id ?? i} style={{ ...S.dot, marginLeft: i === 0 ? 0 : -6 }}>
          {(p.full_name || p.email || "?").slice(0, 1).toUpperCase()}
        </span>
      ))}
      {peers.length > 4 && <span style={S.more}>+{peers.length - 4}</span>}
    </span>
  );
}

const S: Record<string, CSSProperties> = {
  wrap: { display: "inline-flex", alignItems: "center", marginRight: 12 },
  dot: {
    width: 22, height: 22, borderRadius: "50%", display: "inline-grid", placeItems: "center",
    fontSize: 10.5, fontWeight: 700, color: T.ink,
    background: "rgba(165,184,255,0.28)", border: "1px solid rgba(255,255,255,0.35)",
    boxShadow: "0 2px 8px rgba(4,6,16,.4)",
  },
  more: { fontSize: 11, color: T.muted, marginLeft: 6 },
};
