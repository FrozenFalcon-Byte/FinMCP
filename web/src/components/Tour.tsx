/* The walkthrough.

   A first look at a finance app is mostly "where is the thing I want". This points at the real controls rather than
   describing them in a paragraph nobody reads: the page dims, one element stays lit, and a card says what it is for.

   It is deliberately quiet — six stops, arrow keys, and Esc leaves at any point. A stop whose element is not on
   screen (the sidebar on a phone, a nav item behind the More sheet) is skipped rather than pointed at emptily, so
   the same script works on both layouts. Finishing or skipping writes `tour_seen_at`, so it never ambushes anyone
   twice; Help can start it again on purpose. */
import { AnimatePresence, motion } from "motion/react";
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Icon } from "./ui";

const SPRING = { type: "spring", stiffness: 380, damping: 34, mass: 0.8 } as const;
const PAD = 8;       // breathing room around the lit element
const GAP = 14;      // between the hole and the card
const CARD = 320;
const CARD_H = 216;  // roughly; only used to decide which side of the target the card goes on

interface Stop {
  /** Candidate selectors, most specific first. The first one actually on screen is the one that gets lit. */
  sel: string;
  title: string;
  body: string;
}

const STOPS: Stop[] = [
  { sel: ".sidebar .nav, .tabbar", title: "Everything lives here",
    body: "Transactions is the ledger itself. Budgets, Goals, Subscriptions and EMIs are the parts of it worth watching on their own." },
  { sel: ".omni", title: "One box for finding things",
    body: "Type a merchant, a category, anything. It drops you into Transactions with the results already filtered — no separate search page." },
  { sel: ".topbar-add, .fab", title: "Adding takes one line",
    body: "Write it the way you would say it: “450 swiggy”, “rent 25000 yesterday”, “890 from company”. It works out the amount, the date and which way the money went. Press N from anywhere." },
  { sel: "[data-tour='pulse']", title: "The month at a glance",
    body: "Spent so far, how that compares with last month, and what is safe to spend per day — worked out from the income and budgets you just set." },
  { sel: "a[href='/app/ask']", title: "Ask instead of hunting",
    body: "“What did I spend on food in August?” The assistant answers from your own ledger, and shows the tool calls it made to get there." },
  { sel: "a[href='/app/mcp']", title: "The engine room",
    body: "Every screen here is an MCP client talking to your ledger. This tab lets you watch that happen live, and Connect hands the same tools to Claude." },
  { sel: "a[href='/app/help']", title: "Help is always here",
    body: "A short map of the app, the keyboard shortcuts, and this walkthrough again whenever you want it." },
];

interface Box { top: number; left: number; width: number; height: number }

/** On screen, not merely in the DOM. The sidebar still has a box when it is parked off to the left on a phone, and
    pointing at something nobody can see is worse than skipping the stop. */
const onScreen = (el: HTMLElement): boolean => {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && r.right > 8 && r.bottom > 8
    && r.left < window.innerWidth - 8 && r.top < window.innerHeight - 8
    && getComputedStyle(el).visibility !== "hidden";
};

const find = (sel: string): HTMLElement | null => {
  for (const one of sel.split(",")) {
    const el = document.querySelector<HTMLElement>(one.trim());
    if (el && onScreen(el)) return el;
  }
  return null;
};

const TourContext = createContext<{ start: () => void; running: boolean }>({ start: () => {}, running: false });
export const useTour = () => useContext(TourContext);

