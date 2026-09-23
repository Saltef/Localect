export type Flag = {
  segment_id: string;
  kind: string;
  span: string;
  reason: string;
  severity: "warn" | "block";
};
export type LedgerEntry = {
  segment_id: string;
  draft_text: string;
  final_text: string;
  back_translation: string;
  source_ids: string[];
  flags: Flag[];
};
export type Source = { id: string; kind: string; text: string; meta: Record<string, unknown> };
export type LocaleProfile = {
  locale: string;
  language: string;
  language_name: string;
  region_name: string;
  variety: string;
  formality: string;
  greeting: string;
  signoff: string;
  formats: { date: string; currency: string; numerals: string };
  notes: string;
  rtl: boolean;
};
export type Result = {
  id: string;
  created_at: string;
  message: string;
  locale: LocaleProfile;
  reading: {
    language: string;
    language_name: string;
    region_guess: string | null;
    gloss: string;
    intent: string;
    asks: string[];
    must_preserve: string[];
    tone: string;
  };
  sources: Source[];
  rewrite: { changes: { segment_id: string; kind: string; note: string }[] };
  final_text: string;
  back_translation: string;
  status: "ready" | "check" | "escalate";
  flags: Flag[];
  ledger: LedgerEntry[];
  revisions: number;
  stage_errors: string[];
  model: string;
};
export type Settings = {
  provider: "stub" | "openai" | "cohere";
  endpoint: string;
  model: string;
  api_key: string;
  user_name: string;
  user_language: string;
};
export type Health = { ok: boolean; version: string; provider: string; model: string; mcp: boolean };
export type GlossaryItem = {
  id: string;
  term: string;
  language: string;
  rendering: string;
  do_not_translate: number;
  notes: string;
};
export type Contact = { id: string; name: string; locale: string; notes: string };
export type KnowledgeItem = { id: string; title: string; size: number };
export type HistoryItem = {
  id: string;
  created_at: string;
  message: string;
  locale: string;
  status: string;
  final_text: string;
};
export type Sample = { label: string; text: string };

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return r.json() as Promise<T>;
}

export const api = {
  health: () => req<Health>("GET", "/api/health"),
  settings: () => req<Settings>("GET", "/api/settings"),
  saveSettings: (p: Partial<Settings>) => req<Settings>("PUT", "/api/settings", p),
  checkSettings: () =>
    req<{ ok: boolean; models: string[]; has_model: boolean; error?: string; note?: string }>(
      "GET",
      "/api/settings/check"
    ),
  compose: (message: string, locale?: string, contact_id?: string, model?: string) =>
    req<{ result: Result }>("POST", "/api/compose", {
      message,
      locale: locale || null,
      contact_id: contact_id || null,
      model: model || null,
    }),
  models: () => req<{ models: string[]; current: string; note?: string }>("GET", "/api/models"),
  glossary: () => req<GlossaryItem[]>("GET", "/api/glossary"),
  addGlossary: (g: Omit<GlossaryItem, "id" | "do_not_translate"> & { do_not_translate: boolean }) =>
    req<{ id: string }>("POST", "/api/glossary", g),
  delGlossary: (id: string) => req<{ ok: boolean }>("DELETE", `/api/glossary/${id}`),
  locales: () => req<LocaleProfile[]>("GET", "/api/locales"),
  saveLocale: (p: LocaleProfile) => req<LocaleProfile>("PUT", `/api/locales/${p.locale}`, p),
  contacts: () => req<Contact[]>("GET", "/api/contacts"),
  addContact: (c: Omit<Contact, "id">) => req<{ id: string }>("POST", "/api/contacts", c),
  delContact: (id: string) => req<{ ok: boolean }>("DELETE", `/api/contacts/${id}`),
  knowledge: () => req<KnowledgeItem[]>("GET", "/api/knowledge"),
  addKnowledge: (k: { title: string; text: string }) =>
    req<{ id: string }>("POST", "/api/knowledge", k),
  delKnowledge: (id: string) => req<{ ok: boolean }>("DELETE", `/api/knowledge/${id}`),
  history: () => req<HistoryItem[]>("GET", "/api/history"),
  historyGet: (id: string) => req<Result>("GET", `/api/history/${id}`),
  loadDemo: () => req<{ glossary: number; knowledge: number; contacts: number }>("POST", "/api/demo"),
  samples: () => req<Sample[]>("GET", "/api/demo/messages"),
};
