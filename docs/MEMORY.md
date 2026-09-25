# Memory: drafting from your own past writing

Envoy's knowledge base holds the facts you wrote down for it. Your mail holds
the facts you actually told people, in the words you use with them. Memory
is the part of Envoy that reads the second kind: your past messages, imported
from an export or captured as you send, searched when a reply is drafted,
and cited like any other source.

The design is borrowed from meeting recorders. They ask once to join, show
that they are recording, and hand you notes afterwards that you can correct.
Envoy's memory asks once per site, shows that it is remembering, and hands
you dated facts with the message each came from.

## The goal, in milestones

| | Milestone | What it delivers | Status |
|---|---|---|---|
| M1 | **Import past mail and documents** | `envoy import` for mbox, `.eml`, Markdown, text and PDF; quoted replies and signatures stripped; a `messages` table; a `mail` MCP tool that ranks the newest statement and the contact being answered first; the Drafter cites mail with who said it and when | done (0.9.0) |
| M2 | **Retrieval across languages** | Embeddings through the configured provider (Cohere's multilingual embed model on the API path, any OpenAI-compatible server's `/embeddings` locally, an offline hashed embedder otherwise), fused with the token search by reciprocal rank; the contact and recency priors applied after fusion; `envoy index`; the knowledge base searched the same way | done (0.9.1) |
| M3 | **Extract the correct fact** | An Extractor agent turns each message into dated facts (topic, statement, value) on a reviewable Memory page; facts are sources with `fc:` ids; the Arbiter flags a reply that cites the newest of two disagreeing facts (warn) or an older one (block); your own sent mail as voice examples for the Rewriter | done (0.9.2) |
| M4 | **Measure it** | A fixture mailbox with superseded facts in seven languages; `envoy bench memory`: recall at k for the token search and the hybrid search, overall and cross-lingual; newest-fact and stale-fact rates; conflict flagging; a Memory section in the report; the stub baseline pinned in the tests | done (0.9.3) |
| M5 | Sources page and docs | What was imported, what each reply cited, exclude a thread, pause | |
| M6 | Remember as you send | The browser extension: turn memory on per site, a visible indicator, capture the message on send with the message it answers, never a keystroke | |
| M7 | Host it | Run Envoy for yourself online and let others try it: an owner login, HTTPS behind a reverse proxy, a persistent data volume for the Docker image, and a public demo mode on the stub or a rate-limited shared key so visitors cannot spend yours | |

## Import

```bash
envoy config --user-email you@example.com          # so Envoy knows which mail you wrote
envoy import ~/Takeout/Mail/All\ mail.mbox         # Gmail Takeout, Apple Mail, Thunderbird
envoy import ~/Desktop/exported-messages/           # a folder of .eml files, searched recursively
envoy import policies.md handbook.pdf               # documents go to the knowledge base
```

Each run prints how many messages were stored, how many you wrote, how many
were already there, and how many had no text once quotes were removed.
Importing the same export twice stores nothing twice: messages are keyed by
their `Message-ID`.

What is stored per message: the author's own words (the part above the first
quoted reply, with the signature removed), the sender, the recipients, the
date in UTC, the subject, the thread, and a guessed language. Attachments are
not stored. HTML-only mail is rendered to text with quoted blocks dropped.

PDF import needs `pip install pypdf` (or `pipx inject envoy-ai pypdf`); the
other formats need nothing.

## Search across languages

Vocabulary overlap cannot find "prazo de devolução" in a policy that says
"return window". Every paragraph of mail and knowledge is therefore also
embedded, and a search runs both rankings and fuses them (reciprocal rank
fusion, so the two need no common score scale). The priors that matter for
mail, the contact being answered and then the newest statement, are applied
after fusion.

Which embedder, by provider:

| provider | embedder | how to set |
|---|---|---|
| cohere | `embed-multilingual-v3.0` through `/v2/embed` (query and document input types, batches of 96) | on by default with your key; `--embed-model` to change |
| openai (Ollama, LM Studio, vLLM) | the model you name, through `/v1/embeddings` | `envoy config --embed-model bge-m3` after `ollama pull bge-m3` |
| stub, or nothing configured | `hash-v1`: hashed words and character trigrams with Envoy's cross-lingual alias table folded in, offline and deterministic | nothing to set |

```bash
envoy index          # embed whatever is not embedded yet; safe to rerun
envoy check          # shows which embedder is in use
```

`envoy import` indexes when it finishes (skip with `--no-index`), the API
indexes after an import and after each captured message, and the offline
embedder indexes at search time because it costs nothing. A remote embedder
is never called during a search except for the query itself. Vectors live in
the same SQLite file, one per paragraph per embedder, and are deleted with
their message.

