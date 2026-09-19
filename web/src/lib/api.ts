/* API client. Every request carries the session's bearer token (Supabase access token, local session JWT, or a
   personal MCP token). A 401 raises the app-wide `finmcp:unauthorized` event so the auth layer can react. */
import { track } from "./loading";
import type { ChatEvent } from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Params = Record<string, string | number | boolean | null | undefined>;

let authToken: string | null = null;
export function setAuthToken(token: string | null): void {
  authToken = token;
}
export function getAuthToken(): string | null {
  return authToken;
}

export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return authToken ? { ...extra, Authorization: `Bearer ${authToken}` } : extra;
}

function qs(params?: Params): string {
  if (!params) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** Every request goes through here, so the page curtain knows when a screen has finished loading. */
const tracked = (url: string, init?: RequestInit) => track(fetch(url, init));

async function handle<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T;
  if (res.status === 401 && !res.url.includes("/api/auth/")) window.dispatchEvent(new Event("finmcp:unauthorized"));
  let message = res.statusText;
  try {
    const body = await res.json();
    message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
  } catch {
    /* keep statusText */
  }
  throw new ApiError(res.status, message);
}

const json = () => ({ "Content-Type": "application/json", ...authHeaders() });

export const api = {
  get: <T>(path: string, params?: Params) => tracked(`/api${path}${qs(params)}`, { headers: authHeaders() }).then((r) => handle<T>(r)),
  post: <T>(path: string, body?: unknown, params?: Params) =>
    tracked(`/api${path}${qs(params)}`, { method: "POST", headers: json(), body: body === undefined ? undefined : JSON.stringify(body) }).then((r) => handle<T>(r)),
  patch: <T>(path: string, body: unknown) => tracked(`/api${path}`, { method: "PATCH", headers: json(), body: JSON.stringify(body) }).then((r) => handle<T>(r)),
  put: <T>(path: string, body: unknown) => tracked(`/api${path}`, { method: "PUT", headers: json(), body: JSON.stringify(body) }).then((r) => handle<T>(r)),
  del: <T>(path: string) => tracked(`/api${path}`, { method: "DELETE", headers: authHeaders() }).then((r) => handle<T>(r)),
  upload: <T>(path: string, form: FormData) => tracked(`/api${path}`, { method: "POST", body: form, headers: authHeaders() }).then((r) => handle<T>(r)),
  /** Fetch a file (CSV export) and hand it to the browser as a download. */
  download: async (path: string, filename: string) => {
    const res = await tracked(`/api${path}`, { headers: authHeaders() });
    if (!res.ok) await handle(res);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  },
};

export async function streamChat(message: string, conversationId: string | null, onEvent: (ev: ChatEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: json(),
    body: JSON.stringify({ message, conversation_id: conversationId ?? undefined }),
    signal,
  });
  if (!res.ok || !res.body) {
    if (res.status === 401) window.dispatchEvent(new Event("finmcp:unauthorized"));
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 1);
      if (line) onEvent(JSON.parse(line) as ChatEvent);
    }
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer.trim()) as ChatEvent);
}
