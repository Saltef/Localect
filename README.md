<div align="center">

# Envoy

**Reply to anyone in their language, and sound like a local.**

Private. Runs on your machine. You always press send.

[![CI](https://github.com/Saltef/Envoy/actions/workflows/ci.yml/badge.svg)](https://github.com/Saltef/Envoy/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/envoy-ai)](https://pypi.org/project/envoy-ai/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[Quick start](#quick-start) · [How it works](#how-it-works) · [Evaluation](#evaluation) · [Architecture](docs/ARCHITECTURE.md) · [Results](docs/EVAL.md)

</div>

---

Paste a message someone sent you in any language. Envoy tells you what it
says, drafts a reply in their language grounded in your own facts, has a
native editor rewrite it so it reads local to their region, and has a critic
back-translate the result so you can see nothing was lost before you send.

![Envoy composing a Levantine Arabic reply with a side-by-side back-translation](docs/screenshots/compose.png)

## Why Envoy

Machine translation gives you a correct sentence that sounds translated.
Envoy treats "sounds local" as its own problem, with its own agent, its own
editable locale profiles, and its own measurement. And because a fluent
rewrite is exactly where meaning slips, every reply is checked by a Critic on
a second read and by deterministic code before you see it.

- **Understand any message.** A faithful gloss in your own language, plus
  what is being asked and what a reply must preserve.
- **A grounded reply.** Every fact, price, or policy comes from your glossary,
  knowledge base, and past replies, reached through built-in
  [MCP](https://modelcontextprotocol.io) servers. Each claim is shown next to
  its source. If the answer is not in your material, the reply says it will
  confirm rather than guess.
- **Sounds local, not translated.** A Rewriter edits for the receiver's
  region: Egyptian, Gulf, or Levantine Arabic; Brazilian or European
  Portuguese; Mexican or Castilian Spanish; British or American English;
  French, German, Japanese. Register, idiom, greetings and sign-offs
  (gendered where the language inflects), and date, number, and currency
  formats. Twelve editable profiles ship in the box.
- **Nothing lost.** A Critic back-translates the final text and flags meaning
  drift, off tone, cultural risk, broken glossary terms, and unsupported
  claims. A deterministic Arbiter re-checks what a model must never get
  wrong: numbers and ids in any digit script, do-not-translate terms,
  dropped segments.
- **Drafts from what you actually said.** Import your past mail and Envoy
  reads it into dated facts you can review, cites them with who said what
  when, warns when two of them disagree, writes in your own voice, and keeps
  out any thread or person you exclude. See [docs/MEMORY.md](docs/MEMORY.md).
- **Measured, not claimed.** A held-out set no prompt was tuned on, planted
  faults the verifier must catch, an injection set, a dialect-identifier
  ablation, public-benchmark checks on single agents, and a blind human
  study. Numbers and negative results are in [docs/EVAL.md](docs/EVAL.md).
- **Yours, online too.** Host it behind HTTPS with an owner login and,
  if you like, a public demo that runs on sample data and never sees your
  mail. See [docs/HOSTING.md](docs/HOSTING.md).
- **You send.** Envoy never sends anything. You copy the reply.

## Quick start

```bash
pipx install envoy-ai      # or: uv tool install envoy-ai
envoy                      # opens http://127.0.0.1:8765
```

Until you point it at a model, Envoy runs in **stub mode**: a deterministic
stand-in, labelled as such, that exercises the whole pipeline offline. Load
the demo data from **Settings** to try it immediately. Then pick a model:

<table>
<tr><th>Local, private (recommended)</th><th>Cohere's API</th></tr>
<tr><td>

```bash
ollama pull aya-expanse:8b
envoy config --provider openai \
  --endpoint http://127.0.0.1:11434/v1 \
  --model aya-expanse:8b
envoy check
```

Any OpenAI-compatible server works: Ollama, LM Studio, llama.cpp, vLLM.

</td><td>

```bash
envoy config --provider cohere \
  --model command-a-03-2025 \
  --api-key "YOUR_KEY"
envoy check
```

Uses Cohere's own chat API with structured output; the key is stored in
`~/.envoy/settings.json`, never shown again.

</td></tr>
</table>

Give it your past writing, so replies say what you have already told people:

```bash
envoy config --user-email you@example.com
envoy import ~/Takeout/Mail/All\ mail.mbox      # or a folder of .eml files, or .md/.txt/.pdf
```

Reply from Gmail, Outlook or WhatsApp Web, and let Envoy remember what you
send: load the `extension/` folder as an unpacked extension and pair it with
the token from Settings. See [docs/EXTENSION.md](docs/EXTENSION.md).

Prefer a container, or want it online?

```bash
docker build -t envoy .
docker run -p 8765:8765 -v envoy-data:/data envoy   # talks to Ollama on the host

cp .env.example .env && docker compose up -d --build  # hosted: HTTPS via Caddy, owner login,
                                                     # optional public demo; see docs/HOSTING.md
```

Once **Check connection** succeeds, the model field becomes a dropdown of
what your key or server offers, and Compose gets its own model picker so you
can compare models on the same message. Each agent role can run on a
different model (`role_models` in settings), which is also how the Critic is
kept from grading its own author.

## How it works

```mermaid
flowchart LR
    IN([message]) --> R[Reader] --> D[Drafter] --> RW[Rewriter] --> C[Critic] --> A[Arbiter] --> OUT([you send])
    MCP[("your glossary, knowledge,<br/>past mail, history, thread<br/>(MCP servers)")] -.-> D
    A -. "blocking flag:<br/>one revision" .-> RW
```

| Agent | Job | Guarantee |
|---|---|---|
| **Reader** | Language, region, a faithful gloss in your language, the asks, what must be preserved | you understand the message before replying |
| **Drafter** | A reply in their language, each claim tied to a source id from the MCP tools | nothing invented |
| **Rewriter** | A native editor for the receiver's locale profile: dialect, register, idiom, conventions, formats | sounds local |
| **Critic** | Back-translates the rewrite and flags drift, tone, cultural risk, glossary, unsupported claims | nothing lost, visibly |
| **Arbiter** | Deterministic checks: dropped segments, must-preserve items, number drift, glossary law, unsourced claims; decides *ready*, *check*, or *escalate* | the things a model must never get wrong |

The Rewriter is pushed towards naturalness and the Critic guarantees
fidelity; they are adversaries by construction. A blocking flag earns the
Rewriter exactly one revision with the flag as its instruction, then you
decide. Greetings and sign-offs are your setting, enforced in code after
every stage, so no model can improvise them away.

The full design, with diagrams of the system, the pipeline, the data, and the
evaluation, is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

![Dark mode, with an injection attempt in the incoming message that produced no commitment](docs/screenshots/compose-dark.png)

## Evaluation

Every check is deterministic and needs no human. Every number comes with the
count it was computed from. No prompt was ever tuned on the set that counts.

```bash
envoy eval --set heldout --perturb          # 63 never-tuned-on samples + six planted faults each
envoy eval --set injection                  # 20 attacks × 7 languages, each paired with a real question
envoy eval --set heldout --models command-a-03-2025,c4ai-aya-expanse-32b --out compare.json
envoy eval --set heldout --critic-model command-a-03-2025      # judge with a different model
envoy bench massive --data <MASSIVE dir>    # the Reader alone: language accuracy, slot recall
envoy bench flores --data <FLORES-200 dir>  # the Critic alone: chrF of its back-translation
envoy bench memory                          # memory: right message found, newest fact used, conflicts flagged
envoy study export --from heldout.json --out study/            # blind pairwise sheets
envoy study score --sheets study/           # preference with CIs, Krippendorff's α, Cohen's κ
envoy report *.json --out report.md         # one markdown report from any of the above
```

| Question | How it is answered |
|---|---|
| Is the reply correct? | Eight checks per sample: locale, preserved items, required facts (numbers match as whole tokens in any digit script), no contradiction of the knowledge base, glossary terms, no leaked source ids, no forbidden promise, no stage failure |
| Would the verifier notice a mistake? | `--perturb` plants six faults into every finished reply and reports which layer caught each, plus false alarms on untouched runs |
| Does the Rewriter make it local? | A dialect identifier (CAMeL Tools for Arabic, a shipped n-gram classifier for Portuguese and Spanish) classifies the Drafter's body and the Rewriter's body; the gap is the Rewriter's work |
| How good is each agent alone? | The Reader on MASSIVE, the Critic's back-translation on FLORES-200 |
| Does it sound native? | A blind pairwise study with native readers, scored with confidence intervals and inter-rater agreement |
| Can it be tricked? | 140 injection samples; the Drafter cannot ground a claim the sources do not support, and the Arbiter blocks unsourced claims |
| Does memory find the right thing? | A fixture mailbox with facts that change over time, in seven languages: retrieval recall with and without embeddings, newest-fact and stale-fact rates, and whether disagreeing facts were flagged |

CI runs the held-out set with perturbations and the injection set on the
stub on every push and fails the build on any regression. Real-model results,
including the first run's harness faults and what they changed, are in
[docs/EVAL.md](docs/EVAL.md).

## Privacy

Everything runs locally: the model, the database, the glossary, the history.
The only network call Envoy makes is to the model endpoint you configure,
which by default is on your own machine. There is no account and no
telemetry.

## Project structure

```
src/envoy/
  pipeline.py     compose(): Reader → Drafter → Rewriter → Critic → Arbiter, one revision loop
  agents/         reader, drafter, rewriter, critic, extractor (model-driven); arbiter (code)
  prompts/        one versioned prompt per agent
  schemas.py      typed contracts for every agent and the Result
  conventions.py  greeting / sign-off enforcement, gender forms
  models/         openai_compat (Ollama, LM Studio, vLLM), cohere, stub, fake (tests)
  mcp/            client + servers: glossary, knowledge, history, thread, mail
  memory/         past mail: import, embeddings, hybrid search, extracted facts
  locales/        twelve starter locale profiles (YAML)
  eval.py, perturb.py, evalset/, evalx/, study.py, report.py   the evaluation
  db.py, app.py, cli.py, demo.py
ui/               React + Vite + Tailwind, built into src/envoy/static
extension/        Chrome/Edge extension: side-panel Compose, capture on send (no build step)
tests/            unit · agents · mcp · pipeline · api · e2e
docs/             ARCHITECTURE.md · EVAL.md · MEMORY.md · EXTENSION.md · HOSTING.md · DESIGN.md · RUBRIC.md
```

## Development

```bash
pip install -e ".[dev]"
ruff check src tests
pytest -q --ignore=tests/e2e     # unit, agents, MCP over stdio, pipeline, API
cd ui && npm ci && npm run build # bundles the UI into src/envoy/static (committed)
playwright install chromium
pytest -q tests/e2e              # boots the real server and drives the UI in Chromium
```

One pull request per change, version bumped per release, UTF-8 everywhere.
The evaluation has its own rules, in [docs/EVAL.md](docs/EVAL.md): never
tune a prompt on the held-out set, never write a number the code did not
produce, keep the negative results.

## Roadmap

- **Now:** inbound replies with Rewriter and Critic, local web app,
  one-command install, twelve locales, MCP-backed grounding, the evaluation.
- **Next:** results tables filled from real-model runs; outbound, one message
  localized to many regions with the same Critic; more locales.
- **Later:** email and chat connectors as MCP servers with a Send action, a
  native desktop wrapper, community-contributed locale profiles.

## License

[MIT](LICENSE)
