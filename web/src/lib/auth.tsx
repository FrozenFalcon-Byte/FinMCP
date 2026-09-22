/* Sign-in state for the whole app. Two identity providers behind one interface:
   - Supabase Auth (email/password + OAuth) when the API says it is configured; tokens come from supabase-js.
   - The API's own local accounts otherwise.
   Either way the session lives in first-party cookies (see cookies.ts) and signing out clears them. */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { SupabaseClient } from "@supabase/supabase-js";
import { clearCache } from "./cache";
import { api, setAuthToken } from "./api";
import { cookieStorage, getCookie, removeCookie, setCookie } from "./cookies";
import { signInWithPasskey } from "./passkey";

export interface AuthUser {
  id: string; email: string; name: string; currency: string; created_at: string;
  /** A small square data URL, or null. Kept on the profile so it follows the account between devices. */
  avatar: string | null;
  monthly_income: number | null;
  pay_day: number | null;
  keep_pct: number | null;
  /** Set once first-run setup is finished. Until then the app shows the setup instead of the dashboard. */
  onboarded_at: string | null;
  tour_seen_at: string | null;
}
export interface AuthConfig {
  mode: "local" | "supabase";
  supabase_url: string | null;
  supabase_anon_key: string | null;
  oauth_providers: string[];
  min_password: number;
  passkeys?: boolean;
  public_url: string;
  mcp_endpoint: string;
}
export interface RegisterInput { name: string; email: string; password: string; sample_data: boolean }
export interface RegisterResult { user: AuthUser | null; needsConfirmation: boolean }

interface AuthValue {
  config: AuthConfig | null;
  user: AuthUser | null;
  ready: boolean;
  token: string | null;
  supabase: SupabaseClient | null;
  login: (email: string, password: string) => Promise<AuthUser>;
  register: (input: RegisterInput) => Promise<RegisterResult>;
  loginWithProvider: (provider: string) => Promise<void>;
  /** A passkey is this API's own proof, so it mints this API's own session — in either identity mode. */
  loginWithPasskey: () => Promise<AuthUser>;
  logout: () => Promise<void>;
  requestPasswordReset: (email: string) => Promise<void>;
  resetPassword: (password: string, token?: string | null) => Promise<AuthUser | null>;
  refreshUser: () => Promise<AuthUser | null>;
}

const LOCAL_KEY = "finmcp.session";
const SUPABASE_KEY = "finmcp.auth";
const PENDING_SEED = "finmcp.pendingSeed";

const AuthContext = createContext<AuthValue>({
  config: null, user: null, ready: false, token: null, supabase: null,
  login: async () => { throw new Error("auth not ready"); },
  register: async () => { throw new Error("auth not ready"); },
  loginWithProvider: async () => { throw new Error("auth not ready"); },
  loginWithPasskey: async () => { throw new Error("auth not ready"); },
  logout: async () => {},
  requestPasswordReset: async () => {},
  resetPassword: async () => null,
  refreshUser: async () => null,
});

