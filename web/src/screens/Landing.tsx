/* The public landing page. super.money's language: white and brand blue, huge tight headlines, a phone that carries
   the story, full-bleed blue chapters, and motion that is tied to the scroll rather than played at you. No WebGL:
   everything is DOM, CSS and motion values, so it stays light on phones. */
import Lenis from "lenis";
import {
  AnimatePresence, motion, useInView, useMotionValueEvent, useReducedMotion, useScroll, useSpring, useTransform, useVelocity, type MotionValue,
} from "motion/react";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { Icon, useCountUp } from "../components/ui";
import { mcpEndpoint } from "../lib/api";
import { useAuth } from "../lib/auth";
import { NOTES, snippet } from "./Connect";
import "./landing.css";

const EASE = [0.22, 1, 0.36, 1] as const;
const rise = { initial: { opacity: 0, y: 40 }, whileInView: { opacity: 1, y: 0 }, viewport: { once: true, margin: "-60px" }, transition: { duration: 0.8, ease: EASE } };

/* ------------------------------------------------------------------ small pieces */

function Brand({ light }: { light?: boolean }) {
  return (
    <Link to="/" className={`l-brand ${light ? "light" : ""}`} aria-label="FinMCP home">
      <span className="mark"><Icon name="logo" /></span><span>FinMCP</span>
    </Link>
  );
}

function SplitHeadline({ lines, className }: { lines: string[]; className?: string }) {
  let n = 0;
  return (
    <h1 className={className}>
      {lines.map((line, li) => (
        <span className="line" key={li}>
          {line.split(" ").map((w, wi) => {
            const i = n++;
            return (
              <span className="mask" key={wi}>
                <motion.span className="word" initial={{ y: "110%" }} animate={{ y: 0 }} transition={{ duration: 0.9, delay: 0.08 + i * 0.07, ease: EASE }}>{w}</motion.span>
              </span>
            );
          })}
        </span>
      ))}
    </h1>
  );
}

function Phone({ children, className, style }: { children: ReactNode; className?: string; style?: React.ComponentProps<typeof motion.div>["style"] }) {
  return (
    <motion.div className={`l-phone ${className ?? ""}`} style={style}>
      <div className="notch" />
      <div className="screen">{children}</div>
    </motion.div>
  );
}

const TXNS = [
  { m: "Swiggy", c: "Food & Dining", a: "450", t: "#ff7a59" },
  { m: "Uber", c: "Transport", a: "238", t: "#4d43fe" },
  { m: "Netflix", c: "Subscriptions", a: "649", t: "#e2553f" },
  { m: "BigBasket", c: "Groceries", a: "1,820", t: "#0e9f6e" },
];

