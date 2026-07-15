"use client";

import { useState } from "react";
import { StatusBadge, toStatus } from "./StatusBadge";
import {
  addDiscoveredSource,
  discoverSearch,
  generateAIUseStatement,
  useCompliance,
  useIntegrityReport,
  useProvenance,
  useQuoteReport,
  type AIUseStatement,
  type Candidate,
} from "./useTrust";

/**
 * TrustPanel — the always-present verification surface beside the manuscript.
 * A production drop-in wired to the shipped endpoints (Phases 1–4, MF1/MF4).
 * See docs/UI_UX_LLD.md and acadensia-ui-prototype.html for the full design.
 */

type Tab = "provenance" | "verify" | "comply" | "integrity";

const SEV_COLOR: Record<string, string> = {
  block: "#d64545",
  warn: "#c98a1a",
  info: "#6b7688",
};

export function TrustPanel({ projectId }: { projectId: string }) {
  const [tab, setTab] = useState<Tab>("integrity");
  const [discoverOpen, setDiscoverOpen] = useState(false);

  return (
    <aside style={S.panel}>
      <style>{"@keyframes acad-pulse{0%,100%{opacity:1}50%{opacity:.35}}"}</style>
      <div style={S.tabs}>
        {(["provenance", "verify", "comply", "integrity"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{ ...S.tab, ...(tab === t ? S.tabActive : {}) }}
          >
            {t === "provenance" ? "Provenance" : t === "verify" ? "Verify" : t === "comply" ? "Comply" : "Integrity"}
          </button>
        ))}
      </div>
      <div style={S.body}>
        <button style={{ ...S.btn, ...S.btnPri, marginBottom: 14 }} onClick={() => setDiscoverOpen(true)}>
          🔍 Discover sources
        </button>
        {tab === "provenance" && <ProvenanceTab projectId={projectId} />}
        {tab === "verify" && <VerifyTab projectId={projectId} />}
        {tab === "comply" && <ComplianceTab projectId={projectId} />}
        {tab === "integrity" && <IntegrityTab projectId={projectId} />}
      </div>
      {discoverOpen && <DiscoverModal projectId={projectId} onClose={() => setDiscoverOpen(false)} />}
    </aside>
  );
}

/* ---------------- Provenance ---------------- */

