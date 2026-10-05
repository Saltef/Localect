# Localect — product build plan

Localect is a finished, easy-to-use product first. Every decision below is
optimized for one thing: someone installs it in three steps and uses it the
same day, and it works.

---

## 1. Principles

1. **Finished, not a demo.** Polished UI, sensible defaults, an onboarding
   flow, no config files to edit.
2. **Easy.** Three-step install. Runs on a laptop. No cloud account.
3. **Private.** Local models, local data. Nothing leaves the machine by default.
4. **Sounds local.** The output must read as native to the receiver, not
   translated. This is the feature users notice.
5. **Never wrong silently.** Whatever the Rewriter changes, the Critic checks.
   Humans always send.

---

## 2. What the user does

**Inbound (v1).**
1. Paste an incoming message (email, chat, DM). Later: connectors deliver it.
2. Localect detects the language and shows *what they said* in your language.
3. Localect drafts your reply in their language, grounded in your facts.
4. The Rewriter makes it read local to the receiver's region.
5. The Critic shows a back-translation next to the final text and inline flags.
6. You edit if you want, then **Copy** or **Send** (via a connector). Done.

**Outbound (v1.5).** Write one message; Localect produces a local-sounding version
for each target region, each Critic-checked.

**Setup (first launch, ~2 minutes).** Your name and role, your default
language, a glossary (brand terms, do-not-translate, preferred renderings), and
the regions you write to most. Everything editable later in Settings.

---

## 3. The agents

Five agents in a fixed pipeline. Each has one job and its own prompt.

- **Reader.** Detects the source language and region, produces a faithful gloss
  in the user's language, and a short structured read: intent, what is being
  asked, any deadline or number that must be preserved.
- **Drafter.** Writes the reply in the receiver's language using tools:
  glossary, facts/policy, past replies, the thread. Every factual claim is
  tagged to its source. It answers only from sources.
- **Rewriter (the local native editor).** Takes the draft and rewrites it to
  read as if written by a native of the receiver's locale. It adjusts:
  - **variety/dialect** (Gulf, Egyptian, Levantine Arabic; pt-BR vs pt-PT;
    es-MX vs es-ES; en-GB vs en-US),
  - **register and formality** norms for that culture and relationship,
  - **idiom and phrasing** so it stops sounding translated,
  - **greetings, sign-offs, and politeness conventions**,
  - **formats**: dates, numbers, currency, addresses,
  - **cultural adaptation**: what to soften, what to state directly.
  It is driven by a **locale profile** (Section 4). It must not change meaning,
  facts, glossary terms, or commitments; that is enforced by the Critic, not
  trusted to the Rewriter.
- **Critic.** Back-translates the Rewriter's output into the user's language,
  reads it as a skeptical native of the receiver's locale, and flags per
  segment: `drifted`, `tone_off`, `cultural_risk`, `off_glossary`,
  `unsupported_claim`, with the span and a one-line reason. Fail-closed: a
  flagged segment shows a warning until the user resolves it or Localect revises.
- **Arbiter.** Deterministic gate. Enforces: glossary terms exact; any number,
  date, or policy identical to the source; the Rewriter's output covers every
  point of the Drafter's. Sets status `ready`, `check`, or `escalate` and
  assembles the final message plus the side-by-side view.

The Rewriter–Critic loop is the core mechanic: one maximizes naturalness, the
other guarantees fidelity. If the Critic flags, the Rewriter gets one revision
pass with the flag as instruction, then the user decides.

---

## 4. Locale profiles

A locale profile is what makes "sound local" concrete and editable.

```
locale: ar-EG            # language-region
variety: Egyptian Arabic
formality: warm-formal   # default register for this relationship
greeting: "..."          # conventions, examples
signoff: "..."
formats: {date: DD/MM/YYYY, currency: EGP, numerals: eastern-arabic}
notes: "avoid X; prefer Y; humour lands differently"
```

Localect ships a starter set for common regions and infers a likely locale from
the incoming message. Users pick, correct, and refine per contact. Profiles are
plain, human-readable, and shareable; a community can contribute them.

