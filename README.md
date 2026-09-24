# Envoy

**Reply to anyone in their language, and sound like a local.**
Private. Runs on your machine. You always press send.

Paste a message someone sent you in any language. Envoy tells you what it
says, drafts a reply in their language grounded in your own facts, has a
native editor rewrite it so it reads local to their region, and has a critic
back-translate the result so you can see nothing was lost before you send.

![Envoy composing a Levantine Arabic reply with a side-by-side back-translation](docs/screenshots/compose.png)

## What you get

- **Understand any message.** A faithful gloss in your own language.
- **A grounded reply.** Every fact, price, or policy comes from your knowledge
  base and glossary, and each claim is shown next to its source. Nothing is
  invented; if the answer is not in your materials, the reply says it will
  confirm rather than guess.
- **Sounds local, not translated.** A Rewriter edits for the receiver's region
  and dialect (Egyptian, Gulf, or Levantine Arabic; Brazilian or European
  Portuguese; Mexican or Castilian Spanish, and more), formality, idiom,
  greetings and sign-offs, and date, number, and currency formats. Twelve
  editable locale profiles ship out of the box.
- **Nothing lost.** A Critic back-translates the final text and flags meaning
  drift, off tone, cultural risks, broken glossary terms, and unsupported
  claims. A deterministic Arbiter re-checks the things a model must never get
  wrong: preserved numbers and ids, do-not-translate terms, dropped segments.
- **You send.** Envoy never sends anything. You copy the reply.

## Install (three steps)

1. Install [Ollama](https://ollama.com) and pull a multilingual model, for
   example a Cohere Aya model:
   ```bash
   ollama pull aya-expanse:8b
   ```
2. Install Envoy (from the repository until the first PyPI release):
   ```bash
   pipx install git+https://github.com/Saltef/Envoy   # or: uv tool install git+https://github.com/Saltef/Envoy
   ```
3. Run it:
   ```bash
   envoy
   ```
   It opens `http://127.0.0.1:8765`. Go to **Settings**, choose *Local model*,
   set the model name you pulled, and click **Check connection**. Load the
   demo data from the same screen to try it immediately.

Until you point it at a model, Envoy runs in **stub mode**: a deterministic
stand-in that exercises the whole pipeline offline. It is labelled as such in
the sidebar. It is not a language model and its replies are not translations;
it exists so the product works with no setup, in CI, and in places where
weights cannot be downloaded.

Prefer a container?

```bash
docker build -t envoy .
docker run -p 8765:8765 -v envoy-data:/data envoy   # talks to Ollama on the host
```

## How it works

```
message in  ──►  Reader    what they said, in your language, plus what must be preserved
                 Drafter   a reply in their language, each claim tied to a source (via MCP tools)
                 Rewriter  a native editor for their region: dialect, register, idiom, formats
                 Critic    back-translates and flags drift, tone, culture, glossary, claims
                 Arbiter   deterministic checks; keep, revise once, or escalate; you send
```

Each stage is a separate agent with its own prompt. The Rewriter pushes for
naturalness; the Critic guarantees fidelity; if the Critic finds a blocking
problem the Rewriter gets one revision pass with the flag as its instruction,
then you decide. The Drafter reaches your data through four built-in
[MCP](https://modelcontextprotocol.io) servers (glossary, knowledge, history,
thread) that start automatically, which is also how Envoy will grow
connectors for email, chat, and shops without touching the core.

![Dark mode, with an injection attempt in the incoming message that produced no commitment](docs/screenshots/compose-dark.png)

## Using a real model

Two providers, configured from **Settings** or the shell.

**Cohere's API directly** (recommended if you have a Cohere key; uses Cohere's
own chat API and model list):

```bash
envoy config --provider cohere --model command-a-03-2025 --api-key "YOUR_KEY"
envoy check      # verifies the key and lists the chat models it can use
envoy demo       # loads demo data and runs one sample message in the terminal
```

**Any OpenAI-compatible server**: Ollama, LM Studio, llama.cpp server, vLLM,
or a hosted endpoint:

```bash
envoy config --provider openai --endpoint http://127.0.0.1:11434/v1 --model aya-expanse:8b
envoy check
```

In the app, once **Check connection** succeeds the model field becomes a
dropdown of what your key or server offers, and Compose gets its own model
picker so you can compare models on the same message.