## Facts: what was said, with a date

Search finds paragraphs. A reply needs the fact inside the paragraph, and it
needs to know whether a later message changed it. So each stored message is
read once by an Extractor agent (one model call per message; the stub does
it with a rule) that lists what the message states:

- **topic**: a short English key for what the fact is about ("return
  window", "shipping time"), the same however it is phrased;
- **statement**: the sentence as written, in its own language;
- **value**: the number, amount, date or duration it fixes, if any.

Each fact keeps who said it (you or them), to or from whom, the date, the
language, and the message it came from. The Memory page in the app lists
them, searchable, with confirm and reject for each, and shows at the top
every topic on which two facts disagree, newest first.

```bash
envoy import mail.mbox --extract   # read the mail for facts right after importing it
envoy extract                      # read whatever has not been read yet
```

A captured message is read on arrival. `POST /api/extract` runs it from the
app; `GET /api/facts`, `PUT /api/facts/{id}` (status, statement, value,
topic) and `DELETE /api/facts/{id}` are the review endpoints, and
`GET /api/memory` reports the counts and the conflicts.

### When facts disagree

Facts reach the Drafter as sources (`fc:` ids) with "you said on 2025-09-10"
attached, ranked with the party being answered first, then confirmed over
automatic, then newest. The Arbiter then compares the retrieved facts by
topic key:

- the reply cites the **newest** of two disagreeing facts: a warning
  (`conflicting_sources`) naming both values and dates, so the reply lands
  as *check*, and the reader sees that an older statement exists;
- the reply cites an **older** one: a block (`stale_source`), because the
  reply repeats something that was later changed. This is not handed to the
  Rewriter for a revision, since fixing a fact means changing meaning; a
  person decides.

Rejecting a fact on the Memory page removes it from retrieval and from the
conflict; confirming one ranks it above automatic ones. Deleting a message
deletes its facts.

### Your voice

The Rewriter is given up to three of your own recent messages in the
receiver's language, to the same contact when there are any, as examples of
how you write. It is told to match the register and phrasing and never to
copy content or change a fact.

## How a reply uses it

When you compose, the pipeline searches your mail with the Reader's gloss and
asks, in the receiver's language when the message's language is known. Hits
are paragraphs, scored by vocabulary overlap; on a tie the newer message wins,
and mail to or from the contact you are answering outranks the rest. The
Drafter sees each hit as a source with its attribution ("you wrote on
2025-09-10, re: Returns") and is told that when two mail sources disagree
the newest wins, and that the knowledge base and the glossary win over mail.
The Arbiter's rules apply unchanged: a claim without a source id is blocked,
and mail ids (`ml:…`) are stripped from the reply text like any other.

## Capture

The extension is milestone M6, but the endpoint it will use exists now:

```
POST /api/messages   {"text": …, "from_addr": …, "to_addrs": […], "subject": …, "thread_id": …}
```

The server strips quotes and signatures, decides whether the message is yours
from `user_email`, dates it, and stores it with `origin: capture`. It refuses
a message that is empty once quotes are removed. `GET /api/messages` lists
what is stored, `DELETE /api/messages/{id}` forgets one.

## Measuring it

```bash
envoy bench memory                     # the built-in fixture mailbox, configured model
envoy bench memory --models command-a-03-2025 --out memory.json
envoy bench memory --data my-mailbox.yaml   # your own, same YAML shape
```

The fixture is `evalset/mailbox.yaml`: messages with `id`, `date`, `from`,
`to`, `subject`, `text`, and questions with `text`, `locale`, `relevant`
(the message ids that hold the current answer), `newest` (the value a
correct reply uses) and `stale` (values it must not use). The bench stores
the messages in a fresh database, indexes them with the configured embedder,
runs the model's Extractor over them, then asks every question through the
whole pipeline. Method and the stub baseline are in
[EVAL.md](EVAL.md#memory-the-right-message-the-newest-fact).

One finding from building it: the pipeline used to search mail and facts in
the reply's language only, which made a Portuguese question blind to an
answer given in English. Retrieval is now language-independent; only voice
examples and past replies stay in the reply's language.

## Privacy

- Nothing is fetched. You hand Envoy a file, or the extension hands it a
  message you chose to send with memory on.
- Messages never leave the machine. Only the paragraphs retrieved for one
  reply are sent to the model endpoint you configured, inside the Drafter's
  prompt, the same as knowledge-base snippets today.
- Every stored message can be listed and deleted.

## Rules for the work

The same rules as the evaluation: one pull request per milestone, real
mailboxes and models run on your machine, no number in a document that the
code did not produce, and the fixture mailbox in `tests/fixtures/mail` is
what the tests and the retrieval metrics run on.