function readLocal(): string | null {
  try {
    const legacy = localStorage.getItem(LOCAL_KEY);  // sessions saved before cookies: move them over once
    if (legacy) { localStorage.removeItem(LOCAL_KEY); setCookie(LOCAL_KEY, legacy); }
  } catch { /* storage unavailable */ }
  try {
    const raw = getCookie(LOCAL_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { access_token: string; expires_at: number };
    if (parsed.expires_at && parsed.expires_at < Date.now() / 1000) { removeCookie(LOCAL_KEY); return null; }
    return parsed.access_token;
  } catch { return null; }
}

function writeLocal(token: string | null, expiresIn = 30 * 24 * 3600): void {
  if (!token) removeCookie(LOCAL_KEY);
  else setCookie(LOCAL_KEY, JSON.stringify({ access_token: token, expires_at: Math.floor(Date.now() / 1000) + expiresIn }), expiresIn);
}

function clearSessionCookies(): void {
  removeCookie(LOCAL_KEY);
  removeCookie(SUPABASE_KEY);
}

async function seedIfPending(): Promise<void> {
  try {
    if (localStorage.getItem(PENDING_SEED) === "1") {
      localStorage.removeItem(PENDING_SEED);
      await api.post("/auth/seed-demo");
      window.dispatchEvent(new Event("finmcp:ledger-changed"));
    }
  } catch { /* nothing to do */ }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const supabaseRef = useRef<SupabaseClient | null>(null);
  const [supabase, setSupabase] = useState<SupabaseClient | null>(null);

  const loadUser = useCallback(async (tok: string | null): Promise<AuthUser | null> => {
    setAuthToken(tok);
    setToken(tok);
    if (!tok) { setUser(null); return null; }
    try {
      const r = await api.get<{ user: AuthUser }>("/auth/me");
      setUser(r.user);
      await seedIfPending();
      return r.user;
    } catch {
      setUser(null);
      return null;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let unsubscribe: (() => void) | null = null;
    (async () => {
      let cfg: AuthConfig | null = null;
      try { cfg = await api.get<AuthConfig>("/auth/config"); } catch { cfg = null; }
      if (cancelled) return;
      setConfig(cfg);
      if (cfg?.mode === "supabase" && cfg.supabase_url && cfg.supabase_anon_key) {
        const { createClient } = await import("@supabase/supabase-js");
        const client = createClient(cfg.supabase_url, cfg.supabase_anon_key, {
          auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, storage: cookieStorage, storageKey: SUPABASE_KEY },
        });
        supabaseRef.current = client;
        setSupabase(client);
        const { data } = await client.auth.getSession();
        await loadUser(data.session?.access_token ?? readLocal());
        const { data: sub } = client.auth.onAuthStateChange((event, session) => {
          void loadUser(session?.access_token ?? readLocal());
          // A recovery link that Supabase sent to its Site URL instead of ours still ends on the reset form.
          if (event === "PASSWORD_RECOVERY" && window.location.pathname !== "/reset-password") window.location.replace("/reset-password");
        });
        unsubscribe = () => sub.subscription.unsubscribe();
      } else {
        await loadUser(readLocal());
      }
      if (!cancelled) setReady(true);
    })();
    const onUnauthorized = () => {
      const client = supabaseRef.current;
      if (client) void client.auth.getSession().then(({ data }) => { if (!data.session) void loadUser(null); });
      else { clearSessionCookies(); void loadUser(null); }
    };
    window.addEventListener("finmcp:unauthorized", onUnauthorized);
    return () => { cancelled = true; unsubscribe?.(); window.removeEventListener("finmcp:unauthorized", onUnauthorized); };
  }, [loadUser]);

  const login = useCallback(async (email: string, password: string) => {
    const client = supabaseRef.current;
    if (client) {
      const { data, error } = await client.auth.signInWithPassword({ email, password });
      if (error) throw new Error(error.message);
      const u = await loadUser(data.session?.access_token ?? null);
      if (!u) throw new Error("Signed in, but the ledger API did not accept the session.");
      return u;
    }
    const r = await api.post<{ access_token: string; expires_in: number; user: AuthUser }>("/auth/login", { email, password });
    writeLocal(r.access_token, r.expires_in);
    const u = await loadUser(r.access_token);
    if (!u) throw new Error("Could not load your account.");
    return u;
  }, [loadUser]);

  const register = useCallback(async (input: RegisterInput): Promise<RegisterResult> => {
    const client = supabaseRef.current;
    if (client) {
      const { data, error } = await client.auth.signUp({ email: input.email, password: input.password, options: { data: { name: input.name }, emailRedirectTo: `${window.location.origin}/app` } });
      if (error) throw new Error(error.message);
      try { if (input.sample_data) localStorage.setItem(PENDING_SEED, "1"); } catch { /* ignore */ }
      if (!data.session) return { user: null, needsConfirmation: true };
      const u = await loadUser(data.session.access_token);
      return { user: u, needsConfirmation: false };
    }
    const r = await api.post<{ access_token: string; expires_in: number; user: AuthUser }>("/auth/register", input);
    writeLocal(r.access_token, r.expires_in);
    const u = await loadUser(r.access_token);
    return { user: u, needsConfirmation: false };
  }, [loadUser]);

  const loginWithProvider = useCallback(async (provider: string) => {
    const client = supabaseRef.current;
    if (!client) throw new Error("Social sign-in needs Supabase.");
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { error } = await client.auth.signInWithOAuth({ provider: provider as any, options: { redirectTo: `${window.location.origin}/app` } });
    if (error) throw new Error(error.message);
  }, []);

  const loginWithPasskey = useCallback(async () => {
    const r = await signInWithPasskey();
    writeLocal(r.access_token, r.expires_in);
    const u = await loadUser(r.access_token);
    if (!u) throw new Error("Signed in, but the ledger API did not accept the session.");
    return u;
  }, [loadUser]);

  const logout = useCallback(async () => {
    try { await api.post("/auth/logout"); } catch { /* ignore */ }
    const client = supabaseRef.current;
    if (client) {
      // "local" scope ends this browser's session even when the network call to revoke the refresh token fails.
      try { await client.auth.signOut({ scope: "local" }); } catch { /* cookies are cleared below regardless */ }
    }
    clearSessionCookies();
    clearCache();
    await loadUser(null);
  }, [loadUser]);

  const requestPasswordReset = useCallback(async (email: string) => {
    const client = supabaseRef.current;
    if (client) {
      const { error } = await client.auth.resetPasswordForEmail(email, { redirectTo: `${window.location.origin}/reset-password` });
      if (error) throw new Error(error.message);
      return;
    }
    await api.post("/auth/password/forgot", { email });
  }, []);

  const resetPassword = useCallback(async (password: string, resetToken?: string | null) => {
    const client = supabaseRef.current;
    if (client) {
      const { data, error } = await client.auth.updateUser({ password });
      if (error) throw new Error(error.message);
      const { data: s2 } = await client.auth.getSession();
      return data.user ? loadUser(s2.session?.access_token ?? null) : null;
    }
    if (!resetToken) throw new Error("This reset link is incomplete. Ask for a new one.");
    const r = await api.post<{ access_token: string; expires_in: number; user: AuthUser }>("/auth/password/reset", { token: resetToken, password });
    writeLocal(r.access_token, r.expires_in);
    return loadUser(r.access_token);
  }, [loadUser]);

  const refreshUser = useCallback(() => loadUser(token), [loadUser, token]);

  const value = useMemo<AuthValue>(() => ({ config, user, ready, token, supabase, login, register, loginWithProvider, loginWithPasskey, logout, requestPasswordReset, resetPassword, refreshUser }),
    [config, user, ready, token, supabase, login, register, loginWithProvider, loginWithPasskey, logout, requestPasswordReset, resetPassword, refreshUser]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
