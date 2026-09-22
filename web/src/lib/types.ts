export interface Transaction {
  id: number;
  date: string;
  amount: number;
  direction: "debit" | "credit";
  currency: string;
  merchant: string;
  description: string | null;
  category_id: number | null;
  category: string | null;
  category_kind: string | null;
  category_confidence: number | null;
  category_source: string | null;
  source: string;
  client: string | null;
  raw_text: string | null;
  needs_review: boolean;
  created_at: string;
  updated_at: string;
}

export interface TransactionPage {
  count: number;
  total: number;
  offset: number;
  period: string | null;
  start: string | null;
  end: string | null;
  transactions: Transaction[];
}

export interface Category {
  id: number;
  name: string;
  kind: "expense" | "income" | "transfer";
  budget_limit: number | null;
  description: string | null;
}

export interface SummaryBreakdown {
  category?: string;
  merchant?: string;
  day?: string;
  week?: string;
  month?: string;
  kind?: string;
  spent: number;
  count: number;
  received?: number;
  credit_count?: number;
  share_pct?: number | null;
  budget_limit?: number;
  budget_used_pct?: number;
}

export interface Summary {
  period: { start: string; end: string; label: string; days: number };
  totals: { spent: number; transfers_out: number; received: number; net: number; transaction_count: number; uncategorized_count: number; avg_daily_spend: number };
  group_by: string;
  breakdown: SummaryBreakdown[];
  income_breakdown: { category: string; received: number; count: number }[];
}

export interface BudgetCategory {
  category: string;
  spent: number;
  count: number;
  projected: number;
  budget_limit?: number;
  remaining?: number;
  used_pct?: number;
  projected_pct?: number;
  status: "exceeded" | "warning" | "on_track" | "no_budget";
}

export interface BudgetSummary {
  month: string;
  label: string;
  is_current_month: boolean;
  days_elapsed: number;
  days_in_month: number;
  totals: { budget: number; spent_in_budgeted: number; remaining: number; used_pct: number | null };
  categories: BudgetCategory[];
}

export interface Alert {
  level: "exceeded" | "warning" | "pace";
  category: string;
  spent: number;
  budget_limit: number;
  used_pct: number;
  projected: number;
  remaining: number;
  message: string;
}

export interface Alerts { month: string; label: string; alert_count: number; alerts: Alert[]; checked_at: string }

export interface Recurring {
  /** Written down by hand rather than read out of a payment rhythm. */
  declared?: boolean;
  key: string;
  merchant: string;
  category: string | null;
  category_kind: string;
  cadence: "weekly" | "fortnightly" | "monthly" | "quarterly" | "yearly";
  cadence_days: number;
  amount: number;
  amount_varies: boolean;
  last_amount: number;
  /** Null on a declared bill with no payment behind it yet. */
  last_date: string | null;
  next_due: string;
  days_until: number;
  status: "overdue" | "due" | "upcoming";
  occurrences: number;
  regularity: number;
  monthly_cost: number;
  transaction_ids: number[];
  /** What this bill has actually cost, counted from the payments themselves. */
  first_date: string | null;
  paid_total: number;
  paid_12m: number;
  paid_this_year: number;
  count_this_year: number;
  /** The standing instruction, when there is one. Null means nobody has asked us to file this one. */
  autopay: AutopayRule | null;
}

export interface AutopayRule { active: boolean; amount: number; next_due: string; posted_count: number; last_posted_on: string | null }

export interface RecurringReport {
  count: number; monthly_total: number; monthly_expenses: number; paid_12m: number;
  autopay_count: number; autopay_monthly: number;
  upcoming: Recurring[]; items: Recurring[]; checked_at: string;
}

export interface Emi {
  id: number;
  name: string;
  lender: string | null;
  amount: number;
  start_date: string;
  tenure_months: number;
  principal: number | null;
  paid_count: number;
  left_count: number;
  progress_pct: number;
  paid_total: number;
  outstanding: number;
  total_payable: number;
  interest: number | null;
  next_due: string | null;
  days_until: number | null;
  ends_on: string;
  closed: boolean;
}

export interface EmiReport { count: number; monthly_total: number; outstanding: number; next: Emi | null; items: Emi[] }

export interface Goal {
  id: number;
  name: string;
  target: number;
  saved: number;
  due: string | null;
  icon: string | null;
  created_at: string;
  updated_at: string;
  progress_pct?: number;
  remaining?: number;
  monthly_needed?: number | null;
  months_left?: number | null;
}

