import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { initials } from "../lib/format";

const reducedMotion = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Tweens a number toward `target` so big values glide instead of jumping. The first value renders at once. */
export function useCountUp(target: number | null | undefined, duration = 700): number | null {
  const [shown, setShown] = useState<number | null>(target ?? null);
  const from = useRef<number | null>(target ?? null);
  useEffect(() => {
    if (target === null || target === undefined) { from.current = null; setShown(null); return; }
    const start = from.current;
    if (start === null || reducedMotion() || start === target) { from.current = target; setShown(target); return; }
    let raf = 0;
    const t0 = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - t0) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const v = start + (target - start) * eased;
      from.current = v;
      setShown(v);
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    const snap = window.setTimeout(() => { cancelAnimationFrame(raf); from.current = target; setShown(target); }, duration + 80);
    return () => { cancelAnimationFrame(raf); window.clearTimeout(snap); };
  }, [target, duration]);
  return shown;
}

export function Stat({ value, format }: { value: number | null | undefined; format: (n: number) => string }) {
  const v = useCountUp(value);
  return <>{v === null ? "—" : format(v)}</>;
}

export function Chip({ tone, children, onClick, on, title }: { tone?: "good" | "warn" | "bad" | "accent" | "dark" | "outline" | ""; children: ReactNode; onClick?: () => void; on?: boolean; title?: string }) {
  if (onClick) return <button type="button" className={`chip btn-chip ${tone ?? ""} ${on ? "on" : ""}`} onClick={onClick} title={title}>{children}</button>;
  return <span className={`chip ${tone ?? ""}`} title={title}>{children}</span>;
}

export function Avatar({ name, src, credit, neutral, lg }: { name: string; src?: string | null; credit?: boolean; neutral?: boolean; lg?: boolean }) {
  return (
    <span className={`ava ${credit ? "credit" : ""} ${neutral ? "neutral" : ""} ${lg ? "lg" : ""} ${src ? "photo" : ""}`} aria-hidden="true">
      {src ? <img src={src} alt="" /> : initials(name)}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return <div className="error-box">{children}</div>;
}

export function Spinner() {
  return <span className="spinner" aria-label="loading" />;
}

export function Skeleton({ h = 16, w = "100%", style }: { h?: number; w?: number | string; style?: React.CSSProperties }) {
  return <div className="skeleton" style={{ height: h, width: w, ...style }} />;
}

/** A progress ring. `pct` beyond 100 is clamped for the stroke but the tone reflects the overshoot. */
export function Ring({ pct, size = 84, stroke = 9, tone, children }: { pct: number; size?: number; stroke?: number; tone?: "warn" | "bad" | ""; children?: ReactNode }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, pct));
  const t = tone ?? (pct >= 100 ? "bad" : "");
  return (
    <div className={`ring ${t}`} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle className="track" cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} />
        <motion.circle className="fill" cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} strokeDasharray={c}
          initial={{ strokeDashoffset: c }} animate={{ strokeDashoffset: c * (1 - clamped / 100) }} transition={{ duration: 1, ease: [0.22, 1, 0.36, 1] }} />
      </svg>
      <div className="in">{children}</div>
    </div>
  );
}

/** Minimal sparkline with a soft area and a dot on the last point. */
export function Sparkline({ values, height = 76, color = "var(--accent)", labels }: { values: number[]; height?: number; color?: string; labels?: string[] }) {
  const w = 600;
  const h = height;
  const pad = 6;
  const max = Math.max(1, ...values);
  const n = values.length;
  const pts = values.map((v, i) => [pad + (i / Math.max(1, n - 1)) * (w - pad * 2), h - pad - (v / max) * (h - pad * 2)] as const);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const area = `${path} L${pts[pts.length - 1]?.[0] ?? pad},${h - pad} L${pad},${h - pad} Z`;
  const last = pts[pts.length - 1];
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-label={labels ? `${labels[0]} to ${labels[labels.length - 1]}` : "trend"}>
      {n > 1 ? <path d={area} fill={color} opacity={0.08} /> : null}
      {n > 1 ? <path d={path} fill="none" stroke={color} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" /> : null}
      {last ? <circle cx={last[0]} cy={last[1]} r={4} fill={color} /> : null}
    </svg>
  );
}

export function Bar({ pct, tone, thin }: { pct: number; tone?: "warn" | "bad" | ""; thin?: boolean }) {
  const t = tone ?? (pct >= 100 ? "bad" : "");
  return <div className={`bar ${t} ${thin ? "thin" : ""}`}><i style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} /></div>;
}

