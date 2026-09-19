/* Tiny data hook: fetch on mount and whenever the ledger version (or your deps) change. */
import { useCallback, useEffect, useRef, useState } from "react";
import { useLedger } from "./ledger";

export function useApi<T>(load: () => Promise<T>, deps: unknown[] = [], opts: { live?: boolean } = {}) {
  const { version } = useLedger();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const live = opts.live ?? true;
  const run = useCallback(async () => {
    const id = ++seq.current;
    try {
      const d = await load();
      if (id === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (id === seq.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (id === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { void run(); }, [run, live ? version : 0]);
  return { data, error, loading, reload: run, setData };
}
