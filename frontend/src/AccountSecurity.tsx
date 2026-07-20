"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { apiGet, apiSend } from "./coverageApi";
import { T } from "./theme";

/**
 * AccountSecurity — the account-level surfaces that had no UI:
 * active sessions (list / revoke / revoke-all), step-up reauthentication,
 * data portability (account + everything), and privacy lifecycle requests
 * (export / delete, with cancel). Deletion-class actions require a recent
 * reauthentication — the card walks the user through it honestly.
 */

type Session = { id: string; created_at?: string; last_seen_at?: string; user_agent?: string; ip?: string; current?: boolean };
type Lifecycle = { id: string; request_type: string; status: string; created_at?: string; reason?: string };

export function AccountSecurity({ email }: { email?: string }) {
  return (
    <div>
      <SessionsCard />
      <ReauthCard email={email} />
      <PortabilityCard />
      <LifecycleCard />
    </div>
  );
}

function SessionsCard() {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () =>
    apiGet<{ sessions?: Session[] } | Session[]>("/auth/sessions")
      .then((r) => setSessions(Array.isArray(r) ? r : (r.sessions ?? [])))
      .catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const revoke = (id: string) =>
    apiSend("DELETE", `/auth/sessions/${id}`).then(load).catch((e) => setError(e.message));
  const revokeAll = () =>
    apiSend("POST", "/auth/sessions/revoke-all", { keep_current: true, reason: "User requested from security panel." })
      .then(load).catch((e) => setError(e.message));

  return (
    <section style={S.card}>
      <div style={S.h}>Active sessions</div>
      {error && <p style={S.err}>{error}</p>}
      {sessions === null && !error && <p style={S.muted}>Loading…</p>}
      {sessions?.map((s) => (
        <div key={s.id} style={S.row}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={S.rowTitle}>{s.current ? "This device" : (s.user_agent?.slice(0, 60) || "Session")}</div>
            <div style={S.rowSub}>{s.last_seen_at ? `last seen ${new Date(s.last_seen_at).toLocaleString()}` : s.id.slice(0, 8)}</div>
          </div>
          {!s.current && <button style={S.ghost} onClick={() => revoke(s.id)}>Revoke</button>}
        </div>
      ))}
      {sessions && sessions.length > 0 && (
        <button style={S.ghostWide} onClick={revokeAll}>Sign out everywhere else</button>
      )}
    </section>
  );
}

function ReauthCard({ email }: { email?: string }) {
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    setError(null);
    try {
      await apiSend("POST", "/auth/request-otp", { email });
      setSent(true); setMsg("Code sent to your email.");
    } catch (e) { setError((e as Error).message); }
  };
  const confirm = async () => {
    setError(null);
    try {
      await apiSend("POST", "/auth/sessions/reauthenticate", { code });
      setMsg("Identity confirmed — sensitive actions unlocked for a short window.");
      setCode("");
    } catch (e) { setError((e as Error).message); }
  };

  return (
    <section style={S.card}>
      <div style={S.h}>Confirm it's you</div>
      <p style={S.muted}>Deletion-class requests below require a fresh six-digit code, even mid-session.</p>
      <div style={{ display: "flex", gap: 8 }}>
        <button style={S.ghost} onClick={send}>{sent ? "Resend code" : "Send code"}</button>
        <input style={S.input} inputMode="numeric" maxLength={6} placeholder="123456"
          value={code} onChange={(e) => setCode(e.target.value)} />
        <button style={S.primary} disabled={code.length !== 6} onClick={confirm}>Confirm</button>
      </div>
      {msg && <p style={S.ok}>{msg}</p>}
      {error && <p style={S.err}>{error}</p>}
    </section>
  );
}

function PortabilityCard() {
  return (
    <section style={S.card}>
      <div style={S.h}>Your data, portable</div>
      <p style={S.muted}>Complete machine-readable exports — everything Acadensia holds, no lock-in.</p>
      <a style={S.linkBtn} href="/account/data-export">Download my account export</a>
    </section>
  );
}

