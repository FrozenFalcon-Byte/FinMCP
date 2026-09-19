const currencyCache = new Map<string, Intl.NumberFormat>();

function fmt(currency: string, digits: number): Intl.NumberFormat {
  const key = `${currency}:${digits}`;
  let f = currencyCache.get(key);
  if (!f) {
    f = new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: digits, minimumFractionDigits: digits });
    currencyCache.set(key, f);
  }
  return f;
}

export function money(value: number | null | undefined, currency = "INR", digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return fmt(currency, digits).format(value);
}

export function compact(value: number, currency = "INR"): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  const sym = currency === "INR" ? "₹" : `${currency} `;
  const trim = (n: number, d: number) => n.toFixed(d).replace(/\.?0+$/, "");
  if (abs >= 1e7) return `${sign}${sym}${trim(abs / 1e7, 2)} Cr`;
  if (abs >= 1e5) return `${sign}${sym}${trim(abs / 1e5, 2)} L`;
  if (abs >= 1e3) return `${sign}${sym}${trim(abs / 1e3, 1)}K`;
  return `${sign}${sym}${abs.toFixed(0)}`;
}

export function pct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(digits)}%`;
}

export function signed(value: number, digits = 0): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function dateLabel(iso: string, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" }): string {
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  return d.toLocaleDateString("en-IN", opts);
}

export function monthLabel(yyyymm: string, opts: Intl.DateTimeFormatOptions = { month: "short", year: "2-digit" }): string {
  const [y, m] = yyyymm.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", opts);
}

export function relTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.round(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

export function num(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-IN").format(value);
}

export const pad2 = (n: number): string => String(n).padStart(2, "0");

export function isoLocal(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

export const todayIso = (): string => isoLocal(new Date());

export function addDays(iso: string, n: number): string {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  return isoLocal(d);
}

export function daysBetween(a: string, b: string): number {
  return Math.round((new Date(b + "T00:00:00").getTime() - new Date(a + "T00:00:00").getTime()) / 86400000);
}

/** "Today", "Yesterday", or "Mon, 15 Sep" (with the year when it differs). */
export function dayLabel(iso: string, today = todayIso()): string {
  if (iso === today) return "Today";
  if (iso === addDays(today, -1)) return "Yesterday";
  const d = new Date(iso + "T00:00:00");
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) });
}

export function greeting(d = new Date()): string {
  const h = d.getHours();
  if (h < 5) return "Still up";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

export function initials(name: string): string {
  const w = name.replace(/[^a-z0-9 ]/gi, " ").trim().split(/\s+/).filter(Boolean);
  const s = ((w[0]?.[0] ?? "") + (w[1]?.[0] ?? "")).toUpperCase();
  return s || "•";
}
