import { useEffect, useState, type FormEvent } from "react";
import { Trash2 } from "lucide-react";
import { api, type Contact, type GlossaryItem, type HistoryItem, type KnowledgeItem, type LocaleProfile, type Result, type Settings } from "../api";
import ResultView from "../components/ResultView";
import { Badge, Button, Card, Empty, Field, inputCls } from "../components/ui";

const LANGS = ["*", "ar", "en", "es", "pt", "fr", "de", "ja"];

export function GlossaryPage() {
  const [items, setItems] = useState<GlossaryItem[]>([]);
  const [term, setTerm] = useState(""); const [rendering, setRendering] = useState("");
  const [language, setLanguage] = useState("*"); const [dnt, setDnt] = useState(false); const [notes, setNotes] = useState("");
  const load = () => api.glossary().then(setItems);
  useEffect(() => { load(); }, []);
  const add = async (e: FormEvent) => { e.preventDefault(); await api.addGlossary({ term, rendering, language, do_not_translate: dnt, notes }); setTerm(""); setRendering(""); setNotes(""); setDnt(false); load(); };
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <Card title="Glossary">
        {items.length ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-zinc-500"><tr><th className="py-1">Term</th><th>Rule</th><th>Language</th><th></th></tr></thead>
            <tbody>
              {items.map((g) => (
                <tr key={g.id} className="border-t border-zinc-100 dark:border-zinc-800">
                  <td className="py-2 font-medium">{g.term}</td>
                  <td>{g.do_not_translate ? <Badge tone="indigo">do not translate</Badge> : <span>render as <b>{g.rendering}</b></span>}</td>
                  <td className="text-zinc-500">{g.language}</td>
                  <td className="text-right"><Button kind="danger" onClick={() => api.delGlossary(g.id).then(load)}><Trash2 className="h-4 w-4" /></Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <Empty>No terms yet. Add brand names and words that must be rendered a specific way.</Empty>}
      </Card>
      <Card title="Add a term">
        <form onSubmit={add} className="space-y-3">
          <Field label="Term"><input className={inputCls} value={term} onChange={(e) => setTerm(e.target.value)} required /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={dnt} onChange={(e) => setDnt(e.target.checked)} /> Never translate this term</label>
          {!dnt && <Field label="Preferred rendering"><input className={inputCls} value={rendering} onChange={(e) => setRendering(e.target.value)} /></Field>}
          <Field label="Applies to language"><select className={inputCls} value={language} onChange={(e) => setLanguage(e.target.value)}>{LANGS.map((l) => <option key={l} value={l}>{l === "*" ? "all languages" : l}</option>)}</select></Field>
          <Field label="Notes"><input className={inputCls} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
          <Button type="submit">Add</Button>
        </form>
      </Card>
    </div>
  );
}

export function ContactsPage() {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [locales, setLocales] = useState<LocaleProfile[]>([]);
  const [name, setName] = useState(""); const [locale, setLocale] = useState("en-US"); const [notes, setNotes] = useState("");
  const [gender, setGender] = useState("unknown");
  const [editing, setEditing] = useState<LocaleProfile | null>(null);
  const load = () => { api.contacts().then(setContacts); api.locales().then(setLocales); };
  useEffect(() => { load(); }, []);
  const add = async (e: FormEvent) => { e.preventDefault(); await api.addContact({ name, locale, notes, gender }); setName(""); setNotes(""); setGender("unknown"); load(); };
  const setVariant = (kind: "greetings" | "signoffs", g: string, v: string) => {
    if (!editing) return;
    const next = { ...(editing[kind] || {}) }; if (v) next[g] = v; else delete next[g];
    setEditing({ ...editing, [kind]: next });
  };
  const save = async () => { if (editing) { await api.saveLocale(editing); setEditing(null); load(); } };
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card title="Contacts">
          {contacts.length ? (
            <ul className="divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
              {contacts.map((c) => (
                <li key={c.id} className="flex items-center justify-between py-2">
                  <span><b>{c.name}</b> <Badge tone="indigo">{c.locale}</Badge>{c.gender && c.gender !== "unknown" ? <Badge>{c.gender}</Badge> : null} <span className="text-zinc-500">{c.notes}</span></span>
                  <Button kind="danger" onClick={() => api.delContact(c.id).then(load)}><Trash2 className="h-4 w-4" /></Button>
                </li>
              ))}
            </ul>
          ) : <Empty>No contacts yet. A contact pins the locale Envoy writes in.</Empty>}
        </Card>
        <Card title="Add a contact">
          <form onSubmit={add} className="space-y-3">
            <Field label="Name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} required /></Field>
            <Field label="Locale"><select className={inputCls} value={locale} onChange={(e) => setLocale(e.target.value)}>{locales.map((l) => <option key={l.locale} value={l.locale}>{l.variety} ({l.locale})</option>)}</select></Field>
            <Field label="Addressed as" hint="Arabic and Portuguese greetings change with the receiver's gender"><select className={inputCls} value={gender} onChange={(e) => setGender(e.target.value)}>{["unknown", "female", "male"].map((g) => <option key={g} value={g}>{g}</option>)}</select></Field>
            <Field label="Notes"><input className={inputCls} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
            <Button type="submit">Add</Button>
          </form>
        </Card>
      </div>
      <Card title="Locale profiles · what “sound local” means per region">
        <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
          {locales.map((l) => (
            <button key={l.locale} onClick={() => setEditing({ ...l })} className="rounded-lg border border-zinc-200 p-3 text-left text-sm hover:border-indigo-400 dark:border-zinc-800">
              <div className="font-medium">{l.variety} <span className="text-zinc-500">· {l.locale}</span></div>
              <div className="text-xs text-zinc-500">{l.formality} · {l.formats.date} · {l.formats.currency}{l.rtl ? " · RTL" : ""}</div>
            </button>
          ))}
        </div>
        {editing && (
          <div className="mt-4 space-y-3 rounded-lg border border-indigo-200 p-4 dark:border-indigo-900">
            <div className="font-medium">Editing {editing.variety} ({editing.locale})</div>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Greeting" hint="{name} is replaced with the contact's name; used when their gender is unknown"><input className={inputCls} value={editing.greeting} onChange={(e) => setEditing({ ...editing, greeting: e.target.value })} /></Field>
              <Field label="Sign-off"><input className={inputCls} value={editing.signoff} onChange={(e) => setEditing({ ...editing, signoff: e.target.value })} /></Field>
              <Field label="Greeting · female" hint="optional, for languages that inflect address"><input className={inputCls} value={editing.greetings?.female || ""} onChange={(e) => setVariant("greetings", "female", e.target.value)} /></Field>
              <Field label="Greeting · male"><input className={inputCls} value={editing.greetings?.male || ""} onChange={(e) => setVariant("greetings", "male", e.target.value)} /></Field>
              <Field label="Sign-off · female"><input className={inputCls} value={editing.signoffs?.female || ""} onChange={(e) => setVariant("signoffs", "female", e.target.value)} /></Field>
              <Field label="Sign-off · male"><input className={inputCls} value={editing.signoffs?.male || ""} onChange={(e) => setVariant("signoffs", "male", e.target.value)} /></Field>
              <Field label="Formality"><select className={inputCls} value={editing.formality} onChange={(e) => setEditing({ ...editing, formality: e.target.value })}>{["casual", "warm-formal", "formal"].map((f) => <option key={f}>{f}</option>)}</select></Field>
              <Field label="Numerals"><select className={inputCls} value={editing.formats.numerals} onChange={(e) => setEditing({ ...editing, formats: { ...editing.formats, numerals: e.target.value } })}>{["western", "eastern-arabic"].map((f) => <option key={f}>{f}</option>)}</select></Field>
            </div>
            <Field label="Notes for the editor and the critic" hint="Write 'avoid: x; y' to have the critic flag those"><textarea className={`${inputCls} min-h-20`} value={editing.notes} onChange={(e) => setEditing({ ...editing, notes: e.target.value })} /></Field>
            <div className="flex gap-2"><Button onClick={save}>Save</Button><Button kind="ghost" onClick={() => setEditing(null)}>Cancel</Button></div>
          </div>
        )}
      </Card>
    </div>
  );
}

export function KnowledgePage() {
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [title, setTitle] = useState(""); const [text, setText] = useState("");
  const load = () => api.knowledge().then(setItems);
  useEffect(() => { load(); }, []);
  const add = async (e: FormEvent) => { e.preventDefault(); await api.addKnowledge({ title, text }); setTitle(""); setText(""); load(); };
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
      <Card title="Knowledge · your facts, policies, FAQ">
        {items.length ? (
          <ul className="divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
            {items.map((k) => (
              <li key={k.id} className="flex items-center justify-between py-2"><span><b>{k.title}</b> <span className="text-zinc-500">· {k.size} chars</span></span><Button kind="danger" onClick={() => api.delKnowledge(k.id).then(load)}><Trash2 className="h-4 w-4" /></Button></li>
            ))}
          </ul>
        ) : <Empty>Nothing yet. Envoy only states facts it can find here, so add your policies, prices, and answers.</Empty>}
      </Card>
      <Card title="Add a document">
        <form onSubmit={add} className="space-y-3">
          <Field label="Title"><input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} required /></Field>
          <Field label="Text" hint="Separate topics with a blank line; each paragraph is cited on its own."><textarea className={`${inputCls} min-h-40`} value={text} onChange={(e) => setText(e.target.value)} required /></Field>
          <Button type="submit">Add</Button>
        </form>
      </Card>
    </div>
  );
}

