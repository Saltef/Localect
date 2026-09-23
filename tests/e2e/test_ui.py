"""Drive the built UI in Chromium against the real server, and take screenshots."""

import json
import os
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
        assert final.startswith("مرحبا") and "٢" in final
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
