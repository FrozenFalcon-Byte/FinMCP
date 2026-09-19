/* Sign-in state for the whole app. Two identity providers behind one interface:
   - Supabase Auth (email/password + OAuth) when the API says it is configured; tokens come from supabase-js.
   - The API's own local accounts otherwise; the session JWT is kept in localStorage. */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { SupabaseClient } from "@supabase/supabase-js";
import { api, setAuthToken } from "./api";

export interface AuthUser { id: string; email: string; name: string; currency: string; created_at: string }
export interface AuthConfig {
  mode: "local" | "supabase";
  supabase_url: string | null;
  supabase_anon_key: string | null;
  oauth_providers: string[];
  min_password: number;
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
  logout: () => Promise<void>;
  refreshUser: () => Promise<AuthUser | null>;
}

const LOCAL_KEY = "finmcp.session";
const PENDING_SEED = "finmcp.pendingSeed";

const AuthContext = createContext<AuthValue>({
  config: null, user: null, ready: false, token: null, supabase: null,
  login: async () => { throw new Error("auth not ready"); },
  register: async () => { throw new Error("auth not ready"); },
  loginWithProvider: async () => { throw new Error("auth not ready"); },
  logout: async () => {},
  refreshUser: async () => null,
});

function readLocal(): string | null {
  try {
    const raw = localStorage.getItem(LOCAL_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { access_token: string; expires_at: number };
    if (parsed.expires_at && parsed.expires_at < Date.now() / 1000) { localStorage.removeItem(LOCAL_KEY); return null; }
    return parsed.access_token;
  } catch { return null; }
}

function writeLocal(token: string | null, expiresIn = 30 * 24 * 3600): void {
  try {
    if (!token) localStorage.removeItem(LOCAL_KEY);
    else localStorage.setItem(LOCAL_KEY, JSON.stringify({ access_token: token, expires_at: Math.floor(Date.now() / 1000) + expiresIn }));
  } catch { /* storage unavailable */ }
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
        const client = createClient(cfg.supabase_url, cfg.supabase_anon_key, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } });
        supabaseRef.current = client;
        setSupabase(client);
        const { data } = await client.auth.getSession();
        await loadUser(data.session?.access_token ?? null);
        const { data: sub } = client.auth.onAuthStateChange((_event, session) => { void loadUser(session?.access_token ?? null); });
        unsubscribe = () => sub.subscription.unsubscribe();
      } else {
        await loadUser(readLocal());
      }
      if (!cancelled) setReady(true);
    })();
    const onUnauthorized = () => {
      const client = supabaseRef.current;
      if (client) void client.auth.getSession().then(({ data }) => { if (!data.session) void loadUser(null); });
      else { writeLocal(null); void loadUser(null); }
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

  const logout = useCallback(async () => {
    try { await api.post("/auth/logout"); } catch { /* ignore */ }
    const client = supabaseRef.current;
    if (client) await client.auth.signOut();
    writeLocal(null);
    await loadUser(null);
  }, [loadUser]);

  const refreshUser = useCallback(() => loadUser(token), [loadUser, token]);

  const value = useMemo<AuthValue>(() => ({ config, user, ready, token, supabase, login, register, loginWithProvider, logout, refreshUser }),
    [config, user, ready, token, supabase, login, register, loginWithProvider, logout, refreshUser]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
