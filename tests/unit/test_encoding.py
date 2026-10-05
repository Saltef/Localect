"""Localect must read its own UTF-8 files even when the platform default is not UTF-8.

Windows defaults to a legacy code page (cp1252). We can't switch platforms in
CI, but we can force Python's default text encoding to ASCII in a subprocess
and confirm every loader still works. The probe is written to a UTF-8 file
because a C locale cannot even decode non-ASCII command-line arguments.
"""

import os
import subprocess
import sys

CODE = """
from localect.locales import load_starter_profiles
from localect.prompts import load
from localect.config import Settings
ps = load_starter_profiles()
eg = [p for p in ps if p.locale == "ar-EG"][0]
assert len(ps) == 12 and "\\u0623\\u0647\\u0644\\u0627\\u064b" in eg.greeting, eg.greeting
assert "Reader" in load("reader")
name = "\\u0635\\u0641\\u0627\\u0621"
s = Settings(user_name=name); s.save(); assert Settings.load().user_name == name
print("ok")
"""


def test_loaders_survive_non_utf8_default(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text(CODE, encoding="utf-8")
    env = {**os.environ, "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C",
           "LANG": "C", "LOCALECT_DATA_DIR": str(tmp_path / "data")}
    r = subprocess.run([sys.executable, str(probe)], env=env, capture_output=True, text=True,
                       encoding="utf-8")
    assert r.returncode == 0, r.stderr[-1500:]
    assert r.stdout.strip() == "ok"
