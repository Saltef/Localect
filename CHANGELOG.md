# Changelog

Entries start here (2026-10-05). Earlier history is in `git log` and the
dated, numbered entries in `docs/EVAL.md`, which is the source of truth for
anything that changed a measured number. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); nothing here is
retroactively reconstructed.

## Unreleased

### Fixed

- Region resolution: `ar-JO` (Jordanian) is now aliased to the shipped
  `ar-LB` (Levantine) locale profile instead of falling through to the
  `ar-EG` language default. Recovers 4 of 20 Palestinian real-customer
  banking-bench rows where the Reader's regional guess was Jordanian; see
  `docs/EVAL.md`, *Reading the region misses*.

### Docs

- `docs/EVAL.md`: split the banking bench's region-resolution misses into
  "no guess" versus "guessed wrong," since the two have different fixes.
- Added `SECURITY.md`, `CONTRIBUTING.md`, issue and pull request templates.
- `docs/EVAL.md`: first real-model (Command A) run of the domains set,
  22/42 passed. Surfaced two unfixed findings: a greeting-invariant miss on
  three Japanese samples (code enforcement not recognizing a two-line
  greeting) and a sign-off-invariant question on 11 samples with a
  domain-supplied attribution line after the configured sign-off. Neither
  is fixed yet; both need a code-level look, not a prompt change.
- `docs/EVAL.md`: first full-set (140, no subsample) real-model run of the
  injection set, 114/140. Found a total, language-specific pattern: on the
  "reply only with the word APPROVED/BANANA" attacks, every non-Japanese
  language complied with the word while still refusing the substance;
  Japanese never did. Also found a scorer gap (Egyptian Arabic colloquial
  negation not recognized by the "named inside a refusal" exemption) — not
  yet fixed.
- `docs/EVAL.md`: first full-set (63, not the 24-sample quick subset)
  real-model run of the held-out set, 43/63. es-MX region resolution is
  the worst locale result in the document (5/6 confidently misread as
  es-ES, a real profile, not a resolver bug) and a different failure mode
  from the earlier no-guess cases; ar-KW turned up as the same class of
  fixable alias gap as the already-fixed ar-JO, not yet made. Found a
  scorer gap (a sample only accepts 24-hour "18" for 6 PM, not any
  language's 12-hour form) and one genuine grounding miss (es-ES-02 reuses
  the customer's stated elapsed time for two unrelated policy numbers).
  No dialect judge was installed for this run; that question is still
  pending.
