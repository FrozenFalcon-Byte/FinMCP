/* Adding to the ledger. One card, opened from anywhere: type a line the way you would say it, and the pieces it
   understood (amount, merchant, date, category) settle in underneath as you write. One box covers both directions
   — a leading "+" is money in — so there is nothing to choose before you start typing.

   The dialog lives once, in `AddProvider`; `useAdd()` and `<AddButton/>` open it, so the same action can sit in the
   top bar, on a page header and under your thumb without any of them owning it. */
import { AnimatePresence, motion } from "motion/react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { useLedger } from "../lib/ledger";
import { QUICK_ADD_EXAMPLES, parseQuickAdd, titleCase, type DirectionSource, type QuickAddDraft } from "../lib/quickadd";
import { useStatus } from "../lib/status";
import type { Category, Transaction } from "../lib/types";
import { useToast } from "./Toast";
import { Icon, Spinner } from "./ui";

const SPRING = { type: "spring", stiffness: 460, damping: 32, mass: 0.7 } as const;
const POP = { initial: { opacity: 0, y: 8, scale: 0.92 }, animate: { opacity: 1, y: 0, scale: 1 }, exit: { opacity: 0, scale: 0.92 }, transition: SPRING };

const AddContext = createContext<() => void>(() => {});
/** Opens the new-entry card. Any screen can call it; the card itself is mounted once by `AddProvider`. */
export const useAdd = () => useContext(AddContext);

export function AddProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const add = useCallback(() => setOpen(true), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null;
      const typing = !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
      if (!typing && (e.key === "n" || e.key === "N") && !e.metaKey && !e.ctrlKey && !e.altKey) { e.preventDefault(); setOpen(true); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <AddContext.Provider value={add}>
      {children}
      <QuickAdd open={open} onClose={() => setOpen(false)} />
    </AddContext.Provider>
  );
}

/** The one add button, wherever it is needed. */
export function AddButton({ className = "btn sm primary", label = "Add" }: { className?: string; label?: string }) {
  const add = useAdd();
  return (
    <motion.button type="button" className={className} onClick={add} whileTap={{ scale: 0.96 }} transition={SPRING} aria-label="Add an entry" title="Add an entry (N)">
      <Icon name="plus" /><span className="lbl">{label}</span>
    </motion.button>
  );
}

type Dir = "debit" | "credit";
interface Refine { line: string; direction: Dir | null; merchant: string | null; amount: number | null; confidence: number; source: DirectionSource }

const SURE = 0.8;          // above this the line says which way it went plainly enough
const ASK_AFTER_MS = 450;  // a pause in the typing, not a keystroke
const WHY: Record<DirectionSource, string> = {
  sign: "you typed the sign",
  words: "from how you put it",
  grammar: "from how you put it",
  default: "assumed — tap to flip",
  history: "how you always file this one",
  model: "read by the model",
  you: "your call",
};

/** The card's reading of a line, in three layers.

    The local parse is instant and offline. When it is only guessing at the direction, the server is asked once the
    typing settles — what this account has done at that merchant before, and failing that the model — so a phrasing
    nobody wrote a rule for still lands the right way round. A tap on the chip beats both and stops the asking. */
