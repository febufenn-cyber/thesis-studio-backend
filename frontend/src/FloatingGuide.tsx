"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { apiGet, apiPost } from "./api";

/**
 * FloatingGuide — the animated Robofox companion. A floating fox that bobs,
 * blinks and waves; opening it gives (1) contextual "how do I use this" tips
 * and (2) the Start-from-zero journey: pick your subject, work the topic
 * worksheet + methodology, then one click creates a chapter skeleton of
 * [TO WRITE] prompts. Guidance only — it never writes prose for the student
 * and never overwrites existing work (server enforces both).
 */

interface Playbook {
  key: string;
  label: string;
  audience: string;
  citation_hint: string;
  topic_worksheet: string[];
  methodology: string[];
  source_types: string[];
  skeleton: [number, string, string[]][];
  checklist: string[];
}

const TIPS: { title: string; body: string }[] = [
  { title: "Upload or start from zero", body: "Have a draft? Upload the DOCX — chapters, sources and quotes are read automatically. No draft yet? Use “Plan my thesis” below." },
  { title: "Sources are never auto-trusted", body: "Imported references show [VERIFY] until YOU confirm each one. That's your integrity trail, not an error." },
  { title: "Quotes get receipts", body: "Enter quotations via the registry and use Verify to check them against open-access full text." },
  { title: "Watch the readiness dial", body: "Integrity → Submission Readiness shows exactly what blocks a final export. Fix blockers first." },
  { title: "One-click deliverable", body: "Export → Submission Pack downloads your PDF + integrity report + AI-use statement in one zip." },
];

export function FloatingGuide({ getProjectId }: { getProjectId?: () => string | null }) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"home" | "plan" | "worksheet">("home");
  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  const [picked, setPicked] = useState<Playbook | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open && view === "plan" && playbooks.length === 0) {
      apiGet<{ playbooks: Playbook[] }>("/guide/playbooks")
        .then((r) => setPlaybooks(r.playbooks))
        .catch(() => setPlaybooks([]));
    }
  }, [open, view, playbooks.length]);

  async function scaffold() {
    const pid = getProjectId?.();
    if (!pid) { setMsg("Open (or create) a project first, then I can build your skeleton."); return; }
    if (!picked) return;
    setBusy(true); setMsg(null);
    try {
      const r = await apiPost<{ chapters_created: number }>(
        `/projects/${pid}/guide/scaffold`, { playbook: picked.key });
      setMsg(`Done — ${r.chapters_created} chapters created as [TO WRITE] prompts. Open the editor and start answering them.`);
      // Classic app: refresh the structure tree in place (no-op in the SPA).
      try {
        (window as unknown as { App?: { refreshAll?: () => Promise<void> } }).App?.refreshAll?.();
      } catch { /* non-fatal */ }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Scaffold failed");
    } finally { setBusy(false); }
  }

  return (
    <div className="rf-root" style={S.root}>
      <style>{CSS_ANIM}</style>
      {open && (
        <div style={S.panel} role="dialog" aria-label="Robofox guide">
          <div style={S.head}>
            <FoxFace size={30} />
            <div style={{ flex: 1 }}>
              <div style={S.title}>Robofox Guide</div>
              <div style={S.subtitle}>plan → write → verify → submit</div>
            </div>
            <button style={S.close} onClick={() => setOpen(false)} aria-label="Close guide">×</button>
          </div>

          {view === "home" && (
            <div style={S.body}>
              <button style={S.primary} onClick={() => setView("plan")}>
                🧭 Plan my thesis from zero
              </button>
              <div style={S.tipHead}>How Acadensia works</div>
              {TIPS.map((t) => (
                <div key={t.title} style={S.tip}>
                  <div style={S.tipTitle}>{t.title}</div>
                  <div style={S.tipBody}>{t.body}</div>
                </div>
              ))}
            </div>
          )}

          {view === "plan" && (
            <div style={S.body}>
              <button style={S.back} onClick={() => setView("home")}>← back</button>
              <div style={S.tipHead}>What are you writing?</div>
              {playbooks.length === 0 && <div style={S.tipBody}>Loading subjects…</div>}
              {playbooks.map((p) => (
                <button key={p.key} style={S.domainBtn} onClick={() => { setPicked(p); setView("worksheet"); setMsg(null); }}>
                  <span style={{ fontWeight: 700 }}>{p.label}</span>
                  <span style={S.tipBody}>{p.audience}</span>
                </button>
              ))}
            </div>
          )}

          {view === "worksheet" && picked && (
            <div style={S.body}>
              <button style={S.back} onClick={() => setView("plan")}>← subjects</button>
              <div style={S.tipHead}>{picked.label}</div>
              <div style={S.badge}>{picked.citation_hint}</div>

              <div style={S.sec}>1 · Choose your topic — answer these honestly</div>
              <ol style={S.list}>{picked.topic_worksheet.map((q, i) => <li key={i}>{q}</li>)}</ol>

              <div style={S.sec}>2 · Methodology for this domain</div>
              <ul style={S.list}>{picked.methodology.map((q, i) => <li key={i}>{q}</li>)}</ul>

              <div style={S.sec}>3 · Sources you'll need</div>
              <ul style={S.list}>{picked.source_types.map((q, i) => <li key={i}>{q}</li>)}</ul>

              <div style={S.sec}>4 · Your chapter skeleton</div>
              <ul style={S.list}>
                {picked.skeleton.map(([n, t]) => <li key={n}>Chapter {n}: {t}</li>)}
              </ul>

              <button style={S.primary} onClick={scaffold} disabled={busy}>
                {busy ? "Building…" : "✨ Create my thesis skeleton"}
              </button>
              <p style={S.tipBody}>
                Creates the chapters above as clearly-marked [TO WRITE] prompts in the current
                project. It never writes prose for you and never touches existing chapters.
              </p>
              {msg && <p style={S.msg}>{msg}</p>}
            </div>
          )}
        </div>
      )}

      <button
        style={S.fab}
        className="rf-bob"
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Close Robofox guide" : "Open Robofox guide"}
        title="Robofox Guide"
      >
        <FoxFace size={40} waving={!open} />
      </button>
    </div>
  );
}

