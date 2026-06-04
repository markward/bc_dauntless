"""End-to-end: TGCreditAction.Play → SDKMirrorPanel payload contains text.

Uses monkeypatched time.monotonic so expiry is deterministic.
"""
import json
import pytest

from engine.appc import top_window
from engine.appc.actions import TGCreditAction_Create
from engine.appc.sdk_mirror_panel import SDKMirrorPanel
from engine.appc.windows import _STStylizedWindow, STStylizedWindow_CreateW


@pytest.fixture(autouse=True)
def _reset_tw():
    _STStylizedWindow._counter = 0
    top_window.reset_for_tests()


def _decode(payload: str) -> dict:
    assert payload.startswith("setSdkMirror(")
    assert payload.endswith(");")
    return json.loads(payload[len("setSdkMirror("):-len(");")])


def test_credit_action_text_reaches_mirror_payload(monkeypatch):
    fake_now = [100.0]
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: fake_now[0])
    monkeypatch.setattr("engine.appc.sdk_mirror_panel.time.monotonic", lambda: fake_now[0])

    subtitle = top_window._the_top_window.FindMainWindow(top_window.MWT_SUBTITLE)
    panel = SDKMirrorPanel()

    # Pre-play: nothing visible, payload is None.
    assert panel.render_payload() is None

    # Play a 5-second banner.
    TGCreditAction_Create("Disable the patrol", subtitle, 0.0, 0.0, 5.0).Play()

    out = panel.render_payload()
    body = _decode(out)
    subtitle_entry = next(e for e in body["entries"] if e["type"] == "subtitle")
    assert subtitle_entry["lines"] == ["Disable the patrol"]

    # Same state → next render returns None.
    assert panel.render_payload() is None

    # Advance time past expiry; payload should re-emit without the text.
    fake_now[0] = 110.0
    out2 = panel.render_payload()
    body2 = _decode(out2)
    subtitle_entries = [e for e in body2["entries"] if e["type"] == "subtitle"]
    # With subtitle still off (only set on by SetOn — TGCreditAction didn't
    # touch _visible) and no active texts, the subtitle entry is absent.
    assert subtitle_entries == []


def test_stylized_window_and_subtitle_coexist_in_payload(monkeypatch):
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    monkeypatch.setattr("engine.appc.sdk_mirror_panel.time.monotonic", lambda: 0.0)
    subtitle = top_window._the_top_window.FindMainWindow(top_window.MWT_SUBTITLE)
    subtitle.SetOn()

    w = STStylizedWindow_CreateW("Mission Briefing")
    top_window._the_top_window.AddChild(w, 100.0, 50.0)

    panel = SDKMirrorPanel()
    body = _decode(panel.render_payload())
    types = {e["type"] for e in body["entries"]}
    assert types == {"subtitle", "stylized"}
    stylized = next(e for e in body["entries"] if e["type"] == "stylized")
    assert stylized["title"] == "Mission Briefing"
    assert stylized["id"] == "stylized-1"
