/** Small fetch helpers for the coverage panels (same conventions as useFeatures). */

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(path, { credentials: "include" });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

export async function apiSend<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    credentials: "include",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await errText(r));
  if (r.status === 204) return undefined as T;
  return r.json();
}

async function errText(r: Response): Promise<string> {
  try {
    const j = await r.json();
    const d = j.detail ?? j;
    return typeof d === "string" ? d : JSON.stringify(d);
  } catch {
    return `Request failed (${r.status})`;
  }
}
