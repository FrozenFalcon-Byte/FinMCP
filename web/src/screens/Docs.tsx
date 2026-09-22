/* Public documentation for connecting an MCP client to FinMCP. Its own page rather than a landing section, so it
   can be linked and read on its own; it borrows the landing's nav, footer and palette so the two read as one site.
   Everything here is about the protocol surface, so none of it needs an account to be useful. */
import Lenis from "lenis";
import { AnimatePresence, motion, useReducedMotion, useScroll, useSpring } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icon, type IconName } from "../components/ui";
import { api, mcpEndpoint } from "../lib/api";
import { useAuth } from "../lib/auth";
import { NOTES, snippet } from "./Connect";
import { Footer, Nav } from "./Landing";
import "./docs.css";

const EASE = [0.22, 1, 0.36, 1] as const;
const rise = { initial: { opacity: 0, y: 28 }, whileInView: { opacity: 1, y: 0 }, viewport: { once: true, margin: "-80px" }, transition: { duration: 0.7, ease: EASE } };

const SECTIONS = [
  { id: "overview", label: "Overview" },
  { id: "token", label: "Get a token" },
  { id: "clients", label: "Client setup" },
  { id: "tools", label: "Tools" },
  { id: "resources", label: "Resources & prompts" },
  { id: "protocol", label: "Protocol features" },
  { id: "troubleshooting", label: "Troubleshooting" },
] as const;

type ClientId = "claude-desktop" | "claude-code" | "cursor" | "generic" | "stdio";
const CLIENTS: { id: ClientId; label: string; sub: string }[] = [
  { id: "claude-desktop", label: "Claude Desktop", sub: "One config block" },
  { id: "claude-code", label: "Claude Code", sub: "One command" },
  { id: "cursor", label: "Cursor", sub: "A global MCP server" },
  { id: "generic", label: "Any MCP client", sub: "Streamable HTTP" },
  { id: "stdio", label: "Local process", sub: "stdio, no API needed" },
];

/* Curated copy. Which tools actually exist comes from the server (`/api/mcp/public-catalog`); anything the
   server lists that is not named here still shows, under "Also available", with the server's own description. */
const GROUPS: { h: string; i: IconName; tools: [string, string][] }[] = [
  { h: "Ledger", i: "list", tools: [
    ["add_transaction", "Add one transaction. Categorised on the way in."],
    ["parse_entry", "Read a typed line — money in or money out, and who. History first, the model when unsure."],
    ["update_transaction", "Change an amount, merchant, date, note or category."],
    ["delete_transaction", "Remove one, by id."],
    ["list_transactions", "Filter by month, category, merchant or amount range."],
  ] },
  { h: "Categories & review", i: "wand", tools: [
    ["list_categories", "The category set, with what each one has cost lately."],
    ["categorize_transaction", "Categorise one, asking you when it is genuinely unclear."],
    ["categorize_uncategorized", "Work through the backlog in one batched pass."],
    ["review_queue", "What the server was not confident about."],
  ] },
  { h: "Budgets", i: "budget", tools: [
    ["set_budget", "Set or clear a monthly cap for a category."],
    ["replace_budgets", "Make a list of budgets the only ones there are; every other category is cleared."],
    ["get_budget_summary", "Caps against actuals, with what is left."],
    ["check_budget_alerts", "Which caps are close or already broken."],
  ] },
  { h: "Overview & summaries", i: "home", tools: [
    ["get_overview", "The month at a glance: spend, income, top categories."],
    ["get_summary", "Totals for any period, grouped how you ask."],
  ] },
  { h: "Goals", i: "goal", tools: [
    ["list_goals", "Savings goals with progress and pace."],
    ["upsert_goal", "Create one or edit its target and date."],
    ["add_to_goal", "Put money towards it."],
    ["delete_goal", "Remove it."],
  ] },
  { h: "Recurring & EMIs", i: "repeat", tools: [
    ["list_recurring", "Subscriptions the server detected from your own history."],
    ["list_emis", "Loan instalments with what is left to pay."],
    ["upsert_emi", "Add or edit an instalment plan."],
    ["delete_emi", "Remove one."],
  ] },
  { h: "Import", i: "upload", tools: [
    ["parse_statement", "Read a PDF or CSV statement and show what it found, without writing."],
    ["import_statement", "Commit the rows, skipping anything already in the ledger."],
    ["import_text", "Paste SMS alerts or a receipt's text and file them."],
  ] },
  { h: "Ask in SQL", i: "search", tools: [
    ["query_transactions", "A question in English becomes a checked, read-only query."],
    ["run_sql", "One read-only statement, inside your own row-level-security scope."],
  ] },
  { h: "Audit", i: "activity", tools: [
    ["recent_activity", "Every write, stamped with the client that made it."],
  ] },
];

