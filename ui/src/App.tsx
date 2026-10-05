import { useEffect, useState, type FormEvent } from "react";
import { BookOpen, Brain, Clock, Languages, LogOut, MessageSquare, Settings as SettingsIcon, Users } from "lucide-react";
import { api, type Health } from "./api";
import { Badge, Button, Card, inputCls } from "./components/ui";
import { ContactsPage, GlossaryPage, HistoryPage, KnowledgePage, SettingsPage } from "./pages/Admin";
import Compose from "./pages/Compose";
import MemoryPage from "./pages/Memory";

const NAV = [
  { id: "compose", label: "Compose", Icon: MessageSquare },
  { id: "contacts", label: "Contacts & locales", Icon: Users },
  { id: "glossary", label: "Glossary", Icon: BookOpen },
  { id: "knowledge", label: "Knowledge", Icon: Languages },
  { id: "memory", label: "Memory", Icon: Brain },
  { id: "history", label: "History", Icon: Clock },
  { id: "settings", label: "Settings", Icon: SettingsIcon },
] as const;
type Page = (typeof NAV)[number]["id"];

function Login({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState(""); const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setError("");
    try { await api.login(password); onDone(); } catch (err) { setError(String((err as Error).message || err)); }
  };
  return (
    <div className="grid min-h-screen place-items-center bg-zinc-50 p-4 dark:bg-zinc-950">
      <Card title="Sign in to Localect" className="w-full max-w-sm">
        <form onSubmit={submit} className="space-y-3">
          <input className={inputCls} type="password" autoFocus placeholder="Owner password" value={password} onChange={(e) => setPassword(e.target.value)} data-testid="password" />
          {error && <p className="text-sm text-rose-600" data-testid="login-error">{error}</p>}
          <Button type="submit" className="w-full">Sign in</Button>
        </form>
      </Card>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>("compose");
  const [health, setHealth] = useState<Health | null>(null);
  const [tick, setTick] = useState(0);
  const [wantLogin, setWantLogin] = useState(false);
  useEffect(() => { api.health().then(setHealth).catch(() => setHealth(null)); }, [page, tick]);
  useEffect(() => { const bump = () => setTick((t) => t + 1); window.addEventListener("localect:composed", bump); return () => window.removeEventListener("localect:composed", bump); }, []);
  const visitor = !!health && !health.owner;
  const gated = !!health && health.auth_required && !health.owner && (health.public_mode !== "demo" || wantLogin);
  if (gated) return <Login onDone={() => { setWantLogin(false); setTick((t) => t + 1); }} />;
  const nav = visitor ? NAV.filter((n) => n.id === "compose") : NAV;
  const logout = async () => { await api.logout(); setTick((t) => t + 1); };

  return (
    <div className="flex min-h-screen bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900 md:flex">
        <div className="mb-6 flex items-center gap-2 px-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-indigo-600 text-white"><Languages className="h-4 w-4" /></span>
          <div><div className="font-semibold leading-tight">Localect</div><div className="text-[11px] text-zinc-500">reply like a local</div></div>
        </div>
        <nav className="space-y-1">
          {nav.map(({ id, label, Icon }) => (
            <button key={id} onClick={() => setPage(id)} data-testid={`nav-${id}`}
              className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm ${page === id ? "bg-indigo-50 font-medium text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300" : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"}`}>
              <Icon className="h-4 w-4" /> {label}
            </button>
          ))}
        </nav>
        <div className="mt-auto space-y-1 px-2 text-[11px] text-zinc-500">
          {health && (
            <div className="flex flex-wrap gap-1">
              {health.provider === "stub" ? <Badge tone="amber">stub mode · not a model</Badge> : <Badge tone="green">{health.model}</Badge>}
              {health.mcp && <Badge>MCP</Badge>}
              {visitor && <Badge tone="indigo">public demo</Badge>}
            </div>
          )}
          {visitor ? <div>Demo on sample data. Nothing you type is kept.</div> : <div>Private. Runs on your machine.</div>}
          {health?.auth_required && health.owner && <button onClick={logout} className="flex items-center gap-1 hover:text-zinc-700 dark:hover:text-zinc-300" data-testid="logout"><LogOut className="h-3 w-3" /> Sign out</button>}
          {visitor && health?.auth_required && <button onClick={() => setWantLogin(true)} className="hover:text-zinc-700 dark:hover:text-zinc-300" data-testid="owner-login">Owner? Sign in</button>}
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl p-4 md:p-8">
          <div className="mb-4 flex items-center gap-2 md:hidden">
            {NAV.map(({ id, label }) => <button key={id} onClick={() => setPage(id)} className={`rounded-full px-3 py-1 text-xs ${page === id ? "bg-indigo-600 text-white" : "bg-zinc-100 dark:bg-zinc-800"}`}>{label}</button>)}
          </div>
          <h1 className="mb-4 text-xl font-semibold">{NAV.find((n) => n.id === page)?.label}</h1>
          {visitor && (
            <div className="mb-4 rounded-xl border border-indigo-200 bg-indigo-50 p-3 text-sm text-indigo-900 dark:border-indigo-900 dark:bg-indigo-950/40 dark:text-indigo-200" data-testid="demo-banner">
              <b>Public demo.</b> Replies are grounded in a sample store, run on {health?.provider === "stub" ? "a deterministic stand-in, not a model" : health?.model}, and are not stored.{typeof health?.tries_left === "number" && <> You have <b>{health.tries_left}</b> tries left this hour.</>}
            </div>
          )}
          {page === "compose" && <Compose />}
          {page === "contacts" && <ContactsPage />}
          {page === "glossary" && <GlossaryPage />}
          {page === "knowledge" && <KnowledgePage />}
          {page === "memory" && <MemoryPage />}
          {page === "history" && <HistoryPage />}
          {page === "settings" && <SettingsPage />}
        </div>
      </main>
    </div>
  );
}
