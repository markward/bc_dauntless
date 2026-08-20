"""Every CEF panel script must PARSE.

This exists because of a real failure. Adding a Warp button to the star map
introduced a second `const warpEl` in one function — colliding with the
warp-POINT list already declared there — which is a SyntaxError. The whole
file then failed to parse, so `setStarMapPanel` was never defined and the
DOMContentLoaded handlers never attached: the panel rendered its native GL
map (driven from Python, independent of CEF) with no chrome at all and
ignored the mouse entirely.

Nothing caught it. The CEF asset tests assert that strings appear in the
files — `"warp_label" in js` passes just as happily in a file that cannot
parse — and no Python test executes JS. A whole panel can be dead while the
suite is green, and the only signal is a live run.

Parsing is the cheapest real check available: it needs no DOM, no CEF and no
browser. It cannot catch logic errors, but it catches the class that silently
disables an entire panel.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

JS_DIR = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef" / "js"

_NODE = shutil.which("node")

_SCRIPTS = sorted(JS_DIR.glob("*.js"))


def test_there_are_scripts_to_check():
    """Guard the guard: a bad glob would make every case below vanish and the
    file would still report as passing."""
    assert len(_SCRIPTS) > 5, [p.name for p in _SCRIPTS]


@pytest.mark.skipif(_NODE is None, reason="node not available to parse JS")
@pytest.mark.parametrize("script", _SCRIPTS, ids=lambda p: p.name)
def test_panel_script_parses(script):
    result = subprocess.run([_NODE, "--check", str(script)],
                            capture_output=True, text=True)
    assert result.returncode == 0, (
        script.name + " does not parse — CEF would fail to define its render "
        "function and to attach its event handlers, leaving the panel dead "
        "and unresponsive with the suite green:\n" + result.stderr)