function LifecycleCard() {
  const [requests, setRequests] = useState<Lifecycle[] | null>(null);
  const [reason, setReason] = useState("");
  const [kind, setKind] = useState("data_export");
  const [error, setError] = useState<string | null>(null);
  const load = () =>
    apiGet<{ requests?: Lifecycle[] } | Lifecycle[]>("/privacy/lifecycle-requests")
      .then((r) => setRequests(Array.isArray(r) ? r : (r.requests ?? [])))
      .catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const submit = () =>
    apiSend("POST", "/privacy/lifecycle-requests", { request_type: kind, reason })
      .then(() => { setReason(""); load(); })
      .catch((e) => setError(e.message));
  const cancel = (id: string) =>
    apiSend("POST", `/privacy/lifecycle-requests/${id}/cancel`).then(load).catch((e) => setError(e.message));

  return (
    <section style={S.card}>
      <div style={S.h}>Privacy requests</div>
      <p style={S.muted}>Formal export or deletion requests with an auditable trail. Deletion requires the confirmation step above.</p>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <select style={S.select} value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="data_export">Export my data (formal)</option>
          <option value="account_delete">Delete my account</option>
        </select>
      </div>
      <textarea style={S.textarea} rows={2} placeholder="Reason (required, min 5 characters)"
        value={reason} onChange={(e) => setReason(e.target.value)} />
      <button style={S.primary} disabled={reason.trim().length < 5} onClick={submit}>Submit request</button>
      {error && <p style={S.err}>{error}</p>}
      {requests && requests.length > 0 && (
        <div style={{ marginTop: 10 }}>
          {requests.map((r) => (
            <div key={r.id} style={S.row}>
              <div style={{ flex: 1 }}>
                <div style={S.rowTitle}>{r.request_type.replace(/_/g, " ")} — {r.status}</div>
                {r.created_at && <div style={S.rowSub}>{new Date(r.created_at).toLocaleString()}</div>}
              </div>
              {["pending", "received", "queued"].includes(r.status) && (
                <button style={S.ghost} onClick={() => cancel(r.id)}>Cancel</button>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

const S: Record<string, CSSProperties> = {
  card: { border: `1px solid ${T.line}`, borderRadius: 14, padding: "14px 16px", marginBottom: 14, background: T.card },
  h: { fontWeight: 600, fontSize: 13.5, marginBottom: 6, color: T.ink },
  muted: { color: T.muted, fontSize: 12.5, lineHeight: 1.5, margin: "0 0 10px" },
  row: { display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderTop: `1px solid ${T.line}` },
  rowTitle: { fontSize: 12.5, fontWeight: 600, color: T.ink, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" },
  rowSub: { fontSize: 11, color: T.muted },
  ghost: { fontFamily: "inherit", fontSize: 12, fontWeight: 600, padding: "7px 13px", borderRadius: 999, border: `1px solid ${T.lineStrong}`, background: "rgba(255,255,255,0.06)", color: T.ink, cursor: "pointer" },
  ghostWide: { fontFamily: "inherit", fontSize: 12, fontWeight: 600, padding: "8px 14px", borderRadius: 999, border: `1px solid ${T.lineStrong}`, background: "rgba(255,255,255,0.06)", color: T.ink, cursor: "pointer", marginTop: 10 },
  primary: { fontFamily: "inherit", fontSize: 12.5, fontWeight: 600, padding: "8px 16px", borderRadius: 999, border: 0, background: T.pillBg, color: T.pillInk, cursor: "pointer", marginTop: 8 },
  input: { flex: 1, fontFamily: T.mono, fontSize: 13, border: `1px solid ${T.line}`, background: "rgba(255,255,255,0.07)", color: T.ink, borderRadius: 10, padding: "8px 10px", letterSpacing: "0.2em" },
  select: { flex: 1, fontFamily: "inherit", fontSize: 12.5, border: `1px solid ${T.line}`, background: "rgba(255,255,255,0.07)", color: T.ink, borderRadius: 10, padding: "8px 10px" },
  textarea: { width: "100%", boxSizing: "border-box", fontFamily: "inherit", fontSize: 12.5, border: `1px solid ${T.line}`, background: "rgba(255,255,255,0.07)", color: T.ink, borderRadius: 10, padding: "8px 10px", resize: "vertical" },
  linkBtn: { display: "inline-block", fontSize: 12.5, fontWeight: 600, padding: "8px 16px", borderRadius: 999, background: T.pillBg, color: T.pillInk, textDecoration: "none" },
  err: { color: T.bad, fontSize: 12.5, marginTop: 8 },
  ok: { color: T.good, fontSize: 12.5, marginTop: 8 },
};
