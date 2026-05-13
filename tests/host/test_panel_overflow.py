"""Regression checks for components.rcss scrollbar styling.  A prior
attempt at custom slidertrack/sliderbar rules rendered as a giant blue
block (RmlUi appears to render scrollbar chrome unconstrained when only
the bar/track are styled without their parent scrollbarvertical
container)."""
from pathlib import Path


_RCSS = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui" / "components.rcss"


def _rcss_text():
    return _RCSS.read_text(encoding="utf-8")


def test_components_rcss_does_not_style_sliderbar_directly():
    """Regression: a bare `sliderbar { background-color: ... }` rule made
    the scrollbar chrome render as a giant blue block over the panel
    body.  The correct RmlUi pattern wraps slidertrack/sliderbar inside
    a scrollbarvertical container — until we adopt that, no custom
    scrollbar styling at all."""
    text = _rcss_text()
    # Allow the word "sliderbar" inside comments; check for an actual rule.
    # An RCSS rule begins with the selector at column 0 followed by '{'.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("sliderbar") and "{" in stripped:
            raise AssertionError(
                "components.rcss contains a bare `sliderbar` rule — "
                "this rendered as a giant blue block in the panel body."
            )