export function HistoryPage() {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [open, setOpen] = useState<Result | null>(null);
  useEffect(() => { api.history().then(setItems); }, []);
  const tone = (s: string) => (s === "ready" ? "green" : s === "check" ? "amber" : "red");
  return (
    <div className="space-y-4">
      <Card title="History">
        {items.length ? (
          <ul className="divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
            {items.map((h) => (
              <li key={h.id} className="flex cursor-pointer items-center gap-3 py-2 hover:bg-zinc-50 dark:hover:bg-zinc-800/50" onClick={() => api.historyGet(h.id).then(setOpen)}>
                <Badge tone={tone(h.status)}>{h.status}</Badge>
                <Badge tone="indigo">{h.locale}</Badge>
                <span className="truncate">{h.message}</span>
                <span className="ml-auto shrink-0 text-xs text-zinc-500">{h.created_at.slice(0, 16).replace("T", " ")}</span>
              </li>
            ))}
          </ul>
        ) : <Empty>No replies yet.</Empty>}
      </Card>
      {open && <ResultView result={open} />}
    </div>
  );
}

export function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [check, setCheck] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [demo, setDemo] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => { api.settings().then(setS); api.models().then((m) => setModels(m.models)).catch(() => {}); }, []);
  if (!s) return null;
  const save = async () => { const out = await api.saveSettings(s); setS(out); setSaved(true); setTimeout(() => setSaved(false), 1500); };
  const doCheck = async () => {
    const saved = await api.saveSettings(s); setS(saved);
    const r = await api.checkSettings();
    setModels(r.models);
    setCheck(r.ok ? (r.has_model ? `Connected. Model available.${r.note ? " " + r.note : ""}` : `Endpoint reachable, but "${saved.model}" is not listed. Pick one below.`) : `Cannot reach the endpoint: ${r.error}`);
  };
  const loadDemo = async () => { const r = await api.loadDemo(); setDemo(r.knowledge ? `Loaded ${r.knowledge} documents, ${r.glossary} glossary terms, ${r.contacts} contacts.` : "Demo data is already loaded."); };
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Model">
        <div className="space-y-3">
          <Field label="Provider">
            <div className="flex flex-wrap gap-3 text-sm">
              <label className="flex items-center gap-2"><input type="radio" checked={s.provider === "cohere"} onChange={() => setS({ ...s, provider: "cohere" })} /> Cohere API (direct)</label>
              <label className="flex items-center gap-2"><input type="radio" checked={s.provider === "openai"} onChange={() => setS({ ...s, provider: "openai" })} /> Local or OpenAI-compatible (Ollama, LM Studio, vLLM)</label>
              <label className="flex items-center gap-2"><input type="radio" checked={s.provider === "stub"} onChange={() => setS({ ...s, provider: "stub" })} /> Stub (offline, deterministic)</label>
            </div>
          </Field>
          {s.provider !== "cohere" && (
            <Field label="Endpoint" hint="OpenAI-compatible base URL. Ollama: http://127.0.0.1:11434/v1"><input className={inputCls} value={s.endpoint} onChange={(e) => setS({ ...s, endpoint: e.target.value })} /></Field>
          )}
          <Field label="Model name" hint={models.length ? "Pick from what the endpoint offers, or type a name" : "Type a model name, then Check connection to list what the endpoint offers"}>
            {models.length ? (
              <select className={inputCls} value={models.includes(s.model) ? s.model : ""} onChange={(e) => setS({ ...s, model: e.target.value })} data-testid="model-select">
                {!models.includes(s.model) && <option value="">{s.model ? `${s.model} (not listed)` : "— choose —"}</option>}
                {models.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            ) : (
              <input className={inputCls} value={s.model} onChange={(e) => setS({ ...s, model: e.target.value })} />
            )}
          </Field>
          <Field label={s.provider === "cohere" ? "Cohere API key" : "API key (only for hosted endpoints)"}><input className={inputCls} type="password" value={s.api_key === "set" ? "" : s.api_key} placeholder={s.api_key === "set" ? "•••••••• (set)" : ""} onChange={(e) => setS({ ...s, api_key: e.target.value })} /></Field>
          <div className="flex items-center gap-2"><Button onClick={save}>{saved ? "Saved" : "Save"}</Button><Button kind="ghost" onClick={doCheck}>Check connection</Button></div>
          {check && <p className="text-sm text-zinc-600 dark:text-zinc-300" data-testid="check">{check}</p>}
        </div>
      </Card>
      <div className="space-y-4">
        <Card title="You">
          <div className="space-y-3">
            <Field label="Your name" hint="Used in sign-offs"><input className={inputCls} value={s.user_name} onChange={(e) => setS({ ...s, user_name: e.target.value })} /></Field>
            <Field label="Your language" hint="Glosses and back-translations are shown in this language"><select className={inputCls} value={s.user_language} onChange={(e) => setS({ ...s, user_language: e.target.value })}>{["en", "ar", "es", "pt", "fr", "de", "ja"].map((l) => <option key={l}>{l}</option>)}</select></Field>
            <Button onClick={save}>{saved ? "Saved" : "Save"}</Button>
          </div>
        </Card>
        <Card title="Demo data">
          <p className="mb-3 text-sm text-zinc-600 dark:text-zinc-300">Load a fabricated small store (glossary, policies, contacts) to try Envoy immediately.</p>
          <Button kind="ghost" onClick={loadDemo}>Load demo data</Button>
          {demo && <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300" data-testid="demo">{demo}</p>}
        </Card>
      </div>
    </div>
  );
}
