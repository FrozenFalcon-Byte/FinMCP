import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { useLedger } from "../lib/ledger";
import { QUICK_ADD_EXAMPLES, parseQuickAdd } from "../lib/quickadd";
import { useStatus } from "../lib/status";
import type { Category, Transaction } from "../lib/types";
import { useToast } from "./Toast";
import { Icon, Spinner } from "./ui";

export function QuickAdd() {
  const { currency } = useStatus();
  const { bump, version } = useLedger();
  const toast = useToast();
  const [text, setText] = useState("");
  const [cats, setCats] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [focused, setFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const blurTimer = useRef<number | null>(null);

  useEffect(() => {
    api.get<Category[]>("/categories").then((cs) => setCats(cs.map((c) => c.name))).catch(() => undefined);
  }, [version]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null;
      const typing = !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
      if (!typing && (e.key === "n" || e.key === "N") && !e.metaKey && !e.ctrlKey && !e.altKey) { e.preventDefault(); inputRef.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const draft = useMemo(() => parseQuickAdd(text, cats), [text, cats]);

  const submit = async () => {
    if (!draft.valid || busy) return;
    setBusy(true);
    try {
      const r = await api.post<{ transaction: Transaction }>("/transactions", {
        date: draft.date, amount: draft.amount, merchant: draft.merchant, direction: draft.direction,
        description: draft.description ?? undefined, category: draft.category ?? undefined, source: "manual",
      });
      const tx = r.transaction;
      setText("");
      bump();
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

  const onFocus = () => { if (blurTimer.current) window.clearTimeout(blurTimer.current); setFocused(true); };
  const onBlur = () => { blurTimer.current = window.setTimeout(() => setFocused(false), 120); };
  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") { if (text) setText(""); else inputRef.current?.blur(); }
  };
  const showPanel = focused && text.trim().length > 0;

  return (
    <div className="qa">
      <form className="box" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <Icon name="plus" className="lead" />
        <input ref={inputRef} id="quick-add" value={text} onChange={(e) => setText(e.target.value)} onFocus={onFocus} onBlur={onBlur} onKeyDown={onKeyDown}
          placeholder="Add anything: 450 swiggy · coffee 120 yesterday · +50000 salary" autoComplete="off" spellCheck={false} aria-label="Quick add a transaction" />
        {text ? <button className="go" type="submit" disabled={!draft.valid || busy}>{busy ? <Spinner /> : <>Add <Icon name="enter" /></>}</button> : <span className="kbd">N</span>}
      </form>
      {showPanel ? (
        <div className="panel" role="status">
          <div className="parse">
            {draft.amount ? <span className="tok amt"><span className="k">amount</span><b>{money(draft.amount, currency, 2)}</b></span> : <span className="tok miss">amount</span>}
            {draft.merchant ? <span className="tok"><span className="k">{draft.direction === "credit" ? "from" : "at"}</span><b>{draft.merchant}</b></span> : <span className="tok miss">merchant</span>}
            <span className={`tok ${draft.direction === "credit" ? "in" : ""}`}><b>{draft.direction === "credit" ? "money in" : "money out"}</b></span>
            <span className="tok"><span className="k">on</span><b>{draft.dateLabel}</b></span>
            <span className="tok"><span className="k">filed</span><b>{draft.category ?? "auto"}</b></span>
            {draft.description ? <span className="tok"><span className="k">note</span><b>{draft.description}</b></span> : null}
          </div>
          <div className="hint">
            <span>{draft.valid ? "Enter to add" : "Needs an amount and a merchant"}</span>
            <span>#category · (note) · yesterday · 12 sep · + for money in</span>
            {!draft.valid ? <span>e.g. <code>{QUICK_ADD_EXAMPLES[0]}</code></span> : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
