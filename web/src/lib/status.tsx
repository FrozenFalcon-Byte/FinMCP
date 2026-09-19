import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { useAuth } from "./auth";
import type { Health } from "./types";

interface StatusValue { health: Health | null; error: string | null; refresh: () => Promise<void>; currency: string }

const StatusContext = createContext<StatusValue>({ health: null, error: null, refresh: async () => {}, currency: "INR" });

export function StatusProvider({ children }: { children: ReactNode }) {
  const { token, user } = useAuth();
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try {
      setHealth(await api.get<Health>("/health"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "API unreachable");
    }
  }, []);
  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 60000);
    return () => clearInterval(t);
  }, [refresh, token]);
  const currency = health?.status?.currency ?? user?.currency ?? "INR";
  return <StatusContext.Provider value={{ health, error, refresh, currency }}>{children}</StatusContext.Provider>;
}

export const useStatus = () => useContext(StatusContext);
