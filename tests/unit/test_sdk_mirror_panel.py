"""SDKMirrorPanel: snapshot dedup, child walk, unrecognised logging, invalidate."""
import json
import logging
import pytest

from engine.appc import top_window
from engine.appc.sdk_mirror_panel import SDKMirrorPanel
from engine.appc.windows import (
    _SubtitleWindow, _STStylizedWindow, STStylizedWindow_CreateW,
)


@pytest.fixture(autouse=True)
def _reset_tw():
    _STStylizedWindow._counter = 0
    top_window.reset_for_tests()


def _seed_subtitle():
    sw = _SubtitleWindow()
    top_window._the_top_window._main_windows[top_window.MWT_SUBTITLE] = sw
    return sw


def test_name_is_sdk_mirror():
    assert SDKMirrorPanel().name == "sdk-mirror"


def test_empty_state_returns_none():
    _seed_subtitle()
    p = SDKMirrorPanel()
    assert p.render_payload() is None


def test_visible_subtitle_emits_payload():
    sw = _seed_subtitle()
    sw.SetOn()
    p = SDKMirrorPanel()
    out = p.render_payload()
    assert out is not None and out.startswith("setSdkMirror(") and out.endswith(");")
    body = json.loads(out[len("setSdkMirror("):-len(");")])
    assert body["entries"][0]["type"] == "subtitle"
    assert body["entries"][0]["visible"] is True


def test_dedup_returns_none_on_unchanged_state():
    sw = _seed_subtitle()
    sw.SetOn()
    p = SDKMirrorPanel()
    assert p.render_payload() is not None
    assert p.render_payload() is None  # second call: no change → None


def test_stylized_window_appears_in_payload():
    _seed_subtitle()
    w = STStylizedWindow_CreateW("Brief")
    top_window._the_top_window.AddChild(w, 0.0, 0.0)
    p = SDKMirrorPanel()
    out = p.render_payload()
    body = json.loads(out[len("setSdkMirror("):-len(");")])
    titles = [e["title"] for e in body["entries"] if e["type"] == "stylized"]
    assert titles == ["Brief"]


def test_unrecognised_child_logged_once(caplog):
    _seed_subtitle()
    class _Bare: pass
    obj = _Bare()
    top_window._the_top_window.AddChild(obj, 0.0, 0.0)
    p = SDKMirrorPanel()
    with caplog.at_level(logging.INFO, logger="engine.appc.sdk_mirror_panel"):
        p.render_payload()
        p.invalidate()
        p.render_payload()  # second walk
    matching = [r for r in caplog.records if "_Bare" in r.message]
    assert len(matching) == 1


def test_tgobject_child_without_snapshot_is_not_serialized():
    """A bare TGObject child (e.g. QuickBattle's g_pPane TGPane on the
    TopWindow) must be treated as unrecognised, NOT serialized.

    TGObject.__getattr__ returns a _Stub for any attribute, so a naive
    hasattr(child, "_snapshot") is always True and calling the stub yields a
    _Stub that json.dumps cannot serialize. The panel must detect a *real*
    _snapshot via the MRO."""
    _seed_subtitle()
    from engine.core.ids import TGObject
    pane = TGObject()  # no real _snapshot — only the __getattr__ stub
    top_window._the_top_window.AddChild(pane, 0.0, 0.0)
    p = SDKMirrorPanel()
    # Must not raise (the bug raised TypeError inside json.dumps because the
    # stubbed _snapshot() returned a non-serializable _Stub). Only the
    # subtitle entry is present; the bare TGObject contributes nothing.
    out = p.render_payload()
    assert out is None  # subtitle is off → quiescent, no payload, no raise


def test_invalidate_forces_reemit():
    sw = _seed_subtitle()
    sw.SetOn()
    p = SDKMirrorPanel()
    assert p.render_payload() is not None
    assert p.render_payload() is None
    p.invalidate()
    assert p.render_payload() is not None


def test_dispatch_event_logs_click_and_returns_true(caplog):
    # The `/close` suffix is forward-looking: Task 8 JS will emit
    # `click:<id>` only. This richer input verifies the handler
    # tolerates sub-actions for future close-button work.
    p = SDKMirrorPanel()
    with caplog.at_level(logging.INFO, logger="engine.appc.sdk_mirror_panel"):
        handled = p.dispatch_event("click:stylized-3/close")
    assert handled is True
    assert any("stylized-3/close" in r.message for r in caplog.records)


def test_dispatch_event_unhandled_returns_false():
    p = SDKMirrorPanel()
    assert p.dispatch_event("garbage") is False
