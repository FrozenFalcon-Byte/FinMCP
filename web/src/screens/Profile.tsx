import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useCurtain } from "../components/Curtain";
import { SignOutButton } from "../components/SignOut";
import { useToast } from "../components/Toast";
import { Avatar, Chip, Icon, PageHead, Sheet, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { money, num } from "../lib/format";
import { addPasskey, listPasskeys, readError, removePasskey, supported, type PasskeyRow } from "../lib/passkey";
import { squarePhoto } from "../lib/photo";
import { useLedger } from "../lib/ledger";
import type { BudgetSummary } from "../lib/types";
import { useApi } from "../lib/useApi";
import { useStatus } from "../lib/status";

/** Passkeys on this account. Adding one enrols the device you are on; removing one is immediate, so the page
    keeps a plain-spoken warning when the last one would go. */
function Passkeys() {
  const toast = useToast();
  const [rows, setRows] = useState<PasskeyRow[] | null>(null);
  const [busy, setBusy] = useState<number | "add" | null>(null);

  const load = useCallback(() => { listPasskeys().then(setRows).catch(() => setRows([])); }, []);
  useEffect(load, [load]);

  const add = async () => {
    setBusy("add");
    try {
      const made = await addPasskey(deviceName());
      setRows((r) => [made, ...(r ?? [])]);
      toast("Passkey added. You can sign in with it from now on.", "ok");
    } catch (e) {
      const msg = readError(e);
      if (msg) toast(msg, "err");
    } finally { setBusy(null); }
  };

  const drop = async (row: PasskeyRow) => {
    setBusy(row.id);
    try {
      await removePasskey(row.id);
      setRows((r) => (r ?? []).filter((x) => x.id !== row.id));
      toast("Passkey removed.", "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally { setBusy(null); }
  };

  if (!supported()) return null;
  return (
    <section className="card">
      <div className="card-head">
        <h2>Passkeys</h2>
        <button className="btn sm primary" onClick={() => void add()} disabled={busy !== null}>{busy === "add" ? <Spinner /> : <><Icon name="plus" />Add this device</>}</button>
      </div>
      <p className="small muted">Sign in with your fingerprint, face or screen lock instead of a password. The key never leaves the device, and it only works on this site — so there is nothing to phish.</p>
      <div className="list" style={{ marginTop: 6 }}>
        <AnimatePresence initial={false}>
          {rows === null ? <div className="item"><span className="spinner" /><div className="grow"><div className="s">Looking…</div></div></div>
            : !rows.length ? <div className="item"><Icon name="key" /><div className="grow"><div className="s">None yet. Add one and the next sign-in takes a fingerprint instead of a password.</div></div></div>
            : rows.map((row) => (
              <motion.div className="item" key={row.id} layout initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.22 }}>
                <Icon name="key" />
                <div className="grow">
                  <div className="t">{row.label ?? "Passkey"}</div>
                  <div className="s">Added {new Date(row.created_at).toLocaleDateString()}{row.last_used_at ? ` · last used ${new Date(row.last_used_at).toLocaleDateString()}` : " · not used yet"}</div>
                </div>
                <button className="btn sm ghost" onClick={() => void drop(row)} disabled={busy !== null} aria-label="Remove passkey">{busy === row.id ? <Spinner /> : <Icon name="trash" />}</button>
              </motion.div>
            ))}
        </AnimatePresence>
      </div>
    </section>
  );
}

/** A name you would recognise in a list of devices. The browser tells us nothing reliable, so this is a guess
    from the platform and it stays editable nowhere — it is a label, not a fact. */
function deviceName(): string {
  const ua = navigator.userAgent;
  const os = /iPhone|iPad/.test(ua) ? "iPhone" : /Android/.test(ua) ? "Android" : /Mac OS X/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows" : "This device";
  const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : /Firefox\//.test(ua) ? "Firefox" : "";
  return browser ? `${os} · ${browser}` : os;
}

export default function Profile() {
  const { user, config, logout, refreshUser, requestPasswordReset } = useAuth();
  const { health, refresh } = useStatus();
  const { bump } = useLedger();
  const toast = useToast();
  const { go } = useCurtain();
  const [name, setName] = useState(user?.name ?? "");
  const [currency, setCurrency] = useState(user?.currency ?? "INR");
  const [income, setIncome] = useState(user?.monthly_income ? String(user.monthly_income) : "");
  const [payDay, setPayDay] = useState(user?.pay_day ? String(user.pay_day) : "");
  const [keepPct, setKeepPct] = useState(user?.keep_pct ?? 20);
  const [busy, setBusy] = useState<"save" | "reset" | "delete" | "photo" | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [phrase, setPhrase] = useState("");
  if (!user) return null;
  const s = health?.status;
  // Budgets outrank take-home in safe-to-spend, so the field has to be able to say when it is not the one in charge.
  const budget = useApi(() => api.get<BudgetSummary>("/budget"), []);
  const budgeted = budget.data?.totals.budget ?? 0;
  const supabase = config?.mode === "supabase";
  const since = user.created_at ? new Date(user.created_at).toLocaleDateString("en-IN", { month: "long", year: "numeric" }) : null;
  const asNumber = (t: string): number => { const n = parseFloat(t.replace(/[^\d.]/g, "")); return Number.isFinite(n) && n > 0 ? n : 0; };
  const dirty = name.trim() !== user.name || currency.trim().toUpperCase() !== user.currency
    || asNumber(income) !== (user.monthly_income ?? 0) || (payDay ? Number(payDay) : null) !== user.pay_day || keepPct !== (user.keep_pct ?? 20);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy("save");
    try {
      await api.patch("/auth/profile", {
        name: name.trim(), currency: currency.trim().toUpperCase(),
        monthly_income: asNumber(income), pay_day: payDay ? Number(payDay) : undefined, keep_pct: keepPct,
      });
      await refreshUser();
      await refresh();
      bump();
      toast("Profile saved.");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "err");
    } finally {
      setBusy(null);
    }
  };
  /** The photo is stored on the profile row as a small square, so it follows the account onto any device. */
  const setPhoto = async (file: File | undefined | null) => {
    if (!file) return;
    setBusy("photo");
    try {
      await api.patch("/auth/profile", { avatar: await squarePhoto(file) });
      await refreshUser();
      toast("Photo updated.");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "err");
    } finally {
      setBusy(null);
    }
  };
  const clearPhoto = async () => {
    setBusy("photo");
    try { await api.patch("/auth/profile", { avatar: "" }); await refreshUser(); } catch (err) { toast(err instanceof Error ? err.message : String(err), "err"); } finally { setBusy(null); }
  };

  const sendReset = async () => {
    setBusy("reset");
    try {
      await requestPasswordReset(user.email);
      toast(supabase ? `Reset link sent to ${user.email}.` : "Reset link created. Local mode prints it in the API console.");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "err");
    } finally {
      setBusy(null);
    }
  };
  const remove = async () => {
    setBusy("delete");
    try {
      await api.del("/auth/account");
      go("/", { afterSwap: () => void logout() });
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "err");
      setBusy(null);
    }
  };

  return (
    <>
      <PageHead title="Profile" sub="Your account, how you sign in, and your data." />
      <section className="card profile-hero">
        <button type="button" className="profile-pfp" onClick={() => fileRef.current?.click()} disabled={busy === "photo"}
          title="Change your photo" aria-label="Change your photo"
          onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); void setPhoto(e.dataTransfer.files[0]); }}>
          <Avatar name={user.name} src={user.avatar} lg />
          <span className="edit">{busy === "photo" ? <Spinner /> : <Icon name="edit" />}</span>
        </button>
        <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => { void setPhoto(e.target.files?.[0]); e.target.value = ""; }} />
        <div className="who">
          <h2>{user.name}</h2>
          <div className="muted">{user.email}</div>
          <div className="chips">
            {since ? <Chip>Member since {since}</Chip> : null}
            <Chip>{supabase ? "Supabase Auth" : "Local account"}</Chip>
            <Chip>{user.currency}</Chip>
            {user.monthly_income ? <Chip tone="accent">{money(user.monthly_income, user.currency)} a month</Chip> : null}
          </div>
          {user.avatar ? <button type="button" className="linkish" onClick={() => void clearPhoto()}>Remove photo</button> : null}
        </div>
        <SignOutButton className="btn" />
      </section>

      <div className="grid three profile-stats">
        <div className="card stat"><span className="k">Transactions</span><span className="v">{s ? num(s.transactions) : "…"}</span></div>
        <div className="card stat"><span className="k">Waiting for review</span><span className="v">{s ? num(s.needs_review) : "…"}</span></div>
        <div className="card stat"><span className="k">Merchants learned</span><span className="v">{s ? num(s.merchant_memory) : "…"}</span></div>
      </div>

      <div className="grid two profile-split">
        <section className="card">
          <div className="card-head"><h2>Details</h2></div>
          <form className="stack" onSubmit={(e) => void save(e)}>
            <div className="field"><label htmlFor="p-name">Name</label><input id="p-name" className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required /></div>
            <div className="field"><label htmlFor="p-cur">Currency</label><input id="p-cur" className="input" value={currency} onChange={(e) => setCurrency(e.target.value)} maxLength={3} minLength={3} required /><span className="help">Three-letter code. Amounts are stored as entered; this changes how they are shown and what the assistant says.</span></div>
            <div className="field"><label htmlFor="p-income">Monthly take-home</label>
              <input id="p-income" className="input" inputMode="numeric" value={income} onChange={(e) => setIncome(e.target.value)} placeholder="85,000" />
              <span className="help">{budgeted
                ? <>Your budgets come to {money(budgeted, currency)} a month, and <Link to="/app/budgets">those</Link> are what safe-to-spend uses. This is what the assistant knows you earn.</>
                : <>What safe-to-spend is measured against until you set budgets, which take over.</>}</span></div>
            <div className="field"><label htmlFor="p-payday">Pay day</label>
              <input id="p-payday" className="input" inputMode="numeric" value={payDay} onChange={(e) => setPayDay(e.target.value.replace(/\D/g, "").slice(0, 2))} placeholder="1" />
              <span className="help">The day of the month it lands. Optional.</span></div>
            <div className="field"><label htmlFor="p-keep">Keep back each month · {keepPct}%{asNumber(income) ? ` · ${money(Math.round((asNumber(income) * keepPct) / 100), currency)}` : ""}</label>
              <input id="p-keep" type="range" min={0} max={60} step={5} value={keepPct} onChange={(e) => setKeepPct(Number(e.target.value))} />
              <span className="help">Held out of safe-to-spend, so the number you see is already after saving.</span></div>
            <button className="btn primary" type="submit" disabled={busy !== null || !dirty}>{busy === "save" ? <Spinner /> : "Save changes"}</button>
          </form>
        </section>
        {/* Sign-in is two cards, stacked: the column grows with them rather than one card stretching to match
            the form beside it and leaving a hole under its last row. */}
        <div className="stack">
          <section className="card">
            <div className="card-head"><h2>Sign-in and security</h2></div>
            <div className="list">
              <div className="item"><Icon name="user" /><div className="grow"><div className="t">Email</div><div className="s">{user.email}</div></div></div>
              <div className="item"><Icon name="key" /><div className="grow"><div className="t">Password</div><div className="s">We email you a link to choose a new one.</div></div>
                <button className="btn sm" onClick={() => void sendReset()} disabled={busy !== null}>{busy === "reset" ? <Spinner /> : "Send reset link"}</button></div>
              <div className="item"><Icon name="shield" /><div className="grow"><div className="t">This browser</div><div className="s">Signed in. Signing out removes the saved session and cached data here.</div></div>
                <SignOutButton /></div>
            </div>
          </section>
          <Passkeys />
        </div>
      </div>

      <section className="card danger-zone">
        <div className="card-head"><h2>Delete account</h2></div>
        <p className="small muted">Erases every transaction, category, goal, token and the activity trail. There is no undo.</p>
        <button className="btn danger sm" style={{ marginTop: 12 }} onClick={() => setConfirmDelete(true)}><Icon name="trash" />Delete my account and data</button>
      </section>
      <Sheet open={confirmDelete} onClose={() => setConfirmDelete(false)} title="Delete everything?" sub="Type DELETE to confirm.">
        <div className="stack">
          <input className="input" value={phrase} onChange={(e) => setPhrase(e.target.value)} placeholder="DELETE" autoFocus />
          <button className="btn danger" disabled={phrase !== "DELETE" || busy !== null} onClick={() => void remove()}>{busy === "delete" ? <Spinner /> : "Delete account"}</button>
        </div>
      </Sheet>
    </>
  );
}
