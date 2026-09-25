"""Drive the built UI in Chromium against the real server, and take screenshots."""

import json
import os
import re
import urllib.request
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

SHOTS = Path(__file__).resolve().parents[2] / "docs" / "screenshots"


def _launch(p):
    try:
        return p.chromium.launch()
    except Exception:  # noqa: BLE001 - version mismatch with a preinstalled browser
        root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
        exe = next(root.glob("chromium-*/chrome-linux/chrome"), None)
        if exe is None:
            raise
        return p.chromium.launch(executable_path=str(exe))


def test_health_reports_mcp(server):
    with urllib.request.urlopen(f"{server}/api/health") as r:
        h = json.loads(r.read())
    assert h["ok"] and h["mcp"] is True and h["provider"] == "stub"


def test_compose_flow_and_screenshots(server):
    SHOTS.mkdir(parents=True, exist_ok=True)
    with pw.sync_playwright() as p:
        browser = _launch(p)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="light")
        page = ctx.new_page()
        page.goto(server)
        page.get_by_test_id("nav-settings").click()
        page.get_by_role("button", name="Load demo data").click()
        page.get_by_test_id("demo").wait_for()
        assert "Loaded" in page.get_by_test_id("demo").inner_text()
        page.screenshot(path=str(SHOTS / "settings.png"))

        page.get_by_test_id("nav-compose").click()
        page.get_by_test_id("samples").select_option(label="Levantine Arabic: shipping and returns")
        assert "#4521" in page.get_by_test_id("message").input_value()
        page.get_by_role("button", name="Compose reply").click()
        page.get_by_test_id("result").wait_for(timeout=60000)
        assert "Ready to send" in page.get_by_test_id("result").inner_text()
        final = page.get_by_test_id("final").inner_text()
        assert final.startswith("مرحبا") and "within 2 business" in final
        assert page.get_by_test_id("final").get_attribute("dir") == "rtl"
        page.screenshot(path=str(SHOTS / "compose.png"), full_page=True)

        page.get_by_test_id("nav-glossary").click()
        page.get_by_text("SkyPack").first.wait_for()
        page.screenshot(path=str(SHOTS / "glossary.png"))

        page.get_by_test_id("nav-history").click()
        page.get_by_text("#4521").first.wait_for()

        dark = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="dark")
        dp = dark.new_page()
        dp.goto(server)
        dp.get_by_test_id("samples").select_option(label="English with an injection attempt")
        dp.get_by_role("button", name="Compose reply").click()
        dp.get_by_test_id("result").wait_for(timeout=60000)
        text = dp.get_by_test_id("final").inner_text().lower()
        assert "gift card" not in text and "full refund" not in text
        dp.screenshot(path=str(SHOTS / "compose-dark.png"), full_page=True)
        browser.close()
    assert (SHOTS / "compose.png").stat().st_size > 10_000


def test_memory_page_imports_reads_facts_and_settles_a_conflict(server):
    """Import the fixture mailbox from the Memory page, read it for facts, see
    the two return windows disagree, reject the old one."""
    from pathlib import Path

    fix = Path(__file__).resolve().parents[1] / "fixtures" / "mail" / "sample.mbox"
    with pw.sync_playwright() as p:
        browser = _launch(p)
        page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        page.goto(server)
        page.get_by_test_id("nav-settings").click()
        page.get_by_label("Your email address(es)").fill("safea@example.com")
        page.get_by_role("button", name="Save").first.click()
        page.get_by_role("button", name="Saved").first.wait_for()
        page.get_by_test_id("nav-memory").click()
        page.get_by_test_id("import-paths").fill(str(fix))
        page.get_by_role("button", name="Import").click()
        page.get_by_test_id("memory-note").wait_for()
        assert "5 message(s) stored (3 written by you)" in page.get_by_test_id(
            "memory-note").inner_text()
        page.get_by_test_id("message-row").first.wait_for()
        assert page.get_by_test_id("message-row").count() == 5
        page.get_by_role("button", name=re.compile(r"Read \d+ message")).click()
        page.get_by_text("fact(s) found").wait_for()
        page.get_by_test_id("fact-row").first.wait_for()  # the list refetches after the note
        assert page.get_by_test_id("fact-row").count() >= 2
        assert page.get_by_text("topic(s) with disagreeing facts").count() == 1
        page.screenshot(path=str(SHOTS / "memory.png"))
        # reject the older statement from the conflict card
        card = page.get_by_text("Facts that disagree").locator("xpath=ancestor::section")
        card.get_by_role("button").nth(3).click()  # second row: reject
        page.get_by_test_id("memory-search").fill("zz-nothing")
        page.get_by_test_id("memory-search").fill("")
        page.wait_for_function("!document.body.innerText.includes('disagreeing facts')")
        # a reply drawn from memory shows where each claim came from
        page.get_by_test_id("nav-compose").click()
        # a question only the imported mail can answer (the demo knowledge base cannot)
        page.get_by_test_id("message").fill("الشحن للإسكندرية بياخد قد إيه؟")
        page.get_by_role("button", name="Compose reply").click()
        page.get_by_test_id("result").wait_for(timeout=60000)
        # the panel must label every cited source by kind and, for memory, by who said it when
        labels = {"knowledge": "knowledge base", "mail": "your mail", "fact": "remembered fact",
                  "glossary": "glossary", "history": "past reply", "thread": "this thread"}
        with urllib.request.urlopen(f"{server}/api/history") as r:
            latest = json.loads(r.read())[0]["id"]
        with urllib.request.urlopen(f"{server}/api/history/{latest}") as r:
            res = json.loads(r.read())
        by_id = {x["id"]: x for x in res["sources"]}
        cited = [by_id[i] for e in res["ledger"] for i in e["source_ids"]]
        assert cited, "the stub always cites something for a shipping question"
        panel = page.get_by_test_id("sources").inner_text()
        summary = page.get_by_test_id("cited-summary").inner_text()
        for src in cited:
            assert labels[src["kind"]] in panel and f"from {labels[src['kind']]}" in summary
            if src["kind"] in ("mail", "fact"):
                assert src["meta"]["said"] in panel
        # open a message, exclude its thread, see it greyed out and listed; then pause capture
        page.get_by_test_id("nav-memory").click()
        page.get_by_text("Re: Return window").first.click()
        page.get_by_test_id("message-text").wait_for()
        page.get_by_role("button", name="Exclude this thread").click()
        page.get_by_test_id("exclusion-row").wait_for()
        assert page.get_by_text("excluded", exact=True).count() >= 1
        page.get_by_test_id("capture-toggle").click()
        page.get_by_text("capture paused").wait_for()
        page.screenshot(path=str(SHOTS / "memory.png"))
        browser.close()