export function TourProvider({ children }: { children: ReactNode }) {
  const { user, refreshUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [running, setRunning] = useState(false);
  const [i, setI] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  const asked = useRef(false);

  /** Stops whose target is actually on this screen, so the phone gets its own shorter run. Taken again once the
      page has settled: started from Help, the tour opens while the dashboard it points at is still arriving. */
  const [stops, setStops] = useState<Stop[]>(STOPS);
  useEffect(() => {
    if (!running) return;
    const settle = () => setStops(STOPS.filter((s) => find(s.sel)));
    settle();
    const t = window.setTimeout(settle, 500);
    return () => window.clearTimeout(t);
  }, [running, location.pathname]);

  const start = useCallback(() => { setI(0); setRunning(true); }, []);

  // A new account is shown around once, after the setup, and only on the dashboard where the targets live.
  useEffect(() => {
    if (asked.current || !user?.onboarded_at || user.tour_seen_at || location.pathname !== "/app") return;
    asked.current = true;
    const t = window.setTimeout(start, 900);   // let the page settle first; a tour over a skeleton points at nothing
    return () => window.clearTimeout(t);
  }, [user, location.pathname, start]);

  const stop = useCallback(async () => {
    setRunning(false);
    if (user && !user.tour_seen_at) {
      try { await api.patch("/auth/profile", { tour_seen: true }); await refreshUser(); } catch { /* it simply runs again */ }
    }
  }, [user, refreshUser]);

  // Measure the lit element, and keep measuring: the layout shifts as the page finishes loading.
  useLayoutEffect(() => {
    if (!running) { setBox(null); return; }
    const target = stops[i] ? find(stops[i].sel) : null;
    if (!target) { setBox(null); return; }
    target.scrollIntoView({ block: "nearest", behavior: "smooth" });
    const measure = () => {
      const r = target.getBoundingClientRect();
      setBox({ top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 });
    };
    measure();
    const frame = window.setInterval(measure, 250);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => { window.clearInterval(frame); window.removeEventListener("resize", measure); window.removeEventListener("scroll", measure, true); };
  }, [running, i, stops]);

  const next = useCallback(() => { if (i + 1 >= stops.length) void stop(); else setI((n) => n + 1); }, [i, stops.length, stop]);

  useEffect(() => {
    if (!running) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); void stop(); }
      if (e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); next(); }
      if (e.key === "ArrowLeft") { e.preventDefault(); setI((n) => Math.max(0, n - 1)); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [running, next, stop]);

  // The tour points at the dashboard, so send it there first if we are somewhere else.
  useEffect(() => { if (running && location.pathname !== "/app") navigate("/app"); }, [running, location.pathname, navigate]);

  const stopNow = stops[Math.min(i, stops.length - 1)];
  /** Beside the lit element if it fits, then under it, then over it — and for something taller than the screen
      (the whole hero card), pinned to the bottom edge, where it covers the least of what is being pointed at. */
  const place = ((): { top: number; left: number } => {
    if (!box) return { top: 0, left: 0 };
    const vw = window.innerWidth, vh = window.innerHeight;
    const beside = box.left + box.width + GAP;
    if (beside + CARD < vw - 16) return { left: beside, top: Math.max(16, Math.min(box.top, vh - CARD_H - 16)) };
    const left = Math.max(16, Math.min(box.left, vw - CARD - 16));
    const below = box.top + box.height + GAP;
    if (below + CARD_H < vh - 16) return { left, top: below };
    const above = box.top - GAP - CARD_H;
    return { left, top: above > 16 ? above : vh - CARD_H - 16 };
  })();

  return (
    <TourContext.Provider value={{ start, running }}>
      {children}
      <AnimatePresence>
        {running && stopNow ? (
          <div className="tour" role="dialog" aria-modal="true" aria-label="Walkthrough">
            {/* The scrim is the hole's own shadow, so there is exactly one moving element and the edges stay crisp. */}
            <motion.div className="tour-hole" initial={{ opacity: 0 }} animate={{ opacity: 1, ...(box ?? { top: 0, left: 0, width: 0, height: 0 }) }}
              exit={{ opacity: 0 }} transition={SPRING} onClick={() => void stop()} />
            <motion.div className="tour-card" initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1, ...place }} exit={{ opacity: 0, scale: 0.97 }} transition={SPRING}>
              <div className="tour-step">{i + 1} of {stops.length}</div>
              <h3>{stopNow.title}</h3>
              <p>{stopNow.body}</p>
              <div className="tour-acts">
                <button type="button" className="tour-skip" onClick={() => void stop()}>Skip</button>
                <div className="tour-right">
                  {i > 0 ? <button type="button" className="tour-back" onClick={() => setI((n) => n - 1)} aria-label="Back"><Icon name="arrowRight" /></button> : null}
                  <button type="button" className="tour-next" onClick={next}>{i + 1 >= stops.length ? "Done" : "Next"}<Icon name="arrowRight" /></button>
                </div>
              </div>
            </motion.div>
          </div>
        ) : null}
      </AnimatePresence>
    </TourContext.Provider>
  );
}
