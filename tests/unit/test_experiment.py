import json
from pathlib import Path

from localect.config import Settings
from localect.evalx import experiment
from localect.evalx.diagnose import diagnose, render_findings

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "bench"


def _settings():
    return Settings(provider="stub", user_name="Safea")


def test_conditions_set_ablations_and_plan_names_only_sections_a_switch_can_change():
    s = experiment.condition_settings(_settings(), "no_critic")
    assert s.ablations == ["no_critic"] and _settings().ablations == []
    assert set(experiment.PLAN) == set(experiment.CONDITIONS)
    assert all(set(v) <= set(experiment.SECTIONS) for v in experiment.PLAN.values())
    assert "replay" in experiment.PLAN["no_voice"] and "heldout" not in experiment.PLAN["no_voice"]
    assert len(experiment.quick_indexes("heldout")) == 24
    assert len(experiment.quick_indexes("domains")) == 21


def _data_dir(tmp_path):
    """One folder with every dataset subfolder, the layout --data expects."""
    import shutil

    data = tmp_path / "data"
    for group in ("banking", "health"):
        for sub in (FIX / group).iterdir():
            shutil.copytree(sub, data / sub.name)
    return data


def test_experiment_runs_resumes_and_writes_the_two_summaries(tmp_path, settings, demo_con):
    out = tmp_path / "exp"
    FIX = _data_dir(tmp_path)  # noqa: N806
    m = experiment.run_experiment(_settings(), out, FIX, conditions=["base", "no_critic"],
                                  sections=["heldout", "domains", "banking", "health", "memory"],
                                  quick=True)
    assert set(m["runs"]) == {"base/heldout", "base/domains", "base/banking", "base/health",
                              "base/memory", "no_critic/heldout", "no_critic/domains"}
    assert (out / "base" / "heldout.json").exists()
    assert (out / "no_critic" / "domains.json").exists()
    assert not (out / "no_critic" / "banking.json").exists()
    doc = json.loads((out / "no_critic" / "heldout.json").read_text(encoding="utf-8"))
    assert doc["runs"] and not doc.get("partial")
    # without the Critic every planted fault is still caught by code or neutralized
    pert = [p for p in doc["perturbations"] if p["applicable"] and p["mutation"] != "slang"]
    assert pert and all(p["detected"] for p in pert) and not any(p["by_critic"] for p in pert)
    table = (out / "experiment.md").read_text(encoding="utf-8")
    assert "## heldout" in table and "| base | no_critic |" in table
    assert "## banking" in table and "region guessed" in table and "## memory" in table
    findings = (out / "findings.md").read_text(encoding="utf-8")
    assert "Findings" in findings and "What the Critic model adds (heldout)" in findings
    # a second run resumes: nothing reruns, the manifest keeps its entries
    m2 = experiment.run_experiment(_settings(), out, FIX, conditions=["base", "no_critic"],
                                   sections=["heldout", "domains", "banking", "health", "memory"],
                                   quick=True)
    assert m2["runs"] == m["runs"] and m2.get("finished")
    found = experiment.load_experiment(out)
    assert set(found) == {"base", "no_critic"} and "banking" in found["base"]


def _run(sample_id, **kw):
    r = {"sample_id": sample_id, "set": sample_id.split("-")[0], "label": "", "status": "ready",
         "locale": "en-US", "checks": {"locale": True, "preserved": True, "fact": True,
                                        "no_wrong": True, "terms": True, "no_leaks": True,
                                        "no_forbidden": True, "verified": True},
         "reading": {"language": "en", "region_guess": None}, "flags": [], "passed": True,
         "error": "", "revisions": 0}
    r.update(kw)
    r["passed"] = all(r["checks"].values()) and r["status"] != "escalate"
    return r


def test_diagnosis_attributes_failures_to_stages_and_ranks_safety_first():
    runs = [
        _run("en-GB-01", checks={"locale": False, "preserved": True, "fact": True,
                                 "no_wrong": True, "terms": True, "no_leaks": True,
                                 "no_forbidden": True, "verified": True},
             reading={"language": "en", "region_guess": None}),
        _run("inj-pt-13", label="Portuguese: injection, i_am_a_bot",
             checks={"locale": True, "preserved": True, "fact": True, "no_wrong": True,
                     "terms": True, "no_leaks": True, "no_forbidden": False, "verified": True}),
        _run("fr-FR-02", status="escalate", flags=["s3:drifted:block plural to singular"]),
        _run("ar-EG-01", checks={"locale": True, "preserved": True, "fact": False,
                                 "no_wrong": True, "terms": True, "no_leaks": True,
                                 "no_forbidden": True, "verified": True}),
    ]
    base = {"runs": runs, "perturbations": [
        {"applicable": True, "detected": True, "by_critic": True, "by_arbiter": False,
         "neutralized": False, "mutation": "slang"},
        {"applicable": True, "detected": True, "by_critic": False, "by_arbiter": True,
         "neutralized": False, "mutation": "change_number"}],
        "false_alarms": {"runs": 4, "critic_block": 1, "arbiter_block": 0, "arbiter_warn": 0}}
    no_critic = {"runs": [dict(r, status="ready") for r in runs], "perturbations": [
        {"applicable": True, "detected": False, "by_critic": False, "by_arbiter": False,
         "neutralized": False, "mutation": "slang"},
        {"applicable": True, "detected": True, "by_critic": False, "by_arbiter": True,
         "neutralized": False, "mutation": "change_number"}]}
    found = {"base": {"heldout": base}, "no_critic": {"heldout": no_critic}}
    fs = diagnose(found)
    titles = [f.title for f in fs]
    assert titles[0] == "The reply states what the message told it to"
    assert "The reply leaves out the knowledge base's number" in titles
    assert "Correct replies are escalated" in titles
    assert "The Reader gets the language but not the region" in titles
    critic = next(f for f in fs if f.title.startswith("What the Critic model adds"))
    assert "earns its call" in critic.evidence and "1 caught by the Critic alone" in critic.evidence
    text = render_findings(fs)
    assert text.startswith("# Findings") and "Lever: src/localect/prompts/drafter.md" in text
    assert "en-GB-01" in text and "inj-pt-13" in text
    assert render_findings([]).count("Nothing to report") == 1
