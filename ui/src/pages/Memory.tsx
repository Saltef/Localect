import { useEffect, useState, type FormEvent } from "react";
import { Check, Trash2, X } from "lucide-react";
import { api, type Fact, type MemoryStatus, type MessageItem } from "../api";
import { Badge, Button, Card, Empty, Field, inputCls } from "../components/ui";

const day = (iso: string) => (iso || "").slice(0, 10);

export default function MemoryPage() {
  const [status, setStatus] = useState<MemoryStatus | null>(null);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("");
  const [paths, setPaths] = useState("");
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");

  const load = () => {
    api.memory().then(setStatus).catch(() => setStatus(null));
    api.facts(q, filter).then(setFacts).catch(() => setFacts([]));
    api.messages(q).then((m) => setMessages(m.messages)).catch(() => setMessages([]));
  };
  useEffect(() => { load(); }, [q, filter]);

  const run = async (what: string, fn: () => Promise<string>) => {
    setBusy(what); setNote("");
    try { setNote(await fn()); } catch (e) { setNote(String((e as Error).message || e)); }
    setBusy(""); load();
  };
  const doImport = (e: FormEvent) => {
    e.preventDefault();
    const list = paths.split("\n").map((p) => p.trim()).filter(Boolean);
    if (!list.length) return;
    run("import", async () => { const r = await api.importPaths(list); setPaths(""); return r.summary; });
  };
  const doExtract = () => run("extract", async () => {
    const r = await api.extract();
    return `${r.messages} message(s) read, ${r.facts} fact(s) found${r.failed ? `, ${r.failed} failed` : ""}`;
  });
  const setFact = (f: Fact, status: Fact["status"]) => api.patchFact(f.id, { status }).then(load);
  const tone = (s: Fact["status"]) => (s === "confirmed" ? "green" : s === "rejected" ? "red" : "zinc");

  return (
    <div className="space-y-4">
      {status && (
        <div className="flex flex-wrap gap-2 text-sm">
          <Badge>{status.counts.messages} messages · {status.counts.mine} by you</Badge>
          <Badge>{status.facts.facts} facts · {status.facts.confirmed} confirmed</Badge>
          <Badge tone={status.embedder.offline ? "amber" : "green"}>search: {status.embedder.name}</Badge>
          {status.unextracted > 0 && <Badge tone="amber">{status.unextracted} message(s) not yet read for facts</Badge>}
          {status.conflicts.length > 0 && <Badge tone="red">{status.conflicts.length} topic(s) with disagreeing facts</Badge>}
        </div>
      )}
      {status && status.conflicts.length > 0 && (
        <Card title="Facts that disagree · the newest is used, confirm or reject to settle it">
          <ul className="space-y-2 text-sm">
            {status.conflicts.map((group) => (
              <li key={group[0].id} className="rounded-lg border border-rose-200 p-3 dark:border-rose-900/50">
                <div className="mb-1 font-medium">{group[0].topic}</div>
                <ul className="space-y-1">
                  {group.map((f, i) => (
                    <li key={f.id} className="flex flex-wrap items-center gap-2">
                      <Badge tone={i === 0 ? "green" : "zinc"}>{f.value}</Badge>
                      <span className="text-zinc-500">{f.said_by === "you" ? "you" : f.party || "they"} · {day(f.said_on)}</span>
                      <span className="min-w-0 flex-1 truncate">{f.statement}</span>
                      <span className="ml-auto flex gap-1">
                        <Button kind="ghost" onClick={() => setFact(f, "confirmed")}><Check className="h-4 w-4" /></Button>
                        <Button kind="danger" onClick={() => setFact(f, "rejected")}><X className="h-4 w-4" /></Button>
                      </span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-4">
          <Card title="Facts · what your conversations state, with dates" action={
            <div className="flex items-center gap-2">
              <input className={`${inputCls} w-44`} placeholder="search" value={q} onChange={(e) => setQ(e.target.value)} data-testid="memory-search" />
              <select className={`${inputCls} w-32`} value={filter} onChange={(e) => setFilter(e.target.value)}>
                <option value="">all</option><option value="auto">unreviewed</option><option value="confirmed">confirmed</option><option value="rejected">rejected</option>
              </select>
            </div>}>
            {facts.length ? (
              <div className="overflow-x-auto"><table className="w-full text-sm">
                <thead className="text-left text-xs text-zinc-500"><tr><th className="py-1">Topic</th><th>Value</th><th>Statement</th><th>Said</th><th></th></tr></thead>
                <tbody>
                  {facts.map((f) => (
                    <tr key={f.id} className="border-t border-zinc-100 align-top dark:border-zinc-800" data-testid="fact-row">
                      <td className="py-2 pr-2 font-medium">{f.topic}</td>
                      <td className="pr-2"><Badge tone={tone(f.status)}>{f.value || "—"}</Badge></td>
                      <td className="min-w-48 break-words pr-2 text-zinc-700 dark:text-zinc-300">{f.statement}</td>
                      <td className="whitespace-nowrap pr-2 text-xs text-zinc-500">{f.said_by === "you" ? "you" : f.party || "they"}<br />{day(f.said_on)}</td>
                      <td className="whitespace-nowrap text-right">
                        {f.status !== "confirmed" && <Button kind="ghost" onClick={() => setFact(f, "confirmed")}><Check className="h-4 w-4" /></Button>}
                        {f.status !== "rejected" && <Button kind="ghost" onClick={() => setFact(f, "rejected")}><X className="h-4 w-4" /></Button>}
                        <Button kind="danger" onClick={() => api.delFact(f.id).then(load)}><Trash2 className="h-4 w-4" /></Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            ) : <Empty>No facts yet. Import your past mail, then read it for facts.</Empty>}
          </Card>
          <Card title="Messages · your past mail, imported or captured">
            {messages.length ? (
              <ul className="divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
                {messages.map((m) => (
                  <li key={m.id} className="flex items-start gap-3 py-2" data-testid="message-row">
                    <span className="w-24 shrink-0 text-xs text-zinc-500">{day(m.date)}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2"><b className="truncate">{m.subject || "(no subject)"}</b>{m.is_mine ? <Badge tone="indigo">you</Badge> : <span className="text-xs text-zinc-500">{m.from_name || m.from_addr}</span>}{m.origin === "capture" && <Badge tone="amber">captured</Badge>}</span>
                      <span className="block truncate text-zinc-500">{m.preview}</span>
                    </span>
                    <Button kind="danger" onClick={() => api.delMessage(m.id).then(load)}><Trash2 className="h-4 w-4" /></Button>
                  </li>
                ))}
              </ul>
            ) : <Empty>Nothing imported yet.</Empty>}
          </Card>
        </div>
        <div className="min-w-0 space-y-4">
          <Card title="Import past mail">
            <form onSubmit={doImport} className="space-y-3">
              <Field label="Files or folders on this machine" hint="One per line. mbox exports (Gmail Takeout, Apple Mail, Thunderbird), .eml files, .md/.txt/.pdf documents.">
                <textarea className={`${inputCls} min-h-24`} value={paths} onChange={(e) => setPaths(e.target.value)} data-testid="import-paths" />
              </Field>
              <Button type="submit" disabled={busy !== ""}>{busy === "import" ? "Importing…" : "Import"}</Button>
            </form>
          </Card>
          <Card title="Read mail for facts">
            <p className="mb-3 text-sm text-zinc-600 dark:text-zinc-400">Turns each message into dated facts (policies, prices, deadlines) you can confirm or reject. One model call per message.</p>
            <Button kind="ghost" onClick={doExtract} disabled={busy !== "" || !status || status.unextracted === 0} data-testid="extract">{busy === "extract" ? "Reading…" : `Read ${status?.unextracted ?? 0} message(s)`}</Button>
          </Card>
          {note && <p className="text-sm text-zinc-600 dark:text-zinc-400" data-testid="memory-note">{note}</p>}
          <p className="text-xs text-zinc-500">Everything here stays on this machine. Only the paragraphs retrieved for one reply are sent to the model you configured.</p>
        </div>
      </div>
    </div>
  );
}
