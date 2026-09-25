"""Importing past mail: parsing, cleaning, storage, search."""

import asyncio
from pathlib import Path

import pytest

from envoy import db
from envoy.memory import import_paths
from envoy.memory.clean import clean_body, html_to_text, strip_quotes, strip_signature
from envoy.memory.embed import HashEmbedder
from envoy.memory.facts import extract_pending
from envoy.memory.parse import iter_eml, iter_mbox
from envoy.memory.search import mail_search as hybrid
from envoy.models.stub import StubModel

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mail"


def test_quotes_are_cut_in_every_language():
    for header in ["On Sun, 31 Aug 2025 at 18:02, Layla <l@x> wrote:",
                   "Le mar. 2 sept. 2025 à 10:00, Marc <m@x> a écrit :",
                   "El mar, 2 sept 2025 a las 10:00, Ana <a@x> escribió:",
                   "Em ter., 2 de set. de 2025 às 10:00, Rui <r@x> escreveu:",
                   "Am Di., 2. Sept. 2025 um 10:00 Uhr schrieb Uwe <u@x>:",
                   "2025/09/02 10:00 田中 <t@x>:",
                   "في الثلاثاء، 2 سبتمبر 2025، كتب عمر:",
                   "-----Original Message-----",
                   "-----Mensaje original-----",
                   "From: Jo <jo@x>"]:
        text = f"Mine.\n\n{header}\n> theirs\n"
        assert strip_quotes(text) == "Mine.", header
    assert strip_quotes("Mine.\n> theirs\n> more") == "Mine."
    assert strip_quotes("No quotes here.") == "No quotes here."


def test_signatures_and_sent_from_lines_are_dropped():
    assert strip_signature("Body.\n-- \nSafea\nSupport") == "Body."
    assert strip_signature("Body.\n--\nSafea") == "Body."
    assert strip_signature("Body.\n\nSent from my iPhone") == "Body."
    assert strip_signature("Body.\n\nEnviado desde mi iPhone") == "Body."


def test_html_becomes_text_without_styles_or_quoted_blocks():
    html = ("<html><head><style>p{color:red}</style><title>t</title></head><body>"
            "<p>Hi&nbsp;Layla,</p><p>Window is <b>30 days</b>.</p>"
            "<blockquote>old text</blockquote><div>Bye</div></body></html>")
    assert html_to_text(html) == "Hi Layla,\n\nWindow is 30 days.\n\nBye"
    assert clean_body(html, html=True) == "Hi Layla,\n\nWindow is 30 days.\n\nBye"


def test_mbox_parsing_decodes_headers_charsets_and_threads():
    msgs = list(iter_mbox(FIX / "sample.mbox"))
    assert len(msgs) == 7
    m1 = msgs[0]
    assert m1.external_id == "m1@example.com" and m1.from_addr == "safea@example.com"
    assert m1.from_name == "Safea" and m1.to_addrs == ["layla@shop.example"]
    assert m1.date == "2025-09-01T07:00:00Z"
    assert m1.text == "Hi Layla,\n\nOur return window is 14 days from delivery. Items must be " \
                      "unused.\n\nBest,\nSafea"
    assert msgs[1].thread_id == "m1@example.com" and msgs[1].text.endswith("warranty?")
    assert msgs[2].text == "Hi Layla,\n\nGood news: from this month the return window is 30 " \
                           "days from delivery.\n\nWarm regards,\nSafea"
    assert msgs[4].from_name == "عمر فريد" and msgs[4].subject == "الشحن إلى الإسكندرية"
    assert msgs[5].text.endswith("صفاء") and "كتب" not in msgs[5].text
    assert msgs[6].text == ""  # attachment only


def test_eml_parsing_handles_outlook_style_quotes_and_cc():
    (m,) = list(iter_eml(FIX / "warranty.eml"))
    assert m.to_addrs == ["jo@partner.example", "team@example.com"]
    assert m.text.endswith("Kind regards,\nSafea") and "Original Message" not in m.text


def test_import_is_idempotent_marks_mine_and_adds_documents():
    con = db.connect()
    r = import_paths(con, [FIX], my_addresses=["Safea@Example.com"])
    assert (r.files, r.messages, r.mine, r.duplicates, r.empty, r.documents) == (3, 6, 4, 1, 1, 1)
    assert r.skipped == [str(FIX / "ignore.bin")]
    assert "6 message(s) stored (4 written by you)" in r.summary()
    assert db.message_count(con) == {"messages": 6, "mine": 4, "excluded": 0}
    again = import_paths(con, [FIX / "sample.mbox"], my_addresses=["safea@example.com"])
    assert again.messages == 0 and again.duplicates == 6  # 5 unique + the repeated m3
    assert db.message_count(con)["messages"] == 6
    assert [k["title"] for k in db.knowledge_list(con)] == ["shipping-policy"]
    langs = {m["from_addr"]: m["language"] for m in db.message_list(con)}
    assert langs["omar@example.org"] == "ar" and langs["safea@example.com"] == "en"


