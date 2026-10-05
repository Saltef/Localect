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
