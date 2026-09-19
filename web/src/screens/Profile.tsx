import { useState } from "react";
import { useCurtain } from "../components/Curtain";
import { SignOutButton } from "../components/SignOut";
import { useToast } from "../components/Toast";
import { Avatar, Chip, Icon, PageHead, Sheet, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { num } from "../lib/format";
import { useLedger } from "../lib/ledger";
import { useStatus } from "../lib/status";

export default function Profile() {
  const { user, config, logout, refreshUser, requestPasswordReset } = useAuth();
  const { health, refresh } = useStatus();
  const { bump } = useLedger();
  const toast = useToast();
  const { go } = useCurtain();
  const [name, setName] = useState(user?.name ?? "");
  const [currency, setCurrency] = useState(user?.currency ?? "INR");
  const [busy, setBusy] = useState<"save" | "reset" | "delete" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [phrase, setPhrase] = useState("");
  if (!user) return null;
  const s = health?.status;
  const supabase = config?.mode === "supabase";
  const since = user.created_at ? new Date(user.created_at).toLocaleDateString("en-IN", { month: "long", year: "numeric" }) : null;
  const dirty = name.trim() !== user.name || currency.trim().toUpperCase() !== user.currency;

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy("save");
    try {
      await api.patch("/auth/profile", { name: name.trim(), currency: currency.trim().toUpperCase() });
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
        <Avatar name={user.name} />
        <div className="who">
          <h2>{user.name}</h2>
          <div className="muted">{user.email}</div>
          <div className="chips">
            {since ? <Chip>Member since {since}</Chip> : null}
            <Chip>{supabase ? "Supabase Auth" : "Local account"}</Chip>
            <Chip>{user.currency}</Chip>
          </div>
        </div>
        <SignOutButton className="btn" />
      </section>

      <div className="grid three profile-stats">
        <div className="card stat"><span className="k">Transactions</span><span className="v">{s ? num(s.transactions) : "…"}</span></div>
        <div className="card stat"><span className="k">Waiting for review</span><span className="v">{s ? num(s.needs_review) : "…"}</span></div>
        <div className="card stat"><span className="k">Merchants learned</span><span className="v">{s ? num(s.merchant_memory) : "…"}</span></div>
      </div>

      <div className="grid two">
        <section className="card">
          <div className="card-head"><h2>Details</h2></div>
          <form className="stack" onSubmit={(e) => void save(e)}>
            <div className="field"><label htmlFor="p-name">Name</label><input id="p-name" className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required /></div>
            <div className="field"><label htmlFor="p-cur">Currency</label><input id="p-cur" className="input" value={currency} onChange={(e) => setCurrency(e.target.value)} maxLength={3} minLength={3} required /><span className="help">Three-letter code. Amounts are stored as entered; this changes how they are shown and what the assistant says.</span></div>
            <button className="btn primary" type="submit" disabled={busy !== null || !dirty}>{busy === "save" ? <Spinner /> : "Save changes"}</button>
          </form>
        </section>
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