def test_mail_search_prefers_the_newest_statement_and_the_contact():
    con = db.connect()
    import_paths(con, [FIX], my_addresses=["safea@example.com"])
    hits = db.mail_search(con, "how long is the return window")
    assert hits and hits[0]["text"].startswith("Good news: from this month the return window is "
                                                "30 days")
    assert hits[0]["is_mine"] and hits[0]["date"].startswith("2025-09-10")
    assert hits[0]["id"].endswith(":11") and hits[0]["subject"] == "Return window update"
    older = [h for h in hits if "14 days" in h["text"]]
    assert older, "the superseded statement is still retrievable, ranked below"
    # the contact being answered outranks an equal match with someone else
    assert db.mail_search(con, "warranty", contact_email="jo@partner.example")[0]["from_addr"] \
        == "safea@example.com"
    assert db.mail_search(con, "warranty", contact_email="layla@shop.example")[0]["text"] \
        == "Thanks Safea. And what about the warranty?"
    # cross-script: Arabic query finds the Arabic reply, language filter respected
    assert "٣ لـ ٥" in db.mail_search(con, "الشحن للإسكندرية", language="ar")[0]["text"]
    assert db.mail_search(con, "", language="ar") == []


def test_message_list_get_delete():
    con = db.connect()
    import_paths(con, [FIX / "warranty.eml"], my_addresses=["safea@example.com"])
    (m,) = db.message_list(con)
    assert m["preview"].startswith("Hi Jo") and m["size"] > 50 and m["origin"] == "import"
    assert db.message_list(con, query="nothing-like-this") == []
    assert db.message_get(con, m["id"])["text"].startswith("Hi Jo")
    db.message_delete(con, m["id"])
    assert db.message_count(con)["messages"] == 0


def test_exclusions_hide_threads_and_addresses_from_every_search():
    con = db.connect()
    import_paths(con, [FIX], my_addresses=["safea@example.com"])
    asyncio.run(extract_pending(con, StubModel()))
    assert db.facts_search(con, "return window")
    # exclude the return-window thread: its messages leave search, facts, voice and extraction
    xid = db.exclusion_add(con, "thread", "m1@example.com", "2026-01-01T00:00:00Z")
    assert db.message_count(con)["excluded"] == 2
    assert all("14 days" not in h["text"] for h in db.mail_search(con, "return window"))
    assert any("30 days" in h["text"] for h in db.mail_search(con, "return window"))  # other thread
    assert all("14 days" not in h["text"] for h in hybrid(con, HashEmbedder(), "return window"))
    assert all("14" != f["value"] for f in db.facts_search(con, "return window"))
    assert all(not v["text"].startswith("Hi Layla,\n\nOur return") for v in
               db.voice_examples(con, "en"))
    (rule,) = db.exclusion_list(con)
    assert rule["kind"] == "thread" and rule["messages"] == 2 and rule["id"] == xid
    assert db.exclusion_add(con, "thread", "m1@example.com") == xid  # idempotent
    # an address rule catches senders and recipients, and applies to new messages too
    db.exclusion_add(con, "address", "Omar@Example.org")
    assert db.message_count(con)["excluded"] == 4
    mid = db.message_add(con, text="Later note to Omar with 9 items.",
                         from_addr="safea@example.com", to_addrs="omar@example.org",
                         date="2026-02-01T00:00:00Z")
    assert db.message_get(con, mid)["excluded"] == 1 and db.messages_unextracted(con) == []
    # removing a rule brings the messages back
    db.exclusion_delete(con, xid)
    assert db.message_count(con)["excluded"] == 3
    assert any("14 days" in h["text"] for h in db.mail_search(con, "return window"))
    with pytest.raises(ValueError):
        db.exclusion_add(con, "banana", "x")
    with pytest.raises(ValueError):
        db.exclusion_add(con, "address", "  ")


def test_raw_rfc822_files_without_an_extension_import_like_eml():
    """Maildir exports and the Enron corpus store one raw message per file with
    no extension; the importer must read them, and the replay must pair them."""
    from envoy.evalx.replay import find_pairs

    con = db.connect()
    r = import_paths(con, [FIX.parent / "enron-style"], my_addresses=["mark.taylor@enron.com"])
    assert (r.files, r.messages, r.mine, r.skipped) == (2, 2, 1, [])
    sent = next(m for m in db.message_list(con) if m["is_mine"])
    assert sent["subject"] == "RE: ISDA with Bank X" and sent["date"] == "2001-09-12T21:22:00Z"
    assert "Original Message" not in db.message_get(con, sent["id"])["text"]
    (pair,) = find_pairs(con)
    assert pair.incoming["from_addr"] == "sara.shackleton@enron.com" and pair.reply["is_mine"]
    assert (FIX / "ignore.bin").exists() and import_paths(con, [FIX / "ignore.bin"]).skipped
