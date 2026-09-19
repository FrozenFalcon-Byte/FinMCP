/* One sign-out action for every place that offers it. The veil carries you to the landing page, and the session
   ends once the app is gone from underneath: signing out while it is still mounted would bounce it to sign-in. */
import { useState } from "react";
import { useAuth } from "../lib/auth";
import { useCurtain } from "./Curtain";
import { Icon } from "./ui";

export function SignOutButton({ className = "btn sm ghost", label = "Sign out", onDone }: { className?: string; label?: string; onDone?: () => void }) {
  const { logout } = useAuth();
  const { go } = useCurtain();
  const [busy, setBusy] = useState(false);
  const signOut = () => {
    if (busy) return;
    setBusy(true);
    onDone?.();
    go("/", { afterSwap: () => void logout() });
  };
  return <button type="button" className={className} onClick={signOut} disabled={busy}><Icon name="logout" />{label}</button>;
}
