"""A hosted Localect in the browser: the public demo, the sign-in, and sign-out."""

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def hosted():
    port = _free_port()
    env = {**os.environ, "LOCALECT_DATA_DIR": tempfile.mkdtemp(), "LOCALECT_PROVIDER": "stub",
           "LOCALECT_PORT": str(port), "LOCALECT_OWNER_PASSWORD": "owner-pass-word",
           "LOCALECT_PUBLIC_MODE": "demo", "LOCALECT_PUBLIC_HOURLY": "5"}
    proc = subprocess.Popen([sys.executable, "-m", "localect.cli", "serve", "--no-browser"],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=1) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("server did not start:\n" + proc.stdout.read().decode()[-2000:])
    yield url
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def _launch(p):
    try:
        return p.chromium.launch()
    except Exception:  # noqa: BLE001
        root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
        exe = next(root.glob("chromium-*/chrome-linux/chrome"), None)
        return p.chromium.launch(executable_path=str(exe))


def test_visitor_sees_the_demo_and_the_owner_signs_in(hosted):
    with pw.sync_playwright() as p:
        browser = _launch(p)
        page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        page.goto(hosted)
        page.get_by_test_id("demo-banner").wait_for()
        banner = page.get_by_test_id("demo-banner").inner_text()
        assert "Public demo" in banner and "5 tries left" in banner
        assert page.get_by_test_id("nav-compose").count() == 1
        assert page.get_by_test_id("nav-settings").count() == 0
        # a visitor can compose on the demo store
        page.get_by_test_id("samples").select_option(index=1)
        page.get_by_role("button", name="Compose reply").click()
        page.get_by_test_id("result").wait_for(timeout=60000)
        # the banner refetches the count after the reply arrives
        page.get_by_test_id("demo-banner").get_by_text("4 tries left").wait_for()
        # the owner signs in from the demo
        page.get_by_test_id("owner-login").click()
        page.get_by_test_id("password").fill("wrong")
        page.get_by_role("button", name="Sign in").click()
        page.get_by_test_id("login-error").wait_for()
        page.get_by_test_id("password").fill("owner-pass-word")
        page.get_by_role("button", name="Sign in").click()
        page.get_by_test_id("nav-settings").wait_for()
        assert page.get_by_test_id("demo-banner").count() == 0
        page.get_by_test_id("logout").click()
        page.get_by_test_id("demo-banner").wait_for()
        browser.close()
