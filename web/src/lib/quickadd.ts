/* Natural-language quick add. "450 swiggy", "coffee 120 yesterday", "+50000 salary", "₹1,250 uber to airport on 12 sep",
   "gym 1500 #health", "rent 25000 (september) in Rent & Housing". Everything is optional except an amount and a merchant. */
import { isoLocal } from "./format";

export interface QuickAddDraft {
  /** The line as typed, tidied. The card sends this on when it wants a second opinion. */
  raw: string;
  amount: number | null;
  merchant: string;
  direction: "debit" | "credit";
  date: string;
  dateLabel: string;
  category: string | null;
  description: string | null;
  valid: boolean;
  /** How sure the direction is, 0-1, and what settled it. Below ~0.8 the card asks the server for a better answer. */
  confidence: number;
  source: DirectionSource;
}

export type DirectionSource = "sign" | "words" | "grammar" | "default" | "history" | "model" | "you";

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const WEEKDAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
/* Which way the money went. Not a list of income words — those run out at the second sentence anyone types — but
   the frame the line is in: you pay *to* or *at* someone and you are paid *from* them, and a verb of receiving beats
   a preposition. What the reading cannot settle, `source` and `confidence` say so, and the card asks the server
   (history, then the model) and lets you flip it by hand. */
const EARN = /\b(received|credited|got|refund(?:ed)?|cashback|salary|stipend|bonus|income|reimburse(?:d|ment)?|paid me|sent me|gave me|deposit(?:ed)?|dividend|interest|earned|sold|payout|winnings?|settled up|repaid)\b/i;
const SPEND = /\b(paid(?!\s+me)|pay(?!\s+me)|spent|spend|bought|buy|sent(?!\s+me)|gave(?!\s+me)|bill|billed|recharge[ds]?|ordered|subscription|renewed|topped up|donated|lent)\b/i;
const CREDIT_DROP = /\b(received|credited|got|paid me|sent me|gave me|deposited|earned)\b/gi;
const LEAD_FILLER = /^(?:at|to|for|from|on|paid|pay|spent|bought|via|the|a|an|of|in|by|with|and|-|–|:)\s+/i;
const TRAIL_FILLER = /\s+(?:at|to|for|from|on|via|the|in|by|with|and|-|–|:)$/i;

export const QUICK_ADD_EXAMPLES = ["450 swiggy", "coffee 120 yesterday", "+50000 salary", "uber 340 on 12 sep #transport", "rent 25000 (sept) in Rent & Housing"];

