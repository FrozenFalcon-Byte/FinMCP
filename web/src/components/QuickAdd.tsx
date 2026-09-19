/* Adding to the ledger. The bar in the top bar (or the N key) opens a card: type a line the way you would say it,
   and the pieces it understood (amount, merchant, date, category) settle in underneath as you write. */
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { useLedger } from "../lib/ledger";
import { QUICK_ADD_EXAMPLES, parseQuickAdd } from "../lib/quickadd";
import { useStatus } from "../lib/status";
import type { Category, Transaction } from "../lib/types";
import { useToast } from "./Toast";
import { Icon, Spinner } from "./ui";

const SPRING = { type: "spring", stiffness: 460, damping: 32, mass: 0.7 } as const;
const POP = { initial: { opacity: 0, y: 8, scale: 0.92 }, animate: { opacity: 1, y: 0, scale: 1 }, exit: { opacity: 0, scale: 0.92 }, transition: SPRING };

export function QuickAdd() {
  const { currency } = useStatus();
  const { bump, version } = useLedger();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [cats, setCats] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.get<Category[]>("/categories").then((cs) => setCats(cs.map((c) => c.name))).catch(() => undefined);
  }, [version]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null;
      const typing = !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
      if (!typing && !open && (e.key === "n" || e.key === "N") && !e.metaKey && !e.ctrlKey && !e.altKey) { e.preventDefault(); setOpen(true); }
      if (open && e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setDone(false);
    document.body.style.overflow = "hidden";
    const t = window.setTimeout(() => inputRef.current?.focus(), 60);
    return () => { window.clearTimeout(t); document.body.style.overflow = ""; };
  }, [open]);

  const draft = useMemo(() => parseQuickAdd(text, cats), [text, cats]);
  const credit = draft.direction === "credit";

  const submit = async () => {
    if (!draft.valid || busy) return;
    setBusy(true);
    try {
      const r = await api.post<{ transaction: Transaction }>("/transactions", {
        date: draft.date, amount: draft.amount, merchant: draft.merchant, direction: draft.direction,
        description: draft.description ?? undefined, category: draft.category ?? undefined, source: "manual",
      });
      const tx = r.transaction;
      bump();
      setDone(true);
      window.setTimeout(() => { setOpen(false); setText(""); }, 650);
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
      <button type="button" className="qa-trigger" onClick={() => setOpen(true)} aria-label="Add a transaction">
        <Icon name="plus" className="lead" />
        <span className="ph">Add anything: 450 swiggy · coffee 120 yesterday · +50000 salary</span>
        <span className="kbd">N</span>
      </button>
      {createPortal(
        <AnimatePresence>
          {open ? (
            <motion.div key="qa" className="qa-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}
              onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false); }}>
              <motion.form className={`qa-card ${credit ? "in" : ""}`} role="dialog" aria-modal="true" aria-label="New entry"
                initial={{ opacity: 0, y: 40, scale: 0.94 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 24, scale: 0.97 }} transition={SPRING}
                onSubmit={(e) => { e.preventDefault(); void submit(); }}>
                <div className="qa-head">
                  <span className="qa-title">New entry</span>
                  <button type="button" className="qa-x" onClick={() => setOpen(false)} aria-label="Close"><Icon name="x" /></button>
                </div>

                <div className="qa-amount">
                  <AnimatePresence mode="popLayout" initial={false}>
                    <motion.span key={`${draft.amount ?? "none"}-${draft.direction}`} className={`num ${draft.amount ? "" : "empty"}`}
                      initial={{ opacity: 0, y: 14, filter: "blur(4px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }} exit={{ opacity: 0, y: -14, filter: "blur(4px)" }}
                      transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}>
                      {draft.amount ? `${credit ? "+" : "−"}${money(draft.amount, currency, 2)}` : money(0, currency)}
                    </motion.span>
                  </AnimatePresence>
                  <motion.span className="qa-dir" layout transition={SPRING}>{credit ? "money in" : "money out"}</motion.span>
                </div>
                <div className="qa-merchant">
                  <AnimatePresence mode="wait" initial={false}>
                    <motion.span key={draft.merchant ?? ""} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.16 }}>
                      {draft.merchant ? <>{credit ? "from" : "at"} <b>{draft.merchant}</b></> : "Who was it? Type a merchant"}
                    </motion.span>
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
                  <span className="qa-hint">{text && !draft.valid ? "Needs an amount and a merchant" : "#category · (note) · yesterday · 12 sep · + for money in"}</span>
                  <motion.button type="submit" className={`qa-go ${done ? "done" : ""}`} disabled={!draft.valid || busy || done}
                    whileHover={draft.valid ? { scale: 1.04 } : undefined} whileTap={draft.valid ? { scale: 0.95 } : undefined} transition={SPRING}>
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
