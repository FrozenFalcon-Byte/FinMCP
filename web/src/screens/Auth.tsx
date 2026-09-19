import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useOutlet } from "react-router-dom";
import { useCurtain } from "../components/Curtain";
import { Icon } from "../components/ui";
import { useAuth } from "../lib/auth";

const PROVIDER_LABEL: Record<string, string> = { google: "Google", github: "GitHub", apple: "Apple", azure: "Microsoft", discord: "Discord", twitter: "X" };

/** Shared frame for the sign-in pages (a layout route): the brand panel stays put while the form swaps. */
export function AuthLayout() {
  const { config } = useAuth();
  const location = useLocation();
  const outlet = useOutlet();
  return (
    <div className="auth">
      <aside className="side">
        <span className="blob a" /><span className="blob b" /><span className="blob c" />
        <Link to="/" className="brand"><span className="mark"><Icon name="logo" /></span><span className="word">FinMCP</span></Link>
        <div>
          <h2>Money you can ask questions of.</h2>
          <p>Track spending in plain words, keep budgets honest, and let the assistants you already use read the same ledger.</p>
        </div>
        <div className="small" style={{ color: "rgba(255,255,255,.5)" }}>{config?.mode === "supabase" ? "Accounts by Supabase Auth · ledger in Postgres with row-level security" : "Local mode · accounts and ledger on this machine"}</div>
      </aside>
      <main className="pane">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={location.pathname} className="box" initial={{ opacity: 0, x: 18 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }}
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}>{outlet}</motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}

export default function AuthScreen({ mode }: { mode: "login" | "register" }) {
  const { user, ready, config, login, register, loginWithProvider } = useAuth();
  const location = useLocation();
  const next = new URLSearchParams(location.search).get("next") || "/app";
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [sample, setSample] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);

  const { go } = useCurtain();
  const leaving = useRef(false); // signing in right now: the curtain takes us to the app, not the redirect below

  useEffect(() => { setError(null); }, [mode]);

  if (ready && user && !leaving.current) return <Navigate to={next} replace />;

  const enterApp = () => go(next);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      leaving.current = true;
      if (mode === "login") {
        await login(email, password);
        enterApp();
      } else {
        const r = await register({ name, email, password, sample_data: sample });
        if (r.needsConfirmation) { leaving.current = false; setConfirm(true); } else enterApp();
      }
    } catch (err) {
      leaving.current = false;
      const msg = err instanceof Error ? err.message : String(err);
      setError(/invalid login credentials/i.test(msg) ? "Wrong email or password. No account with this email yet? Create one below." : msg);
    } finally {
      setBusy(false);
    }
  };

  const providers = config?.mode === "supabase" ? config.oauth_providers : [];
  const minPw = config?.min_password ?? 8;

  return (
    <>
          {confirm ? (
            <>
              <h1>Check your inbox</h1>
              <div className="sub">We sent a confirmation link to <b>{email}</b>. Open it, and you will land in your ledger.</div>
              <div className="notice">Sample data will be added the first time you sign in, so there is something to look at.</div>
              <div className="switch"><Link to="/login">Back to sign in</Link></div>
            </>
          ) : (
            <>
              <h1>{mode === "login" ? "Welcome back" : "Create your ledger"}</h1>
              <div className="sub">{mode === "login" ? "Sign in to pick up where you left off." : "Two fields and you are in. Sample data is optional."}</div>
              {providers.length ? (
                <div className="stack" style={{ gap: 10, marginBottom: 6 }}>
                  {providers.map((p) => (
                    <button key={p} type="button" className="btn lg block" onClick={() => void loginWithProvider(p).catch((e) => setError(e instanceof Error ? e.message : String(e)))}>
                      Continue with {PROVIDER_LABEL[p] ?? p}
                    </button>
                  ))}
                  <div className="or">or with email</div>
                </div>
              ) : null}
              <form onSubmit={(e) => void submit(e)}>
                {mode === "register" ? (
                  <div className="field"><label htmlFor="name">Name</label><input id="name" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ada Lovelace" autoComplete="name" required maxLength={80} /></div>
                ) : null}
                <div className="field"><label htmlFor="email">Email</label><input id="email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" autoComplete="email" required /></div>
                <div className="field">
                  <label htmlFor="password">Password</label>
                  {mode === "login" ? <Link className="forgot" to="/forgot-password">Forgot password?</Link> : null}
                  <input id="password" className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={mode === "register" ? `At least ${minPw} characters` : "Your password"} autoComplete={mode === "register" ? "new-password" : "current-password"} required minLength={mode === "register" ? minPw : 1} />
                </div>
                {mode === "register" ? (
                  <label className="check"><input type="checkbox" checked={sample} onChange={(e) => setSample(e.target.checked)} />Start with 90 days of sample data so the charts have something to show</label>
                ) : null}
                {error ? <div className="error-box">{error}</div> : null}
                <button className="btn primary lg block" type="submit" disabled={busy}>{busy ? "One moment…" : mode === "login" ? "Sign in" : "Create ledger"}</button>
              </form>
              <div className="switch">
                {mode === "login" ? <>New here? <Link to={`/register${location.search}`}>Create your ledger</Link></> : <>Already have a ledger? <Link to={`/login${location.search}`}>Sign in</Link></>}
              </div>
            </>
          )}
    </>
  );
}
