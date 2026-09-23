# Envoy

**Reply to anyone in their language, and sound like a local.**
Private. Runs on your machine. You always press send.

Envoy helps you handle messages across languages. Paste what someone wrote
you, and Envoy shows you what they said, drafts your reply in their language,
rewrites it so it reads as if a native of their region wrote it, and checks
that nothing was lost in translation before you send.

## What you get

- **Understand any message.** A faithful gloss in your own language, so you
  know exactly what was said before you answer.
- **A grounded reply.** Drafted from your own facts, policies, glossary, and
  past replies, never invented.
- **Sounds local, not translated.** A Rewriter edits the reply for the
  receiver's region and dialect, formality, idiom, greetings and sign-offs,
  and date, number, and currency formats.
- **Nothing lost.** A Critic back-translates the final text and flags meaning
  drift, off tone, cultural risks, and any claim your sources don't support.
- **You send.** Envoy stages a message; it never sends on its own.

## Install (three steps)

1. Install [Ollama](https://ollama.com) and pull a multilingual model:
   `ollama pull <model>`
2. `pipx install envoy-ai` (or `uv tool install envoy-ai`)
3. `envoy` — opens `http://localhost:8765`

Prefer containers? `docker run -p 8765:8765 ghcr.io/saltef/envoy` (points at
your host's Ollama).

First launch walks you through a two-minute setup: who you are, your
glossary and do-not-translate terms, and the regions you usually write to.

## How it works

```
your message in  ──►  Reader   what they said, in your language
                      Drafter  a grounded reply in their language
                      Rewriter makes it read like a local wrote it
                      Critic   back-translates and flags what changed
                      Arbiter  keeps, revises, or escalates; you send
```

Each stage is a separate agent with its own job. The Rewriter pushes for
naturalness; the Critic guarantees fidelity. That tension is the product:
a native editor and a proofreader who never agree to let an error through.

## Privacy

Everything runs locally: the models, the data, the glossary, the history.
Nothing is sent to a cloud service unless you explicitly configure one.

## Roadmap

- v1: inbound replies with Rewriter and Critic, local web app, one-command install
- v1.5: outbound, one message localized to many regions with the same Critic
- Later: email and chat connectors over MCP, a native desktop app

## License

MIT
