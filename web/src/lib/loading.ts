/* Counts API requests in flight, so the page curtain (components/Curtain) can stay up until a new page has
   finished loading instead of revealing it half-empty. */
let pending = 0;
let settledAt = 0;
let quiet = 0;

/** Start requests that should not hold the veil (a background refresh of data already on screen). The requests
    are sent synchronously inside `start`, which is when `track` sees them. */
export function quietly<T>(start: () => Promise<T>): Promise<T> {
  quiet += 1;
  try { return start(); } finally { quiet -= 1; }
}

export function track<T>(p: Promise<T>): Promise<T> {
  if (quiet) return p;
  pending += 1;
  return p.finally(() => { pending -= 1; settledAt = performance.now(); });
}

/** Milliseconds since the last request settled, or 0 while any is still running. */
export function quietFor(): number {
  return pending > 0 ? 0 : performance.now() - settledAt;
}
