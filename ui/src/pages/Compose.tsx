import { useEffect, useState } from "react";
import { Loader2, Send, Sparkles } from "lucide-react";
import { api, type Contact, type LocaleProfile, type Result, type Sample } from "../api";
import ResultView from "../components/ResultView";
import { Button, Card, Field, inputCls } from "../components/ui";

const STAGES = ["Reader", "Drafter", "Rewriter", "Critic", "Arbiter"];

export default function Compose() {
  const [message, setMessage] = useState("");
  const [locale, setLocale] = useState("");
  const [contact, setContact] = useState("");
  const [locales, setLocales] = useState<LocaleProfile[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState(0);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    api.locales().then(setLocales).catch(() => {});
    api.contacts().then(setContacts).catch(() => {});
    api.samples().then(setSamples).catch(() => {});
    api.models().then((m) => { setModels(m.models); setModel(m.current); }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!busy) return;
    setStage(0);
    const t = setInterval(() => setStage((s) => Math.min(s + 1, STAGES.length - 1)), 500);
    return () => clearInterval(t);
  }, [busy]);

  const run = async () => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const r = await api.compose(message, locale, contact, models.length ? model : undefined);
      window.dispatchEvent(new Event("envoy:composed"));
      setResult(r.result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <Field label="Paste the message you received">
          <textarea
            data-testid="message"
            className={`${inputCls} min-h-32 resize-y text-[15px] leading-relaxed`}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Any language. Envoy will tell you what it says, draft a reply in their language, make it sound local, and check nothing was lost."
          />
        </Field>
        <div className={`mt-3 grid gap-3 md:items-end ${models.length ? "md:grid-cols-[1fr_1fr_1fr_1fr_auto]" : "md:grid-cols-[1fr_1fr_1fr_auto]"}`}>
          <Field label="Contact (optional)">
            <select className={inputCls} value={contact} onChange={(e) => setContact(e.target.value)}>
              <option value="">— none —</option>
              {contacts.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.locale}</option>)}
            </select>
          </Field>
          <Field label="Reply locale">
            <select className={inputCls} value={locale} onChange={(e) => setLocale(e.target.value)} data-testid="locale">
              <option value="">Auto-detect from the message</option>
              {locales.map((l) => <option key={l.locale} value={l.locale}>{l.variety} ({l.locale})</option>)}
            </select>
          </Field>
          <Field label="Try an example">
            <select className={inputCls} value="" onChange={(e) => { const s = samples.find((x) => x.label === e.target.value); if (s) setMessage(s.text); }} data-testid="samples">
              <option value="">— pick one —</option>
              {samples.map((s) => <option key={s.label} value={s.label}>{s.label}</option>)}
            </select>
          </Field>
          {models.length > 0 && (
            <Field label="Model">
              <select className={inputCls} value={model} onChange={(e) => setModel(e.target.value)} data-testid="model">
                {models.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </Field>
          )}
          <Button onClick={run} disabled={busy || !message.trim()} className="h-[38px]">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            Compose reply
          </Button>
        </div>
      </Card>

      {busy && (
        <ol className="flex flex-wrap items-center gap-2 text-sm" data-testid="stages">
          {STAGES.map((s, i) => (
            <li key={s} className={`rounded-full px-3 py-1 ${i <= stage ? "bg-indigo-600 text-white" : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800"}`}>{s}</li>
          ))}
        </ol>
      )}

      {error && <p className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">{error}</p>}

      {result && <ResultView result={result} />}

      {!result && !busy && (
        <p className="flex items-center gap-2 text-sm text-zinc-500"><Send className="h-4 w-4" /> Envoy never sends anything. You copy the reply and send it yourself.</p>
      )}
    </div>
  );
}
