"""Sample sets for ``envoy eval``.

Two sets ship with Envoy:

- ``demo``: the seven messages shown in the UI. Prompts were tuned against
  them, so a pass here says the pipeline works, not that it generalizes.
- ``heldout``: fresh messages, at least five per starter locale, written
  after the prompts were fixed and never used to tune them. Any prompt change
  that needs a held-out sample to pass must first move that sample into the
  demo set and say so in docs/EVAL.md.
- ``injection``: twenty attack templates in every supported language, each
  paired with a legitimate question, so a reply must both refuse the attack
  and still answer. Scored on ``no_forbidden`` and the paired fact.
- ``domains``: the held-out checks on knowledge bases that are not a shop: a
  family clinic, a bank and a university admissions office, two messages per
  language each. A sample names its domain and the eval seeds that domain's
  glossary and knowledge into a fresh store before composing.

Every sample says what a correct reply must satisfy, so scoring needs no
human: the locale it should resolve to, facts it must contain (numbers match
as whole tokens, in any digit script), values that would contradict the
knowledge base and must not appear, glossary terms that must survive, and
phrases it must never contain.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from ..demo import SAMPLE_MESSAGES

SETS = ("demo", "heldout", "injection", "domains", "all")
_DIR = Path(__file__).parent


class Sample(BaseModel):
    id: str
    set: str = ""  # demo | heldout
    label: str
    text: str
    locale: str  # a full code ("ar-EG") or a language prefix ("fr")
    facts: list[list[str]] = Field(default_factory=list)  # each inner list: alternatives
    wrong: list[str] = Field(default_factory=list)  # contradicting values that must not appear
    terms: list[str] = Field(default_factory=list)  # glossary terms that must appear
    forbid: list[str] = Field(default_factory=list)  # phrases that must never appear
    domain: str = ""  # a knowledge base from domains.yaml; empty means the demo store

    @property
    def has_expectations(self) -> bool:
        return bool(self.facts or self.terms or self.forbid)


def demo_samples() -> list[Sample]:
    out = []
    for i, m in enumerate(SAMPLE_MESSAGES):
        out.append(Sample(
            id=f"demo-{i:02d}", set="demo", label=m["label"], text=m["text"],
            locale=m["expect_locale"],
            facts=[list(m["expect_any"])] if m.get("expect_any") else [],
            terms=list(m.get("expect_all", [])), forbid=list(m.get("forbid", [])),
        ))
    return out


def _yaml_samples(name: str) -> list[Sample]:
    raw = yaml.safe_load((_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    return [Sample(set=name, **item) for item in raw]


def heldout_samples() -> list[Sample]:
    return _yaml_samples("heldout")


def injection_samples() -> list[Sample]:
    return _yaml_samples("injection")


class Domain(BaseModel):
    """A knowledge base for one line of business, seeded in place of the demo
    store when a sample names it."""

    key: str
    name: str
    glossary: list[list] = Field(default_factory=list)  # term, rendering, lang, dnt, notes
    knowledge: list[list[str]] = Field(default_factory=list)  # title, text

    def seed(self, con) -> None:
        from .. import db

        for term, rendering, lang, dnt, notes in self.glossary:
            db.glossary_add(con, term, rendering, lang, bool(dnt), notes)
        for title, text in self.knowledge:
            db.knowledge_add(con, title, text)


def _domains_doc() -> dict:
    return yaml.safe_load((_DIR / "domains.yaml").read_text(encoding="utf-8"))


def domains() -> dict[str, Domain]:
    return {k: Domain(key=k, **v) for k, v in _domains_doc()["domains"].items()}


def domain_samples() -> list[Sample]:
    return [Sample(set="domains", **item) for item in _domains_doc()["samples"]]


def load(name: str = "demo") -> list[Sample]:
    if name == "demo":
        return demo_samples()
    if name == "heldout":
        return heldout_samples()
    if name == "injection":
        return injection_samples()
    if name == "domains":
        return domain_samples()
    if name == "all":
        return demo_samples() + heldout_samples() + injection_samples() + domain_samples()
    raise ValueError(f"unknown sample set {name!r}; choose one of {', '.join(SETS)}")
