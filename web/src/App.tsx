import { useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { ElicitationHost } from "./components/Elicitation";
import { QuickAdd } from "./components/QuickAdd";
import { ToastProvider } from "./components/Toast";
import { Avatar, Chip, Icon, Sheet, type IconName } from "./components/ui";
import { AuthProvider, useAuth } from "./lib/auth";
import { LedgerProvider, useLedger } from "./lib/ledger";
import { StatusProvider, useStatus } from "./lib/status";
import Activity from "./screens/Activity";
import AuthScreen from "./screens/Auth";
import Budgets from "./screens/Budgets";
import Chat from "./screens/Chat";
import Connect from "./screens/Connect";
import Goals from "./screens/Goals";
import Home from "./screens/Home";
import Import from "./screens/Import";
import Landing from "./screens/Landing";
import Mcp from "./screens/Mcp";
import Settings from "./screens/Settings";
import Subscriptions from "./screens/Subscriptions";
import Transactions from "./screens/Transactions";

const NAV: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: "/app", label: "Home", icon: "home", end: true },
  { to: "/app/transactions", label: "Transactions", icon: "list" },
  { to: "/app/budgets", label: "Budgets", icon: "budget" },
  { to: "/app/goals", label: "Goals", icon: "goal" },
  { to: "/app/subscriptions", label: "Subscriptions", icon: "repeat" },
  { to: "/app/ask", label: "Ask", icon: "chat" },
  { to: "/app/import", label: "Import", icon: "upload" },
  { to: "/app/mcp", label: "MCP live", icon: "bolt" },
];
const NAV_2: { to: string; label: string; icon: IconName }[] = [
  { to: "/app/connect", label: "Connect", icon: "plug" },
  { to: "/app/activity", label: "Activity", icon: "activity" },
  { to: "/app/settings", label: "Settings", icon: "settings" },
];

function LiveIndicator() {
  const { live } = useLedger();
  return (
    <div className={`live ${live ? "" : "off"}`} title="Changes made through Claude Desktop, the CLI or another tab show up here as they happen.">
      <span className="pulse" />{live ? "Live" : "Reconnecting…"}
    </div>
  );
}

function EngineChip() {
  const { health, error } = useStatus();
  if (error) return <Chip tone="bad">API offline</Chip>;
  if (!health) return <Chip>connecting</Chip>;
  return health.driver === "anthropic" ? <Chip tone="accent"><Icon name="spark" />Claude</Chip> : <Chip title="Add ANTHROPIC_API_KEY for Claude-powered answers and categorisation">offline engine</Chip>;
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
          <NavLink key={n.to} to={n.to} end={n.end}><Icon name={n.icon} />{n.label}{n.to === "/app/transactions" && review ? <span className="badge">{review}</span> : null}</NavLink>
        ))}
        <div className="sep" />
        {NAV_2.map((n) => <NavLink key={n.to} to={n.to}><Icon name={n.icon} />{n.label}</NavLink>)}
      </nav>
      <div className="foot">
        <LiveIndicator />
        {user ? (
          <Link to="/app/settings" className="account">
            <Avatar name={user.name} />
            <div className="who"><div className="n">{user.name}</div><div className="e">{user.email}</div></div>
          </Link>
        ) : null}
      </div>
    </aside>
  );
}

function TabBar() {
  const [more, setMore] = useState(false);
  const location = useLocation();
  const moreActive = ["/app/goals", "/app/subscriptions", "/app/import", "/app/connect", "/app/activity", "/app/settings"].some((p) => location.pathname.startsWith(p));
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
          {[...NAV.slice(3, 5), NAV[6], NAV[7], ...NAV_2].map((n) => <NavLink key={n.to} to={n.to} onClick={() => setMore(false)}><Icon name={n.icon} />{n.label}</NavLink>)}
        </div>
      </Sheet>
    </>
  );
}

function Shell() {
  return (
    <StatusProvider>
      <LedgerProvider>
        <div className="shell">
          <Sidebar />
          <main className="main">
            <div className="topbar">
              <QuickAdd />
              <span className="engine"><EngineChip /></span>
            </div>
            <div className="content">
              <Routes>
                <Route index element={<Home />} />
                <Route path="transactions" element={<Transactions />} />
                <Route path="budgets" element={<Budgets />} />
                <Route path="goals" element={<Goals />} />
                <Route path="subscriptions" element={<Subscriptions />} />
                <Route path="ask" element={<Chat />} />
                <Route path="chat" element={<Navigate to="/app/ask" replace />} />
                <Route path="import" element={<Import />} />
                <Route path="mcp" element={<Mcp />} />
                <Route path="connect" element={<Connect />} />
                <Route path="activity" element={<Activity />} />
                <Route path="settings" element={<Settings />} />
                <Route path="*" element={<Navigate to="/app" replace />} />
              </Routes>
            </div>
          </main>
          <ElicitationHost />
          <TabBar />
        </div>
      </LedgerProvider>
    </StatusProvider>
  );
}

function RequireAuth({ children }: { children: React.ReactElement }) {
  const { user, ready } = useAuth();
  const location = useLocation();
  if (!ready) return <div className="splash" aria-busy="true"><span className="spinner" /></div>;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<AuthScreen mode="login" />} />
          <Route path="/register" element={<AuthScreen mode="register" />} />
          <Route path="/app/*" element={<RequireAuth><Shell /></RequireAuth>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ToastProvider>
    </AuthProvider>
  );
}
