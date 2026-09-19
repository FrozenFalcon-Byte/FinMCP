/* Browser-side read cache. A screen that was loaded before renders its last data instantly, and does not ask the
   server again unless the ledger changed since (any write, here or through MCP) or the copy is older than FRESH_MS.
   Entries are also kept in localStorage per account, so a reload or a new tab paints from cache and refreshes
   quietly behind it. Everything is dropped on sign-out. */

const FRESH_MS = 5 * 60_000;
const MAX_ENTRY = 1_500_000; // characters; bigger payloads stay in memory only
const PREFIX = "finmcp.cache.";
const KEEP_MS = 7 * 24 * 3600_000; // saved copies older than this are dropped

interface Entry { data: unknown; at: number; disk?: boolean }

let owner: string | null = null;
let mem = new Map<string, Entry>();
let staleBefore = 0;
let saveTimer: number | null = null;

function storageKey(user: string) { return PREFIX + user; }

/** Point the cache at an account: loads its saved entries, and forgets another account's. */
export function setCacheOwner(user: string | null) {
  if (user === owner) return;
  owner = user;
  mem = new Map();
  staleBefore = 0;
  if (!user) return;
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey(user)) ?? "{}") as Record<string, Entry>;
    for (const [k, e] of Object.entries(saved)) mem.set(k, { data: e.data, at: e.at, disk: true });
  } catch { /* unreadable or blocked storage: start empty */ }
}

function persist() {
  if (saveTimer !== null || !owner) return;
  saveTimer = window.setTimeout(() => {
    saveTimer = null;
    if (!owner) return;
    const out: Record<string, { data: unknown; at: number }> = {};
    for (const [k, e] of mem) {
      if (Date.now() - e.at > KEEP_MS) continue;
      const s = JSON.stringify(e.data);
      if (s && s.length <= MAX_ENTRY) out[k] = { data: e.data, at: e.at };
    }
    try { localStorage.setItem(storageKey(owner), JSON.stringify(out)); } catch {
      try { localStorage.removeItem(storageKey(owner)); } catch { /* storage unavailable */ }
    }
  }, 400);
}

export function peek<T>(key: string): T | undefined {
  return mem.get(key)?.data as T | undefined;
}

/** Fresh means: fetched in this page load, after the last ledger change, within FRESH_MS. */
export function isFresh(key: string): boolean {
  const e = mem.get(key);
  return !!e && !e.disk && e.at >= staleBefore && Date.now() - e.at < FRESH_MS;
}

/** `startedAt` is when the request went out, so a write that lands mid-flight still marks the result stale. */
export function put(key: string, data: unknown, startedAt: number) {
  mem.set(key, { data, at: startedAt });
  persist();
}

/** The ledger changed: every cached read is now suspect (screens on show refetch on their own). */
export function markStale() {
  staleBefore = Date.now();
}

export function clearCache() {
  mem = new Map();
  staleBefore = 0;
  try {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (k?.startsWith(PREFIX)) localStorage.removeItem(k);
    }
  } catch { /* storage unavailable */ }
  owner = null;
}
