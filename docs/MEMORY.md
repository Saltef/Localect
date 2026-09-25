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
| M5 | **Sources, exclusions, pause** | Every reply's source panel labels each citation by kind and, for memory, by who said it and when; the Memory page opens any message with its facts, excludes a thread or an address (never searched, read for facts, or used as a voice example, new arrivals included), lists the exclusions, and pauses capture with one click | done (0.9.4) |
| M6 | **Remember as you send** | The browser extension (Chrome, Edge): Compose in a side panel, a recording-style pill on Gmail, Outlook web and WhatsApp Web, capture on send of the message and the one it answered, per-site pause, paired to your Envoy with a token; the server refuses any other browser origin. See [EXTENSION.md](EXTENSION.md) | done (0.10.0) |
| M2b | A reranker, if the numbers ask for it | Cohere's multilingual reranker as a third step after fusion, off by default, one call per reply. Decided by the real-model `envoy bench memory` run: worth it if the first relevant message is often in the top 5 but not at rank 1, not worth its latency if the gap closes with real embeddings | pending that run |
| M7 | **Host it** | An owner password (PBKDF2) with a signed session cookie and a sign-in screen; the extension token counts as the owner; a public demo mode with its own in-memory demo store, per-address hourly and global daily caps, on the stub or your model; proxy-aware origin guard, client address and Secure cookie; Docker Compose with Caddy for automatic HTTPS and a persistent volume. See [HOSTING.md](HOSTING.md) | done (0.11.0) |

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

## Where a reply came from, and what to keep out

Every reply's **Sources behind each claim** panel labels each citation by
kind (knowledge base, your mail, remembered fact, glossary, past reply, this
thread) and, for anything from memory, by who said it and when ("you wrote
on 2025-09-10, re: Returns", "you said on 2025-09-10, confirmed by you"),
with a one-line count of where the reply drew from. History shows the same
panel for past replies.

On the Memory page, opening a message shows its full text and the facts read
from it, with two buttons: **Exclude this thread** and **Exclude &lt;the other
person&gt;**. An exclusion is a rule, kept in its own table: the messages it
matches are greyed out and leave search, vectors, facts, extraction and
voice examples at once, and a message that arrives later and matches the
rule is excluded on arrival. Removing the rule brings them back. The
**capture** badge at the top toggles whether new messages are remembered;
while paused, the capture endpoint stores nothing and says so, which is what
the extension will show.

```
GET    /api/messages/{id}     text and facts of one message
GET    /api/exclusions        rules with how many messages each matches
POST   /api/exclusions        {"kind": "thread" | "address", "value": …}
DELETE /api/exclusions/{id}
PUT    /api/settings          {"memory_capture": false}   pause; true resumes
```

## Privacy

- Nothing is fetched. You hand Envoy a file, or the extension hands it a
  message you chose to send with memory on.
- Messages never leave the machine. Only the paragraphs retrieved for one
  reply are sent to the model endpoint you configured, inside the Drafter's
  prompt, the same as knowledge-base snippets today.
- Every stored message can be listed and deleted.

## What the research says, and what Envoy took from it

Four pieces were read against this design in September 2026. Full texts of
the arXiv papers were not reachable from the build container; the notes rest
on their abstracts, the authors' stated results, Karpathy's own gist, and
secondary write-ups, and say so where it matters.

**Ingest-time semantic compilation** ("RAG Deserves an Index", Wild,
Takahashi and Uraki, [arXiv:2608.20845](https://arxiv.org/abs/2608.20845)).
Compile the corpus once, at write time, into two coupled layers: embeddings
maintained incrementally, and atomic claims each carrying its verbatim source
span, author and location, validated mechanically at compile time. On 500
interview transcripts, compiled claims as the retrieval payload gave 85.2%
correct answers from about 2.2k reader tokens against 72.5% from 16.3k for
the best chunking. This is the shape Envoy's memory already has: facts are
compiled at import with who, when and the source message, and vectors are
maintained per paragraph as messages arrive. Two things were missing and one
was taken: facts are now **validated against their source** at extraction
(a statement whose wording is not in the message is dropped and counted,
which removes a model's paraphrases and inventions before they can be
cited); and the paper's stronger claim, that claims alone beat claims plus
chunks, is a measurable ablation for `envoy bench memory`, listed below.

**The LLM wiki** (Karpathy's gist, and the Medium piece "RAG is dead"). Raw
sources, LLM-written markdown pages, a schema; ingest rewrites the pages a
source touches, query loads an index into context, lint finds
contradictions and stale claims. Karpathy states it "works surprisingly well
at moderate scale (~100 sources, ~hundreds of pages)" and the gist is
"intentionally abstract". For a mailbox of thousands of messages in seven
languages with facts that change, LLM-maintained prose pages as the source
of truth would cost a rewrite of many pages per message and lose provenance
silently, which the thread's own contributors warn about. What Envoy keeps
from it is the reviewable, compounding artifact: the facts table is the
wiki, kept by code rather than prose, with the conflict check as the lint
and the Memory page as the index. A deterministic per-topic timeline
("return window: 30 days since 2025-09-10, was 14 days from 2025-06-02")
rendered from facts, not written by a model, is the one wiki-like view worth
adding. The "valid time versus belief time" distinction from that thread is
already the split between `said_on` and `created_at`.

**Noēsis** (Cogotti, [arXiv:2609.07663](https://arxiv.org/abs/2609.07663),
patent pending). For small local models, the failure on factual queries is
confabulation rather than retrieval: they invent numbers and dates with the
evidence in context. The remedy is deterministic-first: precomputed facts
rendered verbatim, cross-source alignment resolved before generation, and a
two-tier context, a skeleton of facts and structure with no prose, then
verbatim passages only when the model asks for them. Reported: a 2B model
at parity with a 35B on factual integrity, structured retrieval +11.4 points
over flat RAG at 2B, prompts 26% smaller. This is the most relevant of the
four for Envoy's local path (an 8B model through Ollama). Envoy already
renders facts verbatim with dates and judges deterministically after
generation (the Arbiter); the idea to test is **facts first, paragraphs only
when no fact covers an ask**, which shrinks the Drafter's prompt and gives a
small model fewer places to confabulate. It is an ablation for the bench,
not a rewrite. The specific mechanisms are the subject of a patent
application; Envoy uses the general principle, which is also the ISC
paper's.

**AlgoRAG** (Adhikari, [arXiv:2609.14572](https://arxiv.org/abs/2609.14572)).
A domain RAG for teaching complexity theory: notation-aware retrieval,
pedagogical reranking, 179 exam questions. Not applicable to mail; its one
transferable habit, a curated held-out question set per domain, is what
`mailbox.yaml` already is.

Decisions: no replacement of the retrieval design; provenance validation
added now; two ablations queued for the real-model bench run (facts-only
versus facts plus paragraphs; skeleton-first context for the local model);
a per-topic timeline view queued for the Memory page. A reranker remains
conditional on the same run.

## Rules for the work

The same rules as the evaluation: one pull request per milestone, real
mailboxes and models run on your machine, no number in a document that the
code did not produce, and the fixture mailbox in `tests/fixtures/mail` is
what the tests and the retrieval metrics run on.