function useReading(open: boolean, draft: QuickAddDraft) {
  const [remote, setRemote] = useState<Refine | null>(null);
  const [mine, setMine] = useState<Dir | null>(null);
  const [thinking, setThinking] = useState(false);

  useEffect(() => { setRemote(null); setMine(null); setThinking(false); }, [open]);
  // Your call is about one counterparty. Type a different one and the card goes back to reading the line.
  useEffect(() => { setMine(null); }, [draft.merchant]);

  // Worth asking when the direction is a guess, and also when the line defeated the local parse altogether
  // ("two thousand from mom" has no number in it). Short fragments mid-typing are left alone.
  const ask = open && mine === null && draft.raw.length >= 6 && (!draft.valid || draft.confidence < SURE);
  const text = draft.raw;
  const merchant = draft.merchant;
  useEffect(() => {
    if (!ask) return;
    const t = window.setTimeout(() => {
      setThinking(true);
      api.post<Omit<Refine, "line">>("/transactions/parse", { text, merchant })
        .then((r) => setRemote({ ...r, line: text }))
        .catch(() => undefined)          // the line still reads fine on its own
        .finally(() => setThinking(false));
    }, ASK_AFTER_MS);
    return () => window.clearTimeout(t);
  }, [ask, text, merchant]);

  const fit = remote && remote.line === text && remote.direction ? remote : null;
  const direction: Dir = mine ?? fit?.direction ?? draft.direction;
  const source: DirectionSource = mine ? "you" : fit ? fit.source : draft.source;
  return {
    direction,
    source,
    thinking: thinking && !mine,
    merchant: draft.merchant || (fit?.merchant ? titleCase(fit.merchant.toLowerCase()) : ""),
    amount: draft.amount ?? fit?.amount ?? null,
    flip: () => setMine(direction === "credit" ? "debit" : "credit"),
  };
}

