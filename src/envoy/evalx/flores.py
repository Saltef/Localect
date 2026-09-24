"""The Critic's back-translation against FLORES-200 references.

Every Critic verdict rests on its own reading of the final text: it
back-translates each segment into the user's language and compares. If that
reading is poor, its flags are noise. FLORES-200 has the same sentences in
200 languages, so the Critic can back-translate the source sentence for a
language and be scored against the English reference with chrF.

chrF (Popović 2015) is implemented here in pure Python: character n-grams
for n = 1..6 with whitespace removed, precision and recall averaged over n,
F-beta with beta = 2. Corpus scores accumulate n-gram counts over sentences.
sacrebleu's ``chrF`` on the same pairs should agree to within rounding.

Data: the FLORES-200 release (``flores200_dataset/devtest/<code>.devtest``,
one sentence per line, parallel across files). Point ``--data`` at the
unpacked directory.
"""

from __future__ import annotations

import random
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import db
from ..agents import critic
from ..agents.stage import StageError
from ..config import Settings
from ..locales import seed_locales
from ..models import build_model
from ..pipeline import LANG_NAMES, _fallback_locale, critic_model_for
from ..schemas import Draft, Rewrite, RewrittenSegment, Segment

FLORES_CODES = {"ar": "arb_Arab", "pt": "por_Latn", "es": "spa_Latn", "fr": "fra_Latn",
                "de": "deu_Latn", "ja": "jpn_Jpan", "en": "eng_Latn"}
REFERENCE = "eng_Latn"
FLOOR = 40.0  # below this chrF, the Critic's reading of that language is not trusted


def find_split(data_dir: Path, code: str, split: str = "devtest") -> Path | None:
    for candidate in (data_dir / split / f"{code}.{split}", data_dir / f"{code}.{split}"):
        if candidate.exists():
            return candidate
    found = sorted(data_dir.rglob(f"{code}.{split}"))
    return found[0] if found else None


def load_pairs(data_dir: Path, language: str, n: int = 50, split: str = "devtest",
               seed: int = 7) -> list[tuple[int, str, str]]:
    """(line index, source sentence, English reference) for ``n`` lines."""
    src_f = find_split(data_dir, FLORES_CODES.get(language, language), split)
    ref_f = find_split(data_dir, REFERENCE, split)
    if src_f is None or ref_f is None:
        return []
    src = src_f.read_text(encoding="utf-8").splitlines()
    ref = ref_f.read_text(encoding="utf-8").splitlines()
    idx = list(range(min(len(src), len(ref))))
    random.Random(seed).shuffle(idx)
    return [(i, src[i], ref[i]) for i in sorted(idx[:n])]


# --- chrF -------------------------------------------------------------------


def _ngrams(text: str, n: int) -> Counter:
    t = "".join(text.split())
    return Counter(t[i:i + n] for i in range(len(t) - n + 1))


def chrf_stats(hyp: str, ref: str, order: int = 6) -> list[tuple[int, int, int]]:
    """Per order: (matched, hypothesis n-grams, reference n-grams)."""
    out = []
    for n in range(1, order + 1):
        h, r = _ngrams(hyp, n), _ngrams(ref, n)
        out.append((sum((h & r).values()), sum(h.values()), sum(r.values())))
    return out


def chrf_from_stats(stats: list[tuple[int, int, int]], beta: float = 2.0) -> float:
    precisions, recalls = [], []
    for matched, hyp_n, ref_n in stats:
        if hyp_n == 0 or ref_n == 0:
            continue
        precisions.append(matched / hyp_n)
        recalls.append(matched / ref_n)
    if not precisions:
        return 0.0
    p, r = sum(precisions) / len(precisions), sum(recalls) / len(recalls)
    if p == 0 or r == 0:
        return 0.0
    b2 = beta * beta
    return 100 * (1 + b2) * p * r / (b2 * p + r)


def chrf(hyp: str, ref: str) -> float:
    return chrf_from_stats(chrf_stats(hyp, ref))


def chrf_corpus(pairs: list[tuple[str, str]]) -> float:
    total = [(0, 0, 0)] * 6
    for hyp, ref in pairs:
        total = [(a + m, b + h, c + r)
                 for (a, b, c), (m, h, r) in zip(total, chrf_stats(hyp, ref), strict=True)]
    return chrf_from_stats(total)


# --- running the Critic -------------------------------------------------------


@dataclass
class BackScore:
    model: str
    language: str
    index: int
    source: str
    reference: str
    hypothesis: str = ""
    chrf: float = 0.0
    seconds: float = 0.0
    error: str = ""


async def back_translate(model, text: str, locale, user_language_name: str) -> str:
    """Run the Critic on a one-segment 'reply' and return its back-translation."""
    d = Draft(language=locale.language, segments=[Segment(id="s1", text=text)])
    rw = Rewrite(segments=[RewrittenSegment(id="s1", text=text)])
    cq = await critic.critique(model, d, rw, locale, [], [], user_language_name)
    return cq.back_translation()


async def run_flores(settings: Settings, data_dir: Path, languages: list[str] | None = None,
                     n: int = 50, models: list[str] | None = None, con=None, on_row=None
                     ) -> list[BackScore]:
    con = con if con is not None else db.connect(settings.db_path)
    seed_locales(con)
    base = build_model(settings)
    names = models or [getattr(base, "model", base.name)]
    user_language_name = LANG_NAMES.get(settings.user_language, settings.user_language)
    langs = [lang for lang in (languages or list(FLORES_CODES)) if lang != "en"]
    rows: list[BackScore] = []
    for name in names:
        model = base.with_model(name) if hasattr(base, "with_model") and name != getattr(
            base, "model", None) else base
        judge = critic_model_for(settings, model)
        for lang in langs:
            locale = db.locale_for_language(con, lang) or _fallback_locale(lang)
            for i, src, ref in load_pairs(data_dir, lang, n):
                t0 = time.perf_counter()
                row = BackScore(model=judge.name, language=lang, index=i, source=src,
                                reference=ref)
                try:
                    row.hypothesis = await back_translate(judge, src, locale, user_language_name)
                    row.chrf = round(chrf(row.hypothesis, ref), 1)
                except StageError as e:
                    row.error = str(e)[:200]
                row.seconds = round(time.perf_counter() - t0, 1)
                rows.append(row)
                if on_row:
                    on_row(row)
    return rows


def render_flores(rows: list[BackScore], floor: float = FLOOR) -> str:
    lines = []
    by_model: dict[str, list[BackScore]] = {}
    for r in rows:
        by_model.setdefault(r.model, []).append(r)
    for model, rs in by_model.items():
        lines.append(f"\nCritic back-translation on FLORES-200 devtest, {model}: "
                     f"{len(rs)} sentences, {sum(r.seconds for r in rs):.0f}s")
        lines.append(f"  {'lang':5} {'n':>4} {'errors':>6} {'chrF':>6}  trust")
        by_lang: dict[str, list[BackScore]] = {}
        for r in rs:
            by_lang.setdefault(r.language, []).append(r)
        for lang, ls in sorted(by_lang.items()):
            ok = [r for r in ls if not r.error]
            score = chrf_corpus([(r.hypothesis, r.reference) for r in ok]) if ok else 0.0
            trust = "ok" if ok and score >= floor else f"LOW (below {floor:.0f})"
            lines.append(f"  {lang:5} {len(ls):>4} {len(ls) - len(ok):>6} {score:>6.1f}  {trust}")
    return "\n".join(lines)


def flores_to_dicts(rows: list[BackScore]) -> list[dict]:
    return [asdict(r) for r in rows]
