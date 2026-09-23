import { useEffect, useState } from "react";
import { BookOpen, Clock, Languages, MessageSquare, Settings as SettingsIcon, Users } from "lucide-react";
import { api, type Health } from "./api";
import { Badge } from "./components/ui";
import { ContactsPage, GlossaryPage, HistoryPage, KnowledgePage, SettingsPage } from "./pages/Admin";
import Compose from "./pages/Compose";

const NAV = [
  { id: "compose", label: "Compose", Icon: MessageSquare },
  { id: "contacts", label: "Contacts & locales", Icon: Users },
  { id: "glossary", label: "Glossary", Icon: BookOpen },
  { id: "knowledge", label: "Knowledge", Icon: Languages },
  { id: "history", label: "History", Icon: Clock },
  { id: "settings", label: "Settings", Icon: SettingsIcon },
] as const;
type Page = (typeof NAV)[number]["id"];

export default function App() {
  const [page, setPage] = useState<Page>("compose");
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => { api.health().then(setHealth).catch(() => setHealth(null)); }, [page]);

  return (
    <div className="flex min-h-screen bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900 md:flex">
        <div className="mb-6 flex items-center gap-2 px-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-indigo-600 text-white"><Languages className="h-4 w-4" /></span>
          <div><div className="font-semibold leading-tight">Envoy</div><div className="text-[11px] text-zinc-500">reply like a local</div></div>
        </div>
        <nav className="space-y-1">
          {NAV.map(({ id, label, Icon }) => (
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
            </div>
          )}
          <div>Private. Runs on your machine.</div>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl p-4 md:p-8">
          <div className="mb-4 flex items-center gap-2 md:hidden">
            {NAV.map(({ id, label }) => <button key={id} onClick={() => setPage(id)} className={`rounded-full px-3 py-1 text-xs ${page === id ? "bg-indigo-600 text-white" : "bg-zinc-100 dark:bg-zinc-800"}`}>{label}</button>)}
          </div>
          <h1 className="mb-4 text-xl font-semibold">{NAV.find((n) => n.id === page)?.label}</h1>
          {page === "compose" && <Compose />}
          {page === "contacts" && <ContactsPage />}
          {page === "glossary" && <GlossaryPage />}
          {page === "knowledge" && <KnowledgePage />}
          {page === "history" && <HistoryPage />}
          {page === "settings" && <SettingsPage />}
        </div>
      </main>
    </div>
  );
}
