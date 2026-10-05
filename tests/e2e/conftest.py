import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server():
    """Boot the real app (MCP servers included) on a temp data dir."""
    port = _free_port()
    env = {**os.environ, "LOCALECT_DATA_DIR": tempfile.mkdtemp(), "LOCALECT_PROVIDER": "stub",
           "LOCALECT_PORT": str(port)}
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