/** The fox: pure SVG, blinking eyes, waving paw. No external assets. */
function FoxFace({ size, waving }: { size: number; waving?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      {/* ears */}
      <polygon points="10,26 16,4 30,20" fill="#e8722e" />
      <polygon points="54,26 48,4 34,20" fill="#e8722e" />
      <polygon points="14,22 17,9 26,19" fill="#7c3a12" />
      <polygon points="50,22 47,9 38,19" fill="#7c3a12" />
      {/* head */}
      <ellipse cx="32" cy="38" rx="24" ry="21" fill="#e8722e" />
      {/* cheeks */}
      <ellipse cx="16" cy="45" rx="10" ry="9" fill="#fff4ea" />
      <ellipse cx="48" cy="45" rx="10" ry="9" fill="#fff4ea" />
      <ellipse cx="32" cy="50" rx="12" ry="9" fill="#fff4ea" />
      {/* eyes (blink via CSS) */}
      <g className="rf-eyes">
        <circle cx="23" cy="36" r="3.2" fill="#241a12" />
        <circle cx="41" cy="36" r="3.2" fill="#241a12" />
        <circle cx="24.2" cy="34.8" r="1" fill="#fff" />
        <circle cx="42.2" cy="34.8" r="1" fill="#fff" />
      </g>
      {/* nose + mouth */}
      <ellipse cx="32" cy="46" rx="3.4" ry="2.6" fill="#241a12" />
      <path d="M32 48 q0 4 -4 5 M32 48 q0 4 4 5" stroke="#241a12" strokeWidth="1.6" fill="none" strokeLinecap="round" />
      {/* waving paw */}
      {waving && (
        <g className="rf-wave">
          <ellipse cx="57" cy="52" rx="6" ry="7" fill="#e8722e" />
          <ellipse cx="57" cy="49" rx="6" ry="3.4" fill="#fff4ea" />
        </g>
      )}
    </svg>
  );
}

const CSS_ANIM = `
@keyframes rf-bob { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
@keyframes rf-blink { 0%, 92%, 100% { transform: scaleY(1); } 95% { transform: scaleY(0.08); } }
@keyframes rf-wave-k { 0%,100% { transform: rotate(0deg); } 50% { transform: rotate(-22deg); } }
.rf-bob { animation: rf-bob 2.6s ease-in-out infinite; }
.rf-eyes { transform-origin: 32px 36px; animation: rf-blink 4.2s infinite; }
.rf-wave { transform-origin: 57px 58px; animation: rf-wave-k 1.1s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .rf-bob, .rf-eyes, .rf-wave { animation: none; }
}
`;

