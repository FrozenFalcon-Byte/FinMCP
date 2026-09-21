/* Cold starts, made honest.

   The API is on a free tier that stops the container after a quarter of an hour of quiet, so the first request
   after a lull hangs while it boots again — around fifty seconds. Left unexplained that reads as a broken app, so
   this watches reachability and says what is happening: a card with a bar that fills over the expected wait, and a
   toast when the backend answers. Requests report in through `finmcp:online` / `finmcp:offline` (see lib/api.ts);
   a probe of /api/health drives the rest. */
import { AnimatePresence, motion } from "motion/react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { apiUrl } from "../lib/api";
import { useToast } from "./Toast";
import { Icon } from "./ui";

/** How long a healthy backend may take before we assume it is asleep rather than slow. */
const SLOW_MS = 2600;
/** What a cold start costs on the free tier; the bar is paced to it. */
const WAKE_MS = 50_000;
/** After this we stop guessing and offer a retry instead. */
const GIVE_UP_MS = 150_000;
const POLL_MS = 4000;
/** A sleeping container holds the connection open while it boots, but a dropped network holds it open forever.
    Abandoning each attempt keeps the loop moving either way. */
const PING_TIMEOUT_MS = 20_000;

export type Reach = "online" | "waking" | "down";
interface WakeValue { reach: Reach; since: number | null; check: () => void }

const WakeContext = createContext<WakeValue>({ reach: "online", since: null, check: () => {} });

async function ping(): Promise<boolean> {
  const abort = new AbortController();
  const timer = window.setTimeout(() => abort.abort(), PING_TIMEOUT_MS);
  try {
    const res = await fetch(apiUrl("/health"), { signal: abort.signal, cache: "no-store" });
    return res.ok; // /api/health answers 503 until the MCP registry has finished starting
  } catch {
    return false;
  } finally {
    window.clearTimeout(timer);
  }
}

export function WakeProvider({ children }: { children: ReactNode }) {
  const [reach, setReach] = useState<Reach>("online");
  const [since, setSince] = useState<number | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const toast = useToast();
  const running = useRef(false);
  const confirmed = useRef(false); // a real request succeeded; stop probing
  const noticed = useRef(false);   // the card was shown for this outage, so recovery is worth announcing
  const startedAt = useRef(0);
  const reachRef = useRef<Reach>("online");
  reachRef.current = reach;

  /** Back to normal. Clears the notice and, if the person saw it, says so. Safe to call more than once. */
  const settle = useCallback(() => {
    setReach("online");
    setSince(null);
    if (!noticed.current) return;
    noticed.current = false;
    const took = Math.round((Date.now() - startedAt.current) / 1000);
    toast(took > 5 ? `Back online · woke in ${took}s.` : "Back online.");
  }, [toast]);

  /* One probe loop at a time. It keeps asking until the backend answers, showing the notice once the wait stops
     looking like ordinary latency. Each attempt is bounded, so a connection that simply hangs still retries. */
  const check = useCallback(() => {
    if (running.current) return;
    running.current = true;
    const started = Date.now();
    startedAt.current = started;
    confirmed.current = false;
    void (async () => {
      const slow = window.setTimeout(() => {
        if (!running.current) return;
        noticed.current = true;
        setSince(started);
        setDismissed(false);
        setReach("waking");
      }, SLOW_MS);
      try {
        for (;;) {
          if (confirmed.current || (await ping())) return settle();
          if (Date.now() - started > GIVE_UP_MS) return setReach("down");
          await new Promise((r) => setTimeout(r, POLL_MS));
        }
      } finally {
        window.clearTimeout(slow);
        running.current = false;
      }
    })();
  }, [settle]);

  useEffect(() => {
    check();
    const onDown = () => { if (reachRef.current === "online") check(); };
    const onUp = () => { confirmed.current = true; if (reachRef.current !== "online") settle(); };
    window.addEventListener("finmcp:offline", onDown);
    window.addEventListener("finmcp:online", onUp);
    // A tab left in the background misses the container going to sleep; re-check when it comes back.
    const onVisible = () => { if (document.visibilityState === "visible") check(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("finmcp:offline", onDown);
      window.removeEventListener("finmcp:online", onUp);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [check, settle]);

  const open = reach !== "online" && !dismissed;
  return (
    <WakeContext.Provider value={{ reach, since, check }}>
      {children}
      <AnimatePresence>{open ? <WakeCard reach={reach} since={since} onClose={() => setDismissed(true)} onRetry={check} /> : null}</AnimatePresence>
    </WakeContext.Provider>
  );
}

/** Seconds waited so far, ticking once a second. */
function useElapsed(since: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (since === null) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [since]);
  return since === null ? 0 : Math.max(0, Math.round((now - since) / 1000));
}

function WakeCard({ reach, since, onClose, onRetry }: { reach: Reach; since: number | null; onClose: () => void; onRetry: () => void }) {
  const waited = useElapsed(since);
  const down = reach === "down";
  const inApp = useLocation().pathname.startsWith("/app"); // only there does a tab bar need clearing on a phone
  return (
    <motion.div className={`wake-wrap ${inApp ? "in-app" : ""}`} role="status" aria-live="polite"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.25 }}>
      <motion.div className={`wake ${down ? "down" : ""}`}
        initial={{ opacity: 0, y: 28, scale: 0.94, filter: "blur(8px)" }}
        animate={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)" }}
        exit={{ opacity: 0, y: 16, scale: 0.96, filter: "blur(6px)" }}
        transition={{ type: "spring", stiffness: 340, damping: 30, mass: 0.9 }}>
        <div className="wake-head">
          <span className="wake-orb" aria-hidden><span className={down ? "dead" : "pulse"} /></span>
          <div>
            <b>{down ? "The backend is not answering" : "Waking the server"}</b>
            <span>{down
              ? "It has been quiet for a while now. Give it another try, or come back in a minute."
              : "Free hosting stops the API after 15 minutes of quiet. The first request wakes it, which takes about 50 seconds."}</span>
          </div>
          <button className="wake-x" onClick={onClose} aria-label="Dismiss"><Icon name="x" /></button>
        </div>
        {down ? null : (
          <div className="wake-bar" aria-hidden>
            {/* Paced to the expected cold start, then it eases to a crawl rather than pretending to finish. */}
            <motion.i initial={{ width: "4%" }} animate={{ width: ["4%", "88%", "96%"] }}
              transition={{ duration: WAKE_MS / 1000 + 40, times: [0, 0.55, 1], ease: "easeOut" }} />
          </div>
        )}
        <div className="wake-foot">
          <span className="num">{waited}s</span>
          {down ? <button className="wake-retry" onClick={onRetry}>Try again</button>
            : <span>Everything you have already loaded still works.</span>}
        </div>
      </motion.div>
    </motion.div>
  );
}

export const useWake = () => useContext(WakeContext);
