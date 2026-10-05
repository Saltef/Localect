# Contributing

Localect already states most of its own rules in `README.md` (*Development*)
and `docs/EVAL.md`. This page points to them and adds what was missing.

## Before you start

- One pull request per change.
- Read `docs/ARCHITECTURE.md` for how the pipeline and the five agents fit
  together, and `docs/EVAL.md` for the evaluation's own rules before
  touching a prompt, a check, or a sample set.
- UTF-8 everywhere. Tests run on Linux, macOS and Windows; a fixture
  filename Windows cannot check out is a real bug (see the repo's own
  history for one that happened).

## Setup

```bash
pip install -e ".[dev]"
ruff check src tests
pytest -q --ignore=tests/e2e     # unit, agents, MCP over stdio, pipeline, API
cd ui && npm ci && npm run build # the built UI is committed to src/localect/static
playwright install chromium
pytest -q tests/e2e              # boots the real server, drives the UI in Chromium
```

## The rule that matters most: never tune a prompt on the held-out set

If a held-out or domains sample exposes a real fault, the fix is: move the
sample into the demo set, fix the prompt or the code, and record the move
under *Samples moved out of held-out* in `docs/EVAL.md`. A prompt change
made to pass one specific held-out sample invalidates that set quietly, for
everyone who reads the numbers later. This is enforced by convention, not
by code, so a reviewer should ask "which sample motivated this?" on any
prompt diff.

## Numbers

Never write a number into a doc that a command did not print. If a claim
in a PR description or a doc update depends on a run, paste the command
and its output (or `localect report`'s markdown), not a remembered figure.
Negative results and tables marked `pending` stay in `docs/EVAL.md` —
that's the existing rule, not a new one.

## Commit style

Match the existing log: a short, specific summary of what changed and why
it matters, not which file moved. `git log --oneline` is the style guide.

## Reporting bugs or proposing features

Use the issue templates, or open a pull request directly for anything
small enough to just fix. For a security issue, see `SECURITY.md` instead
of a public issue.
