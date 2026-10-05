## What changed and why

## Did you touch a prompt, a check, or a sample set?

If yes: which held-out or domains sample (if any) motivated this, and was
it moved out of held-out per `docs/EVAL.md`'s rule? If this changes a
measured number, paste the command and its output.

## Tests

- [ ] `pytest -q --ignore=tests/e2e` passes
- [ ] `ruff check src tests` passes
- [ ] e2e / UI build ran, if `ui/` or an `app.py` route changed
