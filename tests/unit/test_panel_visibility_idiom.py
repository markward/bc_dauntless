"""Panels write visibility through the setter, everywhere but __init__.

This is an IDIOM test, not a correctness one — PanelRegistry observes
visibility flips itself now (774f4c8d), so a direct `_visible` write no
longer strands chrome on screen. It did for months: the registry's
hidden-panel skip was safe only if the flip was announced, the announcing
lived in the `Panel.visible` setter, and six panels bypassed it in `close()`.
ESC then killed a panel's GL half and left its CEF half drawn (star map,
QuickBattle setup — both confirmed live).

Keeping one idiom is what stops that history being re-learned. The rule is
mechanical, so it is checked mechanically rather than left in a comment that
the next panel author may not read.

`__init__` is exempt on purpose: it runs before registration, nothing is
observing yet, and the base class starts every panel due anyway.
"""
import re
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "engine" / "ui"


def _direct_writes_outside_init(path):
    """(line_no, text) for every `self._visible = ...` not inside __init__."""
    lines = path.read_text(encoding="utf-8").splitlines()
    out, method = [], None
    for i, line in enumerate(lines, start=1):
        m = re.match(r"\s*def\s+(\w+)", line)
        if m:
            method = m.group(1)
        if re.search(r"self\._visible\s*=", line) and method != "__init__":
            out.append((i, line.strip()))
    return out


def test_panels_set_visibility_through_the_setter():
    offenders = []
    for path in sorted(UI.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        # Only real Panel subclasses; panel.py itself IS the setter.
        if path.name == "panel.py" or "Panel)" not in src:
            continue
        for line_no, text in _direct_writes_outside_init(path):
            offenders.append(f"{path.name}:{line_no}  {text}")

    assert not offenders, (
        "write visibility through the `visible` SETTER outside __init__, so "
        "every panel reads the same way:\n  " + "\n  ".join(offenders))


def test_the_check_can_actually_see_a_direct_write():
    """Guard against the scan silently matching nothing — a regex typo or a
    changed base-class name would make the test above pass vacuously forever.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "fake_panel.py"
        p.write_text(
            "class FakePanel(Panel):\n"
            "    def __init__(self):\n"
            "        self._visible = False\n"     # exempt
            "    def close(self):\n"
            "        self._visible = False\n",    # offender
            encoding="utf-8")
        found = _direct_writes_outside_init(p)

    assert [n for n, _ in found] == [5], found


def test_at_least_one_real_panel_is_being_scanned():
    """The other half of the same guard: prove the glob and the Panel-subclass
    filter actually select files, so a rename cannot empty the sweep."""
    scanned = [p.name for p in sorted(UI.glob("*.py"))
               if p.name != "panel.py"
               and "Panel)" in p.read_text(encoding="utf-8")]
    assert "star_map_panel.py" in scanned, scanned
    assert len(scanned) >= 6, scanned
