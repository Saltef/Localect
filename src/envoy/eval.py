"""``envoy eval``: run the sample set through one or more models and score it.

This is the release quality bar, made runnable. Every check is deterministic
and needs no human: did the reply resolve to the right locale, keep every
must-preserve item, contain the fact the question was about, keep the locale
greeting and sign-off, leak no source ids, and, on the injection sample, make
no promise. A model comparison is one command, and any prompt change can be
checked for regressions the same way.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from . import db
from .config import Settings
from .conventions import rendered_greeting, rendered_signoff
from .demo import SAMPLE_MESSAGES, seed_demo
from .locales import seed_locales
from .models import build_model
from .pipeline import PipelineError, compose
from .schemas import ComposeRequest, Result
from .text import strip_citations, to_western
from .tools import DirectTools


@dataclass
class RunScore:
    model: str
    index: int
    label: str
    seconds: float
    status: str = ""
    locale: str = ""
    error: str = ""
    checks: dict[str, bool] = field(default_factory=dict)
    flags_block: int = 0
    flags_warn: int = 0
    suggestions: int = 0
    revisions: int = 0
    final_text: str = ""

    @property
    def passed(self) -> bool:
        return not self.error and all(self.checks.values()) and self.status != "escalate"


def score(result: Result, sample: dict[str, Any], user_name: str) -> dict[str, bool]:
    final = result.final_text
    final_w = to_western(final)
    low = final_w.lower()
    exp = sample.get("expect_locale", "")
    checks = {
        "locale": result.locale.locale == exp or result.locale.locale.startswith(exp + "-")
        if exp else True,
        # The Arbiter's rule: anything preserved into the draft must survive the rewrite.
        "preserved": all(to_western(item).lower() in low for item in result.reading.must_preserve
                         if to_western(item).lower() in to_western(result.draft.text()).lower()),
        "fact": any(to_western(x).lower() in low for x in sample.get("expect_any", []))
        if sample.get("expect_any") else True,
        "terms": all(x.lower() in low for x in sample.get("expect_all", [])),
        "greeting": final.startswith(rendered_greeting(result.locale, "")),
        "signoff": final.rstrip().endswith(rendered_signoff(result.locale, user_name).rstrip()),
        "no_leaks": strip_citations(final) == final.strip(),
        "no_forbidden": not any(x.lower() in low for x in sample.get("forbid", [])),
        "verified": not result.stage_errors,
    }
    return checks


async def run_eval(settings: Settings, models: list[str] | None = None,
                   indexes: list[int] | None = None, con=None,
                   on_row=None) -> list[RunScore]:
    con = con if con is not None else db.connect(settings.db_path)
    seed_locales(con)
    seed_demo(con)
    base = build_model(settings)
    names = models or [getattr(base, "model", base.name)]
    idx = indexes if indexes is not None else list(range(len(SAMPLE_MESSAGES)))
    rows: list[RunScore] = []
    for name in names:
        model = base.with_model(name) if hasattr(base, "with_model") and name != getattr(
            base, "model", None) else base
        for i in idx:
            sample = SAMPLE_MESSAGES[i]
            t0 = time.perf_counter()
            row = RunScore(model=model.name, index=i, label=sample["label"], seconds=0.0)
            try:
                r = await compose(ComposeRequest(message=sample["text"]), settings=settings,
                                  model=model, tools=DirectTools(con), con=con)
                row.status, row.locale = r.status.value, r.locale.locale
                row.checks = score(r, sample, settings.user_name)
                row.flags_block = sum(1 for f in r.flags if f.severity == "block")
                row.flags_warn = sum(1 for f in r.flags if f.severity == "warn")
                row.suggestions = len(r.suggestions)
                row.revisions = r.revisions
                row.final_text = r.final_text
            except PipelineError as e:
                row.error = str(e)[:200]
            row.seconds = round(time.perf_counter() - t0, 1)
            rows.append(row)
            if on_row:
                on_row(row)
    return rows


CHECK_ORDER = ["locale", "preserved", "fact", "terms", "greeting", "signoff", "no_leaks",
               "no_forbidden", "verified"]


def render_table(rows: list[RunScore]) -> str:
    lines = []
    by_model: dict[str, list[RunScore]] = {}
    for r in rows:
        by_model.setdefault(r.model, []).append(r)
    for model, rs in by_model.items():
        passed = sum(1 for r in rs if r.passed)
        lines.append(f"\n{model}: {passed}/{len(rs)} passed, "
                     f"{sum(r.seconds for r in rs):.0f}s total")
        lines.append(f"  {'#':>2} {'result':7} {'status':9} {'locale':7} {'s':>4}  checks")
        for r in rs:
            if r.error:
                lines.append(f"  {r.index:>2} {'ERROR':7} {'':9} {'':7} {r.seconds:>4}  {r.error}")
                continue
            failed = [k for k in CHECK_ORDER if not r.checks.get(k, True)]
            marks = "ok" if not failed else "FAIL " + ",".join(failed)
            extra = []
            if r.flags_block or r.flags_warn:
                extra.append(f"flags {r.flags_block}b/{r.flags_warn}w")
            if r.suggestions:
                extra.append(f"{r.suggestions} sugg")
            if r.revisions:
                extra.append("revised")
            lines.append(f"  {r.index:>2} {('pass' if r.passed else 'fail'):7} {r.status:9} "
                         f"{r.locale:7} {r.seconds:>4}  {marks}"
                         + (f"  ({', '.join(extra)})" if extra else ""))
    return "\n".join(lines)


def to_json(rows: list[RunScore]) -> str:
    return json.dumps([{**asdict(r), "passed": r.passed} for r in rows], ensure_ascii=False,
                      indent=1)


def main_eval(settings: Settings, models: list[str] | None, indexes: list[int] | None,
              out: str | None) -> int:
    def live(row: RunScore) -> None:
        state = "ERROR" if row.error else ("pass" if row.passed else "fail")
        print(f"  [{row.model}] #{row.index} {row.label}: {state} ({row.seconds}s)", flush=True)

    print(f"Envoy eval  provider={settings.provider}  models={models or ['(configured)']}")
    rows = asyncio.run(run_eval(settings, models, indexes, on_row=live))
    print(render_table(rows))
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(to_json(rows))
        print(f"\nWrote {out}")
    return 0 if all(r.passed for r in rows) else 1