function HomeScreen() {
  return (
    <div className="app">
      <div className="app-top"><span>Hi, Riya</span><span className="dot" /></div>
      <div className="app-card">
        <span className="lbl">Spent this month</span>
        <b>₹42,380</b>
        <div className="bars">{[38, 62, 45, 80, 54, 70, 30].map((h, i) => <i key={i} style={{ height: `${h}%` }} />)}</div>
        <span className="hint">₹7,620 left of your ₹50,000 budget</span>
      </div>
      <div className="app-list">
        {TXNS.map((t) => (
          <div className="row" key={t.m}><span className="av" style={{ background: t.t }}>{t.m[0]}</span><span className="grow"><b>{t.m}</b><small>{t.c}</small></span><b>₹{t.a}</b></div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ nav + floating CTA */

export function Nav({ signedIn }: { signedIn: boolean }) {
  const onLanding = useLocation().pathname === "/";
  const to = (hash: string) => (onLanding ? hash : `/${hash}`); // other pages link back into the landing sections
  const { scrollY } = useScroll();
  const [hidden, setHidden] = useState(false);
  const [solid, setSolid] = useState(false);
  const last = useRef(0);
  useMotionValueEvent(scrollY, "change", (y) => {
    setSolid(y > 24);
    setHidden(y > 420 && y > last.current + 4 ? true : y < last.current - 4 ? false : hidden);
    last.current = y;
  });
  return (
    <motion.header className={`l-nav ${solid ? "solid" : ""}`} animate={{ y: hidden ? -90 : 0 }} transition={{ duration: 0.35, ease: EASE }}>
      <div className="in">
        <Brand />
        <nav className="links">
          <a href={to("#story")}>How it works</a>
          <a href={to("#security")}>Security</a>
          <Link to="/docs" className="docs-link">MCP docs</Link>
        </nav>
        <div className="acts">
          {signedIn ? <Link className="l-btn" to="/app">Open app</Link> : (<>
            <Link className="l-link" to="/login">Sign in</Link>
            <Link className="l-btn" to="/register">Get started</Link>
          </>)}
        </div>
      </div>
    </motion.header>
  );
}

function FloatingCta({ signedIn }: { signedIn: boolean }) {
  const { scrollY } = useScroll();
  const [show, setShow] = useState(false);
  const [closed, setClosed] = useState(false);
  useMotionValueEvent(scrollY, "change", (y) => setShow(y > window.innerHeight * 0.9));
  return (
    <AnimatePresence>
      {show && !closed && (
        <motion.aside className="l-float" initial={{ opacity: 0, y: 30, scale: 0.95 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 30 }} transition={{ duration: 0.4, ease: EASE }}>
          <button className="x" onClick={() => setClosed(true)} aria-label="Dismiss"><Icon name="x" /></button>
          <div className="coin" aria-hidden />
          <b>Track your first ₹ in 30 seconds</b>
          <span>Free · sample data included · no card</span>
          <Link className="l-btn" to={signedIn ? "/app" : "/register"}>{signedIn ? "Open app" : "Start free"} <Icon name="arrowRight" /></Link>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

/* ------------------------------------------------------------------ hero */

function Hero({ signedIn }: { signedIn: boolean }) {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress: p } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const phoneY = useTransform(p, [0, 1], [0, -160]);
  const phoneScale = useTransform(p, [0, 1], [1, 1.12]);
  const copyY = useTransform(p, [0, 1], [0, 140]);
  const copyO = useTransform(p, [0, 0.55], [1, 0]);
  const fastY = useTransform(p, [0, 1], [0, -320]);
  const slowY = useTransform(p, [0, 1], [0, -90]);
  const spin = useTransform(p, [0, 1], [0, 140]);
  return (
    <section className="l-hero" ref={ref}>
      <div className="l-hero-bg" aria-hidden><span className="ring r1" /><span className="ring r2" /></div>
      <motion.div className="copy" style={{ y: copyY, opacity: copyO }}>
        <motion.span className="l-eyebrow" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}>
          <i /> Personal finance, built on the Model Context Protocol
        </motion.span>
        <SplitHeadline className="l-h1" lines={["Money that", "answers back."]} />
        <motion.p initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.5, ease: EASE }}>
          Type “450 swiggy” and it is filed. Ask “where did my money go?” and it answers. Your ledger is an MCP server, so this app, Claude and your other tools all speak to the same money.
        </motion.p>
        <motion.div className="ctas" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.65, ease: EASE }}>
          <Link className="l-btn lg" to={signedIn ? "/app" : "/register"}>{signedIn ? "Open your ledger" : "Start free"} <Icon name="arrowRight" /></Link>
          <a className="l-btn lg ghost" href="#mcp">See MCP at work</a>
        </motion.div>
      </motion.div>
      <div className="stage">
        <motion.div className="float f1" style={{ y: fastY }} initial={{ opacity: 0, x: -40 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.9, duration: 0.8, ease: EASE }}>
          <span className="av" style={{ background: "#ff7a59" }}>S</span><span><b>Swiggy · ₹450</b><small>filed under Food &amp; Dining</small></span>
        </motion.div>
        <motion.div className="float f2" style={{ y: slowY }} initial={{ opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 1.05, duration: 0.8, ease: EASE }}>
          <span className="tag">elicitation/create</span><b>Where should “Kavya Pottery” go?</b>
          <span className="opts"><i className="on">Shopping</i><i>Gifts</i></span>
        </motion.div>
        <motion.div className="float f3" style={{ y: fastY }} initial={{ opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 1.2, duration: 0.8, ease: EASE }}>
          <svg viewBox="0 0 44 44" className="ring"><circle cx="22" cy="22" r="18" /><circle cx="22" cy="22" r="18" className="v" /></svg>
          <span><b>Food budget</b><small>72% used · 9 days left</small></span>
        </motion.div>
        <motion.span className="coin c1" style={{ y: slowY, rotate: spin }} aria-hidden>₹</motion.span>
        <motion.span className="coin c2" style={{ y: fastY, rotate: spin }} aria-hidden />
        <motion.span className="blob b1" style={{ y: slowY }} aria-hidden />
        <Phone className="hero-phone" style={{ y: phoneY, scale: phoneScale }}>
          <motion.div initial={{ opacity: 0, y: 60 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 1, delay: 0.3, ease: EASE }}><HomeScreen /></motion.div>
        </Phone>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ marquee, velocity-skewed */

const TAPE = ["Swiggy → Food & Dining", "Rent → Housing", "SIP → Investments", "Netflix → Subscriptions", "Salary → Income", "Uber → Transport", "BESCOM → Utilities", "Zepto → Groceries"];

function Marquee() {
  const { scrollY } = useScroll();
  const v = useVelocity(scrollY);
  const skew = useSpring(useTransform(v, [-2500, 0, 2500], [8, 0, -8]), { stiffness: 300, damping: 40 });
  return (
    <div className="l-tape" aria-hidden>
      <motion.div className="track" style={{ skewX: skew }}>
        {[0, 1].map((k) => <div className="run" key={k}>{TAPE.map((t) => <span key={t}>{t}<i /></span>)}</div>)}
      </motion.div>
    </div>
  );
}

/* ------------------------------------------------------------------ scroll-linked word reveal */

function Word({ p, range, children }: { p: MotionValue<number>; range: [number, number]; children: string }) {
  const o = useTransform(p, range, [0.14, 1]);
  const y = useTransform(p, range, [8, 0]);
  return <motion.span style={{ opacity: o, y }}>{children} </motion.span>;
}

function Reveal({ text, accent }: { text: string; accent: string[] }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const { scrollYProgress: p } = useScroll({ target: ref, offset: ["start 0.85", "end 0.4"] });
  const words = text.split(" ");
  return (
    <section className="l-reveal">
      <p ref={ref}>
        {words.map((w, i) => (
          <span key={i} className={accent.includes(w.replace(/[.,]/g, "")) ? "hl" : ""}>
            <Word p={p} range={[i / words.length, (i + 1) / words.length]}>{w}</Word>
          </span>
        ))}
      </p>
    </section>
  );
}

/* ------------------------------------------------------------------ pinned story: one phone, four chapters */

const STORY = [
  { k: "01", h: "Say it like a text.", p: "“450 swiggy”, “coffee 120 yesterday”, “+50000 salary”. One line becomes a transaction, categorised and remembered." },
  { k: "02", h: "Unsure? It asks you.", p: "When a merchant is new, the server pauses and asks where it belongs, right inside the app. That is MCP elicitation." },
  { k: "03", h: "Budgets that nudge.", p: "Monthly limits per category, gentle alerts before you cross them, and bills detected from your own history." },
  { k: "04", h: "Ask anything.", p: "“How much went on food last month?” The assistant calls the same MCP tools and shows you exactly which ones." },
];

function StoryScreen({ i }: { i: number }) {
  if (i === 0) {
    return (
      <div className="app">
        <div className="qa"><Icon name="plus" /><span className="typing">450 swiggy</span></div>
        <motion.div className="row new" initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }}>
          <span className="av" style={{ background: "#ff7a59" }}>S</span><span className="grow"><b>Swiggy</b><small>Food &amp; Dining · today</small></span><b>₹450</b>
        </motion.div>
        <div className="app-list dim">{TXNS.slice(1).map((t) => <div className="row" key={t.m}><span className="av" style={{ background: t.t }}>{t.m[0]}</span><span className="grow"><b>{t.m}</b><small>{t.c}</small></span><b>₹{t.a}</b></div>)}</div>
      </div>
    );
  }
  if (i === 1) {
    return (
      <div className="app">
        <div className="ask">
          <span className="tag">elicitation/create</span>
          <b>Where should Kavya Pottery Studio (₹349) be filed?</b>
          <div className="opts">{["Shopping", "Gifts", "Entertainment", "Personal Care"].map((o, k) => <motion.i key={o} className={k === 0 ? "on" : ""} initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.2 + k * 0.08 }}>{o}</motion.i>)}</div>
          <span className="send">Send answer</span>
        </div>
      </div>
    );
  }
  if (i === 2) {
    const B = [["Food & Dining", 72, ""], ["Transport", 41, ""], ["Shopping", 96, "warn"], ["Subscriptions", 100, "bad"]] as const;
    return (
      <div className="app">
        <div className="app-top"><span>Budgets · September</span></div>
        {B.map(([n, v, tone], k) => (
          <div className="budget" key={n}>
            <span className="grow"><b>{n}</b><small>{v}% used</small></span>
            <div className="track"><motion.i className={tone} initial={{ width: 0 }} animate={{ width: `${v}%` }} transition={{ duration: 0.9, delay: k * 0.1, ease: EASE }} /></div>
          </div>
        ))}
        <div className="alert">Shopping is at 96%. ₹180 left for 11 days.</div>
      </div>
    );
  }
  return (
    <div className="app convo">
      <div className="bub me">How much went on food last month?</div>
      <motion.div className="tool" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }}><Icon name="bolt" /> get_summary · 38 ms</motion.div>
      <motion.div className="bub" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.6 }}>₹11,240 on Food &amp; Dining in August, 18% less than July. Swiggy was 62% of it.</motion.div>
    </div>
  );
}

