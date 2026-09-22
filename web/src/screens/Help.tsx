/* Help: a map of the app rather than a manual.

   Most questions at the start are "where do I do X", so this is organised by place — every screen, one line about
   what it is for, and a link straight to it — with the few things worth knowing that are not a screen (writing an
   entry in one line, the shortcuts) underneath. The walkthrough can be replayed from here on purpose. */
import { motion } from "motion/react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTour } from "../components/Tour";
import { Icon, type IconName } from "../components/ui";
import { useAuth } from "../lib/auth";
import { money } from "../lib/format";

const SPRING = { type: "spring", stiffness: 380, damping: 32 } as const;
const rise = (i: number) => ({
  initial: { opacity: 0, y: 14 }, animate: { opacity: 1, y: 0 },
  transition: { duration: 0.42, delay: Math.min(0.04 * i, 0.3), ease: [0.22, 1, 0.36, 1] as const },
});

interface Place { to: string; icon: IconName; name: string; what: string; when: string }

const PLACES: Place[] = [
  { to: "/app", icon: "home", name: "Home", what: "The month so far: spent, pace against last month, safe to spend per day, what is coming up.", when: "Start here each time you open the app." },
  { to: "/app/transactions", icon: "list", name: "Transactions", what: "The ledger itself. Filter by date, category, merchant or amount, fix a category, or delete a mistake.", when: "When you want the detail behind a number." },
  { to: "/app/budgets", icon: "budget", name: "Budgets", what: "A monthly limit per category, and how much of each is gone. Alerts fire before you cross, not after.", when: "Set the ones you actually want to hold yourself to." },
  { to: "/app/goals", icon: "goal", name: "Goals", what: "Things you are saving towards, with a target and an optional date. Put money against one as it goes in.", when: "A trip, a fund, a purchase you are building up to." },
  { to: "/app/subscriptions", icon: "repeat", name: "Subscriptions", what: "Charges that repeat, found in your own history rather than declared by you, with the next date due.", when: "To catch what renews quietly." },
  { to: "/app/emis", icon: "calendar", name: "EMIs", what: "Loan instalments: what is left, what is paid, and what each month costs you.", when: "If you are carrying a loan." },
  { to: "/app/ask", icon: "chat", name: "Ask", what: "Questions in plain language, answered from your ledger. It shows the tool calls it made, so nothing is a black box.", when: "Faster than filtering, when you know what you want to know." },
  { to: "/app/import", icon: "upload", name: "Import", what: "A bank statement (PDF or CSV), a receipt photo, or pasted SMS alerts. Everything is categorised on the way in.", when: "The quickest way to fill an empty ledger." },
  { to: "/app/mcp", icon: "bolt", name: "MCP live", what: "The protocol the whole app runs on, demonstrated against your own account: tools, resources, sampling, elicitation.", when: "When you are curious how this works." },
  { to: "/app/connect", icon: "plug", name: "Connect", what: "A token that lets Claude, or any MCP client, work with this ledger with the same tools the app uses.", when: "To use your finances from outside this app." },
  { to: "/app/activity", icon: "activity", name: "Activity", what: "An audit trail: every change, which client made it, and when.", when: "To see what the assistant did on your behalf." },
  { to: "/app/profile", icon: "user", name: "Profile", what: "Your name, photo, income, pay day and how much you keep back each month.", when: "When the numbers you gave at setup change." },
  { to: "/app/settings", icon: "settings", name: "Settings", what: "Currency, categories, sample data and deleting the account.", when: "Rarely, and that is the idea." },
];

const LINES: [string, string][] = [
  ["450 swiggy", "amount and merchant — the shortest useful entry"],
  ["coffee 120 yesterday", "a day back; “12 sep” and “3 days ago” work too"],
  ["890 from company", "money in, worked out from the wording"],
  ["+50000 salary", "a leading plus, if you would rather be explicit"],
  ["rent 25000 #housing (september)", "a category with #, a note in brackets"],
];

const KEYS: [string, string][] = [
  ["N", "New entry, from anywhere"],
  ["/", "Jump to the search box"],
  ["⌘K", "The same, if that is the reflex"],
  ["Esc", "Close whatever is open"],
  ["→ ←", "Move through the walkthrough"],
];

export default function Help() {
  const { start } = useTour();
  const { user } = useAuth();
  const [q, setQ] = useState("");
  const places = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return PLACES;
    return PLACES.filter((p) => `${p.name} ${p.what} ${p.when}`.toLowerCase().includes(needle));
  }, [q]);

  return (
    <div className="page help">
      <div className="help-hero">
        <div>
          <h1>Where everything is</h1>
          <p>Thirteen screens, one ledger underneath. This is the short version; the walkthrough points at the real thing.</p>
        </div>
        <motion.button type="button" className="btn primary" onClick={start} whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }} transition={SPRING}>
          <Icon name="spark" />Show me around
        </motion.button>
      </div>

      <div className="help-find">
        <Icon name="search" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="What are you looking for? Try “budget” or “statement”" aria-label="Search help" />
        {q ? <button type="button" onClick={() => setQ("")} aria-label="Clear"><Icon name="x" /></button> : null}
      </div>

      <div className="help-grid">
        {places.map((p, i) => (
          <motion.div key={p.to} {...rise(i)}>
            <Link to={p.to} className="help-card">
              <span className="ic"><Icon name={p.icon} /></span>
              <div className="b">
                <div className="n">{p.name}<Icon name="arrowRight" /></div>
                <p>{p.what}</p>
                <span className="w">{p.when}</span>
              </div>
            </Link>
          </motion.div>
        ))}
        {!places.length ? <p className="help-none">Nothing matches “{q}”. The assistant on the Ask screen will take the question directly.</p> : null}
      </div>

      <div className="help-two">
        <motion.section className="card help-panel" {...rise(0)}>
          <h2>Writing an entry</h2>
          <p className="sub">One line, however you would say it. The parts it recognises appear underneath as you type, and you can correct any of them before saving.</p>
          <ul className="help-lines">
            {LINES.map(([line, what]) => (
              <li key={line}><code>{line}</code><span>{what}</span></li>
            ))}
          </ul>
        </motion.section>

        <motion.section className="card help-panel" {...rise(1)}>
          <h2>Keyboard</h2>
          <ul className="help-keys">
            {KEYS.map(([k, what]) => <li key={k}><kbd>{k}</kbd><span>{what}</span></li>)}
          </ul>
          <h2 className="mt">Your setup</h2>
          <p className="sub">
            {user?.monthly_income
              ? <>You told us {money(user.monthly_income, user.currency)} a month{user.keep_pct ? `, keeping ${user.keep_pct}% back` : ""}. Safe-to-spend is worked out from that until you set budgets, which take over.</>
              : <>Add your monthly income in Profile and the dashboard can tell you what is safe to spend.</>}
          </p>
          <Link to="/app/profile" className="btn sm ghost">Change it in Profile</Link>
        </motion.section>
      </div>

      <motion.section className="card help-panel wide" {...rise(2)}>
        <h2>Still stuck?</h2>
        <p className="sub">
          The <Link to="/app/ask">assistant</Link> answers questions about your own money. For how the protocol underneath works — the tools,
          resources and prompts this app is built on — there is a <Link to="/docs">full page of documentation</Link>, and{" "}
          <Link to="/app/mcp">MCP live</Link> runs each of them against your account while you watch.
        </p>
      </motion.section>
    </div>
  );
}
