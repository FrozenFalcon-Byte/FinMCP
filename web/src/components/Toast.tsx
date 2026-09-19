/* Notifications. On a desktop they rise from the bottom of the screen. On a phone they live in an "island": a black
   capsule at the top, just under the iPhone's Dynamic Island, that grows out of a small pill into a card for a
   message and shrinks back when it is done. It also carries live activity (the assistant working through its tools,
   with a running timer), so what is happening is visible at a glance. Swipe it up to dismiss. */
import { AnimatePresence, motion } from "motion/react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

export interface ToastAction { label: string; onClick: () => void | Promise<void> }
interface Toast { id: number; text: string; kind: "ok" | "err"; action?: ToastAction }
type Push = (text: string, kind?: "ok" | "err", action?: ToastAction) => void;
export interface Activity { label: string; href?: string }
interface IslandApi {
  /** Show live work (null clears it). `done` briefly shows a finished state, such as "Answered · 12s". */
  activity: (a: Activity | null, done?: string) => void;
}

const ToastContext = createContext<Push>(() => {});
const IslandContext = createContext<IslandApi>({ activity: () => {} });
const SPRING = { type: "spring", stiffness: 420, damping: 32, mass: 0.9 } as const;

function useNarrow(): boolean {
  const q = "(max-width: 900px)";
  const [narrow, setNarrow] = useState(() => window.matchMedia(q).matches);
  useEffect(() => {
    const m = window.matchMedia(q);
    const on = () => setNarrow(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return narrow;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const [live, setLive] = useState<(Activity & { since: number }) | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const narrow = useNarrow();
  const doneTimer = useRef<number | undefined>(undefined);

  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const push = useCallback<Push>((text, kind = "ok", action) => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs.slice(-3), { id, text, kind, action }]);
    setTimeout(() => dismiss(id), kind === "err" ? 7000 : action ? 6000 : 3500);
  }, [dismiss]);

  const activity = useCallback<IslandApi["activity"]>((a, fin) => {
    window.clearTimeout(doneTimer.current);
    setLive((prev) => (a ? { ...a, since: prev?.since ?? Date.now() } : null));
    setDone(a ? null : fin ?? null);
    if (!a && fin) doneTimer.current = window.setTimeout(() => setDone(null), 1800);
  }, []);

  return (
    <IslandContext.Provider value={{ activity }}>
      <ToastContext.Provider value={push}>
        {children}
        {narrow ? (
          <Island toast={items[items.length - 1] ?? null} live={live} done={done} onDismiss={dismiss} />
        ) : (
          <div className="toasts" aria-live="polite">
            <AnimatePresence initial={false}>
              {items.map((t) => (
                <motion.div key={t.id} layout className={`toast ${t.kind}`} initial={{ opacity: 0, y: 16, scale: 0.96 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8, scale: 0.96 }} transition={SPRING}>
                  <span>{t.text}</span>
                  {t.action ? <button onClick={() => { void t.action?.onClick(); dismiss(t.id); }}>{t.action.label}</button> : null}
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}
      </ToastContext.Provider>
    </IslandContext.Provider>
  );
}

/** The phone capsule. One shape that morphs between three sizes: a compact pill for live work or a finished note,
    and an expanded card for a message. Content cross-fades inside while the shape springs to its new size. */
function Island({ toast, live, done, onDismiss }: {
  toast: Toast | null; live: (Activity & { since: number }) | null; done: string | null; onDismiss: (id: number) => void;
}) {
  const navigate = useNavigate();
  const mode = toast ? "toast" : live ? "live" : done ? "done" : null;
  const key = toast ? `t${toast.id}` : live ? "live" : done ? "done" : "none";
  return (
    <div className="island-wrap" aria-live="polite">
      <AnimatePresence>
        {mode ? (
          <motion.div key="island" layout className={`island ${mode} ${toast?.kind ?? ""}`}
            style={{ borderRadius: mode === "toast" ? 26 : 22 }}
            initial={{ opacity: 0, scale: 0.55, y: -14, filter: "blur(6px)" }} animate={{ opacity: 1, scale: 1, y: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, scale: 0.55, y: -14, filter: "blur(6px)" }} transition={SPRING}
            drag="y" dragConstraints={{ top: 0, bottom: 0 }} dragElastic={{ top: 0.6, bottom: 0.1 }}
            onDragEnd={(_, info) => { if (info.offset.y < -18 && toast) onDismiss(toast.id); }}
            onClick={() => { if (!toast && live?.href) navigate(live.href); }}>
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.div key={key} className="island-in" layout="position"
                initial={{ opacity: 0, filter: "blur(4px)", y: 4 }} animate={{ opacity: 1, filter: "blur(0px)", y: 0 }}
                exit={{ opacity: 0, filter: "blur(4px)", y: -4 }} transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}>
                {toast ? (
                  <>
                    <Mark kind={toast.kind} />
                    <span className="txt">{toast.text}</span>
                    {toast.action ? <button onClick={(e) => { e.stopPropagation(); void toast.action?.onClick(); onDismiss(toast.id); }}>{toast.action.label}</button> : null}
                  </>
                ) : live ? (
                  <><span className="orb" /><span className="txt">{live.label}</span><Elapsed since={live.since} /></>
                ) : (
                  <><Mark kind="ok" /><span className="txt">{done}</span></>
                )}
              </motion.div>
            </AnimatePresence>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

/** A tick that draws itself, or an exclamation mark, in a soft coloured disc. */
function Mark({ kind }: { kind: "ok" | "err" }) {
  return (
    <span className={`mark ${kind}`} aria-hidden>
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
        {kind === "ok"
          ? <motion.path d="M5 12.5l4.5 4.5L19 7.5" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.35, delay: 0.12, ease: "easeOut" }} />
          : <><motion.path d="M12 6v8" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.25, delay: 0.1 }} /><circle cx="12" cy="18.5" r="0.6" /></>}
      </svg>
    </span>
  );
}

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const id = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(id); }, []);
  return <span className="sec num">{Math.max(0, Math.round((now - since) / 1000))}s</span>;
}

export const useToast = () => useContext(ToastContext);
export const useIsland = () => useContext(IslandContext);
