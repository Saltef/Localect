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
| M2 | Retrieval across languages | Embeddings through the configured provider (Ollama locally, Cohere's multilingual embed model on the API path, a hashed fallback for the stub), fused with the token search; recency and per-contact priors | next |
| M3 | Extract the correct fact | Dated facts pulled out of messages into a reviewable Memory page; "sources disagree" flag from the Critic when two statements conflict, with both dates; your own sent mail as voice examples for the Rewriter | |
| M4 | Measure it | A fixture mailbox with superseded facts in several languages; recall at k, stale-fact rate, cross-lingual retrieval; held-out samples that depend on the mailbox; a retrieval section in the report | |
| M5 | Sources page and docs | What was imported, what each reply cited, exclude a thread, pause | |
| M6 | Remember as you send | The browser extension: turn memory on per site, a visible indicator, capture the message on send with the message it answers, never a keystroke | |

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
