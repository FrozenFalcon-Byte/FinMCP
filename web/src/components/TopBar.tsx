/* The bar above every app screen.

   It used to be one box that looked like search but added transactions, which read as a trap. Now the two are
   separate: the box searches — typing takes you to Transactions and narrows them as you go, so the results are
   the page rather than a dropdown — and adding is the button beside it. There is exactly one of those: this bar
   is on every screen, so a second copy on a page header only made the two compete. On a phone the same action
   moves under your thumb instead. */
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { AddButton } from "./QuickAdd";
import { Icon } from "./ui";

const SPRING = { type: "spring", stiffness: 480, damping: 36, mass: 0.7 } as const;
const TX = "/app/transactions";

/** Search, wired to the Transactions list through the URL. Focus is kept across the jump because the bar lives
    outside the page transition, so a search started anywhere finishes without a beat. */
function OmniSearch() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const onTx = location.pathname === TX;
  const urlQuery = onTx ? params.get("search") ?? params.get("merchant") ?? "" : "";
  const [q, setQ] = useState(urlQuery);
  const [focused, setFocused] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  const timer = useRef<number | undefined>(undefined);

  // Follow the URL: back and forward, and "all from this merchant" out of a transaction's sheet.
  useEffect(() => { setQ(urlQuery); }, [urlQuery]);

  const go = useCallback((value: string, replace: boolean) => {
    const next = new URLSearchParams(onTx ? params : undefined);
    next.delete("merchant");
    if (value.trim()) next.set("search", value.trim());
    else next.delete("search");
    navigate({ pathname: TX, search: next.toString() }, { replace });
  }, [navigate, onTx, params]);

  /* As you type. The first keystroke moves you to Transactions (a push, so Back returns to where you were);
     everything after that only narrows the list, which replaces rather than piling up history. */
  useEffect(() => {
    if (q === urlQuery) return;
    timer.current = window.setTimeout(() => go(q, onTx), 280);
    return () => window.clearTimeout(timer.current);
  }, [q, urlQuery, onTx, go]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null;
      const typing = !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
      if (!typing && e.key === "/" && !e.metaKey && !e.ctrlKey) { e.preventDefault(); ref.current?.focus(); }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); ref.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const clear = () => { setQ(""); if (onTx) go("", true); ref.current?.focus(); };

  return (
    <motion.div className={`omni ${focused ? "on" : ""}`} layout transition={SPRING}>
      <Icon name="search" className="lead" />
      <input
        ref={ref}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); window.clearTimeout(timer.current); go(q, onTx); }
          if (e.key === "Escape") { if (q) clear(); else ref.current?.blur(); }
        }}
        placeholder="Search transactions, merchants, notes"
        aria-label="Search transactions"
        autoComplete="off"
        spellCheck={false}
      />
      <AnimatePresence initial={false} mode="wait">
        {q ? (
          <motion.button key="x" type="button" className="omni-x" onClick={clear} aria-label="Clear search"
            initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.6 }} transition={{ duration: 0.15 }}>
            <Icon name="x" />
          </motion.button>
        ) : (
          <motion.span key="k" className="kbd" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>/</motion.span>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {focused && !onTx ? (
          <motion.span className="omni-hint" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2 }}>
            Results open in Transactions
          </motion.span>
        ) : null}
      </AnimatePresence>
    </motion.div>
  );
}

/** The bar sits still while the page scrolls under it, so it only draws its own edge once there is something
    behind it to separate from. The page is the scroller, not the window. */
function useLifted(): boolean {
  const [lifted, setLifted] = useState(false);
  useEffect(() => {
    const el = document.querySelector<HTMLElement>(".content");
    if (!el) return;
    const read = () => setLifted(el.scrollTop > 4);
    read();
    el.addEventListener("scroll", read, { passive: true });
    return () => el.removeEventListener("scroll", read);
  }, []);
  return lifted;
}

export function TopBar({ children }: { children?: ReactNode }) {
  const lifted = useLifted();
  return (
    <div className={`topbar ${lifted ? "lifted" : ""}`}>
      <div className="topbar-in">
        <OmniSearch />
        <AddButton className="btn sm topbar-add" label="Add" />
        {children}
      </div>
    </div>
  );
}
