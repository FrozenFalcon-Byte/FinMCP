/* Forgotten password, in two steps. /forgot-password asks for the email and sends a reset link (Supabase emails it;
   local mode writes it to the API console, since there is no mail server). /reset-password is where the link lands:
   choose a new password and you are signed in. */
import { useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { useCurtain } from "../components/Curtain";
import { useAuth } from "../lib/auth";

export default function ResetPassword({ mode }: { mode: "forgot" | "reset" }) {
  const { config, ready, user, requestPasswordReset, resetPassword } = useAuth();
  const { go } = useCurtain();
  const location = useLocation();
  const token = new URLSearchParams(location.search).get("token");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const supabase = config?.mode === "supabase";
  const minPw = config?.min_password ?? 8;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    if (mode === "reset" && password !== confirm) { setError("The two passwords do not match."); return; }
    setBusy(true);
    try {
      if (mode === "forgot") {
        await requestPasswordReset(email.trim());
        setSent(true);
      } else {
        await resetPassword(password, token);
        go("/app");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (mode === "forgot" && sent) {
    return (
      <>
        <h1>Check your inbox</h1>
        <div className="sub">
          {supabase ? <>If an account exists for <b>{email}</b>, a reset link is on its way. It opens this app, where you choose a new password.</>
            : <>If an account exists for <b>{email}</b>, a reset link was created. This server runs in local mode without email, so the link is printed in the API console. It works once and expires in 30 minutes.</>}
        </div>
        <div className="switch"><Link to="/login">Back to sign in</Link></div>
      </>
    );
  }

  // Supabase signs the recovery link's visitor in; local mode carries a token instead.
  const linkMissing = mode === "reset" && ready && (supabase ? !user : !token);
  return (
    <>
      <h1>{mode === "forgot" ? "Reset your password" : "Choose a new password"}</h1>
      <div className="sub">{mode === "forgot" ? "Enter the email you signed up with and we will send you a link." : "Pick something you have not used here before."}</div>
      {linkMissing ? (
        <>
          <div className="error-box">This reset link has expired or was already used.</div>
          <div className="switch"><Link to="/forgot-password">Send a new link</Link></div>
        </>
      ) : (
        <form onSubmit={(e) => void submit(e)}>
          {mode === "forgot" ? (
            <div className="field"><label htmlFor="email">Email</label><input id="email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" autoComplete="email" required /></div>
          ) : (<>
            <div className="field"><label htmlFor="password">New password</label><input id="password" className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={`At least ${minPw} characters`} autoComplete="new-password" required minLength={minPw} /></div>
            <div className="field"><label htmlFor="confirm">Repeat it</label><input id="confirm" className="input" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required minLength={minPw} /></div>
          </>)}
          {error ? <div className="error-box">{error}</div> : null}
          <button className="btn primary lg block" type="submit" disabled={busy}>{busy ? "One moment…" : mode === "forgot" ? "Send reset link" : "Save and sign in"}</button>
        </form>
      )}
      <div className="switch">Remembered it? <Link to="/login">Sign in</Link></div>
    </>
  );
}