function fmtDay(d: Date, today: Date): string {
  const t0 = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const diff = Math.round((t0.getTime() - new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) / 86400000);
  if (diff === 0) return "today";
  if (diff === 1) return "yesterday";
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

export function titleCase(s: string): string {
  return s.replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

export function parseQuickAdd(raw: string, categories: string[] = [], today = new Date()): QuickAddDraft {
  let text = raw.replace(/\s+/g, " ").trim();
  let description: string | null = null;
  let category: string | null = null;
  let direction: "debit" | "credit" = "debit";
  let date = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  let dateLabel = "today";

  // (note) or "note: ..."
  text = text.replace(/\(([^)]*)\)/, (_m, n: string) => { description = n.trim() || null; return " "; });
  text = text.replace(/\s(?:note|memo):\s*(.+)$/i, (_m, n: string) => { description = n.trim(); return " "; });

  // direction: a sign you typed, else the shape of the sentence
  let confidence = 0.25;
  let source: DirectionSource = "default";
  if (/^[+-]/.test(text)) {
    direction = text.startsWith("+") ? "credit" : "debit";
    confidence = 1;
    source = "sign";
    text = text.replace(/^[+-]\s*/, "");
  } else {
    // Verbs carry more weight than prepositions, so "paid 500 from hdfc" stays money out while "890 from company"
    // leans money in. A score of 0 means the line simply does not say, and most of those are spends.
    let score = 0;
    if (EARN.test(text)) score += 2;
    if (SPEND.test(text)) score -= 2;
    if (/\bfrom\b/i.test(text)) score += 1;
    if (/\b(?:to|at)\b/i.test(text)) score -= 1;
    direction = score > 0 ? "credit" : "debit";
    confidence = Math.abs(score) >= 2 ? 0.85 : Math.abs(score) === 1 ? 0.55 : 0.25;
    source = Math.abs(score) >= 2 ? "words" : Math.abs(score) === 1 ? "grammar" : "default";
    if (direction === "credit") text = text.replace(CREDIT_DROP, " ");
  }

  // category: #tag, #"Two Words", or a trailing "in <Category>"
  const lower = categories.map((c) => c.toLowerCase());
  const findCat = (needle: string): string | null => {
    const n = needle.toLowerCase().replace(/[^a-z& ]/g, " ").replace(/\s+/g, " ").trim();
    if (!n) return null;
    let idx = lower.indexOf(n);
    if (idx < 0) idx = lower.findIndex((c) => c.startsWith(n));
    if (idx < 0) idx = lower.findIndex((c) => c.split(/\s*&\s*|\s+/).some((w) => w.startsWith(n)));
    return idx >= 0 ? categories[idx] : null;
  };
  text = text.replace(/#"([^"]+)"|#([\w&-]+)/, (_m, a?: string, b?: string) => { category = findCat(a ?? b ?? "") ?? category; return " "; });
  if (!category && categories.length) {
    const m = /\s(?:in|under|as)\s+([a-z&][a-z& ]{2,})$/i.exec(text);
    if (m) {
      const c = findCat(m[1]);
      if (c) { category = c; text = text.slice(0, m.index); }
    }
  }

  // date
  const setDate = (d: Date, label?: string) => { date = d; dateLabel = label ?? fmtDay(d, today); };
  const shift = (n: number) => { const d = new Date(today); d.setDate(d.getDate() - n); return d; };
  const dm = (day: number, monthIdx: number, year?: number) => {
    const y = year ?? today.getFullYear();
    const d = new Date(y, monthIdx, day);
    if (year === undefined && d > today) d.setFullYear(y - 1);
    return d;
  };
  const rules: [RegExp, (m: RegExpExecArray) => void][] = [
    [/\b(\d{4})-(\d{2})-(\d{2})\b/, (m) => setDate(new Date(+m[1], +m[2] - 1, +m[3]))],
    [/\b(?:today|tonight|this morning|this evening)\b/i, () => setDate(shift(0), "today")],
    [/\bday before yesterday\b/i, () => setDate(shift(2))],
    [/\byesterday\b/i, () => setDate(shift(1), "yesterday")],
    [/\b(\d+)\s*days?\s*ago\b/i, (m) => setDate(shift(+m[1]))],
    [/\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?:\s+(\d{4}))?\b/i,
      (m) => setDate(dm(+m[1], MONTHS.indexOf(m[2].toLowerCase()), m[3] ? +m[3] : undefined))],
    [/\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*[\d,.]*\s*(?:k|rs|₹))/i,
      (m) => setDate(dm(+m[2], MONTHS.indexOf(m[1].toLowerCase())))],
    [/\b(\d{1,2})\/(\d{1,2})(?:\/(\d{2,4}))?\b/, (m) => setDate(dm(+m[1], +m[2] - 1, m[3] ? (m[3].length === 2 ? 2000 + +m[3] : +m[3]) : undefined))],
    [/\b(?:last\s+|on\s+)?(sun|mon|tue|wed|thu|fri|sat)(?:day|sday|nesday|rsday|urday)?\b/i, (m) => {
      const want = WEEKDAYS.indexOf(m[1].toLowerCase().slice(0, 3));
      const d = new Date(today);
      const back = (d.getDay() - want + 7) % 7 || 7;
      d.setDate(d.getDate() - back);
      setDate(d);
    }],
  ];
  for (const [re, apply] of rules) {
    const m = re.exec(text);
    if (m) {
      apply(m);
      text = (text.slice(0, m.index) + " " + text.slice(m.index + m[0].length)).replace(/\bon\b/gi, " ");
      break;
    }
  }

  // amount: currency-prefixed first, then the first bare number; "1.2k" = 1200
  let amount: number | null = null;
  const prefixed = /(?:₹|rs\.?|inr)\s*(\d[\d,]*(?:\.\d{1,2})?)\s*(k)?(?![\w.])/i.exec(text);
  const bare = /(?<![\w.₹])(\d[\d,]*(?:\.\d{1,2})?)\s*(k)?(?:\s*(?:rs|inr|rupees|bucks))?(?![\w.])/i.exec(text);
  const m = prefixed ?? bare;
  if (m) {
    const n = parseFloat(m[1].replace(/,/g, "")) * (m[2] ? 1000 : 1);
    if (Number.isFinite(n) && n > 0) amount = Math.round(n * 100) / 100;
    text = text.slice(0, m.index) + " " + text.slice(m.index + m[0].length);
  }

  // merchant: whatever is left, minus filler words
  let merchant = text.replace(/\s+/g, " ").trim();
  for (let i = 0; i < 4; i++) merchant = merchant.replace(LEAD_FILLER, "").replace(TRAIL_FILLER, "").trim();
  merchant = merchant.replace(/^[\s,.:;-]+|[\s,.:;-]+$/g, "").replace(/\s+/g, " ");
  if (merchant && merchant === merchant.toLowerCase()) merchant = titleCase(merchant);
  if (!merchant && direction === "credit" && amount) merchant = "Income";

  return {
    raw: raw.replace(/\s+/g, " ").trim(), amount, merchant, direction, date: isoLocal(date), dateLabel, category, description, confidence, source,
    valid: amount !== null && amount > 0 && merchant.length > 0,
  };
}
