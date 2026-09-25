# Architecture

Envoy turns a message in someone else's language into a reply that reads as
if a native of their region wrote it, and proves to the sender that nothing
was lost on the way. This document explains how the pieces fit, why they are
split the way they are, and how the system is measured. Product intent and
milestones live in [DESIGN.md](DESIGN.md); the evaluation method and the
numbers live in [EVAL.md](EVAL.md).

## 1. The system at a glance

```mermaid
flowchart LR
    subgraph Browser
        UI["React UI<br/>Compose · Memory · Glossary · Knowledge<br/>Contacts · History · Settings"]
        EXT["Extension<br/>side-panel Compose · capture on send<br/>(Gmail, Outlook, WhatsApp Web)"]
    end

    subgraph "envoy (one Python process)"
        API["FastAPI<br/>/api/compose, /api/settings, …"]
        PIPE["Pipeline<br/>Reader → Drafter → Rewriter → Critic → Arbiter"]
        CONV["Conventions<br/>greeting / sign-off enforcement"]
        MCPC["MCP client"]
        DB[("SQLite<br/>~/.envoy/envoy.db")]
        subgraph "MCP servers (stdio, started automatically)"
            G[glossary]
            K[knowledge]
            H[history]
            T[thread]
            ML[mail]
        end
    end

    subgraph "Model provider (one setting)"
        M1["Ollama / LM Studio / vLLM<br/>OpenAI-compatible, local"]
        M2["Cohere API<br/>Command A, Aya Expanse"]
        M3["Stub<br/>deterministic, offline"]
    end

    UI -->|JSON| API --> PIPE
    EXT -->|JSON + pairing token| API
    PIPE --> CONV
    PIPE --> MCPC --> G & K & H & T & ML --> DB
    API --> DB
    PIPE -->|chat completions| M1
    PIPE -->|chat completions| M2
    PIPE -->|chat completions| M3
```

Everything runs in one process on the user's machine. The only network call
is to the model endpoint they configured, and by default that is on
`localhost`. There is no account, no telemetry, and Envoy never sends a
message: the user copies the reply.

**Why one process, one SQLite file.** The product promise is a three-step
install and a private tool. A single `pipx install envoy-ai` ships the API,
the UI (pre-built into the package), the MCP servers, and the sample data.
Nothing to provision.

