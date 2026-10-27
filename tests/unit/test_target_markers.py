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


def test_target_kind_accepted():
    target_markers.clear()
    target_markers.set_marker("Galor-1", "target")
    assert target_markers.marker_for("Galor-1") == "target"
    with pytest.raises(ValueError):
        target_markers.set_marker("Galor-1", "bogus")
    target_markers.clear()


def test_js_renders_target_crosshair_and_keeps_shield():
    root = pathlib.Path(__file__).resolve().parents[2]
    js = (root / "native/assets/ui-cef/js/target_list.js").read_text()
    assert "row.marker === 'target'" in js
    assert "target-list__marker--target" in js
    assert "row.marker === 'protect'" in js
    i = js.index("row.marker === 'target'")
    assert "<svg" in js[i:i + 900]