function Story() {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress: p } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const [i, setI] = useState(0);
  useMotionValueEvent(p, "change", (v) => setI(Math.min(STORY.length - 1, Math.max(0, Math.floor(v * STORY.length * 0.999)))));
  const fill = useTransform(p, [0, 1], ["0%", "100%"]);
  const tilt = useTransform(p, [0, 0.5, 1], [-4, 0, 4]);
  return (
    <section id="story" className="l-story" ref={ref}>
      <div className="sticky">
        <div className="chaps">
          <span className="kicker">How it works</span>
          {STORY.map((s, k) => (
            <motion.div key={s.k} className={`chap ${k === i ? "on" : ""}`} animate={{ opacity: k === i ? 1 : 0.35, x: k === i ? 0 : -6 }} transition={{ duration: 0.4 }}>
              <span className="n">{s.k}</span>
              <div><h3>{s.h}</h3><AnimatePresence initial={false}>{k === i && <motion.p initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}>{s.p}</motion.p>}</AnimatePresence></div>
            </motion.div>
          ))}
          <div className="progress"><motion.i style={{ height: fill }} /></div>
        </div>
        <Phone className="story-phone" style={{ rotate: tilt }}>
          <AnimatePresence mode="wait">
            <motion.div key={i} initial={{ opacity: 0, y: 30, filter: "blur(6px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }} exit={{ opacity: 0, y: -30, filter: "blur(6px)" }} transition={{ duration: 0.45, ease: EASE }}>
              <StoryScreen i={i} />
            </motion.div>
          </AnimatePresence>
        </Phone>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ MCP chapter: horizontal track driven by vertical scroll */

/* Each primitive is a card you can open: it leads to the same primitive running live on the in-app MCP page. The little
   picture on each card is what that primitive looks like on the wire, drawn in HTML (no images, no glyph icons). */
type Tone = "blue" | "ink" | "paper" | "sun";
const PRIMITIVES: { id: string; n?: string; h: string; method: string; p: string; tone: Tone; viz: ReactNode }[] = [
  { id: "playground", n: "28", h: "Tools", method: "tools/call", tone: "blue", p: "Add, categorise, import, budget, plan goals, track EMIs and run guarded SQL. Written once, used by every client.",
    viz: <div className="viz call"><code>add_transaction</code><span className="arg">merchant: <i>"Swiggy"</i>, amount: <i>420</i></span><span className="ok"><Icon name="check" />Food &amp; Dining</span></div> },
  { id: "playground", n: "13", h: "Resources", method: "resources/read", tone: "ink", p: "Overview, alerts, recurring bills, the review queue, and any month as a URI template.",
    viz: <div className="viz uris">{["finmcp://overview", "finmcp://alerts", "finmcp://transactions/2026-09"].map((u) => <code key={u}><span className="live-dot" />{u}</code>)}</div> },
  { id: "playground", n: "4", h: "Prompts", method: "prompts/get", tone: "paper", p: "Monthly review, subscription audit, budget plan, bulk categorising: one click in any MCP host.",
    viz: <div className="viz chips">{["/monthly-review", "/subscription-audit", "/budget-plan"].map((c) => <span key={c}>{c}</span>)}</div> },
  { id: "sampling", h: "Sampling", method: "sampling/createMessage", tone: "sun", p: "Merchants no rule knows go to your client's model in one batched round trip. The server holds no API key.",
    viz: <div className="viz relay"><span className="node">server</span><span className="wire"><i /></span><span className="node">your model</span></div> },
  { id: "elicitation", h: "Elicitation", method: "elicitation/create", tone: "ink", p: "When unsure, and before anything destructive, the server asks you. You always have the last word.",
    viz: <div className="viz ask"><span className="q">Where does <b>Moss &amp; Fern Co</b> belong?</span><span className="btns"><span>Shopping</span><span className="on">Home</span></span></div> },
  { id: "roots", h: "Roots", method: "roots/list", tone: "blue", p: "Statements are read only from folders the client allows. Anything else is refused.",
    viz: <div className="viz roots"><span className="yes"><Icon name="check" />~/Statements</span><span className="no"><Icon name="x" />/etc/hosts</span></div> },
  { id: "subscription", h: "Subscriptions", method: "subscriptions/listen", tone: "paper", p: "Write from Claude Desktop and this app refreshes the same second.",
    viz: <div className="viz pulse"><span className="ring" /><code>resources/updated</code></div> },
  { id: "completion", h: "Completion", method: "completion/complete", tone: "sun", p: "Months and arguments autocomplete, here and in every host that supports it.",
    viz: <div className="viz complete"><span className="field">2026-0<i /></span><span className="opts"><span className="on">2026-09</span><span>2026-08</span><span>2026-07</span></span></div> },
];

function McpTrack() {
  const ref = useRef<HTMLElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const [dist, setDist] = useState(0);
  useLayoutEffect(() => {
    const measure = () => setDist(Math.max(0, (track.current?.scrollWidth ?? 0) - window.innerWidth + 48));
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  const { scrollYProgress: p } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const x = useSpring(useTransform(p, [0.05, 0.95], [0, -dist]), { stiffness: 120, damping: 30, mass: 0.4 });
  const headY = useTransform(p, [0, 0.2], [40, 0]);
  const bar = useTransform(p, [0.05, 0.95], ["0%", "100%"]);
  return (
    <section id="mcp" className="l-mcp" ref={ref} style={{ height: `calc(100vh + ${dist}px)` }}>
      <div className="sticky">
        <motion.div className="head" style={{ y: headY }}>
          <span className="kicker">Why MCP</span>
          <h2>One ledger.<br /><span className="accent">Every assistant.</span></h2>
          <p>The Model Context Protocol is how AI apps plug into tools and data. FinMCP uses all eight parts of it, so your money works the same here, in Claude and in whatever comes next. Open any card to watch it run.</p>
        </motion.div>
        <motion.div className="track" ref={track} style={{ x }}>
          {PRIMITIVES.map((c, k) => (
            <Link to={`/app/mcp#${c.id}`} className={`p-card ${c.tone}`} key={c.h}>
              <div className="p-top"><span className="p-idx">{String(k + 1).padStart(2, "0")}</span><code className="p-method">{c.method}</code></div>
              {c.viz}
              <div className="p-body">
                <h3>{c.n ? <b className="p-n">{c.n}</b> : null}{c.h}</h3>
                <p>{c.p}</p>
              </div>
              <span className="p-go">See it live<Icon name="arrowRight" /></span>
            </Link>
          ))}
        </motion.div>
        <div className="p-progress" aria-hidden><motion.span style={{ width: bar }} /></div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ clients + stats */

type ClientId = "app" | "claude-desktop" | "claude-code" | "cursor" | "stdio";
const CLIENTS: { id: ClientId; n: string; d: string }[] = [
  { id: "app", n: "This app", d: "Two built-in MCP clients: the screens and the assistant" },
  { id: "claude-desktop", n: "Claude Desktop", d: "One config block with your personal token" },
  { id: "claude-code", n: "Claude Code", d: "One command in any terminal" },
  { id: "cursor", n: "Cursor", d: "A global MCP server in mcp.json" },
  { id: "stdio", n: "Your scripts", d: "Streamable HTTP or stdio, same tools" },
];
/** The endpoint this deployment actually serves, so the snippets on the page are the real thing. */
const HOST = mcpEndpoint();

function Stat({ to, suffix, label }: { to: number; suffix?: string; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref, { once: true, margin: "-80px" });
  const n = useCountUp(seen ? to : 0, 1400);
  return <div className="stat" ref={ref}><b>{Math.round(n ?? 0)}{suffix}</b><span>{label}</span></div>;
}

function Clients({ signedIn }: { signedIn: boolean }) {
  const [pick, setPick] = useState<ClientId>("claude-code");
  const [copied, setCopied] = useState(false);
  const code = pick === "app" ? "" : snippet(pick, HOST, "");
  const copy = () => { void navigator.clipboard?.writeText(code).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1400); }); };
  return (
    <section className="l-clients">
      <motion.div className="head" {...rise}>
        <span className="kicker">Works where you already are</span>
        <h2>Connect once.<br />Ask from anywhere.</h2>
      </motion.div>
      <div className="grid" role="tablist" aria-label="MCP clients">
        {CLIENTS.map((c, k) => (
          <motion.button type="button" role="tab" aria-selected={pick === c.id} className={`tile ${pick === c.id ? "on" : ""}`} key={c.id} onClick={() => setPick(c.id)}
            initial={{ opacity: 0, y: 50, rotate: k % 2 ? 2 : -2 }} whileInView={{ opacity: 1, y: 0, rotate: 0 }} viewport={{ once: true, margin: "-40px" }}
            transition={{ duration: 0.7, delay: k * 0.08, ease: EASE }} whileHover={{ y: -6 }} whileTap={{ scale: 0.97 }}>
            <span className="dot" /><b>{c.n}</b><small>{c.d}</small>
          </motion.button>
        ))}
      </div>
      <AnimatePresence mode="wait" initial={false}>
        <motion.div key={pick} className="setup" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.28, ease: EASE }}>
          {pick === "app" ? (
            <div className="setup-app">
              <p>Nothing to set up. Sign in and the app opens two MCP sessions for you: one for the screens, one for the assistant.</p>
              <Link className="l-btn" to={signedIn ? "/app" : "/register"}>{signedIn ? "Open the app" : "Create your ledger"} <Icon name="arrowRight" /></Link>
            </div>
          ) : (<>
            <div className="setup-head">
              <span>{NOTES[pick]}</span>
              <button type="button" className="copy" onClick={copy}><Icon name={copied ? "check" : "copy"} />{copied ? "Copied" : "Copy"}</button>
            </div>
            <pre className="snippet">{code}</pre>
            <span className="setup-foot">Your personal token (fm_…) comes from <Link to={signedIn ? "/app/connect" : "/register"}>Connect</Link> inside the app.</span>
          </>)}
        </motion.div>
      </AnimatePresence>
      <div className="stats">
        <Stat to={28} label="MCP tools" />
        <Stat to={13} label="live resources" />
        <Stat to={0} label="API keys on the server" />
        <Stat to={100} suffix="%" label="rows behind row-level security" />
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ security */

const SECURE = [
  { i: "shield" as const, h: "Row-level security", p: "Postgres policies keep every account to its own rows, whichever client is asking." },
  { i: "key" as const, h: "Personal tokens", p: "Each connected app gets its own revocable token. Only a hash is stored." },
  { i: "activity" as const, h: "Every write attributed", p: "The audit trail says which client changed what: the app, the assistant or Claude Desktop." },
  { i: "bolt" as const, h: "Guarded SQL", p: "Natural-language questions become read-only, single-statement SQL checked before it runs." },
];

function Security() {
  return (
    <section id="security" className="l-secure">
      <motion.div className="head" {...rise}>
        <span className="kicker">Security</span>
        <h2>Open protocol. Closed doors.</h2>
      </motion.div>
      <div className="grid">
        {SECURE.map((s, k) => (
          <motion.div className="item" key={s.h} initial={{ opacity: 0, y: 40 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.7, delay: k * 0.1, ease: EASE }}>
            <span className="ic"><Icon name={s.i} /></span><h3>{s.h}</h3><p>{s.p}</p>
          </motion.div>
        ))}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ scale-in CTA */

function BigCta({ signedIn }: { signedIn: boolean }) {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress: p } = useScroll({ target: ref, offset: ["start end", "center center"] });
  const scale = useTransform(p, [0, 1], [0.86, 1]);
  const radius = useTransform(p, [0, 1], [80, 32]);
  const y = useTransform(p, [0, 1], [80, 0]);
  return (
    <section className="l-cta" ref={ref}>
      <motion.div className="panel" style={{ scale, borderRadius: radius }}>
        <motion.div style={{ y }}>
          <h2>Your money,<br />finally on speaking terms.</h2>
          <p>Free on Supabase's free tier. Sample data on first sign in, so there is something to look at.</p>
          <Link className="l-btn lg white" to={signedIn ? "/app" : "/register"}>{signedIn ? "Open your ledger" : "Create your ledger"} <Icon name="arrowRight" /></Link>
        </motion.div>
        <span className="coin k1" aria-hidden>₹</span><span className="coin k2" aria-hidden /><span className="coin k3" aria-hidden />
      </motion.div>
    </section>
  );
}

/* ------------------------------------------------------------------ footer */

const COLS: { h: string; l: [string, string][] }[] = [
  { h: "Product", l: [["How it works", "/#story"], ["Security", "/#security"], ["MCP docs", "/docs"], ["Create account", "/register"]] },
  { h: "MCP", l: [["Live inspector", "/app/mcp"], ["Tools & resources", "#mcp"], ["Sampling", "#mcp"], ["Elicitation", "#mcp"]] },
  { h: "Connect", l: [["MCP docs", "/docs"], ["Claude Desktop", "/docs#clients"], ["Claude Code", "/docs#clients"], ["Any MCP client", "/docs#clients"]] },
  { h: "Inside the app", l: [["MCP live", "/app/mcp"], ["Ask", "/app/ask"], ["Import", "/app/import"], ["Activity", "/app/activity"]] },
  { h: "Built with", l: [["Model Context Protocol", "https://modelcontextprotocol.io"], ["Supabase", "https://supabase.com"], ["Claude", "https://www.anthropic.com/claude"], ["PostgreSQL", "https://www.postgresql.org"]] },
];

export function Footer() {
  return (
    <footer className="l-foot">
      <div className="top">
        <div className="about"><Brand light /><p>A personal-finance ledger that speaks MCP. Built as a portfolio project.</p></div>
        {COLS.map((c) => (
          <div className="col" key={c.h}>
            <b>{c.h}</b>
            {c.l.map(([t, href]) => (href.startsWith("/") ? <Link key={t} to={href}>{t}</Link> : <a key={t} href={href} {...(href.startsWith("http") ? { target: "_blank", rel: "noreferrer" } : {})}>{t}</a>))}
          </div>
        ))}
      </div>
      <div className="word" aria-hidden>FinMCP</div>
      <div className="base"><span>© {new Date().getFullYear()} FinMCP</span><span>Not a bank. Not financial advice.</span></div>
    </footer>
  );
}

/* ------------------------------------------------------------------ page */

export default function Landing() {
  const { user, ready } = useAuth();
  const reduced = useReducedMotion();
  const signedIn = ready && Boolean(user);
  useEffect(() => {
    if (reduced) return;
    const lenis = new Lenis({ autoRaf: true, lerp: 0.1, smoothWheel: true, anchors: true });
    return () => lenis.destroy();
  }, [reduced]);
  useEffect(() => { document.title = "FinMCP · money that answers back"; }, []);
  const { hash } = useLocation();
  useEffect(() => { // arriving from another page at /#story and the like
    if (!hash) return;
    const t = window.setTimeout(() => document.querySelector(hash)?.scrollIntoView({ behavior: "smooth" }), 120);
    return () => window.clearTimeout(t);
  }, [hash]);
  return (
    <div className="landing">
      <Nav signedIn={signedIn} />
      <Hero signedIn={signedIn} />
      <Marquee />
      <Reveal accent={["open", "protocol", "Claude", "permission"]} text="Most finance apps keep your money behind their own screens. FinMCP puts your ledger behind an open protocol, so this app, Claude and any tool you trust can read it, write to it and ask about it, only with your permission." />
      <Story />
      <McpTrack />
      <Clients signedIn={signedIn} />
      <Security />
      <BigCta signedIn={signedIn} />
      <Footer />
      <FloatingCta signedIn={signedIn} />
    </div>
  );
}