export interface Insight { kind: string; tone: "good" | "warn" | "bad" | "neutral"; text: string; category?: string; transaction_id?: number }

export interface Overview {
  today: string;
  currency: string;
  month: { key: string; label: string; day: number; days: number; days_left: number };
  spent: number;
  received: number;
  net: number;
  transaction_count: number;
  previous_spent: number;
  pace_pct: number | null;
  safe_to_spend: { per_day: number | null; left: number | null; basis: "budget" | "plan" | "average" | "none"; budget_total: number | null; used_pct: number | null; plan_total: number | null; income: number | null; keep_pct: number | null };
  top_categories: SummaryBreakdown[];
  movers: { category: string; spent: number; before: number; delta: number }[];
  insights: Insight[];
  alerts: { count: number; items: Alert[] };
  upcoming: Recurring[];
  recurring_monthly: number;
  recurring_count: number;
  recent: Transaction[];
  goals: Goal[];
  emi?: { count: number; monthly_total: number; outstanding: number; next: Emi | null };
  needs_review: number;
  week_end: string;
}

export interface ActivityItem {
  id: number;
  ts: string;
  actor: string;
  client: string | null;
  action: string;
  entity: string | null;
  entity_id: number | null;
  detail: Record<string, unknown> | null;
}

export interface ClientSeen { client: string; actions: number; last_seen: string; first_seen: string }
export interface Activity { items: ActivityItem[]; clients: ClientSeen[] }

export interface McpToken { id: string; name: string; prefix: string; created_at: string; last_used_at: string | null; last_client: string | null }
export interface McpCatalog {
  endpoint: string;
  server: { name: string; instructions: string | null };
  tools: { name: string; title: string | null; description: string | null; read_only: boolean; destructive: boolean }[];
  resources: { uri: string; name: string; description: string | null }[];
  prompts: { name: string; title: string; description: string | null }[];
}

export interface Health {
  ok: boolean;
  version: string;
  mcp?: string;
  driver: "anthropic" | "local" | string;
  model: string | null;
  auth_mode: "local" | "supabase";
  database: "local" | "supabase";
  rls: string;
  accounts: number;
  authenticated: boolean;
  mcp_endpoint: string;
  tools?: number;
  status?: {
    transactions: number;
    categories: number;
    uncategorized: number;
    needs_review: number;
    first_date: string | null;
    last_date: string | null;
    llm_provider: string;
    model: string | null;
    merchant_memory: number;
    currency: string;
    goals: number;
    client: string;
    rls: string;
  };
}

export interface ParsedRow {
  date: string;
  amount: number;
  direction: "debit" | "credit";
  merchant: string;
  description: string | null;
  source: string;
  confidence: number;
  duplicate?: boolean;
  line_items?: { name: string; quantity: number | null; unit_price: number | null; total: number | null }[];
}

export interface ImportPreview {
  source_kind: string;
  source_name: string | null;
  parser: string;
  parsed: number;
  duplicates: number;
  new: number;
  warnings: string[];
  skipped: string[];
  transactions: ParsedRow[];
  upload_path?: string;
  dry_run?: boolean;
}

export interface ImportReport {
  dry_run: boolean;
  import_id?: number;
  source_kind: string;
  source_name: string | null;
  parser: string;
  parsed: number;
  inserted: number;
  duplicates: number;
  needs_review: number;
  categorized: number;
  warnings: string[];
  skipped: string[];
  transactions: (Transaction & { line_items?: ParsedRow["line_items"] })[];
}

export interface ImportRecord { id: number; ts: string; source_kind: string; source_name: string | null; parsed: number; inserted: number; duplicates: number }

export type ChatEvent =
  | { type: "conversation"; conversation_id: string }
  | { type: "text_delta"; text: string }
  | { type: "tool_call"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; ok: boolean; preview: string; elapsed_ms: number; data: unknown }
  | { type: "status"; message: string }
  | { type: "error"; message: string; fatal: boolean }
  | { type: "done"; text: string; conversation_id: string; iterations: number; stop_reason: string | null; usage: Record<string, number> | null };

export interface ToolTraceItem { id: string; name: string; input: Record<string, unknown>; ok?: boolean; preview?: string; elapsed_ms?: number; data?: unknown }

export interface ChatMessage { id: string; role: "user" | "assistant"; text: string; trace: ToolTraceItem[]; error?: string; pending?: boolean; usage?: Record<string, number> | null }

export interface PromptInfo { name: string; title: string; description: string | null; arguments: { name: string; description: string | null; required: boolean }[] }