const S: Record<string, CSSProperties> = {
  root: { position: "fixed", right: 18, bottom: 18, zIndex: 9999, fontFamily: "'Inter', system-ui, sans-serif" },
  fab: { width: 58, height: 58, borderRadius: "50%", border: "1px solid rgba(255,255,255,0.22)", background: "rgba(19,23,44,0.55)", backdropFilter: "blur(24px) saturate(160%)", WebkitBackdropFilter: "blur(24px) saturate(160%)", cursor: "pointer", boxShadow: "0 10px 30px rgba(4,6,16,.5), 0 0 22px rgba(240,155,95,.35), inset 0 1px 0 rgba(255,255,255,.25)", display: "grid", placeItems: "center", padding: 0 },
  panel: { position: "absolute", right: 0, bottom: 70, width: 360, maxWidth: "calc(100vw - 36px)", maxHeight: "min(560px, calc(100vh - 120px))", overflowY: "auto", background: "rgba(16,20,40,0.78)", backdropFilter: "blur(36px) saturate(160%)", WebkitBackdropFilter: "blur(36px) saturate(160%)", color: "rgba(255,255,255,0.96)", border: "1px solid rgba(255,255,255,0.16)", borderRadius: 22, boxShadow: "0 30px 80px rgba(4,6,16,.55), inset 0 1px 0 rgba(255,255,255,.22)" },
  head: { display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", borderBottom: "1px solid rgba(255,255,255,0.13)", position: "sticky", top: 0, background: "rgba(16,20,40,0.92)" },
  title: { fontSize: 14, fontWeight: 800 },
  subtitle: { fontSize: 10.5, color: "rgba(255,255,255,0.55)", letterSpacing: 0.3 },
  close: { width: 30, height: 30, borderRadius: 8, border: "1px solid rgba(255,255,255,0.13)", background: "rgba(255,255,255,0.07)", cursor: "pointer", fontSize: 16 },
  body: { padding: "12px 14px" },
  primary: { width: "100%", padding: "11px 14px", borderRadius: 999, border: 0, background: "rgba(255,255,255,0.92)", color: "#141A38", fontWeight: 600, fontSize: 13, cursor: "pointer", marginBottom: 12, boxShadow: "0 6px 20px rgba(0,0,0,.25)" },
  back: { border: 0, background: "transparent", color: "#A5B8FF", fontWeight: 600, fontSize: 12, cursor: "pointer", padding: 0, marginBottom: 8 },
  tipHead: { fontSize: 11, fontWeight: 800, color: "rgba(255,255,255,0.55)", textTransform: "uppercase", letterSpacing: 0.5, margin: "6px 0 8px" },
  tip: { border: "1px solid rgba(255,255,255,0.13)", borderRadius: 10, padding: "9px 11px", marginBottom: 8 },
  tipTitle: { fontSize: 12.5, fontWeight: 700, marginBottom: 2 },
  tipBody: { fontSize: 11.5, color: "rgba(255,255,255,0.55)", lineHeight: 1.5 },
  domainBtn: { display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 3, width: "100%", textAlign: "left", border: "1px solid rgba(255,255,255,0.13)", borderRadius: 10, padding: "10px 12px", background: "rgba(255,255,255,0.07)", cursor: "pointer", marginBottom: 8, fontFamily: "inherit", fontSize: 13, color: "rgba(255,255,255,0.96)" },
  badge: { display: "inline-block", fontSize: 10.5, fontWeight: 700, color: "#A5B8FF", background: "rgba(165,184,255,0.16)", borderRadius: 999, padding: "3px 9px", marginBottom: 6 },
  sec: { fontSize: 12, fontWeight: 800, margin: "12px 0 5px" },
  list: { margin: "0 0 4px", paddingLeft: 18, fontSize: 12, lineHeight: 1.6, color: "rgba(255,255,255,0.96)" },
  msg: { fontSize: 12, fontWeight: 600, color: "#7DE8A8", background: "rgba(125,232,168,0.14)", borderRadius: 8, padding: "8px 10px" },
};
