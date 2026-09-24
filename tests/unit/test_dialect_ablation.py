import asyncio

from envoy import db
from envoy.config import Settings
from envoy.demo import seed_demo
from envoy.eval import dialect_ablation, render_table, run_eval, to_json
from envoy.locales import seed_locales


class MarkerScorer:
    """Labels Portuguese by the one marker Envoy's stub reliably shows: the
    Brazilian greeting 'Olá' never reaches the body, so the body scorer must
    rely on the text itself."""

    name = "marker"
    language = "pt"

    def predict(self, text):
        low = text.lower()
        if "estamos a" in low or "encomenda" in low:
            return "pt-PT"
        return "pt-BR" if "você" in low or "business" in low else None


def test_ablation_reports_draft_and_final_per_locale():
    con = db.connect()
    seed_locales(con)
    seed_demo(con)
    settings = Settings(provider="stub", user_name="Safea")
    rows = asyncio.run(run_eval(settings, con=con, sample_set="heldout",
                                scorers={"pt": MarkerScorer()}))
    pt = [r for r in rows if r.locale.startswith("pt-")]
    assert pt and all(r.dialect["scorer"] == "marker" for r in pt)
    assert all(not r.dialect for r in rows if not r.locale.startswith("pt-"))
    one = pt[0].dialect
    assert set(one) == {"scorer", "target", "draft", "final", "draft_ok", "final_ok"}
    table = render_table(rows)
    assert "dialect (judged by marker)" in table and "pt-BR" in table and "pt-PT" in table
    assert '"dialect"' in to_json(rows)


def test_ablation_excludes_greeting_and_signoff():
    con = db.connect()
    seed_locales(con)
    seed_demo(con)
    settings = Settings(provider="stub", user_name="Safea")
    rows = asyncio.run(run_eval(settings, con=con, sample_set="heldout", indexes=[0],
                                scorers={}))
    r = rows[0].result
    seen = []

    class Spy:
        name, language = "spy", r.locale.language

        def predict(self, text):
            seen.append(text)
            return None

    d = dialect_ablation(r, Spy())
    assert d["draft_ok"] is False and d["final_ok"] is False
    greeting, signoff = r.rewrite.segments[0].text, r.rewrite.segments[-1].text
    assert all(greeting not in t and signoff not in t for t in seen)
