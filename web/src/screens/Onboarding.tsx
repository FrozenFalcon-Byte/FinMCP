/* First run.

   A dashboard is only worth looking at once it knows something about you, so a brand new account is asked before it
   is shown anything. Not a modal over a dashboard nobody can read yet — the whole screen, in the landing page's
   voice, one question at a time, with the answers assembling the dashboard on the left as they are given. The gate
   is `profiles.onboarded_at` on the server, so closing the tab, reloading or coming back on another device all land
   back here; what has been typed so far is kept in this browser so nobody retypes it.

   Required, optional and conditional live in one place: each step's `done()` says what it needs, and a couple of
   answers make another answer required — pick Rent and the amount stops being optional, because that one you know. */
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useToast } from "../components/Toast";
import { Icon, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { compact, isoLocal, money } from "../lib/format";
import { PhotoCrop } from "../components/PhotoCrop";
import type { Category } from "../lib/types";
import "./onboarding.css";

const SPRING = { type: "spring", stiffness: 420, damping: 34, mass: 0.8 } as const;
const EASE = [0.22, 1, 0.36, 1] as const;
const DRAFT_KEY = "finmcp.setup";

const CURRENCIES = ["INR", "USD", "EUR", "GBP", "AED"];
/** A share of take-home that makes a decent opening suggestion, in the order people tend to think of them —
    alphabetical would bury Transport and Shopping below Fees & Charges. Nobody's real budget, a place to argue from. */
const SUGGESTED: Record<string, number> = {
  "Rent & Housing": 0.3, "Food & Dining": 0.12, Groceries: 0.1, Transport: 0.08, Shopping: 0.08,
  Utilities: 0.05, Subscriptions: 0.02, "Loans & EMI": 0.15, Health: 0.04, Entertainment: 0.04,
  Travel: 0.05, "Personal Care": 0.03, Education: 0.05, Insurance: 0.03, "Gifts & Donations": 0.02,
};
const ORDER = Object.keys(SUGGESTED);
/** Fixed costs you already know to the rupee. Picking one and leaving it blank helps nobody. */
const EXACT = new Set(["Rent & Housing", "Loans & EMI"]);
const FALLBACK = ORDER.slice(0, 10);

interface Draft {
  name: string;
  avatar: string | null;
  currency: string;
  income: string;
  payDay: string;
  keepPct: number;
  picks: Record<string, string>;   // category -> the amount typed, "" while it is still blank
  goalName: string;
  goalTarget: string;
  goalDue: string;
}

const EMPTY: Draft = { name: "", avatar: null, currency: "INR", income: "", payDay: "", keepPct: 20, picks: {}, goalName: "", goalTarget: "", goalDue: "" };

const num = (s: string): number => {
  const n = parseFloat(s.replace(/[^\d.]/g, ""));
  return Number.isFinite(n) && n > 0 ? n : 0;
};

// ------------------------------------------------------------------ the steps

interface Step {
  id: string;
  kicker: string;
  title: string;
  blurb: string;
  /** What this step insists on before it will let go. Everything it does not mention is optional. */
  done: (d: Draft) => boolean;
  need?: (d: Draft) => string | null;
}

const STEPS: Step[] = [
  {
    id: "you", kicker: "Step 1", title: "Who are we\nkeeping books for?",
    blurb: "Your name shows up on the dashboard and nowhere else. A photo is entirely up to you.",
    done: (d) => d.name.trim().length > 0,
    need: (d) => (d.name.trim() ? null : "A name, first"),
  },
  {
    id: "money", kicker: "Step 2", title: "What lands\nevery month?",
    blurb: "Take-home, after tax. This is what every 'can I afford it' answer is measured against, so a rough figure beats none.",
    done: (d) => num(d.income) > 0,
    need: (d) => (num(d.income) > 0 ? null : "A monthly figure is needed"),
  },
  {
    id: "spend", kicker: "Step 3", title: "Where does\nit tend to go?",
    blurb: "Pick the ones you actually spend on. Amounts are suggestions from your income — change them, or leave them for later.",
    done: (d) => Object.keys(d.picks).length > 0 && Object.entries(d.picks).every(([c, v]) => !EXACT.has(c) || num(v) > 0),
    need: (d) => {
      if (!Object.keys(d.picks).length) return "Pick at least one";
      const missing = Object.entries(d.picks).find(([c, v]) => EXACT.has(c) && !num(v));
      return missing ? `${missing[0]} needs an amount — it is a fixed cost` : null;
    },
  },
  {
    id: "keep", kicker: "Step 4", title: "How much\nstays put?",
    blurb: "The share of each month you would rather not touch. Add something you are saving towards if you have one in mind.",
    done: (d) => !d.goalName.trim() || num(d.goalTarget) > 0,
    need: (d) => (!d.goalName.trim() || num(d.goalTarget) > 0 ? null : "A goal needs a target amount"),
  },
  { id: "ready", kicker: "All set", title: "That is the\nwhole setup.", blurb: "Everything here is editable later from Settings and Profile. Nothing is written in stone.", done: () => true },
];

// ------------------------------------------------------------------ the live stage

function Stage({ d, step }: { d: Draft; step: number }) {
  const income = num(d.income);
  const planned = income * (1 - d.keepPct / 100);
  const picked = Object.keys(d.picks);
  const budgeted = picked.reduce((t, c) => t + num(d.picks[c]), 0);
  const perDay = planned ? Math.round(planned / 30) : 0;

  return (
    <div className="onb-stage" aria-hidden="true">
      {/* Fixed height on purpose. This card grew as answers arrived, and animating that meant motion scaling the
          whole panel — which squashes every line of text inside it for the length of the animation, and looked
          different at every window size. Now the frame holds still and only what is inside it moves. */}
      <div className="onb-preview">
        <div className="row head">
          <motion.span className={`pfp ${d.avatar ? "has" : ""}`} layout transition={SPRING}>
            {d.avatar ? <img src={d.avatar} alt="" /> : <Icon name="user" />}
          </motion.span>
          <div className="who">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={d.name || "blank"} className="n" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2 }}>
                {d.name.trim() || "Your dashboard"}
              </motion.div>
            </AnimatePresence>
            <div className="s">{new Date().toLocaleDateString("en-IN", { month: "long", year: "numeric" })}</div>
          </div>
        </div>

        <motion.div className="big" layout transition={SPRING}>
          <div className="k">Safe to spend</div>
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.div key={perDay} className="v" initial={{ opacity: 0, y: 12, filter: "blur(5px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: -12, filter: "blur(5px)" }} transition={{ duration: 0.28, ease: EASE }}>
              {perDay ? `${money(perDay, d.currency)} / day` : "—"}
            </motion.div>
          </AnimatePresence>
          <div className="s">{planned ? `${compact(planned, d.currency)} to spend, ${compact(income - planned, d.currency)} kept back` : "tell us what you earn"}</div>
        </motion.div>

        <motion.div className="bars" layout transition={SPRING}>
          <AnimatePresence initial={false}>
            {picked.length ? picked.map((c, i) => {
              const amount = num(d.picks[c]);
              return (
                <motion.div key={c} className="bar" layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, height: 0 }} transition={{ ...SPRING, delay: 0.03 * i }}>
                  <span className="l">{c}</span>
                  <span className="t">
                    <motion.i initial={{ scaleX: 0 }} animate={{ scaleX: budgeted ? Math.max(0.06, amount / budgeted) : 0.06 }} transition={{ ...SPRING, delay: 0.05 }} />
                  </span>
                  <span className="a">{amount ? compact(amount, d.currency) : "—"}</span>
                </motion.div>
              );
            }) : [0, 1, 2].map((k) => (
              <motion.div key={`ghost-${k}`} className="bar ghost" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.3, delay: 0.05 * k }}>
                <span className="l">{k === 0 ? "Your categories" : ""}</span>
                <span className="t"><i /></span>
                <span className="a">—</span>
              </motion.div>
            ))}
          </AnimatePresence>
        </motion.div>

        <AnimatePresence initial={false}>
          {d.goalName.trim() ? (
            <motion.div className="goal" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={SPRING}>
              <Icon name="goal" />
              <span>{d.goalName.trim()}</span>
              <b>{num(d.goalTarget) ? compact(num(d.goalTarget), d.currency) : "—"}</b>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>

      <motion.p className="onb-stage-note" key={step} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: EASE }}>
        {step === 0 ? "This is yours. It fills in as you answer."
          : step === 1 ? "Every 'can I afford this' is measured against this number."
          : step === 2 ? "Budgets turn into alerts before you overspend, not after."
          : step === 3 ? "What you keep back is held out of safe-to-spend."
          : "Add a few transactions, or import a statement, and the rest fills itself in."}
      </motion.p>
    </div>
  );
}

