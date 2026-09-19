/* The page veil. Moving between surfaces (landing, sign-in, the app) quietly fades the screen to the next page's own
   background colour, swaps the page underneath, and fades it back in only once the new page has loaded: its surface
   is mounted, sign-in state is known, and no API request has been in flight for a moment. There is no logo or
   spinner; if loading runs long, a hairline at the top shows it is still working. The first load of any page starts
   behind the same veil (index.html paints it before the app's code arrives), so there is never a half-drawn page.
   Links are picked up automatically; code that navigates on its own (sign in, sign out) calls `useCurtain().go`. */
import { AnimatePresence, motion } from "motion/react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { quietFor } from "../lib/loading";
import { surface } from "../lib/surface";

type Phase = "idle" | "cover" | "hold" | "reveal";
interface GoOptions { afterSwap?: () => void }
interface CurtainValue { go: (to: string, opts?: GoOptions) => void; active: boolean }

const CurtainContext = createContext<CurtainValue>({ go: () => {}, active: false });
export const useCurtain = () => useContext(CurtainContext);

const COVER_S = 0.3;
const REVEAL_S = 0.6;
const MIN_HOLD_MS = 120;
const MAX_HOLD_MS = 9000; // never trap anyone behind the veil
const QUIET_MS = 150;

/** The colour a surface is painted in, so the veil and the page it hands over to are the same. */
export function veilColor(path: string): string {
  return surface(path) === "app" ? "#f4f5f7" : "#ffffff";
}

export function CurtainProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { ready } = useAuth();
  const [phase, setPhase] = useState<Phase>("hold"); // first load starts covered
  const [color, setColor] = useState(() => veilColor(location.pathname));
  const job = useRef<{ to: string; afterSwap?: () => void; since: number }>({ to: location.pathname, since: performance.now() });
  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  const go = useCallback((to: string, opts: GoOptions = {}) => {
    if (phaseRef.current !== "idle") return;
    job.current = { to, afterSwap: opts.afterSwap, since: 0 };
    setColor(veilColor(new URL(to, window.location.href).pathname));
    setPhase("cover");
  }, []);

  // Fully covered: swap the page underneath, then wait for it to be ready.
  const covered = useCallback(() => {
    if (phaseRef.current !== "cover") return;
    job.current.since = performance.now();
    navigate(job.current.to);
    setPhase("hold");
  }, [navigate]);

  useEffect(() => {
    if (phase !== "hold") return;
    let swapped = false;
    const id = window.setInterval(() => {
      const { since, afterSwap } = job.current;
      // Wherever we ended up (a redirect, such as to sign-in, counts): only that page's surface is on screen.
      const target = surface(window.location.pathname);
      const mounted = document.querySelectorAll("[data-surface]");
      const onTarget = mounted.length === 1 && (mounted[0] as HTMLElement).dataset.surface === target;
      if (onTarget && !swapped) { swapped = true; afterSwap?.(); job.current.afterSwap = undefined; }
      const waited = performance.now() - since;
      if ((onTarget && ready && quietFor() >= QUIET_MS && waited >= MIN_HOLD_MS) || waited >= MAX_HOLD_MS) {
        window.clearInterval(id);
        setColor(veilColor(window.location.pathname));
        setPhase("reveal");
      }
    }, 50);
    return () => window.clearInterval(id);
  }, [phase, ready]);

  // The fade-in runs inside AnimatePresence; accept new trips once it has finished.
  useEffect(() => {
    if (phase !== "reveal") return;
    const t = window.setTimeout(() => setPhase("idle"), REVEAL_S * 1000);
    return () => window.clearTimeout(t);
  }, [phase]);

  // Any link to another surface goes through the veil.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a || (a.target && a.target !== "_self") || a.hasAttribute("download")) return;
      const url = new URL(a.href, window.location.href);
      if (url.origin !== window.location.origin || url.pathname.startsWith("/api")) return;
      if (surface(url.pathname) === surface(window.location.pathname)) return;
      e.preventDefault();
      e.stopPropagation(); // keep the router link from navigating straight away
      go(url.pathname + url.search + url.hash);
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [go]);

  // The boot veil painted by index.html is replaced by this one (same colour) on the first render.
  useEffect(() => { document.getElementById("boot")?.remove(); }, []);

  return (
    <CurtainContext.Provider value={{ go, active: phase !== "idle" }}>
      {children}
      <AnimatePresence>
        {phase === "cover" || phase === "hold" ? (
          <motion.div
            key="veil"
            className="curtain"
            aria-busy="true"
            aria-label="Loading"
            style={{ background: color }}
            initial={phase === "cover" ? { opacity: 0 } : false}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, transition: { duration: REVEAL_S, ease: [0.33, 0, 0.2, 1] } }}
            transition={{ duration: COVER_S, ease: [0.4, 0, 0.2, 1] }}
            onAnimationComplete={covered}
          >
            {phase === "hold" ? <span className="curtain-line" /> : null}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </CurtainContext.Provider>
  );
}