/** Centered modal sheet. Escape and backdrop close it. */
export function Sheet({ open, onClose, title, sub, children, actions }: { open: boolean; onClose: () => void; title: string; sub?: string; children: ReactNode; actions?: ReactNode }) {
  // Keep the last contents on screen while the card animates away (callers usually clear them on close).
  const last = useRef({ title, sub, children, actions });
  if (open) last.current = { title, sub, children, actions };
  const shown = last.current;
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [open, onClose]);
  // Rendered at the document root: inside an animating page, `position: fixed` would pin to that page, not the screen.
  return createPortal(
    <AnimatePresence>
      {open ? (
        <motion.div key="sheet" className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
          <motion.div className="sheet" role="dialog" aria-modal="true" aria-label={title}
            initial={{ opacity: 0, y: 28, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 420, damping: 34, mass: 0.8 }}>
            <button type="button" className="sheet-x" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
            <h2>{shown.title}</h2>
            {shown.sub ? <div className="sub">{shown.sub}</div> : null}
            {shown.children}
            {shown.actions ? <div className="actions">{shown.actions}</div> : null}
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}

/** The big live figure at the top of a form card: it re-renders with a soft roll whenever the value changes. */
export function FormHero({ value, sub, pct }: { value: string; sub?: ReactNode; pct?: number | null }) {
  return (
    <div className="form-hero">
      <div className="v-wrap">
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.span key={value} className="v num" initial={{ opacity: 0, y: 14, filter: "blur(4px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, y: -14, filter: "blur(4px)" }} transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}>{value}</motion.span>
        </AnimatePresence>
      </div>
      {sub ? <div className="s">{sub}</div> : null}
      {pct != null ? <div className="form-hero-bar"><motion.i initial={false} animate={{ width: `${Math.min(100, Math.max(0, pct))}%` }} transition={{ type: "spring", stiffness: 300, damping: 30 }} /></div> : null}
    </div>
  );
}

export function PageHead({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1>{sub ? <div className="sub">{sub}</div> : null}</div>
      {children ? <div className="tools">{children}</div> : null}
    </div>
  );
}

export const CLIENT_COLORS: Record<string, string> = { web: "#4d43fe", assistant: "#e2553f", seed: "#8b93a5", cli: "#0369a1", stdio: "#0369a1" };
export function clientColor(name: string | null | undefined): string {
  if (!name) return "#b3b9c7";
  const k = name.toLowerCase();
  if (CLIENT_COLORS[k]) return CLIENT_COLORS[k];
  if (k.includes("claude")) return "#c2410c";
  if (k.includes("cursor")) return "#0f172a";
  return "#b45309";
}
export function clientLabel(name: string | null | undefined): string {
  if (!name) return "unknown";
  const k = name.toLowerCase();
  if (k === "web") return "You · web";
  if (k === "assistant") return "Assistant";
  if (k === "seed") return "Sample data";
  if (k === "claude-ai") return "Claude Desktop";
  return name;
}
export function ClientPill({ name }: { name: string | null | undefined }) {
  return <span className="client-pill"><i style={{ background: clientColor(name) }} />{clientLabel(name)}</span>;
}

export type IconName =
  | "home" | "list" | "budget" | "goal" | "repeat" | "chat" | "upload" | "plug" | "activity" | "settings" | "send" | "trash" | "refresh" | "wand"
  | "x" | "plus" | "search" | "arrowRight" | "arrowUp" | "arrowDown" | "check" | "enter" | "undo" | "spark" | "logo" | "copy" | "key" | "menu"
  | "download" | "edit" | "shield" | "bolt" | "calendar" | "more" | "logout" | "user" | "alert" | "pause" | "play" | "camera";

export function Icon({ name, className }: { name: IconName; className?: string }) {
  const common = { className, width: "1em", height: "1em", fill: "none", stroke: "currentColor", strokeWidth: 1.9, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, viewBox: "0 0 24 24", "aria-hidden": true };
  switch (name) {
    case "alert": return <svg {...common}><path d="M12 3.5 2.8 19.5h18.4z" /><path d="M12 10v4M12 17.2h.01" /></svg>;
    case "pause": return <svg {...common}><path d="M9 5v14M15 5v14" /></svg>;
    case "play": return <svg {...common}><path d="M7 4.8v14.4l12-7.2z" /></svg>;
    case "camera": return <svg {...common}><path d="M3 8.5A1.5 1.5 0 0 1 4.5 7h2.2l1.4-2h7.8l1.4 2h2.2A1.5 1.5 0 0 1 21 8.5V18a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18z" /><circle cx="12" cy="13" r="3.4" /></svg>;
    case "home": return <svg {...common}><path d="M4 11l8-7 8 7v9a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1z" /></svg>;
    case "list": return <svg {...common}><path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" /></svg>;
    case "budget": return <svg {...common}><circle cx="12" cy="12" r="8" /><path d="M12 4v8l5 3" /></svg>;
    case "goal": return <svg {...common}><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="4" /><circle cx="12" cy="12" r="1" /></svg>;
    case "repeat": return <svg {...common}><path d="M17 2l4 4-4 4" /><path d="M3 11V9a4 4 0 0 1 4-4h14" /><path d="M7 22l-4-4 4-4" /><path d="M21 13v2a4 4 0 0 1-4 4H3" /></svg>;
    case "chat": return <svg {...common}><path d="M4 5h16v11H8l-4 4z" /></svg>;
    case "upload": return <svg {...common}><path d="M12 16V4M6 10l6-6 6 6M4 20h16" /></svg>;
    case "plug": return <svg {...common}><path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4" /></svg>;
    case "activity": return <svg {...common}><path d="M3 12h4l3-8 4 16 3-8h4" /></svg>;
    case "settings": return <svg {...common}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></svg>;
    case "send": return <svg {...common}><path d="M4 12l16-8-6 16-2-6z" /></svg>;
    case "trash": return <svg {...common}><path d="M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></svg>;
    case "refresh": return <svg {...common}><path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5" /></svg>;
    case "wand": return <svg {...common}><path d="M4 20l11-11M13 5l2-2M18 10l2-2M9 3l.5 1.5L11 5l-1.5.5L9 7l-.5-1.5L7 5l1.5-.5z" /></svg>;
    case "x": return <svg {...common}><path d="M6 6l12 12M18 6L6 18" /></svg>;
    case "plus": return <svg {...common}><path d="M12 5v14M5 12h14" /></svg>;
    case "search": return <svg {...common}><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></svg>;
    case "arrowRight": return <svg {...common}><path d="M5 12h14M13 6l6 6-6 6" /></svg>;
    case "arrowUp": return <svg {...common}><path d="M12 19V5M6 11l6-6 6 6" /></svg>;
    case "arrowDown": return <svg {...common}><path d="M12 5v14M6 13l6 6 6-6" /></svg>;
    case "check": return <svg {...common}><path d="M5 12l5 5 9-10" /></svg>;
    case "enter": return <svg {...common}><path d="M20 6v6a2 2 0 0 1-2 2H5M8 10l-4 4 4 4" /></svg>;
    case "undo": return <svg {...common}><path d="M9 14L4 9l5-5M4 9h9a6 6 0 0 1 0 12h-2" /></svg>;
    case "spark": return <svg {...common}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 17l.7 2.3L22 20l-2.3.7L19 23l-.7-2.3L16 20l2.3-.7z" /></svg>;
    case "logo": return <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={className}><rect x="5" y="4" width="4" height="16" rx="2" /><rect x="5" y="4" width="14" height="4" rx="2" /><rect x="5" y="10.5" width="8" height="4" rx="2" /><circle cx="17" cy="12.5" r="2" /></svg>;
    case "copy": return <svg {...common}><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h9" /></svg>;
    case "key": return <svg {...common}><circle cx="8" cy="14" r="4" /><path d="M11 11l9-9M15 7l3 3M18 4l2 2" /></svg>;
    case "menu": return <svg {...common}><path d="M4 7h16M4 12h16M4 17h16" /></svg>;
    case "download": return <svg {...common}><path d="M12 4v12M6 10l6 6 6-6M4 20h16" /></svg>;
    case "edit": return <svg {...common}><path d="M4 20h4l10-10-4-4L4 16zM13 7l4 4" /></svg>;
    case "shield": return <svg {...common}><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" /><path d="M9 12l2 2 4-4" /></svg>;
    case "bolt": return <svg {...common}><path d="M13 2L4 14h7l-1 8 9-12h-7z" /></svg>;
    case "calendar": return <svg {...common}><rect x="4" y="5" width="16" height="15" rx="3" /><path d="M4 10h16M8 3v4M16 3v4" /></svg>;
    case "logout": return <svg {...common}><path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M10 16l-4-4 4-4M6 12h10" /></svg>;
    case "user": return <svg {...common}><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></svg>;
    case "more": return <svg {...common}><circle cx="5" cy="12" r="1.2" /><circle cx="12" cy="12" r="1.2" /><circle cx="19" cy="12" r="1.2" /></svg>;
  }
}