const RESOURCES: [string, string][] = [
  ["finmcp://overview", "This month at a glance"],
  ["finmcp://categories", "Category set and recent totals"],
  ["finmcp://transactions/recent", "The latest entries"],
  ["finmcp://transactions/{month}", "Any month, by template — hosts get completions for the argument"],
  ["finmcp://summary/monthly", "Month-by-month totals"],
  ["finmcp://recurring", "Detected subscriptions"],
  ["finmcp://goals", "Savings goals and progress"],
  ["finmcp://review-queue", "What needs a human decision"],
  ["finmcp://alerts", "Budget caps under pressure"],
  ["finmcp://activity", "The audit trail"],
  ["finmcp://imports/recent", "Recent statement imports"],
  ["finmcp://schema", "The ledger's tables, for writing SQL"],
  ["finmcp://status", "Server, database and account state"],
];

const PROMPTS: [string, string][] = [
  ["monthly_spending_review", "Walk through a month and say what changed"],
  ["subscription_audit", "Find recurring charges and decide which to keep"],
  ["categorize_uncategorized", "Clear the review queue with you in the loop"],
  ["budget_planning", "Propose caps from three months of actual spending"],
];

const PROTOCOL: { h: string; dir: string; p: string }[] = [
  { h: "Tools", dir: "client → server", p: "29 of them. Every read and every write in the app is one of these calls — the screens you use are just another MCP client." },
  { h: "Resources", dir: "client → server", p: "13 live views of your ledger, including a templated one for any month. Hosts can read them without calling a tool." },
  { h: "Prompts", dir: "client → server", p: "Four ready-made conversations, so a host can offer them as slash commands." },
  { h: "Elicitation", dir: "server → client", p: "When a category is genuinely ambiguous the server pauses the tool call and asks. In this app that surfaces as a dialog; in Claude Desktop, as a question." },
  { h: "Sampling", dir: "server → client", p: "The server asks whichever host is connected to run the model, batched into one round. It holds no API key of its own." },
  { h: "Roots", dir: "server → client", p: "Statement imports are confined to the folder the client declares, so a path outside it is refused." },
  { h: "Subscriptions", dir: "both ways", p: "A client listens once and gets resources/updated whenever anything changes — whoever changed it." },
  { h: "Completion", dir: "client → server", p: "Argument autocomplete, so a host can suggest the months you actually have data for." },
  { h: "Progress & logging", dir: "server → client", p: "Long imports and batch categorisation report as they go instead of going quiet." },
];


interface CatalogTool { name: string; description: string | null; read_only: boolean; destructive: boolean }
interface Catalog {
  endpoint: string;
  tools: CatalogTool[];
  resources: { uri: string; name: string; description: string | null }[];
  templates: { uri_template: string; name: string; description: string | null }[];
  prompts: { name: string; title: string | null; description: string | null }[];
}

/** The live protocol surface. Public — no account needed — so the page shows what the server really exposes
    rather than a list that can drift. Null while it loads or if the backend is asleep; the page falls back to
    the bundled reference so it is never empty. */
function useCatalog(): Catalog | null {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  useEffect(() => {
    let live = true;
    api.get<Catalog>("/mcp/public-catalog").then((c) => { if (live) setCatalog(c); }).catch(() => undefined);
    return () => { live = false; };
  }, []);
  return catalog;
}

/** Tool descriptions are written for a model, so they open with the sentence a reader wants and go on. */
const firstSentence = (text: string | null): string => (text ?? "").split(/(?<=\.)\s/)[0];

/* ------------------------------------------------------------------ pieces */

function Section({ id, kicker, title, children }: { id: string; kicker: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="d-sec">
      <motion.div className="d-sec-head" {...rise}>
        <span className="kicker">{kicker}</span>
        <h2>{title}</h2>
      </motion.div>
      {children}
    </section>
  );
}

