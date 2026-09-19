/* The public landing page. super.money's language: white and brand blue, huge tight headlines, a phone that carries
   the story, full-bleed blue chapters, and motion that is tied to the scroll rather than played at you. No WebGL:
   everything is DOM, CSS and motion values, so it stays light on phones. */
import Lenis from "lenis";
import {
  AnimatePresence, motion, useInView, useMotionValueEvent, useReducedMotion, useScroll, useSpring, useTransform, useVelocity, type MotionValue,
} from "motion/react";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icon, useCountUp } from "../components/ui";
import { useAuth } from "../lib/auth";
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

function Nav({ signedIn }: { signedIn: boolean }) {
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
          <a href="#story">How it works</a>
          <a href="#mcp">MCP</a>
          <a href="#security">Security</a>
          <a href="#faq">FAQ</a>
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
  const bg = useTransform(p, [0, 0.08, 0.92, 1], ["#ffffff", "#4d43fe", "#4d43fe", "#ffffff"]);
  const fill = useTransform(p, [0, 1], ["0%", "100%"]);
  const tilt = useTransform(p, [0, 0.5, 1], [-4, 0, 4]);
  return (
    <motion.section id="story" className="l-story" ref={ref} style={{ background: bg }}>
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
    </motion.section>
  );
}

/* ------------------------------------------------------------------ MCP chapter: horizontal track driven by vertical scroll */

