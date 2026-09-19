import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

export interface ToastAction { label: string; onClick: () => void | Promise<void> }
interface Toast { id: number; text: string; kind: "ok" | "err"; action?: ToastAction }
type Push = (text: string, kind?: "ok" | "err", action?: ToastAction) => void;

const ToastContext = createContext<Push>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const push = useCallback<Push>((text, kind = "ok", action) => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs.slice(-3), { id, text, kind, action }]);
    setTimeout(() => dismiss(id), kind === "err" ? 7000 : action ? 6000 : 3500);
  }, [dismiss]);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            <span>{t.text}</span>
            {t.action ? <button onClick={() => { void t.action?.onClick(); dismiss(t.id); }}>{t.action.label}</button> : null}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
