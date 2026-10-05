"""Every data file the package reads at runtime must ship in the wheel.

The editable install used by tests and CI sees the whole source tree, so a
data file missing from ``package-data`` only fails for real users. This test
checks the declared globs against the files actually present.
"""

import fnmatch
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "localect"


def test_every_non_python_file_under_the_package_is_declared_as_package_data():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    globs = pyproject["tool"]["setuptools"]["package-data"]["localect"]
    missing = []
    for f in SRC.rglob("*"):
        if not f.is_file() or f.suffix in (".py", ".pyc") or "__pycache__" in f.parts:
            continue
        rel = f.relative_to(SRC).as_posix()
        if not any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(rel, g.replace("**/", ""))
                   for g in globs):
            missing.append(rel)
    assert missing == [], f"add to [tool.setuptools.package-data] in pyproject.toml: {missing}"


def test_built_wheel_contains_the_sample_sets(tmp_path):
    import subprocess
    import sys
    import zipfile

    import pytest

    pytest.importorskip("pip")  # CI has it; a uv-made venv may not
    r = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-q",
                        "-w", str(tmp_path), str(ROOT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    wheel = next(tmp_path.glob("localect-*.whl"))
    names = set(zipfile.ZipFile(wheel).namelist())
    for needed in ("localect/evalset/heldout.yaml", "localect/evalset/injection.yaml",
                   "localect/locales/ar-EG.yaml", "localect/prompts/critic.md",
                   "localect/static/index.html"):
        assert needed in names, needed