function ProvenanceTab({ projectId }: { projectId: string }) {
  const { data, loading, error } = useProvenance(projectId);
  const [templateKey, setTemplateKey] = useState("neurips");
  const [statement, setStatement] = useState<AIUseStatement | null>(null);
  const [busy, setBusy] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  if (loading) return <Loading />;
  if (error || !data) return <ErrorNote text={error ?? "No data"} />;

  const rc = data.rollup.origin_counts;
  const total = data.rollup.total_blocks || 1;

  async function generate() {
    setBusy(true);
    setGenError(null);
    try {
      setStatement(await generateAIUseStatement(projectId, templateKey));
    } catch (e) {
      setGenError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h3 style={S.h3}>Authorship provenance</h3>
      {["human", "ai_proposal", "ai_edited", "imported", "unknown"].map((k) =>
        rc[k] ? (
          <div key={k} style={S.rowBetween}>
            <span style={S.muted}>{k.replace("_", " ")}</span>
            <b>{Math.round((rc[k] / total) * 100)}%</b>
          </div>
        ) : null,
      )}
      <h3 style={{ ...S.h3, marginTop: 18 }}>AI Use Statement</h3>
      <div style={{ display: "flex", gap: 8 }}>
        <select style={S.select} value={templateKey} onChange={(e) => setTemplateKey(e.target.value)}>
          {data.templates.map((t) => (
            <option key={t.key} value={t.key}>
              {t.label}
            </option>
          ))}
        </select>
        <button style={{ ...S.btn, ...S.btnPri }} disabled={busy} onClick={generate}>
          {busy ? "Generating…" : "Generate"}
        </button>
      </div>
      {genError && <ErrorNote text={genError} />}
      {statement && (
        <div style={S.statement}>
          {statement.body_text}
          <div style={S.meta}>
            bound to v{statement.document_version} · checksum {statement.document_checksum.slice(0, 8)} · content_hash{" "}
            {statement.content_hash.slice(0, 8)}
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- Verify ---------------- */

function VerifyTab({ projectId }: { projectId: string }) {
  const { data, loading, error } = useQuoteReport(projectId);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorNote text={error ?? "No data"} />;
  return (
    <div>
      <h3 style={S.h3}>Quote verification</h3>
      <div style={S.advisory}>
        Advisory only — results never change the human “verified” bit; an unreadable source is reported as
        <b> unverifiable</b>, never verified.
      </div>
      {data.results.length === 0 && <Empty text="No quotes checked yet." />}
      {data.results.map((r) => (
        <div key={`${r.quote_id}-${r.kind}`} style={S.card}>
          <div style={S.rowBetween}>
            <span style={S.muted}>
              {r.kind}
              {r.matched_locator ? ` · ${r.matched_locator}` : ""}
            </span>
            <StatusBadge status={toStatus(r.status)} />
          </div>
          {r.score != null && (
            <div style={S.meter}>
              <div
                style={{
                  ...S.meterFill,
                  width: `${Math.round(r.score * 100)}%`,
                  background: r.status === "verified" ? "#1f9d6b" : r.status === "unverifiable" ? "#6b7688" : "#c98a1a",
                }}
              />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/* ---------------- Compliance ---------------- */

function ComplianceTab({ projectId }: { projectId: string }) {
  const { data, loading, error } = useCompliance(projectId);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorNote text={error ?? "No data"} />;
  if (!data.enforced)
    return (
      <div>
        <h3 style={S.h3}>Venue compliance</h3>
        <Empty text="No enforcing venue profile selected. Set a NeurIPS/ACL/CVPR profile to enable page, anonymization, and reproducibility checks." />
      </div>
    );
  return (
    <div>
      <h3 style={S.h3}>
        Venue compliance · {data.profile}{" "}
        <StatusBadge status={data.ready ? "verified" : "verify"} label={data.ready ? "READY" : "NOT READY"} />
      </h3>
      {data.findings.length === 0 && <Empty text="No compliance findings — you're within limits." />}
      {data.findings.map((f, i) => (
        <div key={i} style={S.finding}>
          <span style={{ ...S.sevDot, background: SEV_COLOR[f.severity] }} />
          <div>
            <div style={{ fontWeight: 700, fontSize: 12 }}>{f.code}</div>
            <div style={{ ...S.muted, fontSize: 12 }}>{f.message}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ---------------- Integrity ---------------- */

function IntegrityTab({ projectId }: { projectId: string }) {
  const { data, loading, error } = useIntegrityReport(projectId);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorNote text={error ?? "No data"} />;

  const checks = [
    { ok: data.references.ready, h: "References", s: describeRefs(data.references.counts) },
    { ok: data.quote_verification.ready, h: "Quotations", s: describeQuotes(data.quote_verification) },
    { ok: data.open_markers.ready, h: "Open markers", s: `${data.open_markers.total} unresolved marker(s)` },
  ];
  return (
    <div>
      <h3 style={S.h3}>Integrity Report</h3>
      <div style={S.assert}>
        This report <b>asserts provenance</b>. It does not detect plagiarism or AI text; absence of a signal is shown as
        unknown, never as clean.
      </div>
      {checks.map((c) => (
        <div key={c.h} style={S.check}>
          <div style={{ ...S.checkIcon, background: c.ok ? "#1f9d6b" : "#c98a1a" }}>{c.ok ? "✓" : "!"}</div>
          <div>
            <div style={{ fontWeight: 600, fontSize: 13 }}>{c.h}</div>
            <div style={{ ...S.muted, fontSize: 12 }}>{c.s}</div>
          </div>
        </div>
      ))}
      <div style={{ ...S.meta, marginTop: 12 }}>
        document_checksum {data.document_checksum.slice(0, 12)}… · v{data.document_version}
      </div>
      <div style={{ marginTop: 12 }}>
        <StatusBadge status={data.ready ? "verified" : "verify"} label={data.ready ? "SUBMISSION-READY" : "NOT READY"} />
      </div>
    </div>
  );
}

function describeRefs(c: Record<string, number>): string {
  const parts = [`${c.resolved ?? 0} resolved`];
  if (c.retracted) parts.push(`${c.retracted} retracted`);
  if (c.verify_incomplete) parts.push(`${c.verify_incomplete} [VERIFY]`);
  return parts.join(" · ");
}
function describeQuotes(q: { checked: number; counts: Record<string, number> }): string {
  return `${q.counts.verified ?? 0} verified · ${q.counts.drift ?? 0} drift · ${q.checked} checked`;
}

/* ---------------- Discover modal ---------------- */

function DiscoverModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState<Set<string>>(new Set());

  async function run() {
    setBusy(true);
    try {
      const res = await discoverSearch(projectId, query);
      setCandidates(res.candidates);
    } finally {
      setBusy(false);
    }
  }
  async function add(identifier: string) {
    await addDiscoveredSource(projectId, identifier);
    setAdded((s) => new Set(s).add(identifier));
  }

  return (
    <div style={S.backdrop} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={S.modal}>
        <div style={S.modalHead}>
          <h3 style={{ margin: 0, fontSize: 15 }}>🔍 Discover sources</h3>
          <button style={S.iconBtn} onClick={onClose}>
            ✕
          </button>
        </div>
        <div style={{ padding: 18 }}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              run();
            }}
            style={S.search}
          >
            🔎{" "}
            <input
              style={S.searchInput}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="attention mechanism transformers"
              autoFocus
            />
          </form>
          <div style={{ ...S.muted, fontSize: 12, marginTop: 8 }}>
            OpenAlex + Crossref · added sources are resolved &amp; verified, never guessed
          </div>
          {busy && <Loading />}
          {candidates.map((c) => (
            <div key={c.identifier} style={S.cand}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{c.title}</div>
                <div style={{ ...S.muted, fontSize: 12 }}>
                  {c.authors.slice(0, 3).join(", ")} · {c.year ?? ""} · {c.authority}
                </div>
              </div>
              <button
                style={{ ...S.btn, ...(added.has(c.identifier) ? {} : S.btnPri) }}
                disabled={added.has(c.identifier)}
                onClick={() => add(c.identifier)}
              >
                {added.has(c.identifier) ? "Added ✓" : "Add"}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------------- shared bits ---------------- */

const Loading = () => <div style={{ ...S.muted, padding: "18px 0", fontSize: 13 }}>Loading…</div>;
const Empty = ({ text }: { text: string }) => <div style={{ ...S.muted, fontSize: 12.5, padding: "8px 0" }}>{text}</div>;
const ErrorNote = ({ text }: { text: string }) => (
  <div style={{ color: "#d64545", fontSize: 12.5, padding: "8px 0" }}>{text}</div>
);

/* ---------------- styles ---------------- */

const S: Record<string, React.CSSProperties> = {
  panel: { width: 396, borderLeft: "1px solid #e7e3db", background: "#fff", height: "100%", overflowY: "auto", fontFamily: "Inter, system-ui, sans-serif" },
  tabs: { display: "flex", gap: 2, padding: "10px 12px 0", borderBottom: "1px solid #e7e3db", position: "sticky", top: 0, background: "#fff" },
  tab: { flex: 1, padding: "9px 4px", border: 0, background: "transparent", borderBottom: "2px solid transparent", fontWeight: 600, fontSize: 12.5, color: "#6b7688", cursor: "pointer" },
  tabActive: { color: "#4b4bd6", borderBottomColor: "#4b4bd6" },
  body: { padding: "16px 15px" },
  h3: { margin: "0 0 12px", fontSize: 14, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 },
  muted: { color: "#6b7688" },
  rowBetween: { display: "flex", justifyContent: "space-between", fontSize: 12.5, margin: "5px 0" },
  select: { fontFamily: "inherit", fontSize: 12, border: "1px solid #e7e3db", background: "#fff", borderRadius: 7, padding: "5px 6px" },
  btn: { display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 12px", borderRadius: 9, border: "1px solid #e7e3db", background: "#fff", color: "#1b2733", fontWeight: 600, fontSize: 12.5, cursor: "pointer" },
  btnPri: { background: "#4b4bd6", color: "#fff", borderColor: "#4b4bd6" },
  statement: { border: "1px solid #e7e3db", borderRadius: 11, background: "#f5f3ee", padding: "13px 14px", fontSize: 13, lineHeight: 1.62, marginTop: 10 },
  meta: { fontSize: 11, color: "#6b7688", fontFamily: "ui-monospace, monospace", marginTop: 10 },
  advisory: { fontSize: 11, color: "#6b7688", background: "#f5f3ee", border: "1px solid #e7e3db", borderRadius: 8, padding: "6px 9px", marginBottom: 12 },
  card: { border: "1px solid #e7e3db", borderRadius: 11, padding: "11px 12px", marginBottom: 9 },
  meter: { height: 9, borderRadius: 6, background: "#f5f3ee", border: "1px solid #e7e3db", overflow: "hidden", marginTop: 8 },
  meterFill: { height: "100%", borderRadius: 6, transition: "width .6s ease" },
  finding: { display: "flex", gap: 9, border: "1px solid #e7e3db", borderRadius: 10, padding: "10px 11px", marginBottom: 8 },
  sevDot: { width: 8, height: 8, borderRadius: "50%", marginTop: 5, flex: "none" },
  assert: { background: "#ecebfb", color: "#4b4bd6", borderRadius: 10, padding: "10px 12px", fontSize: 12, fontWeight: 600, marginBottom: 14, lineHeight: 1.5 },
  check: { display: "flex", alignItems: "center", gap: 11, padding: "11px 0", borderBottom: "1px solid #e7e3db" },
  checkIcon: { width: 22, height: 22, borderRadius: 7, display: "grid", placeItems: "center", color: "#fff", fontSize: 12, fontWeight: 800, flex: "none" },
  backdrop: { position: "fixed", inset: 0, background: "rgba(20,25,35,.42)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 40 },
  modal: { background: "#fff", border: "1px solid #e7e3db", borderRadius: 16, width: 560, maxWidth: "92vw", maxHeight: "86vh", overflow: "hidden", display: "flex", flexDirection: "column" },
  modalHead: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 18px", borderBottom: "1px solid #e7e3db" },
  iconBtn: { width: 34, height: 34, borderRadius: 9, border: "1px solid #e7e3db", background: "#fff", cursor: "pointer" },
  search: { display: "flex", alignItems: "center", gap: 9, border: "1px solid #e7e3db", borderRadius: 10, padding: "9px 12px", background: "#f5f3ee" },
  searchInput: { border: 0, background: "transparent", outline: "none", fontFamily: "inherit", fontSize: 14, flex: 1 },
  cand: { border: "1px solid #e7e3db", borderRadius: 11, padding: "11px 12px", marginTop: 10, display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center" },
};
