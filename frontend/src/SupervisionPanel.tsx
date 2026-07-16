"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { getCommittee, runSemanticDiff, type CommitteeMember } from "./useFeatures";

/**
 * SupervisionPanel — committee roster (3.6) and semantic version comparison.
 * Committee assignment itself happens through the collaboration invite flow;
 * this surface makes the roster and the diff engine reachable.
 */
export function SupervisionPanel({ projectId }: { projectId: string }) {
  return (
    <div style={S.wrap}>
      <CommitteeCard projectId={projectId} />
      <DiffCard projectId={projectId} />
    </div>
  );
}

function CommitteeCard({ projectId }: { projectId: string }) {
  const [members, setMembers] = useState<CommitteeMember[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getCommittee(projectId)
      .then((r) => setMembers(Array.isArray(r) ? r : (r.committee ?? r.members ?? [])))
      .catch((e) => setError(e.message));
  }, [projectId]);

  return (
    <section style={S.card}>
      <div style={S.h}>Committee</div>
      {error && <p style={S.err}>{error}</p>}
      {members === null && !error && <p style={S.muted}>Loading…</p>}
      {members?.length === 0 && (
        <p style={S.muted}>
          No committee assigned yet. Invite members through Collaboration, then assign committee
          roles (chair, examiner, reader) from there.
        </p>
      )}
      {members?.map((m, i) => (
        <div key={i} style={S.row}>
          <span style={S.role}>{m.committee_role}</span>
          <code style={S.mono}>{String(m.user_id).slice(0, 8)}…</code>
          {m.voting && <span style={S.chip}>voting</span>}
          {m.content_access && <span style={S.chip}>content access</span>}
        </div>
      ))}
    </section>
  );
}

function DiffCard({ projectId }: { projectId: string }) {
  const [base, setBase] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true); setError(null); setResult(null);
    try {
      const parsed = JSON.parse(base) as unknown;
      setResult(await runSemanticDiff(projectId, parsed));
    } catch (e) {
      setError(e instanceof SyntaxError ? "That isn't valid JSON — paste a document export." : e instanceof Error ? e.message : "Diff failed");
    } finally { setBusy(false); }
  }

  return (
    <section style={S.card}>
      <div style={S.h}>Compare against a saved version</div>
      <p style={S.muted}>
        Paste a document JSON (from a data export or checkpoint download) to see a semantic diff —
        moved paragraphs are recognized as moves, not delete+insert.
      </p>
      <textarea style={S.area} rows={5} placeholder='{"meta": {...}, "chapters": [...]}' value={base} onChange={(e) => setBase(e.target.value)} />
      <button style={S.btn} onClick={run} disabled={busy || !base.trim()}>
        {busy ? "Comparing…" : "Run semantic diff"}
      </button>
      {error && <p style={S.err}>{error}</p>}
      {result && (
        <pre style={S.pre}>{JSON.stringify(result, null, 2).slice(0, 4000)}</pre>
      )}
    </section>
  );
}

const S: Record<string, CSSProperties> = {
  wrap: { fontFamily: "Inter, system-ui, sans-serif", color: "#1b2733" },
  card: { border: "1px solid #e7e3db", borderRadius: 11, padding: "13px 14px", marginBottom: 10, background: "#fff" },
  h: { fontSize: 13.5, fontWeight: 700, marginBottom: 6 },
  muted: { color: "#6b7688", fontSize: 12.5, margin: "4px 0 10px", lineHeight: 1.5 },
  row: { display: "flex", alignItems: "center", gap: 9, padding: "7px 0", borderTop: "1px solid #f0ede6" },
  role: { fontSize: 12.5, fontWeight: 700, textTransform: "capitalize" },
  mono: { fontFamily: "ui-monospace, monospace", fontSize: 11.5, color: "#6b7688" },
  chip: { fontSize: 10.5, fontWeight: 700, color: "#4b4bd6", background: "#ecebfb", borderRadius: 999, padding: "2px 8px" },
  area: { width: "100%", boxSizing: "border-box", fontFamily: "ui-monospace, monospace", fontSize: 11.5, border: "1px solid #e7e3db", borderRadius: 9, padding: "9px 10px", resize: "vertical", marginBottom: 8 },
  btn: { padding: "8px 14px", borderRadius: 8, border: "1px solid #4b4bd6", background: "#4b4bd6", color: "#fff", fontWeight: 600, fontSize: 12.5, cursor: "pointer" },
  pre: { marginTop: 10, background: "#f5f3ee", border: "1px solid #e7e3db", borderRadius: 9, padding: "10px 11px", fontSize: 11, overflowX: "auto", maxHeight: 320 },
  err: { color: "#d64545", fontSize: 12.5, marginTop: 8 },
};
