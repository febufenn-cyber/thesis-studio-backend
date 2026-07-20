"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { apiGet, apiSend } from "./coverageApi";
import { T } from "./theme";

/**
 * DomainReadiness — surfaces the domain-profile catalog and the advisory
 * submission-readiness check (GET /domain-profiles, /projects/{id}/domain-
 * readiness). Declaring a profile also retunes Robofox's discipline voice
 * and the default citation style. Advisory only — never a hard gate.
 */

type Profile = { key: string; name?: string; description?: string };
type Readiness = {
  profile: string | null;
  ready: boolean;
  missing_sections: string[];
  checklist: { item?: string; label?: string; done?: boolean; satisfied?: boolean }[];
};

export function DomainReadiness({ projectId }: { projectId: string }) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [current, setCurrent] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = () => {
    apiGet<{ profiles?: Profile[] } | Profile[]>("/domain-profiles")
      .then((r) => setProfiles(Array.isArray(r) ? r : (r.profiles ?? [])))
      .catch((e) => setError(e.message));
    apiGet<Readiness>(`/projects/${projectId}/domain-readiness`)
      .then((r) => { setReadiness(r); setCurrent(r.profile ?? ""); })
      .catch((e) => setError(e.message));
  };
  useEffect(load, [projectId]);

  const declare = async (key: string) => {
    setBusy(true); setError(null); setNote(null);
    try {
      // MetaUpdate wants the full ThesisMeta + optimistic version token.
      const detail = await apiGet<{ document_version: number; meta: Record<string, unknown> }>(
        `/projects/${projectId}`,
      );
      const profile = await apiGet<{ key: string; default_citation_style?: string }>(
        `/domain-profiles/${key}`,
      );
      const meta: Record<string, unknown> = { ...(detail.meta ?? {}), domain_profile: key };
      if (profile.default_citation_style) meta.citation_style = profile.default_citation_style;
      await apiSend("PATCH", `/projects/${projectId}/meta`, {
        expected_version: detail.document_version,
        meta,
      });
      setNote("Profile declared — Robofox and readiness now speak this discipline.");
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section style={S.card}>
      <div style={S.h}>Submission readiness</div>
      <p style={S.muted}>
        Declare your discipline's document profile — section checklist, default citation style,
        and Robofox's voice follow it. Advisory only; nothing is ever blocked.
      </p>
      <div style={S.row}>
        <select
          style={S.select}
          value={current}
          disabled={busy}
          onChange={(e) => { setCurrent(e.target.value); if (e.target.value) declare(e.target.value); }}
        >
          <option value="">No profile declared</option>
          {profiles.map((p) => (
            <option key={p.key} value={p.key}>{p.name ?? p.key.replace(/_/g, " ")}</option>
          ))}
        </select>
      </div>
      {error && <p style={S.err}>{error}</p>}
      {note && <p style={S.ok}>{note}</p>}
      {readiness && readiness.profile && (
        <div style={{ marginTop: 10 }}>
          <div style={readiness.ready ? S.ready : S.notReady}>
            {readiness.ready ? "All required sections present" : "Sections still missing"}
          </div>
          {readiness.missing_sections.length > 0 && (
            <ul style={S.list}>
              {readiness.missing_sections.map((s) => (
                <li key={s}>{s.replace(/_/g, " ")}</li>
              ))}
            </ul>
          )}
          {readiness.checklist.length > 0 && (
            <ul style={S.list}>
              {readiness.checklist.map((c, i) => {
                const label = c.label ?? c.item ?? JSON.stringify(c);
                const done = c.done ?? c.satisfied;
                return (
                  <li key={i} style={{ color: done ? T.good : T.muted }}>
                    {done ? "✓ " : "· "}{label}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

const S: Record<string, CSSProperties> = {
  card: { border: `1px solid ${T.line}`, borderRadius: 14, padding: "14px 16px", marginBottom: 14, background: T.card },
  h: { fontWeight: 600, fontSize: 13.5, marginBottom: 6, color: T.ink },
  muted: { color: T.muted, fontSize: 12.5, lineHeight: 1.5, margin: "0 0 10px" },
  row: { display: "flex", gap: 8 },
  select: { flex: 1, fontFamily: "inherit", fontSize: 12.5, border: `1px solid ${T.line}`, background: "rgba(255,255,255,0.07)", color: T.ink, borderRadius: 10, padding: "8px 10px" },
  err: { color: T.bad, fontSize: 12.5, marginTop: 8 },
  ok: { color: T.good, fontSize: 12.5, marginTop: 8 },
  ready: { display: "inline-block", fontSize: 12, fontWeight: 600, color: T.good, background: T.goodWash, borderRadius: 999, padding: "4px 12px" },
  notReady: { display: "inline-block", fontSize: 12, fontWeight: 600, color: T.warn, background: T.warnWash, borderRadius: 999, padding: "4px 12px" },
  list: { margin: "8px 0 0", paddingLeft: 18, fontSize: 12.5, lineHeight: 1.7, color: T.inkSoft },
};
