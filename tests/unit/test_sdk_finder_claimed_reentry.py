"""Regression for 84367c5e: the claimed-namespace lookup in _SDKFinder must
tolerate re-entry while claimed.py itself is being imported. Exercised in a
CLEAN interpreter (pytest has already imported everything, which hides it)
through the game-side finder, tools.mission_harness.setup_sdk().

No SDK is involved: `Custom` is the finder's synthetic empty package (retail
has no Custom folder) and the stock modules are lifted from the install the
suite is configured with (spec 2026-11-11-no-sdk-runtime §4.2)."""
import subprocess
import sys
from pathlib import Path

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
    r = subprocess.run([sys.executable, "-I", "-c", _CODE], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "ok" in r.stdout
