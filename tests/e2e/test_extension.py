"""The browser extension, loaded into Chromium against the real server: pairing
through its options page, capture on send from a page that speaks the generic
adapter's contract, and the on-page indicator."""

import http.server
import json
import os
import shutil
import tempfile
import threading
import urllib.request
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

EXT = Path(__file__).resolve().parents[2] / "extension"
FIX = Path(__file__).resolve().parent / "fixtures"


def _test_extension() -> Path:
    """A copy of the extension whose generic adapter also runs on the fixture
    page's origin (the shipped manifest matches mail sites only)."""
    out = Path(tempfile.mkdtemp()) / "ext"
    shutil.copytree(EXT, out)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    m["content_scripts"].append({"matches": ["http://127.0.0.1/*", "http://localhost/*"],
                                 "js": ["content/core.js", "content/generic.js",
                                        "content/indicator.js"], "run_at": "document_idle"})
    (out / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    return out


@pytest.fixture(scope="module")
def page_server():
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(FIX), **k)  # noqa: E731
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def _launch_with_extension(p, ext: Path):
    args = [f"--disable-extensions-except={ext}", f"--load-extension={ext}", "--headless=new"]
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    exe = next(root.glob("chromium-*/chrome-linux/chrome"), None)
    kw = {"headless": False, "args": args}
    if exe is not None:
        kw["executable_path"] = str(exe)
    return p.chromium.launch_persistent_context(tempfile.mkdtemp(), **kw)


def test_extension_pairs_captures_on_send_and_shows_the_indicator(server, page_server):
    token = _get(f"{server}/api/extension/token")["token"]
    before = _get(f"{server}/api/messages")["counts"]["messages"]
    ext = _test_extension()
    with pw.sync_playwright() as p:
        ctx = _launch_with_extension(p, ext)
        try:
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event(
                "serviceworker")
            ext_id = sw.url.split("/")[2]
            # pair through the options page
            opts = ctx.new_page()
            opts.goto(f"chrome-extension://{ext_id}/options/options.html")
            opts.fill("#server", server)
            opts.fill("#token", token)
            opts.click("#save")
            opts.wait_for_function("document.getElementById('msg').textContent.includes('Paired')")
            assert "Paired with Envoy" in opts.text_content("#msg")
            # the fixture "mail client": indicator on, send captures both messages
            page = ctx.new_page()
            page.goto(f"{page_server}/compose.html")
            page.wait_for_selector("[data-envoy-indicator]")
            page.wait_for_function("document.querySelector('[data-envoy-indicator]')"
                                   ".textContent.includes('remembering')")
            page.fill('[data-envoy="body"]',
                      "Hi Layla,\n\nYou have 30 days from delivery.\n\nBest,\nSafea")
            page.click('[data-envoy="send"]')
            page.wait_for_function(
                "document.querySelector('[data-envoy-indicator]').dataset.envoyLast === 'stored'")
            assert "Remembered" in page.text_content("[data-envoy-indicator]")
            # pausing the site from the pill stops capture without touching the server
            page.click("[data-envoy-indicator]")
            page.wait_for_function("document.querySelector('[data-envoy-indicator]')"
                                   ".textContent.includes('off on generic')")
            page.click('[data-envoy="send"]')
            page.wait_for_function(
                "document.querySelector('[data-envoy-indicator]').dataset.envoyLast === 'skipped'")
        finally:
            ctx.close()
    listing = _get(f"{server}/api/messages")
    assert listing["counts"]["messages"] == before + 2
    mine = next(m for m in listing["messages"] if m["is_mine"] and m["origin"] == "capture"
                and m["subject"] == "Re: Returns")
    theirs = next(m for m in listing["messages"] if not m["is_mine"] and m["from_addr"]
                  == "layla@shop.example")
    assert mine["to_addrs"] == "layla@shop.example" and mine["thread_id"] == "thread-42"
    assert theirs["thread_id"] == "thread-42" and theirs["external_id"] == "msg-777"
    detail = _get(f"{server}/api/messages/{mine['id']}")
    assert detail["text"].startswith("Hi Layla") and detail["facts"], "read for facts on arrival"
    # leave the shared server as it was for the other end-to-end tests
    for m in (mine, theirs):
        urllib.request.urlopen(urllib.request.Request(f"{server}/api/messages/{m['id']}",
                                                      method="DELETE")).read()
    assert _get(f"{server}/api/messages")["counts"]["messages"] == before