/** The endpoint, with a copy button that confirms itself for a moment. */
function Copyable({ text, className, children }: { text: string; className?: string; children?: ReactNode }) {
  const [done, setDone] = useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(text).then(() => { setDone(true); window.setTimeout(() => setDone(false), 1400); });
  };
  return (
    <button type="button" className={`d-copy ${className ?? ""}`} onClick={copy}>
      {children ?? <code>{text}</code>}
      <motion.span className="ic" key={done ? "y" : "n"} initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ duration: 0.2 }}>
        <Icon name={done ? "check" : "copy"} />
      </motion.span>
    </button>
  );
}

/** Side rail. The dot glides between entries as the matching section reaches the top of the viewport. */
function Toc() {
  const [active, setActive] = useState<string>(SECTIONS[0].id);
  /* The last section whose heading has passed a line just under the nav. Intersection ratios do not work here:
     a tall section fills the viewport at a low ratio and loses to a short one that happens to fit. */
  useEffect(() => {
    const LINE = 140;
    let frame = 0;
    const measure = () => {
      frame = 0;
      let current: string = SECTIONS[0].id;
      for (const s of SECTIONS) {
        const el = document.getElementById(s.id);
        if (el && el.getBoundingClientRect().top <= LINE) current = s.id;
      }
      // At the very bottom the last section may never reach the line, so claim it outright.
      if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 220) current = SECTIONS[SECTIONS.length - 1].id;
      setActive(current);
    };
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(measure); };
    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);
  return (
    <nav className="d-toc" aria-label="On this page">
      <span className="t">On this page</span>
      {SECTIONS.map((s) => (
        <a key={s.id} href={`#${s.id}`} className={active === s.id ? "on" : ""}>
          {active === s.id ? <motion.span layoutId="d-toc-dot" className="dot" transition={{ type: "spring", stiffness: 480, damping: 38 }} /> : null}
          {s.label}
        </a>
      ))}
    </nav>
  );
}

/* ------------------------------------------------------------------ page */

