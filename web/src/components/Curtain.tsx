/* The page veil. The first load plays the intro: "FinMCP" is laid down as solid blocks that turn into letters, the
   letters collapse into a ring, and once the page underneath has loaded the ring zooms past the camera so the page
   appears through its hole. Moving between surfaces (landing, sign-in, the app) runs the same ring in reverse: it
   closes over the old page, the new one is swapped in and loads behind it, and the ring opens again.
   "Loaded" means: its surface is mounted, sign-in state is known, and no API request has been in flight for a moment.
   index.html paints the veil colour before the app's code arrives, so there is never a half-drawn page.
   Links are picked up automatically; code that navigates on its own (sign in, sign out) calls `useCurtain().go`. */
import { animate, motion, useMotionValue, useReducedMotion, useTransform, type MotionValue } from "motion/react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { quietFor } from "../lib/loading";
import { surface } from "../lib/surface";

type Phase = "intro" | "idle" | "cover" | "hold" | "reveal";
interface GoOptions { afterSwap?: () => void }
interface CurtainValue { go: (to: string, opts?: GoOptions) => void; active: boolean }

const CurtainContext = createContext<CurtainValue>({ go: () => {}, active: false });
export const useCurtain = () => useContext(CurtainContext);

const EASE = [0.76, 0, 0.24, 1] as const;
const COVER_S = 0.75;
const REVEAL_S = 1.1;
const MIN_HOLD_MS = 120;
const MAX_HOLD_MS = 9000; // never trap anyone behind the veil
const QUIET_MS = 150;
const WORD = "FinMCP";

/** The colour a surface is painted in, so the veil and the page it hands over to are the same. */
export function veilColor(path: string): string {
  return surface(path) === "app" ? "#f4f5f7" : "#ffffff";
}

export function CurtainProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { ready } = useAuth();
  const reduced = useReducedMotion();
  const [phase, setPhase] = useState<Phase>(reduced ? "hold" : "intro"); // the first load starts covered
  const [ring, setRing] = useState(false);
  const [color, setColor] = useState(() => veilColor(location.pathname));
  const open = useMotionValue(0); // 0: the ring is a small mark, 1: its hole is bigger than the screen
  const job = useRef<{ to: string; afterSwap?: () => void; since: number }>({ to: location.pathname, since: performance.now() });
  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  const go = useCallback((to: string, opts: GoOptions = {}) => {
    if (phaseRef.current !== "idle") return;
    job.current = { to, afterSwap: opts.afterSwap, since: 0 };
    setColor(veilColor(new URL(to, window.location.href).pathname));
    setRing(true);
    setPhase("cover");
    open.set(1);
    // Closed over the old page: swap in the new one underneath, then wait for it to be ready.
    void animate(open, 0, { duration: reduced ? 0 : COVER_S, ease: EASE }).then(() => {
      job.current.since = performance.now();
      navigate(job.current.to);
      setPhase("hold");
    });
  }, [navigate, open, reduced]);

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
        setRing(true);
        setPhase("reveal");
        void animate(open, 1, { duration: reduced ? 0 : REVEAL_S, ease: EASE }).then(() => setPhase("idle"));
      }
    }, 50);
    return () => window.clearInterval(id);
  }, [phase, ready, open, reduced]);

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

  const introDone = useCallback(() => setPhase((p) => (p === "intro" ? "hold" : p)), []);
  const showRing = useCallback(() => setRing(true), []);

  return (
    <CurtainContext.Provider value={{ go, active: phase !== "idle" }}>
      {children}
      {phase !== "idle" ? (
        <div className="veil" aria-busy="true" aria-label="Loading"
          style={{ "--veil": color, background: phase === "intro" || (phase === "hold" && !ring) ? color : "transparent" } as CSSProperties}>
          {phase === "intro" ? <Wordmark onRing={showRing} onDone={introDone} /> : null}
          {ring ? <Ring open={open} pop={phase === "intro"} breathe={phase === "hold"} /> : null}
        </div>
      ) : null}
    </CurtainContext.Provider>
  );
}

/** A thick rounded ring whose hole shows the page. Everything outside it is the veil colour, so at open = 0 it is a
    mark on a plain screen and at open = 1 the hole is larger than the screen and nothing of the veil is left. */