---

## 5. Grounding and the glossary

The Drafter answers only from the user's own material via MCP tools:

- **glossary** — exact lookups: brand terms, do-not-translate, preferred
  renderings per language. The Arbiter treats this as law.
- **knowledge** — search over the user's facts, policies, FAQ (uploaded files).
- **history** — search past replies for voice and precedent. Precedent never
  overrides glossary or knowledge.
- **thread** — the current conversation.

Each result carries an id and exact text so a claim anchors to a source the
user can see on hover.

---

## 6. Models

**Default path (ease):** any local runtime that speaks the OpenAI-compatible
API: Ollama, LM Studio, llama.cpp server, vLLM. The user pulls a multilingual
model (Cohere's Aya family is the intended default for language work, with a
tool-capable model such as North for orchestration if they want it) and Localect
talks to it at `localhost`. One setting: the endpoint and model name.

**Adapters** behind one interface: `openai-compatible` (the default),
`stub` (deterministic, for development and CI, labelled as such), and an
optional hosted fallback the user must explicitly enable.

**Model roles:** Reader, Drafter, Rewriter, and Critic default to the same
multilingual model with different prompts; each role can be pointed at a
different model in Settings. Tool orchestration can use a separate tool-capable
model. This keeps single-model setups simple and lets power users split.

---

## 7. MCP

The tools in Section 5 are real MCP servers, shipped inside Localect and started
automatically, so users configure nothing. They read local files and the local
database. Because they are MCP, they are also the extension point: a
community-contributed Shopify, CRM, Slack, or email server plugs in without
changing the core. Connectors that *deliver* messages (email, chat) and *send*
staged replies arrive as MCP servers in a later milestone.

---

## 8. Application

- **Backend:** Python, FastAPI. Orchestrates the pipeline, hosts the MCP
  servers, serves the UI. SQLite for profile, glossary, locales, history.
- **Frontend:** React + Vite + Tailwind, built and bundled into the Python
  package, so `pipx install` is the whole install. Dark and light themes.
- **Screens:** Compose (paste in, pipeline stages as a clean vertical flow,
  side-by-side final text and back-translation with inline flags, Copy/Send),
  Contacts and Locales, Glossary, Knowledge (upload files), History, Settings.
- **Packaging:** `pipx install localect`; `localect` starts the server and opens
  the browser. Docker image. Later a native desktop wrapper for a true app feel.
- **Zero-config:** first launch runs the setup wizard; everything has defaults.

---

## 9. Quality bar (kept short, product-oriented)

Before release, Localect passes `localect eval --set heldout --perturb`: fresh
messages in every starter locale with known facts, contradictions, glossary
terms and injection attempts, plus planted faults the Critic and Arbiter must
catch. The Rewriter's output must read native to a human reviewer, measured
by a dialect-identifier ablation and a blind pairwise study. Method and
results live in docs/EVAL.md as a release checklist, not a research paper.

---

## 10. Milestones

1. **M1 — working end to end.** Pipeline on the stub, the four built-in MCP
   servers, SQLite, and the Compose screen. Paste a message, get the full
   side-by-side result. Runnable with one command.
2. **M2 — real models and the local feel.** Ollama adapter, Rewriter and
   Critic prompts tuned on real output, starter locale profiles, the
   Rewriter–Critic revision loop.
3. **M3 — finished product.** Setup wizard, Contacts/Locales, Glossary,
   Knowledge, History, Settings screens; packaging (pipx, Docker); docs and
   screenshots; the release checklist passes.
4. **M4 — reach.** Outbound one-to-many; email and chat MCP connectors with
   Send; desktop wrapper.

---

## 11. Decisions made (so we stop re-deciding)

- Product, not a study. Findings, if any, are a release checklist.
- Local web app now; desktop wrapper later.
- OpenAI-compatible local runtime is the default model path.
- One multilingual model by default; per-role override for power users.
- Rewriter is a first-class agent driven by editable locale profiles.
- Humans always send.