const PRIMITIVES = [
  { n: "24", h: "Tools", p: "Add, categorise, import statements, budgets, goals, guarded SQL. Written once, used by every client." },
  { n: "13", h: "Resources", p: "Overview, alerts, recurring bills, review queue, month-by-month transactions as a URI template." },
  { n: "4", h: "Prompts", p: "Monthly review, subscription audit, budget plan, bulk categorising: one click in any MCP host." },
  { n: "↺", h: "Sampling", p: "New merchants go to your client's model in one batched round trip. The server holds no API key." },
  { n: "?", h: "Elicitation", p: "The server asks you when it is unsure, and before anything destructive. You always have the last word." },
  { n: "⌂", h: "Roots", p: "Statements are read only from folders the client allows. Everything else is refused." },
  { n: "●", h: "Subscriptions", p: "Write from Claude Desktop and this app refreshes the same second, through subscriptions/listen." },
  { n: "⇥", h: "Completion", p: "Months and arguments autocomplete, in this app and in every host that supports it." },
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
  return (
    <section id="mcp" className="l-mcp" ref={ref} style={{ height: `calc(100vh + ${dist}px)` }}>
      <div className="sticky">
        <motion.div className="head" style={{ y: headY }}>
          <span className="kicker light">Why MCP</span>
          <h2>One ledger. Every assistant.</h2>
          <p>The Model Context Protocol is how AI apps plug into tools and data. FinMCP uses all of it, so your money works the same in this app, in Claude and in whatever comes next.</p>
        </motion.div>
        <motion.div className="track" ref={track} style={{ x }}>
          {PRIMITIVES.map((c, k) => (
            <div className="card" key={c.h}>
              <span className="n">{c.n}</span>
              <h3>{c.h}</h3>
              <p>{c.p}</p>
              <span className="idx">{String(k + 1).padStart(2, "0")} / {PRIMITIVES.length}</span>
            </div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ clients + stats */

const CLIENTS = [
  { n: "This app", d: "Two built-in MCP clients: the screens and the assistant" },
  { n: "Claude Desktop", d: "Paste one config block with your personal token" },
  { n: "Claude Code", d: "claude mcp add --transport http finmcp …" },
  { n: "Cursor", d: "Add it as a global MCP server" },
  { n: "Your scripts", d: "Streamable HTTP or stdio, same tools" },
];

function Stat({ to, suffix, label }: { to: number; suffix?: string; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref, { once: true, margin: "-80px" });
  const n = useCountUp(seen ? to : 0, 1400);
  return <div className="stat" ref={ref}><b>{Math.round(n ?? 0)}{suffix}</b><span>{label}</span></div>;
}

function Clients() {
  return (
    <section className="l-clients">
      <motion.div className="head" {...rise}>
        <span className="kicker">Works where you already are</span>
        <h2>Connect once.<br />Ask from anywhere.</h2>
      </motion.div>
      <div className="grid">
        {CLIENTS.map((c, k) => (
          <motion.div className="tile" key={c.n} initial={{ opacity: 0, y: 50, rotate: k % 2 ? 2 : -2 }} whileInView={{ opacity: 1, y: 0, rotate: 0 }} viewport={{ once: true, margin: "-40px" }} transition={{ duration: 0.7, delay: k * 0.08, ease: EASE }}>
            <span className="dot" /><b>{c.n}</b><small>{c.d}</small>
          </motion.div>
        ))}
      </div>
      <motion.pre className="snippet" {...rise}>{`claude mcp add --transport http finmcp https://your-host/mcp \\
  --header "Authorization: Bearer fm_…"`}</motion.pre>
      <div className="stats">
        <Stat to={24} label="MCP tools" />
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

/* ------------------------------------------------------------------ FAQ */

const FAQ = [
  { q: "What is MCP, in one line?", a: "The Model Context Protocol is an open standard for connecting AI apps to tools and data. FinMCP exposes your ledger as an MCP server, so any MCP client can use it with your permission." },
  { q: "Do I need Claude or an API key to use FinMCP?", a: "No. The app works on its own: rules and merchant memory categorise most spending. With a key, the assistant answers questions and the server borrows that model through MCP sampling for unfamiliar merchants." },
  { q: "Can Claude Desktop see everyone's data?", a: "No. A personal token maps to exactly one account, and Postgres row-level security enforces that on every query, whichever client is asking." },
  { q: "What does the server do when it is unsure?", a: "It asks. Through MCP elicitation, the server pauses the tool call and shows you a question in the app. Deleting anything asks for confirmation too." },
  { q: "Can I import bank statements?", a: "Yes: PDF and CSV statements, receipt photos and pasted SMS alerts. Duplicates are skipped by fingerprint, and the server may only read files from folders the client allows." },
  { q: "Is it free?", a: "Yes. It runs on Supabase's free tier for auth and Postgres, and locally on an embedded Postgres when you are offline." },
];

function Faq() {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <section id="faq" className="l-faq">
      <motion.h2 {...rise}>Questions, answered.</motion.h2>
      <div className="list">
        {FAQ.map((f, k) => (
          <motion.div key={f.q} className={`qa ${open === k ? "open" : ""}`} initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.5, delay: k * 0.05 }}>
            <button onClick={() => setOpen(open === k ? null : k)} aria-expanded={open === k}>
              <span>{f.q}</span>
              <motion.span className="chev" animate={{ rotate: open === k ? 180 : 0 }}><Icon name="arrowDown" /></motion.span>
            </button>
            <AnimatePresence initial={false}>
              {open === k && (
                <motion.div className="a" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.35, ease: EASE }}>
                  <p>{f.a}</p>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        ))}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ footer */

const COLS: { h: string; l: [string, string][] }[] = [
  { h: "Product", l: [["How it works", "#story"], ["Security", "#security"], ["FAQ", "#faq"], ["Sign in", "/login"]] },
  { h: "MCP", l: [["Tools & resources", "#mcp"], ["Sampling", "#mcp"], ["Elicitation", "#mcp"], ["Subscriptions", "#mcp"]] },
  { h: "Connect", l: [["Claude Desktop", "/app/connect"], ["Claude Code", "/app/connect"], ["Cursor", "/app/connect"], ["Any MCP client", "/app/connect"]] },
  { h: "Inside the app", l: [["MCP live", "/app/mcp"], ["Ask", "/app/ask"], ["Import", "/app/import"], ["Activity", "/app/activity"]] },
  { h: "Built with", l: [["Model Context Protocol", "https://modelcontextprotocol.io"], ["Supabase", "https://supabase.com"], ["Claude", "https://www.anthropic.com/claude"], ["PostgreSQL", "https://www.postgresql.org"]] },
];

function Footer() {
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
  return (
    <div className="landing">
      <Nav signedIn={signedIn} />
      <Hero signedIn={signedIn} />
      <Marquee />
      <Reveal accent={["open", "protocol", "Claude", "permission"]} text="Most finance apps keep your money behind their own screens. FinMCP puts your ledger behind an open protocol, so this app, Claude and any tool you trust can read it, write to it and ask about it, only with your permission." />
      <Story />
      <McpTrack />
      <Clients />
      <Security />
      <BigCta signedIn={signedIn} />
      <Faq />
      <Footer />
      <FloatingCta signedIn={signedIn} />
    </div>
  );
}
