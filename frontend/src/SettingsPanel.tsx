"use client";

import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { apiGet } from "./api";
import {
  getResearchConsent,
  grantResearchConsent,
  patchProjectLocale,
  revokeResearchConsent,
} from "./useFeatures";

/**
 * SettingsPanel — locale & script policy (3.7) and research-donation consent
 * (3.8). Consent is opt-in, scope-by-scope, revocable; the copy says exactly
 * what each scope shares and that revoking stops future inclusion.
 */
export function SettingsPanel({ projectId }: { projectId: string }) {
  return (
    <div style={S.wrap}>
      <LocaleCard projectId={projectId} />
      <ConsentCard />
    </div>
  );
}

interface Locale { tag: string; label: string; direction: string }

function LocaleCard({ projectId }: { projectId: string }) {
  const [locales, setLocales] = useState<Locale[]>([]);
  const [locale, setLocale] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiGet<{ locales: Locale[] }>("/locales")
      .then((r) => setLocales(r.locales ?? []))
      .catch(() => setLocales([]));
  }, []);

  async function save() {
    setBusy(true); setMsg(null);
    try {
      await patchProjectLocale(projectId, locale);
      setMsg("Locale saved. Citation style, spelling and terminology are preserved as-is — nothing is silently converted.");
    } catch (e) { setMsg(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(false); }
  }

  return (
    <section style={S.card}>
      <div style={S.h}>Language & script</div>
      <p style={S.muted}>Sets the manuscript locale (multilingual foundation). Right-to-left scripts get proper isolation in rendered output.</p>
      <div style={S.row}>
        <select style={S.select} value={locale} onChange={(e) => setLocale(e.target.value)}>
          <option value="">— choose a locale —</option>
          {locales.map((l) => (
            <option key={l.tag} value={l.tag}>{l.label} ({l.tag}{l.direction === "rtl" ? " · RTL" : ""})</option>
          ))}
        </select>
        <button style={S.btn} onClick={save} disabled={busy || !locale}>Save</button>
      </div>
      {msg && <p style={S.hint}>{msg}</p>}
    </section>
  );
}

const CONSENT_SCOPES: { key: string; label: string; what: string }[] = [
  { key: "revision_history", label: "Revision history", what: "how drafts evolve over time" },
  { key: "citation_patterns", label: "Citation patterns", what: "how sources are cited (never the prose)" },
  { key: "ai_provenance", label: "AI provenance", what: "which blocks had AI assistance" },
];

function ConsentCard() {
  const [granted, setGranted] = useState<Set<string>>(new Set());
  const [msg, setMsg] = useState<string | null>(null);

  const reload = useCallback(() => {
    getResearchConsent()
      .then((r) => {
        const rows = (r.consents ?? r.grants ?? []) as { scope: string }[];
        setGranted(new Set(rows.map((c) => c.scope)));
      })
      .catch(() => setGranted(new Set()));
  }, []);
  useEffect(reload, [reload]);

  async function toggle(scope: string) {
    setMsg(null);
    try {
      if (granted.has(scope)) await revokeResearchConsent(scope);
      else await grantResearchConsent(scope);
      reload();
    } catch (e) { setMsg(e instanceof Error ? e.message : "Failed"); }
  }

  return (
    <section style={S.card}>
      <div style={S.h}>Research donation (optional)</div>
      <p style={S.muted}>
        Off by default. If you opt in, anonymized signals join a k-anonymous research corpus —
        small groups are suppressed entirely. Revoking stops all future inclusion.
      </p>
      {CONSENT_SCOPES.map((s) => (
        <label key={s.key} style={S.consentRow}>
          <input type="checkbox" checked={granted.has(s.key)} onChange={() => toggle(s.key)} />
          <span>
            <strong style={{ fontSize: 12.5 }}>{s.label}</strong>
            <span style={S.what}> — {s.what}</span>
          </span>
        </label>
      ))}
      {msg && <p style={S.err}>{msg}</p>}
    </section>
  );
}

const S: Record<string, CSSProperties> = {
  wrap: { fontFamily: "'Inter', system-ui, sans-serif", color: "rgba(255,255,255,0.96)" },
  card: { border: "1px solid rgba(255,255,255,0.13)", borderRadius: 11, padding: "13px 14px", marginBottom: 10, background: "rgba(255,255,255,0.07)" },
  h: { fontSize: 13.5, fontWeight: 700, marginBottom: 4 },
  muted: { color: "rgba(255,255,255,0.55)", fontSize: 12.5, margin: "4px 0 10px", lineHeight: 1.5 },
  row: { display: "flex", gap: 8 },
  select: { flex: 1, fontFamily: "inherit", fontSize: 12.5, border: "1px solid rgba(255,255,255,0.13)", background: "rgba(255,255,255,0.07)", borderRadius: 7, padding: "8px" },
  btn: { padding: "8px 14px", borderRadius: 8, border: "1px solid #A5B8FF", background: "#A5B8FF", color: "#fff", fontWeight: 600, fontSize: 12.5, cursor: "pointer" },
  consentRow: { display: "flex", alignItems: "flex-start", gap: 9, padding: "8px 0", borderTop: "1px solid rgba(255,255,255,0.09)", cursor: "pointer" },
  what: { fontSize: 12, color: "rgba(255,255,255,0.55)" },
  hint: { fontSize: 11.5, color: "rgba(255,255,255,0.55)", marginTop: 8 },
  err: { color: "#FF7A76", fontSize: 12.5, marginTop: 6 },
};
