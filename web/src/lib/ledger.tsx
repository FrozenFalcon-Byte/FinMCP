/* Live ledger sync. Any write in the app bumps `version`; the account's change feed (SSE) reports writes made by
   every other client (Claude Desktop through the MCP endpoint, the CLI, another tab), and Supabase Realtime covers
   processes that write to Postgres directly. A slow poll is the safety net. Screens re-fetch on `version`. */
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import { useAuth } from "./auth";
import { subscribeEvents, type LedgerEvent } from "./events";
import { useStatus } from "./status";
import { markStale, setCacheOwner } from "./cache";

interface LedgerStatus { transactions: number; uncategorized: number; needs_review: number; last_date: string | null; merchant_memory: number; goals: number }

interface LedgerValue {
  version: number;
  bump: () => void;
  lastSync: number | null;
  live: boolean;
  lastEvent: LedgerEvent | null;
}

const POLL_MS = 30000;
const LedgerContext = createContext<LedgerValue>({ version: 0, bump: () => {}, lastSync: null, live: false, lastEvent: null });

export function LedgerProvider({ children }: { children: ReactNode }) {
  const { refresh } = useStatus();
  const { token, supabase, user } = useAuth();
  setCacheOwner(user?.id ?? null); // before any screen below reads the cache
  const [version, setVersion] = useState(0);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [live, setLive] = useState(false);
  const [lastEvent, setLastEvent] = useState<LedgerEvent | null>(null);
  const signature = useRef<string | null>(null);
  const debounce = useRef<number | null>(null);

  const bump = useCallback(() => {
    signature.current = null;
    markStale();
    setVersion((v) => v + 1);
    void refresh();
  }, [refresh]);

  const bumpSoon = useCallback((ev: LedgerEvent | null) => {
    if (ev) setLastEvent(ev);
    if (debounce.current) window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(() => { debounce.current = null; bump(); }, 250);
  }, [bump]);

  // change feed
  useEffect(() => {
    if (!token) return;
    const stop = subscribeEvents((ev) => {
      window.dispatchEvent(new CustomEvent("finmcp:event", { detail: ev }));
      if (ev.type === "change") bumpSoon(ev);
      else if (ev.type === "hello") setLastSync(Date.now());
    }, setLive);
    const onLocal = () => bump();
    window.addEventListener("finmcp:ledger-changed", onLocal);
    return () => { stop(); window.removeEventListener("finmcp:ledger-changed", onLocal); };
  }, [token, bump, bumpSoon]);

  // Supabase Realtime (optional): rows changed by processes that talk to Postgres directly
  useEffect(() => {
    if (!supabase || !user) return;
    const channel = supabase.channel(`ledger:${user.id}`)
      .on("postgres_changes", { event: "*", schema: "public", table: "transactions", filter: `user_id=eq.${user.id}` }, () => bumpSoon({ type: "change", entity: "transaction", client: "realtime" }))
      .subscribe();
    return () => { void supabase.removeChannel(channel); };
  }, [supabase, user, bumpSoon]);

  // safety-net poll
  useEffect(() => {
    if (!token) return;
    let stopped = false;
    const tick = async () => {
      try {
        const s = await api.get<LedgerStatus>("/status");
        if (stopped) return;
        const next = `${s.transactions}|${s.uncategorized}|${s.needs_review}|${s.last_date}|${s.merchant_memory}|${s.goals}`;
        if (signature.current !== null && next !== signature.current) { setVersion((v) => v + 1); void refresh(); }
        signature.current = next;
        setLastSync(Date.now());
      } catch { /* the SSE state carries liveness */ }
    };
    void tick();
    const t = setInterval(() => { if (document.visibilityState === "visible") void tick(); }, POLL_MS);
    const onVisible = () => { if (document.visibilityState === "visible") void tick(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { stopped = true; clearInterval(t); document.removeEventListener("visibilitychange", onVisible); };
  }, [token, refresh]);

  return <LedgerContext.Provider value={{ version, bump, lastSync, live, lastEvent }}>{children}</LedgerContext.Provider>;
}

export const useLedger = () => useContext(LedgerContext);
