"""The long experiment: every benchmark, under every ablation, into one
folder, with a diagnosis at the end that says what to change.

A *condition* is a named set of pipeline switches (``Settings.ablations``):

- ``base``: the pipeline as shipped;
- ``no_critic``: the Arbiter judges alone. What does the Critic model catch
  that code does not, and what does it block that it should not?
- ``no_rewriter``: the draft goes out as written. What does the Rewriter add
  to dialect and register, and does it lose anything on the way?
- ``no_revision``: no second pass after a blocking flag. Does the fix loop
  fix?
- ``facts_only`` / ``no_facts``: memory answers from extracted facts alone,
  or from mail paragraphs alone. Which source policy keeps the newest value?
- ``no_voice``: no voice examples from your own mail. Does register suffer?

Each condition runs the sections that can tell it apart (``PLAN``). Results
land in ``OUT/<condition>/<section>.json`` in the same shapes ``envoy eval``
and ``envoy bench`` write, so ``envoy report`` reads them too. A section
whose file exists is skipped, so an interrupted experiment resumes where
it stopped and ``--fresh`` starts over. When everything has run,
``experiment.md`` puts the conditions side by side and ``findings.md``
(``evalx.diagnose``) ranks what the numbers say to change, with the prompt
or setting that is the lever.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from pathlib import Path
from typing import Any

from .. import db
from ..config import Settings

CONDITIONS: dict[str, list[str]] = {
    "base": [],
    "no_critic": ["no_critic"],
    "no_rewriter": ["no_rewriter"],
    "no_revision": ["no_revision"],
    "facts_only": ["facts_only"],
    "no_facts": ["no_facts"],
    "no_voice": ["no_voice"],
}

# Which sections each condition runs: only those its switch can change.
PLAN: dict[str, list[str]] = {
    "base": ["heldout", "injection", "domains", "memory", "replay", "banking", "health",
             "massive", "flores"],
    "no_critic": ["heldout", "injection", "domains"],
    "no_rewriter": ["heldout", "domains", "banking"],
    "no_revision": ["heldout", "injection"],
    "facts_only": ["memory", "replay"],
    "no_facts": ["memory", "replay"],
    "no_voice": ["replay"],
}
SECTIONS = ["heldout", "injection", "domains", "memory", "replay", "banking", "health",
            "massive", "flores"]
# Sections that need a --data folder with the named subfolder present.
NEEDS_DATA = {"banking": ("banking77", "arbanking77", "wolbanking77"),
              "health": ("medlineplus", "aramed", "medpt", "liveqa"),
              "massive": ("massive",), "flores": ("flores",)}


def condition_settings(settings: Settings, condition: str) -> Settings:
    s = dataclasses.replace(settings)
    s.ablations = list(CONDITIONS[condition])
    s.role_models = dict(settings.role_models)
    return s


def quick_indexes(sample_set: str) -> list[int]:
    from ..evalset import load

    if sample_set == "heldout":
        seen: dict[str, int] = {}
        idx = []
        for i, smp in enumerate(load("heldout")):
            if seen.get(smp.locale, 0) < 2:
                seen[smp.locale] = seen.get(smp.locale, 0) + 1
                idx.append(i)
        return idx
    if sample_set == "injection":
        return [i for i, smp in enumerate(load("injection"))
                if smp.id.rsplit("-", 1)[-1] in ("01", "04", "13")]
    return [i for i, smp in enumerate(load("domains")) if smp.id.endswith("-01")]


def _has_data(data: Path | None, section: str) -> bool:
    if section not in NEEDS_DATA:
        return True
    return bool(data) and any((data / sub).exists() for sub in NEEDS_DATA[section])


def run_section(section: str, settings: Settings, out: Path, data: Path | None,
                models: list[str] | None, quick: bool, critic_model: str | None,
                n: int) -> Path | None:
    """One section under one condition, written to ``out/<section>.json``.
    Returns the path, or None when the section had nothing to run."""
    from ..eval import main_eval
    from . import banking, health, massive, memory, replay
    from . import flores as flores_bench

    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{section}.json"
    if section in ("heldout", "injection", "domains"):
        idx = quick_indexes(section) if quick else None
        main_eval(settings, models, idx, str(path), section, perturb=section != "injection",
                  critic_model=critic_model)
        return path
    if section == "memory":
        rows = asyncio.run(memory.run_memory(settings, models, None))
        print(memory.render_memory(rows))
        path.write_text(json.dumps({"memory": memory.memory_to_dicts(rows)}, ensure_ascii=False,
                                   indent=1), encoding="utf-8")
        return path
    if section == "replay":
        con = db.connect(settings.db_path)
        if not replay.find_pairs(con, 1):
            print("(no imported exchanges to replay; skipped)")
            return None
        rows = asyncio.run(replay.run_replay(settings, con, models, 10 if quick else n))
        print(replay.render_replay(rows))
        path.write_text(json.dumps({"replay": replay.replay_to_dicts(rows)}, ensure_ascii=False,
                                   indent=1), encoding="utf-8")
        return path
    if not _has_data(data, section):
        print(f"({section}: no data under --data; skipped)")
        return None
    assert data is not None
    if section == "banking":
        rows = asyncio.run(banking.run_banking(settings, data, 5 if quick else n, models))
        if not rows:
            return None
        print(banking.render_banking(rows))
        path.write_text(json.dumps({"banking": banking.banking_to_dicts(rows)},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        return path
    if section == "health":
        grounded, patients = [], []
        if (data / "medlineplus").exists():
            topics = health.parse_medlineplus(data / "medlineplus")
            grounded = asyncio.run(health.run_grounded(settings, topics, 5 if quick else n,
                                                       models))
        patients = asyncio.run(health.run_patients(settings, data, 5 if quick else n, models))
        if not grounded and not patients:
            return None
        print(health.render_health(grounded, patients))
        path.write_text(json.dumps({"health_grounded": health.grounded_to_dicts(grounded),
                                    "health_patients": health.patients_to_dicts(patients)},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        return path
    if section == "massive":
        rows = asyncio.run(massive.run_massive(settings, data / "massive", None,
                                               10 if quick else 50, models))
        if not rows:
            return None
        print(massive.render_massive(rows))
        path.write_text(json.dumps({"massive": massive.massive_to_dicts(rows)},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        return path
    if section == "flores":
        rows = asyncio.run(flores_bench.run_flores(settings, data / "flores", None,
                                                   10 if quick else 50, models))
        if not rows:
            return None
        print(flores_bench.render_flores(rows))
        path.write_text(json.dumps({"flores": flores_bench.flores_to_dicts(rows)},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        return path
    return None


def run_experiment(settings: Settings, out: Path, data: Path | None = None,
                   models: list[str] | None = None, conditions: list[str] | None = None,
                   sections: list[str] | None = None, quick: bool = False, fresh: bool = False,
                   critic_model: str | None = None, n: int = 30) -> dict[str, Any]:
    """Run the plan, resuming from what is on disk, and write the two
    summaries. Returns the manifest."""
    out.mkdir(parents=True, exist_ok=True)
    conditions = conditions or list(CONDITIONS)
    manifest_path = out / "manifest.json"
    manifest: dict[str, Any] = {"provider": settings.provider, "model": settings.model,
                                "quick": quick, "started": time.strftime("%Y-%m-%d %H:%M"),
                                "runs": {}}
    if manifest_path.exists() and not fresh:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("runs", {})
    for cond in conditions:
        wanted = [s for s in PLAN[cond] if not sections or s in sections]
        cs = condition_settings(settings, cond)
        for section in wanted:
            key = f"{cond}/{section}"
            path = out / cond / f"{section}.json"
            if path.exists() and not fresh and not _partial(path):
                print(f"\n== {key}: done, skipping (delete the file to rerun)")
                continue
            print(f"\n== {key}  ablations={cs.ablations or '-'}")
            t0 = time.perf_counter()
            written = run_section(section, cs, out / cond, data, models, quick, critic_model, n)
            manifest["runs"][key] = {"file": str(written) if written else "",
                                     "seconds": round(time.perf_counter() - t0, 1),
                                     "skipped": written is None}
            manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    manifest["finished"] = time.strftime("%Y-%m-%d %H:%M")
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (out / "experiment.md").write_text(compare(out), encoding="utf-8")
    from .diagnose import diagnose, render_findings

    (out / "findings.md").write_text(render_findings(diagnose(load_experiment(out))),
                                     encoding="utf-8")
    return manifest


def _partial(path: Path) -> bool:
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("partial"))
    except (OSError, ValueError):
        return True


def load_experiment(out: Path) -> dict[str, dict[str, dict[str, Any]]]:
    """``{condition: {section: doc}}`` for every JSON on disk."""
    found: dict[str, dict[str, dict[str, Any]]] = {}
    for cond_dir in sorted(p for p in out.iterdir() if p.is_dir()):
        for f in sorted(cond_dir.glob("*.json")):
            try:
                found.setdefault(cond_dir.name, {})[f.stem] = json.loads(
                    f.read_text(encoding="utf-8"))
            except ValueError:
                continue
    return found


# ---- The side-by-side table ------------------------------------------------------

def _frac(k: int, n: int) -> str:
    return f"{k}/{n}" if n else "-"


def section_metrics(section: str, doc: dict[str, Any]) -> dict[str, str]:
    """The few numbers that tell conditions apart, as ``k/n`` strings."""
    from . import banking, health, memory, replay

    m: dict[str, str] = {}
    if section in ("heldout", "injection", "domains"):
        runs = doc.get("runs", [])
        ok = [r for r in runs if not r.get("error")]
        m["passed"] = _frac(sum(1 for r in runs if r.get("passed")), len(runs))
        m["escalated"] = _frac(sum(1 for r in ok if r.get("status") == "escalate"), len(ok))
        m["ready"] = _frac(sum(1 for r in ok if r.get("status") == "ready"), len(ok))
        dial = [r for r in ok if r.get("dialect")]
        if dial:
            m["dialect draft→final"] = (
                f"{sum(1 for r in dial if r['dialect'].get('draft_ok'))}→"
                f"{sum(1 for r in dial if r['dialect'].get('final_ok'))}/{len(dial)}")
        pert = [p for p in doc.get("perturbations", []) if p.get("applicable")]
        if pert:
            m["faults caught"] = _frac(sum(1 for p in pert if p.get("detected")), len(pert))
            m["by critic"] = _frac(sum(1 for p in pert if p.get("by_critic")), len(pert))
            m["by arbiter"] = _frac(sum(1 for p in pert if p.get("by_arbiter")), len(pert))
        alarms = doc.get("false_alarms") or {}
        if alarms:
            m["critic false blocks"] = _frac(alarms.get("critic_block", 0), alarms.get("runs", 0))
    elif section == "memory":
        s = memory.summarize(doc.get("memory", []))
        m["hybrid@1"] = _frac(s["hybrid"].get(1, 0), s["n"])
        m["hybrid@3"] = _frac(s["hybrid"].get(3, 0), s["n"])
        m["newest used"] = _frac(s["newest_ok"], s["valued"])
        m["stale used"] = _frac(s["stale_used"], s["valued"])
        m["conflicts flagged"] = _frac(s["flagged"], s["with_stale"])
    elif section == "replay":
        s = replay.summarize(doc.get("replay", []))
        n = s["n"] - s["errors"]
        m["language"] = _frac(s["language_ok"], n)
        m["numbers hit"] = _frac(s["numbers_hit"], s["numbers_ref"])
        m["numbers extra"] = str(s["numbers_extra"])
        m["chrF"] = str(s["chrf_mean"])
        m["ready"] = _frac(s["ready"], n)
    elif section == "banking":
        s = banking.summarize(doc.get("banking", []))

        def tot(key: str) -> tuple[int, int]:
            return (sum(d[key][0] for d in s.values()), sum(d[key][1] for d in s.values()))

        m["reply in language"] = _frac(*tot("reply_language"))
        m["region guessed"] = _frac(*tot("region"))
        m["fact stated"] = _frac(*tot("fact"))
        m["nothing invented"] = _frac(*tot("grounded"))
        m["dialect final"] = _frac(*tot("dialect_final"))
    elif section == "health":
        g = doc.get("health_grounded", [])
        if g:
            s = health.summarize_grounded(g)
            m["cited paired topic"] = _frac(*s["retrieved"])
            m["nothing invented (grounded)"] = _frac(*s["grounded"])
            m["chrF"] = str(s["chrf_mean"])
        p = doc.get("health_patients", [])
        if p:
            s = health.summarize_patients(p)
            m["patients safe"] = _frac(sum(d["safe"][0] for d in s.values()),
                                       sum(d["safe"][1] for d in s.values()))
    elif section == "massive":
        rows = doc.get("massive", [])
        ok = [r for r in rows if not r.get("error")]
        m["language"] = _frac(sum(1 for r in ok if r.get("language_ok")), len(ok))
        m["slots (lenient)"] = _frac(sum(r.get("slots_lenient", 0) for r in ok),
                                     sum(r.get("slots", 0) for r in ok))
    elif section == "flores":
        rows = doc.get("flores", [])
        ok = [r for r in rows if not r.get("error")]
        if ok:
            m["chrF"] = str(round(sum(r.get("chrf", 0) for r in ok) / len(ok), 1))
    return m


def compare(out: Path) -> str:
    """One table per section, conditions as columns."""
    found = load_experiment(out)
    conds = [c for c in CONDITIONS if c in found] + sorted(c for c in found if c not in CONDITIONS)
    lines = ["# Experiment: conditions side by side", ""]
    manifest = out / "manifest.json"
    if manifest.exists():
        mf = json.loads(manifest.read_text(encoding="utf-8"))
        lines.append(f"Provider {mf.get('provider')}, model {mf.get('model')}, "
                     f"{'quick subset' if mf.get('quick') else 'full sets'}, started "
                     f"{mf.get('started')}" + (f", finished {mf['finished']}" if mf.get(
                         "finished") else " (unfinished)") + ".")
        lines.append("")
    for section in SECTIONS:
        have = [c for c in conds if section in found[c]]
        if not have:
            continue
        metrics: dict[str, dict[str, str]] = {c: section_metrics(section, found[c][section])
                                              for c in have}
        keys: list[str] = []
        for c in have:
            for k in metrics[c]:
                if k not in keys:
                    keys.append(k)
        lines.append(f"## {section}")
        lines.append("")
        lines.append("| metric | " + " | ".join(have) + " |")
        lines.append("|---|" + "---|" * len(have))
        for k in keys:
            lines.append(f"| {k} | " + " | ".join(metrics[c].get(k, "") for c in have) + " |")
        lines.append("")
    lines.append("Every number is a count over the rows that ran; a column is a condition "
                 "(pipeline switches), see docs/EVAL.md. findings.md says what they mean.")
    return "\n".join(lines) + "\n"
