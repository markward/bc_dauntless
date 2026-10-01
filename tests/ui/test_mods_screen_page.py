"""Static guard for the Mods screen page (no headless CEF render exists).

Asserts the page defines setModsScreen, is loaded by index.html, and only
emits event verbs ModsScreenPanel.dispatch_event accepts."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"
JS = (ROOT / "js" / "mods_screen.js").read_text()
HTML = (ROOT / "index.html").read_text()

ACCEPTED = {"tick", "tick-mod", "clear-ticks", "set", "star",
            "continue", "skip", "play", "quit"}


def test_index_loads_the_page():
    assert 'src="js/mods_screen.js"' in HTML
    assert 'href="css/mods_screen.css"' in HTML
    assert 'id="mods-screen"' in HTML


def test_defines_the_entry_point():
    assert "function setModsScreen(payload)" in JS


def test_only_emits_accepted_verbs():
    # msSend('<verb>...') -- possibly inside an onclick string as msSend(\'...
    # -- plus msSet(), which always sends 'set:'.
    verbs = set(re.findall(r"msSend\(\\?'([a-z-]+)", JS))
    if "msSet(" in JS:
        verbs.add("set")
    assert verbs and verbs <= ACCEPTED, verbs - ACCEPTED


def test_no_native_select_or_title_tooltips():
    assert "<select" not in JS and "title=" not in JS