// ------------------------------------------------------------------ the screen

export default function Onboarding() {
  const { user, refreshUser } = useAuth();
  const toast = useToast();
  const [step, setStep] = useState(0);
  const resumed = useRef(false);
  const [busy, setBusy] = useState(false);
  const [nudge, setNudge] = useState<string | null>(null);
  const [cats, setCats] = useState<string[]>(FALLBACK);
  const fileRef = useRef<HTMLInputElement>(null);
  const [d, setD] = useState<Draft>(() => {
    const saved = ((): Partial<Draft> => { try { return JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "{}"); } catch { return {}; } })();
    return { ...EMPTY, ...saved };
  });
  const set = useCallback(<K extends keyof Draft>(k: K, v: Draft[K]) => setD((p) => ({ ...p, [k]: v })), []);

  // Seed from the account, then keep every keystroke, so a reload mid-setup resumes rather than restarts.
  useEffect(() => {
    if (user) setD((p) => ({ ...p, name: p.name || user.name, currency: p.currency || user.currency, avatar: p.avatar ?? user.avatar }));
  }, [user]);
  // Where to pick up: the first question that is still unanswered. Derived from the draft rather than stored, so a
  // resume cannot land on a step already dealt with, or skip one that was not.
  useEffect(() => {
    if (resumed.current || !user) return;
    resumed.current = true;
    const at = STEPS.findIndex((s) => !s.done(d));
    if (at > 0) setStep(at);
  }, [user, d]);
  useEffect(() => { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(d)); } catch { /* private mode; the server is still the gate */ } }, [d]);
  useEffect(() => {
    api.get<Category[]>("/categories")
      .then((cs) => { const names = cs.filter((c) => c.kind === "expense").map((c) => c.name); if (names.length) setCats(names); })
      .catch(() => undefined);
  }, []);

  const current = STEPS[step];
  const [picked, setPicked] = useState<File | null>(null);
  const ok = current.done(d);
  useEffect(() => { setNudge(null); }, [step]);

  const pick = (c: string) => setD((p) => {
    const picks = { ...p.picks };
    if (c in picks) delete picks[c];
    else picks[c] = SUGGESTED[c] && num(p.income) ? String(Math.round((num(p.income) * SUGGESTED[c]) / 100) * 100) : "";
    return { ...p, picks };
  });

  // Picking a file opens the same cropper the profile uses; nothing is kept until the circle is framed.
  const photo = (file: File | undefined) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) { toast("That file is not an image.", "err"); return; }
    setPicked(file);
  };

  const finish = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.post("/auth/onboarding", {
        name: d.name.trim(), currency: d.currency, avatar: d.avatar ?? undefined,
        monthly_income: num(d.income), pay_day: d.payDay ? Number(d.payDay) : undefined, keep_pct: d.keepPct,
        budgets: Object.entries(d.picks).map(([category, v]) => ({ category, monthly_limit: num(v) || undefined })),
        goal: d.goalName.trim() ? { name: d.goalName.trim(), target: num(d.goalTarget), due: d.goalDue || undefined, icon: "🎯" } : undefined,
      });
      try { localStorage.removeItem(DRAFT_KEY); } catch { /* nothing to clean up */ }
      await refreshUser();   // flips the gate; the app is behind it
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save that.", "err");
      setBusy(false);
    }
  };

  const next = () => {
    if (!ok) { setNudge(current.need?.(d) ?? "Something is missing"); return; }
    if (step === STEPS.length - 1) void finish();
    else setStep((s) => s + 1);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== "Enter" || e.shiftKey) return;
    const el = e.target as HTMLElement;
    if (el.tagName === "TEXTAREA") return;
    e.preventDefault();
    next();
  };

  const income = num(d.income);
  const suggested = useMemo(() => {
    const rank = (n: string) => { const i = ORDER.indexOf(n); return i < 0 ? ORDER.length : i; };
    return [...cats].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b)).slice(0, 14);
  }, [cats]);

  return (
    <div className="onb" onKeyDown={onKey}>
      <header className="onb-top">
        <span className="onb-brand"><span className="mark"><Icon name="logo" /></span>FinMCP</span>
        <div className="onb-rail" role="progressbar" aria-valuenow={step + 1} aria-valuemin={1} aria-valuemax={STEPS.length}>
          {STEPS.map((s, i) => (
            <button key={s.id} type="button" className={`seg ${i <= step ? "on" : ""}`} disabled={i > step}
              onClick={() => setStep(i)} aria-label={`${s.kicker}: ${s.title.replace(/\n/g, " ")}`}>
              {i <= step ? <motion.span layoutId={i === step ? "onb-dot" : undefined} className="fill" transition={SPRING} /> : null}
            </button>
          ))}
        </div>
        <span className="onb-count">{step + 1} / {STEPS.length}</span>
      </header>

      <div className="onb-body">
        <Stage d={d} step={step} />

        <div className="onb-ask">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={current.id} className="onb-panel"
              initial={{ opacity: 0, y: 24, filter: "blur(6px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: -18, filter: "blur(6px)" }} transition={{ duration: 0.4, ease: EASE }}>
              <span className="onb-kicker">{current.kicker}</span>
              <h1>{current.title.split("\n").map((l, i) => <span key={i}>{l}<br /></span>)}</h1>
              <p className="onb-blurb">{current.blurb}</p>

              {current.id === "you" ? (
                <div className="onb-fields">
                  <label className="onb-field">
                    <span className="lab">Your name <i>required</i></span>
                    <input autoFocus value={d.name} onChange={(e) => set("name", e.target.value)} placeholder="Ajinkya" maxLength={80} />
                  </label>
                  <div className="onb-photo">
                    <button type="button" className={`drop ${d.avatar ? "has" : ""}`} onClick={() => fileRef.current?.click()}
                      onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); photo(e.dataTransfer.files[0]); }}>
                      {d.avatar ? <img src={d.avatar} alt="Your photo" /> : <Icon name="user" />}
                      <span className="badge"><Icon name="plus" /></span>
                    </button>
                    <div className="onb-photo-side">
                      <span className="lab">Photo <i className="opt">optional</i></span>
                      <p>{d.avatar ? "Framed by you, kept small, and it follows your account." : "Click the circle or drop an image on it — you get to frame it."}</p>
                      {d.avatar ? <button type="button" className="onb-link" onClick={() => set("avatar", null)}>Remove</button> : null}
                    </div>
                    <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => { photo(e.target.files?.[0]); e.target.value = ""; }} />
                  </div>
                </div>
              ) : null}

              {current.id === "money" ? (
                <div className="onb-fields">
                  <div className="onb-field">
                    <span className="lab">Currency <i>required</i></span>
                    <div className="onb-chips">
                      {CURRENCIES.map((c) => (
                        <button key={c} type="button" className={`chip ${d.currency === c ? "on" : ""}`} onClick={() => set("currency", c)}>
                          {d.currency === c ? <motion.span layoutId="onb-cur" className="pill" transition={SPRING} /> : null}<span>{c}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                  <label className="onb-field">
                    <span className="lab">Monthly take-home <i>required</i></span>
                    <div className="onb-amount">
                      <span className="cur">{money(0, d.currency).replace(/[\d.,\s]/g, "")}</span>
                      <input autoFocus inputMode="numeric" value={d.income} onChange={(e) => set("income", e.target.value)} placeholder="85,000" />
                    </div>
                    {income ? <span className="onb-echo">{money(income, d.currency)} a month · {money(income * 12, d.currency)} a year</span> : null}
                  </label>
                  <label className="onb-field narrow">
                    <span className="lab">Day it lands <i className="opt">optional</i></span>
                    <input inputMode="numeric" value={d.payDay} onChange={(e) => set("payDay", e.target.value.replace(/\D/g, "").slice(0, 2))} placeholder="1" />
                  </label>
                </div>
              ) : null}

              {current.id === "spend" ? (
                <div className="onb-fields">
                  <div className="onb-cats">
                    {suggested.map((c) => {
                      const on = c in d.picks;
                      return (
                        <motion.button key={c} type="button" className={`cat ${on ? "on" : ""}`} onClick={() => pick(c)} whileTap={{ scale: 0.96 }} transition={SPRING} layout>
                          <span className="tick">{on ? <Icon name="check" /> : <Icon name="plus" />}</span>{c}
                          {EXACT.has(c) ? <i>exact</i> : null}
                        </motion.button>
                      );
                    })}
                  </div>
                  <motion.div className="onb-amounts" layout>
                    <AnimatePresence initial={false}>
                      {Object.keys(d.picks).map((c) => (
                        <motion.label key={c} className="onb-amount-row" layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={SPRING}>
                          <span className="n">{c}{EXACT.has(c) ? <i>required</i> : null}</span>
                          <input inputMode="numeric" value={d.picks[c]} placeholder="a month"
                            onChange={(e) => setD((p) => ({ ...p, picks: { ...p.picks, [c]: e.target.value } }))} />
                        </motion.label>
                      ))}
                    </AnimatePresence>
                  </motion.div>
                </div>
              ) : null}

              {current.id === "keep" ? (
                <div className="onb-fields">
                  <div className="onb-field">
                    <span className="lab">Keep back each month <i className="opt">optional</i></span>
                    <div className="onb-slider">
                      <input type="range" min={0} max={60} step={5} value={d.keepPct} onChange={(e) => set("keepPct", Number(e.target.value))} />
                      <div className="onb-slider-out">
                        <b>{d.keepPct}%</b>
                        <span>{income ? `${money(Math.round((income * d.keepPct) / 100), d.currency)} a month` : "of what you earn"}</span>
                      </div>
                    </div>
                  </div>
                  <label className="onb-field">
                    <span className="lab">Saving towards <i className="opt">optional</i></span>
                    <input value={d.goalName} onChange={(e) => set("goalName", e.target.value)} placeholder="Emergency fund" maxLength={80} />
                  </label>
                  <AnimatePresence initial={false}>
                    {d.goalName.trim() ? (
                      <motion.div className="onb-pair" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} transition={SPRING}>
                        <label className="onb-field">
                          <span className="lab">Target <i>required now</i></span>
                          <input autoFocus inputMode="numeric" value={d.goalTarget} onChange={(e) => set("goalTarget", e.target.value)} placeholder="200,000" />
                        </label>
                        <label className="onb-field">
                          <span className="lab">By <i className="opt">optional</i></span>
                          <input type="date" min={isoLocal(new Date())} value={d.goalDue} onChange={(e) => set("goalDue", e.target.value)} />
                        </label>
                      </motion.div>
                    ) : null}
                  </AnimatePresence>
                </div>
              ) : null}

              {current.id === "ready" ? (
                <ul className="onb-summary">
                  <li><span>Name</span><b>{d.name.trim()}</b></li>
                  <li><span>Take-home</span><b>{money(income, d.currency)} a month</b></li>
                  {d.payDay ? <li><span>Pay day</span><b>the {d.payDay}{["st", "nd", "rd"][Number(d.payDay) - 1] ?? "th"}</b></li> : null}
                  <li><span>Keeping back</span><b>{d.keepPct}%{income ? ` · ${money(Math.round((income * d.keepPct) / 100), d.currency)}` : ""}</b></li>
                  <li><span>Budgets</span><b>{Object.values(d.picks).filter((v) => num(v)).length || "none yet"}{Object.values(d.picks).filter((v) => num(v)).length ? " categories" : ""}</b></li>
                  {d.goalName.trim() ? <li><span>Goal</span><b>{d.goalName.trim()} · {money(num(d.goalTarget), d.currency)}</b></li> : null}
                </ul>
              ) : null}

              <AnimatePresence>
                {nudge ? <motion.div className="onb-nudge" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>{nudge}</motion.div> : null}
              </AnimatePresence>
            </motion.div>
          </AnimatePresence>

          <div className="onb-actions">
            {step > 0 ? <button type="button" className="onb-back" onClick={() => setStep((s) => s - 1)}><Icon name="arrowRight" />Back</button> : <span />}
            <motion.button type="button" className={`onb-go ${ok ? "" : "waiting"}`} onClick={next} disabled={busy}
              whileHover={ok ? { scale: 1.03 } : undefined} whileTap={{ scale: 0.97 }} transition={SPRING}>
              <AnimatePresence mode="wait" initial={false}>
                <motion.span key={busy ? "busy" : step === STEPS.length - 1 ? "finish" : "next"} className="in"
                  initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.15 }}>
                  {busy ? <Spinner /> : step === STEPS.length - 1 ? <>Open my dashboard<Icon name="arrowRight" /></> : <>Continue<Icon name="enter" /></>}
                </motion.span>
              </AnimatePresence>
            </motion.button>
          </div>
        </div>
      </div>
      <PhotoCrop file={picked} onCancel={() => setPicked(null)} onSave={(url) => { set("avatar", url); setPicked(null); }} />
    </div>
  );
}
