/* Data hook: paints from the browser cache (lib/cache) when this request was made before, and only goes to the
   server when that copy is stale: the ledger changed since, it came from an earlier visit, or it has aged out. */
import { useCallback, useEffect, useRef, useState } from "react";
import { isFresh, peek, put } from "./cache";
import { quietly } from "./loading";
import { useLedger } from "./ledger";

export function useApi<T>(load: () => Promise<T>, deps: unknown[] = [], opts: { live?: boolean; key?: string } = {}) {
  const { version } = useLedger();
  // The loader's source plus its inputs name the request, e.g. `() => api.get("/budget", { month })` with [month].
  const key = opts.key ?? load.toString() + JSON.stringify(deps);
  const [data, setData] = useState<T | null>(() => peek<T>(key) ?? null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(() => peek(key) === undefined);
  const seq = useRef(0);
  const live = opts.live ?? true;

  const fetchFresh = useCallback(async (force: boolean) => {
    const id = ++seq.current;
    const cached = peek<T>(key);
    if (cached !== undefined) { setData(cached); setLoading(false); } else setLoading(true);
    if (!force && isFresh(key)) return;
    const started = Date.now();
    try {
      // Refreshing something already on screen never holds the page veil; only a first load does.
      const d = await (cached !== undefined ? quietly(load) : load());
      put(key, d, started);
      if (id === seq.current) { setData(d); setError(null); }
    } catch (e) {
      // With something already on screen, keep it; the top bar already says when the API is unreachable.
      if (id === seq.current && cached === undefined) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (id === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  // A ledger change marks the cache stale (lib/ledger), so the version bump below refetches on its own.
  useEffect(() => { void fetchFresh(false); }, [fetchFresh, live ? version : 0]);
  const reload = useCallback(() => fetchFresh(true), [fetchFresh]);
  return { data, error, loading, reload, setData };
}
