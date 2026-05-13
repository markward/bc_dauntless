"""The .bc-panel-body rule in components.rcss declares overflow-y: auto
and a tunable max-height so long target lists scroll.  Scrollbar rules
match the panel palette.

This test asserts the file's textual content; it doesn't execute RmlUi.
A runtime check would require parsing the compiled DOM, which our test
harness doesn't expose."""
from pathlib import Path


_RCSS = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui" / "components.rcss"


def _rcss_text():
    return _RCSS.read_text(encoding="utf-8")


def test_bc_panel_body_has_overflow_y_auto():
    text = _rcss_text()
    # The .bc-panel-body block must include overflow-y: auto somewhere.
    # Use a substring check rather than parsing CSS — RmlUi's RCSS dialect
    # isn't a perfect CSS subset.
    body_block_start = text.index(".bc-panel-body")
    body_block_end   = text.index("}", body_block_start)
    body_block = text[body_block_start:body_block_end]
    assert "overflow-y" in body_block
    assert "auto" in body_block


def test_bc_panel_body_has_max_height():
    text = _rcss_text()
    body_block_start = text.index(".bc-panel-body")
    body_block_end   = text.index("}", body_block_start)
    body_block = text[body_block_start:body_block_end]
    assert "max-height" in body_block


def test_components_rcss_styles_vertical_scrollbar():
    text = _rcss_text()
    assert "scrollbar-vertical" in text
    assert "sliderbar"          in text