function Ring({ open, pop, breathe }: { open: MotionValue<number>; pop: boolean; breathe: boolean }) {
  const geo = (v: number) => {
    const W = window.innerWidth, H = window.innerHeight, s = Math.min(1, W / 520);
    const e = v * v; // the ring thickens first, then the hole races open
    const w = 60 * s + e * (1.6 * W - 60 * s), h = 24 * s + e * (1.6 * H - 24 * s), t = 34 * s + v * 0.7 * Math.max(W, H);
    return { w, h, t };
  };
  const width = useTransform(open, (v) => geo(v).w);
  const height = useTransform(open, (v) => geo(v).h);
  const marginLeft = useTransform(open, (v) => -geo(v).w / 2);
  const marginTop = useTransform(open, (v) => -geo(v).h / 2);
  const borderRadius = useTransform(open, (v) => Math.min(geo(v).w, geo(v).h) / 2);
  const boxShadow = useTransform(open, (v) => { const { t } = geo(v); return `0 0 0 ${t}px #111114, 0 0 0 ${t + 4000}px var(--veil)`; });
  const fill = useTransform(open, [0, 0.05, 0.32], [1, 1, 0]);
  return (
    <motion.div className="veil-pop" initial={pop ? { scale: 0.35, opacity: 0 } : false} animate={{ scale: 1, opacity: 1 }}
      transition={{ type: "spring", stiffness: 420, damping: 26 }}>
      <motion.div className={`iris ${breathe ? "breathe" : ""}`} style={{ width, height, marginLeft, marginTop, borderRadius, boxShadow }}>
        <motion.i style={{ opacity: fill }} />
      </motion.div>
    </motion.div>
  );
}

/** The intro: solid blocks grow left to right, turn into the letters of FinMCP, then fold into the middle. Each stage
    starts when the last letter finishes the one before, so a busy first load slows the intro down rather than
    scrambling it. */
function Wordmark({ onRing, onDone }: { onRing: () => void; onDone: () => void }) {
  const [stage, setStage] = useState(0); // 0 waiting for the font, 1 blocks, 2 letters, 3 collapse
  const [dx, setDx] = useState<number[]>([]);
  const refs = useRef<(HTMLSpanElement | null)[]>([]);
  const box = useRef<HTMLDivElement>(null);
  const blur = useRef<SVGFEGaussianBlurElement>(null);
  const last = WORD.length - 1;

  useEffect(() => {
    let alive = true;
    const font = document.fonts?.load("900 120px Figtree").catch(() => undefined) ?? Promise.resolve();
    void Promise.race([font, new Promise((r) => setTimeout(r, 700))]).then(() => { if (alive) setStage(1); });
    return () => { alive = false; };
  }, []);

  const collapse = () => {
    const mid = box.current ? box.current.getBoundingClientRect().left + box.current.clientWidth / 2 : window.innerWidth / 2;
    setDx(refs.current.map((el) => { const r = el?.getBoundingClientRect(); return r ? mid - (r.left + r.width / 2) : 0; }));
    setStage(3);
    window.setTimeout(onRing, 200);
  };

  // The morph: blocks fade out as letters fade in, seen through a "goo" filter (blur, then a hard alpha threshold), so
  // the solid shapes melt into the letterforms instead of cross-fading. The blur swells and settles back to zero.
  useEffect(() => {
    if (stage !== 2) return;
    const em = box.current ? parseFloat(getComputedStyle(box.current).fontSize) : 120;
    const ctl = animate(0, 1, { duration: 0.8, ease: "linear", onUpdate: (p) => blur.current?.setAttribute("stdDeviation", String(Math.sin(Math.PI * p) * em * 0.07)) });
    return () => ctl.stop();
  }, [stage]);

  return (
    <div className="intro-word" ref={box} aria-hidden style={{ filter: stage === 2 ? "url(#intro-goo)" : undefined }}>
      <svg width="0" height="0" style={{ position: "absolute" }}>
        <filter id="intro-goo" x="-20%" y="-40%" width="140%" height="180%">
          <feGaussianBlur ref={blur} in="SourceGraphic" stdDeviation="0" result="b" />
          <feColorMatrix in="b" mode="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 24 -10" />
        </filter>
      </svg>
      {[...WORD].map((c, i) => (
        <motion.span key={i} className="intro-ch" ref={(el) => { refs.current[i] = el; }}
          animate={stage === 3 ? { x: dx[i] ?? 0, scale: 0.3, opacity: 0 } : { x: 0, scale: 1, opacity: 1 }}
          transition={{ duration: stage === 3 ? 0.42 : 0, ease: [0.7, 0, 0.84, 0], delay: stage === 3 ? Math.abs(i - 2.5) * 0.015 : 0 }}
          onAnimationComplete={() => { if (stage === 3 && i === 0) onDone(); }}>
          <motion.i className="blk" initial={{ scaleX: 0 }}
            animate={stage === 0 ? { scaleX: 0 } : stage === 1 ? { scaleX: 1 } : { scaleX: 1, opacity: 0 }}
            transition={stage === 1 ? { duration: 0.34, ease: [0.22, 1, 0.36, 1], delay: i * 0.07 } : { duration: 0.5, ease: "easeInOut", delay: i * 0.05 }}
            onAnimationComplete={() => { if (stage === 1 && i === last) window.setTimeout(() => setStage(2), 120); }} />
          <motion.span className="gl" initial={{ opacity: 0 }} animate={{ opacity: stage >= 2 ? 1 : 0 }}
            transition={{ duration: 0.5, ease: "easeInOut", delay: stage === 2 ? i * 0.05 : 0 }}
            onAnimationComplete={() => { if (stage === 2 && i === last) window.setTimeout(collapse, 420); }}>{c}</motion.span>
        </motion.span>
      ))}
    </div>
  );
}
