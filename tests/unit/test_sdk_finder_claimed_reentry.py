"""Regression for 84367c5e: the claimed-namespace lookup in _SDKFinder must
tolerate re-entry while claimed.py itself is being imported. Exercised in a
CLEAN interpreter (pytest has already imported everything, which hides it)
through the game-side finder, tools.mission_harness.setup_sdk()."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_CODE = """
import sys
sys.path.insert(0, %r)
import tools.mission_harness as h
h.setup_sdk()
import Custom.NanoFXv2.NanoFX_Lib
print("ok")
""" % str(ROOT)


def test_clean_interpreter_imports_nanofx_lib_through_the_game_finder():
    from engine import paths
    try:
        scripts = paths.sdk_scripts()
    except Exception as e:
        pytest.skip("no SDK scripts configured: %s" % e)
    if not Path(scripts).is_dir():
        pytest.skip("SDK scripts directory not present: %s" % scripts)
    r = subprocess.run([sys.executable, "-I", "-c", _CODE], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "ok" in r.stdout