**Why MCP for the user's data.** The Drafter reaches the glossary, the
knowledge base, the user's past mail, past replies, and the current thread
through five [Model Context Protocol](https://modelcontextprotocol.io)
servers that Envoy starts over stdio. They are the extension point: an email, chat, or shop
connector is another MCP server, and the core never changes. In tests the
same interface (`Tools` in `tools.py`) is served in-process by
`DirectTools`, so the pipeline is tested without subprocesses.

**Why three model adapters behind one interface.** Every adapter exposes
`generate(messages, role, schema)`; the pipeline does not know which one it
has. `openai_compat` covers any local runtime, `cohere` talks to Cohere's
own chat API with structured output, and `stub` is a deterministic stand-in
that quotes the knowledge base. The stub is what CI runs, what a user sees
before they configure a model, and what keeps the eval harness testable.
Each agent role can be pointed at a different model (`role_models`), which
is also how the Critic is kept from judging its own author.

## 2. The pipeline

```mermaid
flowchart TB
    IN([Incoming message]) --> R

    R["<b>Reader</b><br/>language, region guess, faithful gloss,<br/>asks, must-preserve items, tone"]
    R --> LOC["Resolve locale<br/>explicit › contact › Reader's guess › language default"]
    LOC --> SRC["Gather sources via MCP<br/>glossary · knowledge · facts · past mail · history · thread"]
    SRC --> D

    D["<b>Drafter</b><br/>reply in their language,<br/>every claim tied to a source id"]
    D --> E1["enforce greeting / sign-off<br/>strip leaked source ids"]
    E1 --> RW

    RW["<b>Rewriter</b><br/>native editor for the locale profile:<br/>dialect, register, idiom, formats"]
    RW --> E2["polish: enforce conventions,<br/>strip leaked source ids"]
    E2 --> C

    C["<b>Critic</b> (may be a different model)<br/>back-translates, flags drifted · tone_off ·<br/>cultural_risk · off_glossary · unsupported_claim"]
    C --> QC["quiet_critic: drop flags aimed<br/>at the locale's own conventions"]
    QC --> A

    A["<b>Arbiter</b> (deterministic)<br/>dropped segments · must-preserve items ·<br/>glossary law · number drift · unsourced claims ·<br/>facts that disagree · echoed instructions · cut-off text"]
    A -->|blocking flags, first pass| RW2["Rewriter, one revision<br/>with the flags as instructions"]
    RW2 --> C
    A -->|"ready · check · escalate"| OUT([Result: final text, back-translation,<br/>per-segment ledger, flags, status])
```

Five agents in the reply path, one job each, one prompt each (`prompts/*.md`), plus an Extractor that reads stored mail into dated facts outside the reply path (see [MEMORY.md](MEMORY.md)). Every stage
returns a typed JSON object (`schemas.py`); `agents/stage.py` renders the
prompt, validates the reply against the Pydantic schema, and retries once
with the validation error, or with a specific correction when the model
echoed the schema instead of filling it in.

### The Rewriter–Critic loop

This is the core mechanic. The Rewriter is pushed towards naturalness and
told to make the reply sound like a local; the Critic is a skeptical native
of the same locale who reads the result, back-translates it into the user's
language, and reports per segment what changed in meaning. They are
adversaries by construction. If the Critic or the Arbiter raises a blocking
flag on the first pass, the Rewriter gets exactly one revision with those
flags as its instructions, and then the human decides. There is no second
loop: a reply that cannot be fixed in one pass is escalated, not polished
until it looks fine.

### Three layers of verification

| Layer | Who | Catches | Can it be wrong? |
|---|---|---|---|
| Conventions (`conventions.py`) | code, applied after every stage | improvised greetings and sign-offs, leaked `[kb:…]` ids | no: the locale profile is the user's setting, models cannot override it |
| Critic (`agents/critic.py`) | a model, ideally not the Drafter's | meaning drift, tone, cultural risk, register, unsupported claims | yes: measured by planted faults and false alarms |
| Arbiter (`agents/arbiter.py`) | code | dropped segments, missing must-preserve items, numbers added or lost in any digit script, glossary violations, claims without a source, a reply citing a fact that a newer fact contradicts, a phrase the message quoted and the reply repeated, a segment that ends mid-sentence | no: it is a checklist |

The split matters for the evaluation: anything code enforces is reported as
an invariant, not counted as a pass, so the model's score is the model's.

### Locale resolution

An explicit locale on the request wins, then the contact's configured
locale, then the Reader's regional guess when it names a configured profile
(normalised: `ar_eg`, `AR-EG` → `ar-EG`), then the language's default
region (`ar-EG`, `en-US`, `es-MX`, `pt-BR`, chosen by speaker population),
then any profile for the language. Twelve profiles ship as YAML and are
editable in the UI; a profile is greeting, sign-off (with gendered variants
where the language inflects address), formality, formats, and notes for the
Rewriter.

### Prompt injection

The incoming message is untrusted. The Drafter may only make claims it can
tie to a source id; the Arbiter blocks any claim without one; the Critic
flags unsupported claims from the back-translation; and the evaluation ships
140 injection samples (20 attacks × 7 languages, each paired with a real
question that must still be answered). The design accepts that a model can
be talked into anything and makes the pipeline refuse to *ground* it.

## 3. Data

```mermaid
erDiagram
    contacts }o--|| locales : "writes in"
    contacts ||--o{ history : "thread"
    locales {
        text locale PK
        text profile "LocaleProfile as JSON"
        text origin "starter | user"
    }
    contacts {
        text id PK
        text name
        text locale FK
        text gender "unknown | female | male"
        text notes
    }
    glossary {
        text id PK
        text term
        text language "or * for all"
        text rendering "preferred rendering"
        int do_not_translate
    }
    knowledge {
        text id PK
        text title
        text text "searched by the knowledge server"
    }
    messages ||--o{ facts : "extracted from"
    facts {
        text id PK
        text topic "short English key"
        text topic_key "alias-folded, comparable"
        text statement
        text value
        text said_on
        text said_by "you | them"
        text party "the other address"
        text status "auto | confirmed | rejected"
    }
    messages {
        text id PK
        text external_id "Message-ID, unique"
        text thread_id
        text date "UTC"
        text from_addr
        text to_addrs
        text subject
        text text "author's own words, quotes and signature removed"
        int is_mine
        text language
        text origin "import | capture"
    }
    history {
        text id PK
        text created_at
        text message
        text locale
        text status "ready | check | escalate"
        text final_text
        text result "the whole Result as JSON, replayable"
        text contact_id FK
    }
```

Every composed `Result` is stored whole, so History can replay the
side-by-side view, and the eval harness can hand any past result to the
perturbation step without recomposing it.

## 4. How Envoy is measured

The evaluation is built so a pass or a fail needs no human, no prompt was
tuned on the samples that count, and every number in `docs/EVAL.md` comes
with the count it was computed from.

```mermaid
flowchart LR
    subgraph "Sample sets (YAML, shipped in the package)"
        DEMO["demo · 7<br/>prompts were tuned here"]
        HELD["held-out · 63<br/>never tuned on"]
        INJ["injection · 140<br/>20 attacks × 7 languages"]
    end

    DEMO & HELD & INJ --> RUN["envoy eval<br/>compose() on the chosen model"]
    RUN --> SCORE["score()<br/>locale · preserved · fact · no_wrong ·<br/>terms · no_leaks · no_forbidden · verified"]
    RUN --> INV["invariants<br/>greeting · sign-off (code-enforced, not counted)"]
    RUN --> ABL["dialect ablation<br/>Drafter body vs Rewriter body,<br/>judged by a dialect identifier"]
    RUN --> PERT["--perturb: plant six faults in every reply<br/>drop_preserved · change_number · wrong_greeting ·<br/>add_promise · leak_citation · slang"]
    PERT --> VER["Critic + Arbiter again"]
    VER --> ATTR["attribution: caught by Critic,<br/>Arbiter, or neutralized by code ·<br/>false alarms on untouched runs"]

    subgraph "Components alone"
        MASSIVE["envoy bench massive<br/>Reader: language accuracy, slot recall<br/>(MASSIVE 1.1)"]
        FLORES["envoy bench flores<br/>Critic: chrF of its back-translation<br/>(FLORES-200)"]
    end

    subgraph "Humans"
        STUDY["envoy study export / score<br/>blind pairwise sheets per locale,<br/>vote share with bootstrap CI,<br/>Krippendorff's α, Cohen's κ"]
    end

    SCORE & INV & ABL & ATTR --> JSON[("eval JSON<br/>written after every sample")]
    MASSIVE & FLORES & STUDY --> JSON
    JSON --> REPORT["envoy report → markdown<br/>counts next to every percentage"]
    JSON --> CI["CI gate on the stub:<br/>held-out + perturb + injection must pass"]
```

**What each part answers.**

- **Checks** answer "is the reply correct?": right locale, every fact the
  sample demands present (numbers match as whole tokens in Western, Eastern
  Arabic, or full-width digits), nothing that contradicts the knowledge
  base, glossary terms intact, no leaked source ids, no forbidden promise on
  an injection sample, no stage failure.
- **Perturbations** answer "would the verifier notice?": each finished reply
  is corrupted in six known ways and sent back through the Critic and the
  Arbiter. The report attributes each catch to the layer that made it and
  counts false alarms on untouched, passing replies. A fault that code
  removed before any judge saw it is *neutralized*, which is evidence about
  the pipeline, not about the Critic.
- **The dialect ablation** answers "does the Rewriter make it local?": an
  external dialect identifier (CAMeL Tools MADAR-26 for Arabic; a shipped
  character n-gram classifier trained on DSLCC for Portuguese and Spanish)
  classifies the Drafter's body and the Rewriter's body. The gap is the
  Rewriter's work. Greeting and sign-off are excluded because code wrote
  them.
- **Benches** isolate one agent against a public dataset: the Reader on
  MASSIVE (language id and slot recall), the Critic on FLORES-200
  (back-translation quality, which bounds how much its judgements can be
  trusted).
- **The human study** is the only judge of "sounds native": native readers
  see draft and final in random order, blind to condition, and the score
  reports preference with confidence intervals and inter-rater agreement.

**Rules the harness enforces on its authors.** One prompt tuned on the
held-out set invalidates it, so a sample that ever needs a look is moved to
the demo set and the move is recorded in `EVAL.md`. Real models and datasets
run on a machine that can reach them; the container that writes the code
cannot, so nothing in the docs is a number the code did not produce.
Negative results stay in the document.

## 5. Code map

```
src/envoy/
  pipeline.py       compose(): the flow above, locale resolution, one revision loop
  agents/           reader, drafter, rewriter, critic, extractor (model-driven); arbiter (code);
                    stage.py runs one prompt → schema round trip with retry
  prompts/          one versioned prompt per agent
  schemas.py        Reading, Draft, Rewrite, Critique, Flag, Result: the contracts
  conventions.py    greeting / sign-off enforcement, gender forms, quiet_critic
  text.py           tokenizer, digit-script normalisation, cross-lingual aliases
  models/           base (interface, FakeModel), openai_compat, cohere, stub
  mcp/              client (spawns and calls the servers); servers/ glossary,
                    knowledge, history, thread, mail
  memory/           past mail and documents: parse (mbox, .eml), clean (quotes,
                    signatures, HTML), importer, embed, index, search, facts; see MEMORY.md
  tools.py          the Tools interface; DirectTools for in-process use
  locales/          twelve locale profiles (YAML), seeded into SQLite
  db.py             SQLite schema and migrations
  app.py            FastAPI routes; serves the built UI from static/
  cli.py            serve · check · config · demo · eval · bench · dialect · study · report
  eval.py           envoy eval: sets, checks, invariants, ablation, perturbations, JSON
  perturb.py        the six faults and their attribution
  evalset/          demo.yaml, heldout.yaml, injection.yaml and the Sample model
  evalx/            dialect judges, MASSIVE and FLORES loaders and scorers
  study.py          human study export and scoring
  report.py         markdown report from any of the JSON files
ui/                 React + Vite + Tailwind, built into src/envoy/static
tests/              unit · agents · mcp (over stdio) · pipeline · api · e2e (Playwright)
```

## 6. Decisions and trade-offs

- **A native Rewriter instead of a better translation prompt.** Users notice
  "sounds translated" more than any other defect. Making locality a separate
  stage with an editable profile means a user can fix a region's voice
  without touching prompts, and the ablation can measure the stage alone.
- **Conventions in code, not in prompts.** Models improvise greetings.
  Enforcing the user's own greeting and sign-off after every stage removed
  a whole class of flags, and stopped the Critic from arguing with the
  user's settings. The cost is a rule that must understand every script;
  the first real run found it counted whitespace tokens and swallowed
  Japanese replies, which is now measured in characters.
- **One revision, then a human.** A second loop hides problems; a status of
  `escalate` shows them.
- **Deterministic stub in the package.** It lets the product run with no
  setup, lets CI gate on the full harness, and gives every eval feature a
  test. Its numbers say nothing about a model, and the docs say so.
- **The Critic on a different model.** `--critic-model` and `role_models`
  exist because a model grading its own output is the weakest judge. The
  perturbation harness is how that choice is checked rather than assumed.
- **Structured output with a fallback ladder.** The Cohere adapter sends the
  JSON schema as `response_format`, falls back to JSON mode and then to
  free text on a 400, and remembers per model. Smaller models echo schemas;
  the stage runner names that failure and asks for an instance.