export default function Docs() {
  const { user, ready } = useAuth();
  const signedIn = ready && Boolean(user);
  const reduced = useReducedMotion();
  const catalog = useCatalog();
  const endpoint = catalog?.endpoint ?? mcpEndpoint();
  const known = new Set(GROUPS.flatMap((g) => g.tools.map(([n]) => n)));
  const extras = (catalog?.tools ?? []).filter((t) => !known.has(t.name));
  const live = catalog ? new Map(catalog.tools.map((t) => [t.name, t])) : null;
  const counts = {
    tools: catalog?.tools.length ?? GROUPS.reduce((n, g) => n + g.tools.length, 0),
    resources: catalog ? catalog.resources.length + catalog.templates.length : RESOURCES.length,
    prompts: catalog?.prompts.length ?? PROMPTS.length,
  };
  const resourceRows: [string, string][] = catalog
    ? [...catalog.resources.map((r) => [r.uri, firstSentence(r.description) || r.name] as [string, string]),
       ...catalog.templates.map((t) => [t.uri_template, firstSentence(t.description) || t.name] as [string, string])]
    : RESOURCES;
  const promptRows: [string, string][] = catalog
    ? catalog.prompts.map((p) => [p.name, firstSentence(p.description) || p.title || p.name] as [string, string])
    : PROMPTS;
  const [pick, setPick] = useState<ClientId>("claude-code");
  const code = snippet(pick, endpoint, "");
  const top = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll();
  const bar = useSpring(scrollYProgress, { stiffness: 220, damping: 40, restDelta: 0.001 });

  useEffect(() => { document.title = "FinMCP · connect an MCP client"; }, []);
  useEffect(() => {
    if (reduced) return;
    const lenis = new Lenis({ autoRaf: true, lerp: 0.1, smoothWheel: true, anchors: { offset: -84 } });
    return () => lenis.destroy();
  }, [reduced]);

  return (
    <div className="landing docs" ref={top}>
      <motion.div className="d-progress" style={{ scaleX: bar }} aria-hidden />
      <Nav signedIn={signedIn} />

      <header className="d-hero">
        <motion.div className="in" initial={{ opacity: 0, y: 26 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, ease: EASE }}>
          <span className="kicker">Documentation</span>
          <h1>Point your assistant<br />at your own ledger.</h1>
          <p>FinMCP is an MCP server first and an app second. Give any host a personal token and it gets the same
            {" "}{counts.tools} tools, {counts.resources} resources and {counts.prompts} prompts these screens run on — with the same
            rules and the same audit trail.</p>
          <div className="d-endpoint">
            <span className="lbl">Endpoint</span>
            <Copyable text={endpoint} />
            <span className="meta">Streamable HTTP · bearer auth</span>
          </div>
        </motion.div>
      </header>

      <div className="d-body">
        <Toc />
        <main className="d-main">
          <Section id="overview" kicker="Overview" title="One server, every client.">
            <motion.p className="d-lede" {...rise}>
              The business logic does not live in the web app. It lives in the MCP server, and the web app is simply
              the first client to connect. That is why Claude Desktop can do everything these screens can: it is not
              an integration, it is the same door.
            </motion.p>
            <div className="d-cards">
              {[
                { i: "plug" as const, h: "Bring your own host", p: "Claude Desktop, Claude Code, Cursor, or anything that speaks MCP over Streamable HTTP or stdio." },
                { i: "shield" as const, h: "Your rows only", p: "Postgres row-level security scopes every query to the account behind the token. Not application code — database policy." },
                { i: "activity" as const, h: "Attributed writes", p: "Each write records which client made it, so the Activity screen doubles as the MCP audit trail." },
              ].map((c, k) => (
                <motion.div className="d-card" key={c.h} initial={{ opacity: 0, y: 30 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-60px" }} transition={{ duration: 0.6, delay: k * 0.08, ease: EASE }}>
                  <span className="ic"><Icon name={c.i} /></span><h3>{c.h}</h3><p>{c.p}</p>
                </motion.div>
              ))}
            </div>
          </Section>

          <Section id="token" kicker="Step one" title="Get a personal token.">
            <div className="d-steps">
              {[
                ["Open Connect", <>Inside the app, go to <Link to={signedIn ? "/app/connect" : "/register"}>Connect</Link>. No account yet? Creating one takes a moment and comes with sample data.</>],
                ["Create a token", <>Name it after the client you are wiring up. The token starts <code>fm_</code> and is shown once — only a SHA-256 hash is kept.</>],
                ["Paste it below", <>Drop it into the snippet for your client. Revoke it from the same screen whenever you like; it stops working immediately.</>],
              ].map(([h, p], k) => (
                <motion.div className="d-step" key={k} initial={{ opacity: 0, y: 26 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-60px" }} transition={{ duration: 0.6, delay: k * 0.08, ease: EASE }}>
                  <span className="n">{k + 1}</span><h3>{h as string}</h3><p>{p}</p>
                </motion.div>
              ))}
            </div>
          </Section>

          <Section id="clients" kicker="Step two" title="Pick your client.">
            <div className="d-tabs" role="tablist" aria-label="MCP clients">
              {CLIENTS.map((c) => (
                <button type="button" role="tab" key={c.id} aria-selected={pick === c.id} className={pick === c.id ? "on" : ""} onClick={() => setPick(c.id)}>
                  {pick === c.id ? <motion.span layoutId="d-tab" className="bg" transition={{ type: "spring", stiffness: 460, damping: 38 }} /> : null}
                  <b>{c.label}</b><small>{c.sub}</small>
                </button>
              ))}
            </div>
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={pick} className="d-setup" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.26, ease: EASE }}>
                <div className="d-setup-head">
                  <span>{NOTES[pick]}</span>
                  <Copyable text={code} className="dark"><span>Copy</span></Copyable>
                </div>
                <pre className="d-snippet">{code}</pre>
                <span className="d-setup-foot">Replace <code>fm_YOUR_TOKEN</code> with the token from <Link to={signedIn ? "/app/connect" : "/register"}>Connect</Link>.</span>
              </motion.div>
            </AnimatePresence>
          </Section>

          <Section id="tools" kicker="Reference" title={`${counts.tools} tools, by what they touch.`}>
            <div className="d-groups">
              {GROUPS.map((g, k) => {
                // Only claim what the server actually serves; before it answers, show the bundled reference.
                const rows = g.tools.filter(([n]) => !live || live.has(n));
                if (!rows.length) return null;
                return (
                  <motion.div className="d-group" key={g.h} initial={{ opacity: 0, y: 26 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-50px" }} transition={{ duration: 0.55, delay: (k % 3) * 0.07, ease: EASE }}>
                    <div className="h"><span className="ic"><Icon name={g.i} /></span><b>{g.h}</b><span className="n">{rows.length}</span></div>
                    <dl>{rows.map(([n, d]) => <ToolRow key={n} name={n} copy={d} meta={live?.get(n)} />)}</dl>
                  </motion.div>
                );
              })}
              {extras.length ? (
                <motion.div className="d-group" initial={{ opacity: 0, y: 26 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-50px" }} transition={{ duration: 0.55, ease: EASE }}>
                  <div className="h"><span className="ic"><Icon name="bolt" /></span><b>Also available</b><span className="n">{extras.length}</span></div>
                  <dl>{extras.map((t) => <ToolRow key={t.name} name={t.name} copy={firstSentence(t.description)} meta={t} />)}</dl>
                </motion.div>
              ) : null}
            </div>
            <motion.p className="d-note" {...rise}>
              Each tool carries annotations, so a host knows before it calls whether something only reads or can
              destroy. The live catalogue, with full schemas, is on the <Link to={signedIn ? "/app/mcp" : "/register"}>MCP live</Link> screen.
            </motion.p>
          </Section>

          <Section id="resources" kicker="Reference" title="Resources & prompts.">
            <div className="d-two">
              <motion.div className="d-list" {...rise}>
                <h3>Resources <span className="n">{counts.resources}</span></h3>
                {resourceRows.map(([uri, d]) => <div key={uri}><code>{uri}</code><span>{d}</span></div>)}
              </motion.div>
              <motion.div className="d-list" {...rise}>
                <h3>Prompts <span className="n">{counts.prompts}</span></h3>
                {promptRows.map(([n, d]) => <div key={n}><code>{n}</code><span>{d}</span></div>)}
              </motion.div>
            </div>
          </Section>

          <Section id="protocol" kicker="The whole protocol" title="Not just tools.">
            <div className="d-proto">
              {PROTOCOL.map((f, k) => (
                <motion.div className="row" key={f.h} initial={{ opacity: 0, x: -16 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true, margin: "-40px" }} transition={{ duration: 0.5, delay: Math.min(k, 5) * 0.05, ease: EASE }}>
                  <b>{f.h}</b><span className="dir">{f.dir}</span><p>{f.p}</p>
                </motion.div>
              ))}
            </div>
          </Section>

          <Section id="troubleshooting" kicker="When it misbehaves" title="Troubleshooting.">
            <div className="d-faq">
              {[
                ["The first request takes almost a minute", "The API is on a free tier that stops the container after 15 minutes of quiet. The first call wakes it, which takes around 50 seconds; the app shows a notice while that happens. Afterwards it is fast until the next lull."],
                ["401 Unauthorized", "The token is missing, mistyped or revoked. It travels as Authorization: Bearer fm_… on every request, not just the first."],
                ["The host connects but sees no tools", "Check the transport. This endpoint is Streamable HTTP; a client configured for the older SSE transport will connect and then find nothing."],
                ["Claude Desktop shows nothing after editing the config", "It reads the config at launch, so quit and reopen it. The npx snippet also needs Node on your machine."],
                ["Imports fail with a path error", "The server is confined to the folder your client declares as a root. Move the statement inside it, or import through the app instead."],
              ].map(([q, a], k) => <Faq key={k} q={q} a={a} />)}
            </div>
          </Section>

          <motion.div className="d-cta" {...rise}>
            <div>
              <h2>Ready to wire it up?</h2>
              <p>Create a token, paste one snippet, then ask your assistant what you spent on food last month.</p>
            </div>
            <Link className="l-btn lg" to={signedIn ? "/app/connect" : "/register"}>{signedIn ? "Open Connect" : "Create your ledger"} <Icon name="arrowRight" /></Link>
          </motion.div>
        </main>
      </div>
      <Footer />
    </div>
  );
}

/** One tool. The badge comes from the server's own annotations, so a host knows before it calls. */
function ToolRow({ name, copy, meta }: { name: string; copy: string; meta?: CatalogTool }) {
  const tone = meta ? (meta.destructive ? "bad" : meta.read_only ? "read" : "write") : null;
  return (
    <div>
      <dt>{name}{tone ? <span className={`tag ${tone}`}>{tone === "bad" ? "destructive" : tone}</span> : null}</dt>
      <dd>{copy}</dd>
    </div>
  );
}

/** One question. Collapsed by default; the answer springs open so the page does not jump. */
function Faq({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <motion.div className={`d-q ${open ? "on" : ""}`} layout transition={{ duration: 0.3, ease: EASE }}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span>{q}</span>
        <motion.i animate={{ rotate: open ? 45 : 0 }} transition={{ duration: 0.25, ease: EASE }}><Icon name="plus" /></motion.i>
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.p key="a" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.3, ease: EASE }}>
            <span>{a}</span>
          </motion.p>
        ) : null}
      </AnimatePresence>
    </motion.div>
  );
}
