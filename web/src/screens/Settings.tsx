import { useState } from "react";
import { Link } from "react-router-dom";
import { SignOutButton } from "../components/SignOut";
import { useToast } from "../components/Toast";
import { Avatar, Chip, Icon, PageHead } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { num } from "../lib/format";
import { useLedger } from "../lib/ledger";
import { useStatus } from "../lib/status";

function engineLabel(driver: string | undefined, model: string | null | undefined): string {
  if (driver === "openrouter") return `OpenRouter · ${model ?? "default model"}`;
  if (driver === "anthropic") return `Claude (${model})`;
  return "Offline rules. Add OPENROUTER_API_KEY to .env for model-powered categorising and answers.";
}

export default function Settings() {
  const { user, config } = useAuth();
  const { health } = useStatus();
  const { bump } = useLedger();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const s = health?.status;

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

  return (
    <>
      <PageHead title="Settings" sub="How this workspace runs, and your data." />
      <div className="grid two">
        <section className="card">
          <div className="card-head"><h2>Account</h2></div>
          {user ? (
            <Link to="/app/profile" className="account-link">
              <Avatar name={user.name} />
              <div className="grow"><div className="t">{user.name}</div><div className="s">{user.email}</div></div>
              <Icon name="arrowRight" />
            </Link>
          ) : null}
          <p className="small muted" style={{ marginTop: 12 }}>Name, currency, password and account deletion live on your profile.</p>
          <div className="row" style={{ marginTop: 14 }}><SignOutButton /></div>
        </section>
        <section className="card">
          <div className="card-head"><h2>Your ledger</h2>{s ? <Chip tone="good">{num(s.transactions)} transactions</Chip> : null}</div>
          <div className="list">
            <div className="item"><div className="grow"><div className="t">Identity</div><div className="s">{config?.mode === "supabase" ? "Supabase Auth" : "Local accounts on this machine"}</div></div></div>
            <div className="item"><div className="grow"><div className="t">Database</div><div className="s">{health?.database === "supabase" ? "Supabase Postgres" : "Embedded local Postgres"} · row-level security {health?.rls ?? "…"}</div></div></div>
            <div className="item"><div className="grow"><div className="t">Model engine</div><div className="s">{engineLabel(health?.driver, health?.model)}</div></div></div>
            <div className="item"><div className="grow"><div className="t">Merchants learned</div><div className="s">{s ? num(s.merchant_memory) : "…"} from your corrections</div></div></div>
          </div>
          <div className="row" style={{ marginTop: 14, flexWrap: "wrap" }}>
            <button className="btn sm" onClick={() => void api.download("/export.csv", "finmcp-transactions.csv")}><Icon name="download" />Export CSV</button>
            <button className="btn sm" onClick={() => void seed()} disabled={busy}><Icon name="spark" />Add sample data</button>
          </div>
        </section>
      </div>
    </>
  );
}