function QuickAdd({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { currency } = useStatus();
  const { bump, version } = useLedger();
  const toast = useToast();
  const [text, setText] = useState("");
  const [cats, setCats] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.get<Category[]>("/categories").then((cs) => setCats(cs.map((c) => c.name))).catch(() => undefined);
  }, [version]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    setDone(false);
    setText("");
    document.body.style.overflow = "hidden";
    const t = window.setTimeout(() => {
      inputRef.current?.focus();
    }, 60);
    return () => { window.clearTimeout(t); document.body.style.overflow = ""; };
  }, [open]);

  const draft = useMemo(() => parseQuickAdd(text, cats), [text, cats]);
  const read = useReading(open, draft);
  const credit = read.direction === "credit";
  const valid = read.amount !== null && read.amount > 0 && read.merchant.length > 0;

  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true);
    try {
      const r = await api.post<{ transaction: Transaction }>("/transactions", {
        date: draft.date, amount: read.amount, merchant: read.merchant, direction: read.direction,
        description: draft.description ?? undefined, category: draft.category ?? undefined, source: "manual",
      });
      const tx = r.transaction;
      bump();
      setDone(true);
      window.setTimeout(() => { onClose(); setText(""); }, 650);
      toast(
        `${tx.direction === "credit" ? "Received" : "Spent"} ${money(tx.amount, currency, 2)} · ${tx.merchant} → ${tx.category ?? "uncategorized"}`,
        "ok",
        { label: "Undo", onClick: async () => { try { await api.del(`/transactions/${tx.id}`); bump(); } catch { toast("Could not undo.", "err"); } } },
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setBusy(false);
    }
  };

  const tokens: { k: string; label: string; value: string | null }[] = [
    { k: "when", label: "on", value: draft.dateLabel },
    { k: "cat", label: "filed under", value: draft.category ?? "auto" },
    ...(draft.description ? [{ k: "note", label: "note", value: draft.description }] : []),
  ];

  return (
    <>
      {createPortal(
        <AnimatePresence>
          {open ? (
            <motion.div key="qa" className="qa-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}
              onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
              <motion.form className={`qa-card ${credit ? "in" : ""}`} role="dialog" aria-modal="true" aria-label="New entry"
                initial={{ opacity: 0, y: 40, scale: 0.94 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 24, scale: 0.97 }} transition={SPRING}
                onSubmit={(e) => { e.preventDefault(); void submit(); }}>
                <div className="qa-head">
                  <span className="qa-title">New entry</span>
                  <button type="button" className="qa-x" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
                </div>

                <div className="qa-amount">
                  <AnimatePresence mode="popLayout" initial={false}>
                    <motion.span key={`${read.amount ?? "none"}-${read.direction}`} className={`num ${read.amount ? "" : "empty"}`}
                      initial={{ opacity: 0, y: 14, filter: "blur(4px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }} exit={{ opacity: 0, y: -14, filter: "blur(4px)" }}
                      transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}>
                      {read.amount ? `${credit ? "+" : "−"}${money(read.amount, currency, 2)}` : money(0, currency)}
                    </motion.span>
                  </AnimatePresence>
                  {/* A guess you can overrule with one tap, which is the point of showing how it was arrived at. */}
                  <motion.button type="button" className="qa-dir" layout transition={SPRING} onClick={read.flip}
                    whileTap={{ scale: 0.94 }} aria-label={`${credit ? "Money in" : "Money out"} — tap to flip`} title="Tap to flip">
                    <AnimatePresence mode="popLayout" initial={false}>
                      <motion.span key={read.direction} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.16 }}>
                        {credit ? "money in" : "money out"}
                      </motion.span>
                    </AnimatePresence>
                  </motion.button>
                </div>
                <div className="qa-merchant">
                  <AnimatePresence mode="wait" initial={false}>
                    <motion.span key={read.merchant} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.16 }}>
                      {read.merchant ? <>{credit ? "from" : "at"} <b>{read.merchant}</b></> : "Who was it? Type a merchant"}
                    </motion.span>
                  </AnimatePresence>
                  <AnimatePresence initial={false}>
                    {read.merchant ? (
                      <motion.span className="qa-why" key={read.thinking ? "thinking" : read.source} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
                        · {read.thinking ? "checking…" : WHY[read.source]}
                      </motion.span>
                    ) : null}
                  </AnimatePresence>
                </div>

                <div className="qa-field">
                  <input ref={inputRef} value={text} onChange={(e) => setText(e.target.value)} placeholder="450 swiggy" autoComplete="off" spellCheck={false} aria-label="What happened" />
                  <motion.span className="qa-underline" animate={{ scaleX: text ? 1 : 0.18 }} transition={SPRING} />
                </div>

                <motion.div className="qa-tokens" layout>
                  <AnimatePresence initial={false}>
                    {text.trim() ? tokens.map((t) => (
                      <motion.span layout key={t.k} className="qa-tok" {...POP}>
                        <span className="k">{t.label}</span>
                        <AnimatePresence mode="popLayout" initial={false}>
                          <motion.b key={t.value} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.15 }}>{t.value}</motion.b>
                        </AnimatePresence>
                      </motion.span>
                    )) : QUICK_ADD_EXAMPLES.slice(0, 4).map((ex, i) => (
                      <motion.button layout type="button" key={ex} className="qa-ex" {...POP} transition={{ ...SPRING, delay: 0.04 * i }}
                        whileHover={{ y: -2 }} whileTap={{ scale: 0.95 }} onClick={() => { setText(ex); inputRef.current?.focus(); }}>{ex}</motion.button>
                    ))}
                  </AnimatePresence>
                </motion.div>

                <div className="qa-foot">
                  <span className="qa-hint">{text.trim() && !valid ? "Needs an amount and a merchant" : "#category · (note) · yesterday · 12 sep · tap the chip to flip"}</span>
                  <motion.button type="submit" className={`qa-go ${done ? "done" : ""}`} disabled={!valid || busy || done}
                    whileHover={valid ? { scale: 1.04 } : undefined} whileTap={valid ? { scale: 0.95 } : undefined} transition={SPRING}>
                    <AnimatePresence mode="wait" initial={false}>
                      <motion.span key={done ? "done" : busy ? "busy" : "idle"} className="in" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.15 }}>
                        {done ? <><Icon name="check" />Added</> : busy ? <Spinner /> : <>Add <Icon name="enter" /></>}
                      </motion.span>
                    </AnimatePresence>
                  </motion.button>
                </div>
              </motion.form>
            </motion.div>
          ) : null}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}
