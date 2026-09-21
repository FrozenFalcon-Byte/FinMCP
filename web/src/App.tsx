import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { ElicitationHost } from "./components/Elicitation";
import { CurtainProvider } from "./components/Curtain";
import { AddButton, AddProvider } from "./components/QuickAdd";
import { SignOutButton } from "./components/SignOut";
import { TopBar } from "./components/TopBar";
import { ToastProvider } from "./components/Toast";
import { WakeProvider } from "./components/Wake";
import { Avatar, Chip, Icon, Sheet, type IconName } from "./components/ui";
import { AuthProvider, useAuth } from "./lib/auth";
import { LedgerProvider } from "./lib/ledger";
import { StatusProvider, useStatus } from "./lib/status";
import { surface } from "./lib/surface";
import Activity from "./screens/Activity";
import AuthScreen, { AuthLayout } from "./screens/Auth";
import Budgets from "./screens/Budgets";
import Chat from "./screens/Chat";
import Docs from "./screens/Docs";
import Connect from "./screens/Connect";
import Emis from "./screens/Emis";
import Goals from "./screens/Goals";
import Home from "./screens/Home";
import Import from "./screens/Import";
import Landing from "./screens/Landing";
import Mcp from "./screens/Mcp";
import Profile from "./screens/Profile";
import ResetPassword from "./screens/ResetPassword";
import Settings from "./screens/Settings";
import Subscriptions from "./screens/Subscriptions";
import Transactions from "./screens/Transactions";

const NAV: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: "/app", label: "Home", icon: "home", end: true },
  { to: "/app/transactions", label: "Transactions", icon: "list" },
  { to: "/app/budgets", label: "Budgets", icon: "budget" },
  { to: "/app/goals", label: "Goals", icon: "goal" },
  { to: "/app/subscriptions", label: "Subscriptions", icon: "repeat" },
  { to: "/app/emis", label: "EMIs", icon: "calendar" },
  { to: "/app/ask", label: "Ask", icon: "chat" },
  { to: "/app/import", label: "Import", icon: "upload" },
  { to: "/app/mcp", label: "MCP live", icon: "bolt" },
];
const NAV_2: { to: string; label: string; icon: IconName }[] = [
  { to: "/app/connect", label: "Connect", icon: "plug" },
  { to: "/app/activity", label: "Activity", icon: "activity" },
  { to: "/app/profile", label: "Profile", icon: "user" },
  { to: "/app/settings", label: "Settings", icon: "settings" },
];

function EngineChip() {
  const { health, error } = useStatus();
  if (error) return <Chip tone="bad">API offline</Chip>;
  if (!health) return <Chip>connecting</Chip>;
  if (health.driver === "openrouter") return <Chip tone="accent" title={`OpenRouter · ${health.model ?? ""}`}><Icon name="spark" />{(health.model ?? "OpenRouter").split("/").pop()}</Chip>;
  return health.driver === "anthropic" ? <Chip tone="accent"><Icon name="spark" />Claude</Chip> : <Chip title="Add OPENROUTER_API_KEY to .env for model-powered answers and categorisation">offline engine</Chip>;
}

/** The active-page highlight: one element that glides from the old nav item to the new one. */
function NavPill() {
  return <motion.span layoutId="nav-pill" className="nav-pill" transition={{ type: "spring", stiffness: 520, damping: 40 }} />;
}