Every agent role uses the same model by default. Power users can point
individual roles at different models in `~/.envoy/settings.json`
(`role_models`), for example a tool-capable model for orchestration and a
multilingual one for the language work.

## Comparing models: `envoy eval`

```bash
envoy eval                                    # the configured model, the seven demo samples
envoy eval --set heldout --perturb            # 63 never-tuned-on samples, plus planted faults
envoy eval --set heldout --models command-a-03-2025,c4ai-aya-expanse-32b --out compare.json
envoy eval --set heldout --critic-model command-a-03-2025   # judge with a different model
envoy eval --set injection                    # 20 attacks x 7 languages, each paired with a real question
envoy bench massive --data <MASSIVE dir>      # the Reader alone: language accuracy, slot recall
envoy bench flores --data <FLORES-200 dir>    # the Critic alone: chrF of its back-translation
envoy study export --from heldout.json --out study/   # blind pairwise sheets for native readers
envoy study score --sheets study/             # preference with CIs, Krippendorff's alpha, kappa
```

Two sample sets ship with Envoy. The **demo** set is the seven messages in
the UI; prompts were tuned on them. The **held-out** set is 63 fresh messages,
five or more per locale, that no prompt was ever tuned against. Every sample
says what a correct reply must satisfy, so scoring needs no human: the locale
it resolves to, the facts it must contain (numbers match as whole tokens in
any digit script), values that would contradict the knowledge base, glossary
terms, no leaked source ids, and on injection samples no promise. Greeting and
sign-off are enforced in code, so they are reported as invariants rather than
counted as passes.

`--perturb` plants six known faults into every finished reply (a dropped
order number, a changed number, another locale's greeting, an unsupported
promise, a leaked source id, slang) and reports what the Critic, the Arbiter,
and the deterministic steps catch, plus the false-alarm rate on untouched
runs.

Whether the Rewriter actually makes a reply sound local is measured by a
dialect identifier, not by the model: with a judge installed, every eval
table adds a per-locale row of how often the Drafter's body, then the
Rewriter's body, is classified as the target dialect.

```bash
pip install camel-tools && camel_data -i dialectid           # Arabic judge (MADAR-26)
envoy dialect train --language pt --data DSLCC/task1-train.txt   # Portuguese judge from DSLCC
envoy dialect list
```

Method, results, and negative results are in [docs/EVAL.md](docs/EVAL.md).

## Privacy

Everything runs locally: the model, the database, the glossary, the history.
The only network call Envoy makes is to the model endpoint you configure,
which by default is on your own machine. There is no account and no
telemetry.

## Development

```bash
pip install -e ".[dev]"
pytest -q --ignore=tests/e2e     # unit, agents, MCP over stdio, pipeline, API  (~7s)
cd ui && npm ci && npm run build # bundles the UI into src/envoy/static (committed, so
                                 # installing from the repo works without Node)
playwright install chromium
pytest -q tests/e2e              # boots the real server and drives the UI in Chromium
ruff check src tests
```

Layout:

```
src/envoy/
  schemas.py      typed contracts for every agent and the Result
  pipeline.py     Reader → Drafter → Rewriter → Critic → Arbiter, one revision loop
  agents/         reader, drafter, rewriter, critic (model-driven); arbiter (deterministic)
  prompts/        one versioned prompt per agent
  models/         openai_compat (Ollama, LM Studio, vLLM), stub, fake (tests)
  mcp/servers/    glossary, knowledge, history, thread; mcp/client.py spawns them
  locales/        twelve starter locale profiles (YAML)
  text.py         shared tokenizer with a small cross-lingual alias table
  db.py, app.py, cli.py, demo.py
ui/               React + Vite + Tailwind, built into src/envoy/static
tests/            unit · agents · mcp · pipeline · api · e2e
docs/DESIGN.md    the build plan
```

## Roadmap

- **v1 (this):** inbound replies with Rewriter and Critic, local web app,
  one-command install, twelve locales, MCP-backed grounding.
- **v1.5:** outbound, one message localized to many regions with the same
  Critic; prompt tuning on real Aya output; more locales.
- **Later:** email and chat connectors as MCP servers with a Send action, a
  native desktop wrapper, community-contributed locale profiles.

## License

MIT
