export const PERIODS: { value: string; label: string }[] = [
  { value: "this month", label: "This month" },
  { value: "last month", label: "Last month" },
  { value: "last 30 days", label: "Last 30 days" },
  { value: "last 90 days", label: "Last 90 days" },
  { value: "ytd", label: "Year to date" },
  { value: "all time", label: "All time" },
];

function iso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function shiftMonth(y: number, m: number, delta: number): [number, number] {
  const idx = y * 12 + (m - 1) + delta;
  return [Math.floor(idx / 12), (idx % 12) + 1];
}

/** The comparable earlier window for a preset, so deltas mean something. */
export function previousPeriod(period: string, today = new Date()): string | null {
  const y = today.getFullYear();
  const m = today.getMonth() + 1;
  switch (period) {
    case "this month":
      return "last month";
    case "last month": {
      const [py, pm] = shiftMonth(y, m, -2);
      return `${py}-${String(pm).padStart(2, "0")}`;
    }
    case "last 30 days":
    case "last 90 days": {
      const n = period === "last 30 days" ? 30 : 90;
      const end = new Date(today);
      end.setDate(end.getDate() - n);
      const start = new Date(end);
      start.setDate(start.getDate() - n + 1);
      return `${iso(start)}..${iso(end)}`;
    }
    case "ytd":
      return "last year";
    default:
      return null;
  }
}

/** Which month the budget panel should show for a period preset. */
export function budgetMonthFor(period: string): string | undefined {
  if (period === "last month") return "last month";
  if (/^\d{4}-\d{2}$/.test(period)) return period;
  return undefined;
}
