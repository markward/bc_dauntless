import pathlib

import pytest

from engine.ui import target_markers


def test_markers_set_clear_and_reset():
    target_markers.clear()
    assert target_markers.marker_for("Kor") is None
    target_markers.set_marker("Kor", "protect")
    assert target_markers.marker_for("Kor") == "protect"
    assert target_markers.marker_for("Other") is None
    target_markers.clear_marker("Kor")
    assert target_markers.marker_for("Kor") is None
    target_markers.clear_marker("Kor")
    target_markers.set_marker("A", "protect")
    target_markers.set_marker("B", "protect")
    target_markers.clear()
    assert target_markers.marker_for("A") is None
    assert target_markers.marker_for("B") is None


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        target_markers.set_marker("Kor", "bogus")


def test_js_emits_marker_span():
    root = pathlib.Path(__file__).resolve().parents[2]
    js = (root / "native/assets/ui-cef/js/target_list.js").read_text()
    assert "target-list__marker--" in js
    assert "row.marker" in js
