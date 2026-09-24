"""Embeddings and hybrid retrieval."""

import json
from pathlib import Path

import httpx
import pytest

from envoy import db
from envoy.config import Settings
from envoy.memory import import_paths
from envoy.memory.embed import (
    CohereEmbedder,
    HashEmbedder,
    OpenAICompatEmbedder,
    build_embedder,
    dot,
    from_bytes,
    to_bytes,
)
from envoy.memory.index import index_all, index_message, paragraphs
from envoy.memory.search import knowledge_search, mail_search
from envoy.models.base import ModelError

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mail"


def test_hash_embedder_is_unit_length_deterministic_and_cross_lingual():
    e = HashEmbedder()
    a, b = e.embed(["How long is the return window?", "How long is the return window?"])
    assert a == b and abs(dot(a, a) - 1.0) < 1e-6 and len(a) == 1024
    # The alias table folds translations of one concept into one feature, so a
    # Portuguese question lands nearer the English policy than an unrelated one.
    q = e.embed(["Qual é o prazo de devolução?"])[0]
    pol, other = e.embed(["Returns are accepted within 30 days of delivery.",
                          "Our office hours are 9 to 5 on weekdays."])
    assert dot(q, pol) > dot(q, other)
    ar = e.embed(["الشحن بياخد قد إيه؟"])[0]
    ship, hours = e.embed(["Orders ship within 2 business days.", "Support hours are 9 to 5."])
    assert dot(ar, ship) > dot(ar, hours)
    assert from_bytes(to_bytes(a))[:3] == pytest.approx(a[:3], abs=1e-6)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_compat_embedder_posts_to_embeddings_and_normalizes():
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["body"] = json.loads(req.read())
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [0.0, 2.0]}, {"index": 0, "embedding": [3.0, 4.0]}]})

    e = OpenAICompatEmbedder("http://127.0.0.1:11434/v1", "bge-m3")
    e._client = _client(handler)
    vecs = e.embed(["a", "b"])
    assert seen["path"] == "/v1/embeddings" and seen["body"] == {"model": "bge-m3",
                                                                   "input": ["a", "b"]}
    assert vecs == [[0.6, 0.8], [0.0, 1.0]] and e.dim == 2 and e.name == "openai:bge-m3"


def test_cohere_embedder_uses_v2_embed_with_input_types_and_batches():
    calls = []

    def handler(req):
        body = json.loads(req.read())
        calls.append((req.url.path, body["input_type"], len(body["texts"])))
        n = len(body["texts"])
        return httpx.Response(200, json={"embeddings": {"float": [[1.0, 0.0]] * n}})

    e = CohereEmbedder("k")
    e._client = _client(handler)
    assert e.embed(["q"], "query") == [[1.0, 0.0]]
    assert len(e.embed(["d"] * 100)) == 100
    assert calls == [("/v2/embed", "search_query", 1), ("/v2/embed", "search_document", 96),
                     ("/v2/embed", "search_document", 4)]
    assert e.name == "cohere:embed-multilingual-v3.0"

    def bad(req):
        return httpx.Response(401, json={"message": "invalid api token"})

    e._client = _client(bad)
    with pytest.raises(ModelError) as err:
        e.embed(["x"])
    assert "401" in str(err.value)


def test_build_embedder_follows_the_provider():
    assert build_embedder(Settings(provider="stub")).name == "hash-v1"
    assert build_embedder(Settings(provider="openai")).name == "hash-v1"  # no embed_model set
    assert build_embedder(Settings(provider="openai", embed_model="bge-m3")).name == "openai:bge-m3"
    assert build_embedder(Settings(provider="cohere", api_key="k")).name \
        == "cohere:embed-multilingual-v3.0"
    assert build_embedder(Settings(provider="cohere", api_key="k", embed_model="embed-v4.0")).name \
        == "cohere:embed-v4.0"
    assert build_embedder(Settings(provider="cohere")).name == "hash-v1"  # no key: offline


def test_index_all_is_idempotent_and_per_paragraph():
    con = db.connect()
    import_paths(con, [FIX], my_addresses=["safea@example.com"])
    e = HashEmbedder()
    n_mail = sum(1 for _ in paragraphs(con, "mail"))
    first = index_all(con, e)
    assert first == {"mail": n_mail, "knowledge": 3} and n_mail >= 12  # 3 paragraphs in the .md
    assert index_all(con, e) == {"mail": 0, "knowledge": 0}
    assert db.embedding_count(con) == {"knowledge:hash-v1": 3, "mail:hash-v1": n_mail}
    mid = db.message_add(con, text="New note.\n\nSecond paragraph.", date="2026-01-01T00:00:00Z")
    assert index_message(con, e, mid) == 2 and index_message(con, e, "nope") == 0
    db.message_delete(con, mid)
    assert db.embedding_count(con)["mail:hash-v1"] == n_mail


def test_hybrid_mail_search_finds_a_cross_lingual_match_and_keeps_the_priors():
    con = db.connect()
    import_paths(con, [FIX], my_addresses=["safea@example.com"])
    e = HashEmbedder()
    # Portuguese question, English mail: the token search alone finds it only
    # through the alias table; the fused ranking puts the newest statement first.
    hits = mail_search(con, e, "Qual é o prazo de devolução?")
    assert hits and "30 days" in hits[0]["text"] and hits[0]["date"].startswith("2025-09-10")
    assert {"id", "text", "subject", "date", "from_addr", "from_name", "is_mine", "start",
            "end"} <= set(hits[0])
    # contact prior survives fusion
    assert mail_search(con, e, "warranty", contact_email="layla@shop.example")[0]["text"] \
        == "Thanks Safea. And what about the warranty?"
    # language filter, and no embedder means the token search alone
    assert all(h["from_addr"] in ("omar@example.org", "safea@example.com")
               for h in mail_search(con, e, "الشحن", language="ar"))
    assert mail_search(con, None, "return window")[0]["text"].startswith("Good news")


def test_hybrid_knowledge_search_keeps_lexical_tie_breaks_for_the_stub():
    con = db.connect()
    db.knowledge_add(con, "Returns", "Returns are accepted within 30 days of delivery.\n\n"
                                     "Sale items: 14 days.")
    db.knowledge_add(con, "Hours", "Support hours are 9 to 5 on weekdays.")
    e = HashEmbedder()
    hits = knowledge_search(con, e, "prazo de devolução")
    assert hits[0]["title"] == "Returns" and hits[0]["start"] == 0
    assert hits[0]["text"].startswith("Returns are accepted")
    assert knowledge_search(con, None, "return") == db.knowledge_search(con, "return")
