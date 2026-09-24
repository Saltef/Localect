"""Does the text read as the target dialect? Ask a classifier, not the model.

The Rewriter's job is to make a reply sound like it was written in the
receiver's region. The only cheap, repeatable measure of that is a dialect
identifier trained on labelled text from those regions. Two backends:

- ``NgramModel``: a multinomial naive Bayes over hashed character n-grams,
  pure Python, trained by ``envoy dialect train`` from any labelled corpus
  (the DSL Corpus Collection for pt-BR / pt-PT and Spanish varieties, the
  MADAR corpus for Arabic cities) and saved as JSON under the data directory.
- ``CamelScorer``: CAMeL Tools' MADAR-26 city identifier for Arabic, used
  when ``camel-tools`` and its ``dialectid`` data are installed.

Both answer with a locale-like label ("pt-PT", "ar-EG", "es-LA", "ar-MSA")
that ``matches`` compares with the target locale. The scorer is judge, not
teacher: it never sees a prompt and nothing in Envoy is tuned against it.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
import zlib
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

_BUCKETS = 1 << 20
_NGRAMS = (1, 2, 3, 4)

# City codes of the MADAR-26 corpus (and CAMeL Tools' identifier), grouped
# into the locales Envoy ships. Cities outside the starter set map to their
# own region so that a wrong region is counted as wrong, not as unknown.
MADAR_CITIES: dict[str, str] = {
    "CAI": "ar-EG", "ALX": "ar-EG", "ASW": "ar-EG",
    "BEI": "ar-LB", "DAM": "ar-LB", "ALE": "ar-LB", "JER": "ar-LB", "AMM": "ar-LB", "SAL": "ar-LB",
    "RIY": "ar-SA", "JED": "ar-SA", "DOH": "ar-SA", "MUS": "ar-SA",
    "BAG": "ar-IQ", "BAS": "ar-IQ", "MOS": "ar-IQ",
    "SAN": "ar-YE", "KHA": "ar-SD",
    "TRI": "ar-LY", "BEN": "ar-LY", "TUN": "ar-TN", "SFX": "ar-TN", "ALG": "ar-DZ",
    "RAB": "ar-MA", "FES": "ar-MA",
    "MSA": "ar-MSA",
}

# Labels a training corpus may use, normalized to what Envoy compares against.
LABELS: dict[str, str] = {
    **MADAR_CITIES,
    "pt-br": "pt-BR", "pt-pt": "pt-PT", "br": "pt-BR", "pt": "pt-PT",
    "es-es": "es-ES", "es-ar": "es-LA", "es-pe": "es-LA", "es-mx": "es-LA", "es-co": "es-LA",
    "es-cl": "es-LA", "es-la": "es-LA",
    "en-gb": "en-GB", "en-us": "en-US",
}

# Group labels: what a locale must be classified as to count as a hit.
_GROUP = {"es-MX": "es-LA", "es-AR": "es-LA", "es-PE": "es-LA", "es-CO": "es-LA",
          "es-CL": "es-LA"}


def normalize_label(label: str) -> str:
    key = label.strip()
    return LABELS.get(key, LABELS.get(key.lower(), key))


def matches(label: str | None, target_locale: str) -> bool:
    """Is a predicted label a hit for the target locale?"""
    if not label:
        return False
    return label == target_locale or label == _GROUP.get(target_locale, "")


def _clean(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = re.sub(r"\d", "0", t)
    t = re.sub(r"\s+", " ", t).strip()
    return f" {t} "


def features(text: str, ngrams: tuple[int, ...] = _NGRAMS) -> Counter:
    t = _clean(text)
    out: Counter = Counter()
    for n in ngrams:
        for i in range(len(t) - n + 1):
            out[zlib.crc32(t[i:i + n].encode("utf-8")) & (_BUCKETS - 1)] += 1
    return out


class NgramModel:
    """Multinomial naive Bayes over hashed character n-grams."""

    def __init__(self, language: str = "", ngrams: tuple[int, ...] = _NGRAMS) -> None:
        self.language = language
        self.ngrams = ngrams
        self.counts: dict[str, Counter] = {}
        self.docs: Counter = Counter()
        self.alpha = 0.5

    @property
    def labels(self) -> list[str]:
        return sorted(self.counts)

    def train(self, pairs: Iterable[tuple[str, str]]) -> NgramModel:
        for text, raw in pairs:
            label = normalize_label(raw)
            if not text.strip():
                continue
            self.counts.setdefault(label, Counter()).update(features(text, self.ngrams))
            self.docs[label] += 1
        self._prepare()
        return self

    def _prepare(self) -> None:
        self._vocab = len({f for c in self.counts.values() for f in c})
        self._total = {k: sum(c.values()) for k, c in self.counts.items()}
        n = sum(self.docs.values()) or 1
        self._prior = {k: math.log(self.docs[k] / n) for k in self.counts}

    def scores(self, text: str) -> dict[str, float]:
        f = features(text, self.ngrams)
        out = {}
        for label, counts in self.counts.items():
            denom = self._total[label] + self.alpha * self._vocab
            ll = self._prior[label]
            for feat, k in f.items():
                ll += k * math.log((counts.get(feat, 0) + self.alpha) / denom)
            out[label] = ll
        return out

    def predict(self, text: str) -> tuple[str | None, float]:
        """Best label and its margin over the runner-up (in nats per feature)."""
        if not self.counts:
            return None, 0.0
        s = self.scores(text)
        ranked = sorted(s.items(), key=lambda kv: -kv[1])
        best = ranked[0]
        margin = best[1] - ranked[1][1] if len(ranked) > 1 else float("inf")
        n = max(1, sum(features(text, self.ngrams).values()))
        return best[0], margin / n

    def save(self, path: Path) -> None:
        doc = {"language": self.language, "ngrams": list(self.ngrams), "alpha": self.alpha,
               "docs": dict(self.docs),
               "counts": {k: {str(f): n for f, n in c.items()} for k, c in self.counts.items()}}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> NgramModel:
        doc = json.loads(path.read_text(encoding="utf-8"))
        m = cls(doc.get("language", ""), tuple(doc.get("ngrams", _NGRAMS)))
        m.alpha = doc.get("alpha", 0.5)
        m.docs = Counter(doc.get("docs", {}))
        m.counts = {k: Counter({int(f): n for f, n in c.items()})
                    for k, c in doc.get("counts", {}).items()}
        m._prepare()
        return m


def read_corpus(path: Path) -> Iterable[tuple[str, str]]:
    """Labelled text from a file or a directory.

    A file: one ``text<TAB>label`` per line (the DSL Corpus Collection's
    task files, MADAR's corpus files with the label in the last column).
    A directory: every ``*.txt``/``*.tsv`` inside, read the same way; a file
    with no tab in its lines is labelled by its own stem ("CAI.txt").
    """
    files = sorted(p for p in path.rglob("*") if p.suffix in (".txt", ".tsv")) \
        if path.is_dir() else [path]
    for f in files:
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                if "\t" in line:
                    parts = line.split("\t")
                    text, label = "\t".join(parts[:-1]), parts[-1]
                else:
                    text, label = line, f.stem
                yield text, label


class DialectScorer(Protocol):
    name: str
    language: str

    def predict(self, text: str) -> str | None: ...


class NgramScorer:
    def __init__(self, model: NgramModel, name: str = "ngram") -> None:
        self.model = model
        self.language = model.language
        self.name = name

    def predict(self, text: str) -> str | None:
        return self.model.predict(text)[0]


class CamelScorer:
    """CAMeL Tools' MADAR-26 city identifier, mapped to Envoy locales.
    Needs ``pip install camel-tools`` and ``camel_data -i dialectid``."""

    name = "camel-madar26"
    language = "ar"

    def __init__(self) -> None:
        from camel_tools.dialectid import DialectIdentifier  # optional dependency

        self._did = DialectIdentifier.pretrained()

    def predict(self, text: str) -> str | None:
        preds = self._did.predict([text])
        top = getattr(preds[0], "top", None) if preds else None
        return MADAR_CITIES.get(str(top), str(top)) if top else None


def discover(data_dir: Path) -> dict[str, DialectScorer]:
    """Scorers available on this machine: trained n-gram models under
    ``<data>/models/dialect-<lang>.json``, and CAMeL Tools for Arabic when
    installed and no model of our own overrides it."""
    out: dict[str, DialectScorer] = {}
    for f in sorted((data_dir / "models").glob("dialect-*.json")):
        m = NgramModel.load(f)
        lang = m.language or f.stem.split("-", 1)[-1]
        out[lang] = NgramScorer(m, name=f"ngram:{f.name}")
    if "ar" not in out:
        try:
            out["ar"] = CamelScorer()
        except Exception:  # noqa: BLE001 - not installed, or no data
            pass
    return out
