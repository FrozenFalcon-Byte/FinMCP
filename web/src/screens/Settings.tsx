import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useToast } from "../components/Toast";
import { Chip, Icon, PageHead, Sheet, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { num } from "../lib/format";
import { useLedger } from "../lib/ledger";
import { useStatus } from "../lib/status";

export default function Settings() {
  const { user, config, logout, refreshUser } = useAuth();
  const { health, refresh } = useStatus();
  const { bump } = useLedger();
  const toast = useToast();
  const navigate = useNavigate();
  const [name, setName] = useState(user?.name ?? "");
  const [currency, setCurrency] = useState(user?.currency ?? "INR");
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [phrase, setPhrase] = useState("");
  const s = health?.status;

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.patch("/auth/profile", { name: name.trim(), currency: currency.trim().toUpperCase() });
      await refreshUser();
      await refresh();
      bump();
      toast("Saved.");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "err");
    } finally {
      setBusy(false);
    }
  };
  const seed = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ seeded: boolean }>("/auth/seed-demo");
      toast(r.seeded ? "Added 90 days of sample data." : "Your ledger already has transactions; nothing added.");
      bump();
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "err");
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    setBusy(true);
    try {
      await api.del("/auth/account");
      await logout();
      navigate("/", { replace: true });
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "err");
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead title="Settings" sub={user?.email} />
      <div className="grid two">
        <section className="card">
          <div className="card-head"><h2>Profile</h2></div>
          <form className="stack" onSubmit={(e) => void save(e)}>
            <div className="field"><label>Name</label><input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required /></div>
            <div className="field"><label>Currency</label><input className="input" value={currency} onChange={(e) => setCurrency(e.target.value)} maxLength={3} minLength={3} required /><span className="help">Three-letter code. Amounts are stored as entered; this only changes how they are shown and what the assistant says.</span></div>
            <button className="btn primary" type="submit" disabled={busy}>{busy ? <Spinner /> : "Save"}</button>
          </form>
        </section>
        <section className="card">
          <div className="card-head"><h2>Your ledger</h2>{s ? <Chip tone="good">{num(s.transactions)} transactions</Chip> : null}</div>
          <div className="list">
            <div className="item"><div className="grow"><div className="t">Identity</div><div className="s">{config?.mode === "supabase" ? "Supabase Auth" : "Local accounts on this machine"}</div></div></div>
            <div className="item"><div className="grow"><div className="t">Database</div><div className="s">{health?.database === "supabase" ? "Supabase Postgres" : "Embedded local Postgres"} · row-level security {health?.rls ?? "…"}</div></div></div>
            <div className="item"><div className="grow"><div className="t">Categorisation engine</div><div className="s">{health?.driver === "anthropic" ? `Claude (${health.model})` : "Offline rules. Add ANTHROPIC_API_KEY on the server for Claude."}</div></div></div>
            <div className="item"><div className="grow"><div className="t">Merchants learned</div><div className="s">{s ? num(s.merchant_memory) : "…"} from your corrections</div></div></div>
          </div>
          <div className="row" style={{ marginTop: 14, flexWrap: "wrap" }}>
            <button className="btn sm" onClick={() => void api.download("/export.csv", "finmcp-transactions.csv")}><Icon name="download" />Export CSV</button>
            <button className="btn sm" onClick={() => void seed()} disabled={busy}><Icon name="spark" />Add sample data</button>
            <button className="btn sm ghost" onClick={() => void logout().then(() => navigate("/"))}>Sign out</button>
          </div>
        </section>
      </div>
      <section className="card" style={{ marginTop: 16, borderColor: "var(--bad-soft)" }}>
        <div className="card-head"><h2>Delete account</h2></div>
        <p className="small muted">Erases every transaction, category, goal, token and the activity trail. There is no undo.</p>
        <button className="btn danger sm" style={{ marginTop: 12 }} onClick={() => setConfirmDelete(true)}><Icon name="trash" />Delete my account and data</button>
      </section>
      <Sheet open={confirmDelete} onClose={() => setConfirmDelete(false)} title="Delete everything?" sub="Type DELETE to confirm.">
        <div className="stack">
          <input className="input" value={phrase} onChange={(e) => setPhrase(e.target.value)} placeholder="DELETE" autoFocus />
          <button className="btn danger" disabled={phrase !== "DELETE" || busy} onClick={() => void remove()}>{busy ? <Spinner /> : "Delete account"}</button>
        </div>
      </Sheet>
    </>
  );
}