function Sidebar() {
  const { health } = useStatus();
  const { user } = useAuth();
  const review = health?.status?.needs_review ?? 0;
  return (
    <aside className="sidebar">
      <Link to="/" className="brand"><span className="mark"><Icon name="logo" /></span><span className="word">FinMCP</span></Link>
      <nav className="nav">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end}>{({ isActive }) => <>{isActive ? <NavPill /> : null}<Icon name={n.icon} />{n.label}{n.to === "/app/transactions" && review ? <span className="badge">{review}</span> : null}</>}</NavLink>
        ))}
        <div className="sep" />
        {NAV_2.map((n) => <NavLink key={n.to} to={n.to}>{({ isActive }) => <>{isActive ? <NavPill /> : null}<Icon name={n.icon} />{n.label}</>}</NavLink>)}
      </nav>
      <div className="foot">
        {user ? (
          <div className="account-box">
            <Link to="/app/profile" className="account" title="Your profile">
              <Avatar name={user.name} />
              <div className="who"><div className="n">{user.name}</div><div className="e">{user.email}</div></div>
            </Link>
            <SignOutButton className="btn sm ghost block signout" />
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function TabBar() {
  const [more, setMore] = useState(false);
  const location = useLocation();
  const moreActive = ["/app/goals", "/app/subscriptions", "/app/emis", "/app/import", "/app/mcp", "/app/connect", "/app/activity", "/app/profile", "/app/settings"].some((p) => location.pathname.startsWith(p));
  return (
    <>
      <nav className="tabbar">
        <NavLink to="/app" end><Icon name="home" />Home</NavLink>
        <NavLink to="/app/transactions"><Icon name="list" />Activity</NavLink>
        <NavLink to="/app/ask"><Icon name="chat" />Ask</NavLink>
        <NavLink to="/app/budgets"><Icon name="budget" />Budgets</NavLink>
        <a href="#more" className={moreActive ? "active" : ""} onClick={(e) => { e.preventDefault(); setMore(true); }}><Icon name="more" />More</a>
      </nav>
      <Sheet open={more} onClose={() => setMore(false)} title="More">
        <div className="nav">
          {[...NAV.slice(3, 6), ...NAV.slice(7), ...NAV_2].map((n) => <NavLink key={n.to} to={n.to} onClick={() => setMore(false)}><Icon name={n.icon} />{n.label}</NavLink>)}
        </div>
        <SignOutButton className="btn block signout" onDone={() => setMore(false)} />
      </Sheet>
    </>
  );
}

const EASE = [0.22, 1, 0.36, 1] as const;
/* Page change inside the app: a quiet cross-fade through the background, nothing moves. `mode="wait"` keeps the
   two pages from overlapping; the scroll resets in between, while nothing is on screen. */
const PAGE = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: 0.3, ease: EASE } },
  exit: { opacity: 0, transition: { duration: 0.12, ease: "easeIn" as const } },
};
const toTop = () => window.scrollTo(0, 0);

function Shell() {
  const location = useLocation();
  return (
    <StatusProvider>
      <LedgerProvider>
        <AddProvider>
        <div className="shell">
          <Sidebar />
          <main className="main">
            <TopBar><span className="engine"><EngineChip /></span></TopBar>
            <div className="content">
              <AnimatePresence mode="wait" initial={false} onExitComplete={toTop}>
                <motion.div key={location.pathname} {...PAGE}>
              <Routes location={location}>
                <Route index element={<Home />} />
                <Route path="transactions" element={<Transactions />} />
                <Route path="budgets" element={<Budgets />} />
                <Route path="goals" element={<Goals />} />
                <Route path="subscriptions" element={<Subscriptions />} />
                <Route path="emis" element={<Emis />} />
                <Route path="ask" element={<Chat />} />
                <Route path="chat" element={<Navigate to="/app/ask" replace />} />
                <Route path="import" element={<Import />} />
                <Route path="mcp" element={<Mcp />} />
                <Route path="connect" element={<Connect />} />
                <Route path="activity" element={<Activity />} />
                <Route path="profile" element={<Profile />} />
                <Route path="settings" element={<Settings />} />
                <Route path="*" element={<Navigate to="/app" replace />} />
              </Routes>
                </motion.div>
              </AnimatePresence>
            </div>
          </main>
          <ElicitationHost />
          {/* Under the thumb on a phone, where the top bar is a stretch. */}
          <AddButton className="fab" label="Add" />
          <TabBar />
        </div>
        </AddProvider>
      </LedgerProvider>
    </StatusProvider>
  );
}

function RequireAuth({ children }: { children: React.ReactElement }) {
  const { user, ready } = useAuth();
  const location = useLocation();
  if (!ready) return <div className="splash" aria-busy="true"><span className="spinner" /></div>;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search + location.hash)}`} replace />;
  return children;
}

export default function App() {
  const location = useLocation();
  return (
    <AuthProvider>
      <ToastProvider>
        <WakeProvider>
        <MotionConfig reducedMotion="user">
        <CurtainProvider>
        <AnimatePresence mode="wait" initial={false} onExitComplete={toTop}>
          <motion.div key={surface(location.pathname)} data-surface={surface(location.pathname)} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.3, ease: EASE }}>
            <Routes location={location}>
              <Route path="/" element={<Landing />} />
              <Route path="/docs" element={<Docs />} />
              <Route path="/mcp" element={<Navigate to="/app/mcp" replace />} />
              <Route element={<AuthLayout />}>
                <Route path="/login" element={<AuthScreen mode="login" />} />
                <Route path="/register" element={<AuthScreen mode="register" />} />
                <Route path="/forgot-password" element={<ResetPassword mode="forgot" />} />
                <Route path="/reset-password" element={<ResetPassword mode="reset" />} />
              </Route>
              <Route path="/app/*" element={<RequireAuth><Shell /></RequireAuth>} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </motion.div>
        </AnimatePresence>
        </CurtainProvider>
        </MotionConfig>
        </WakeProvider>
      </ToastProvider>
    </AuthProvider>
  );
}
