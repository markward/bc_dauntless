"""A viewscreen hail engages the bridge maincamera zoom (forward, fallback FOV)."""
import pytest
import engine.host_loop as hl
from engine.appc.bridge_set import ZoomCameraObjectClass
from engine.appc.character_position_zoom import POSITION_ZOOM_SENTINEL


class _RemoteChar:
    """Hailed character with no authored bridge position-zoom (GetPositionZoom
    misses -> sentinel), mirroring E1M1 Liu = SetLocation('StarbaseSeated')."""
    def GetLocation(self):
        return "StarbaseSeated"
    def GetPositionZoom(self, loc):
        return POSITION_ZOOM_SENTINEL


class _Controller:
    def __init__(self, char):
        self._char = char
    # _active_comm_feed is monkeypatched to key off this.


def test_hail_resolves_forward_fallback_engagement(monkeypatch):
    char = _RemoteChar()
    ctrl = _Controller(char)
    monkeypatch.setattr(hl, "_active_comm_feed", lambda c: (7, object()))
    monkeypatch.setattr(hl, "_hailed_character", lambda c: char)
    out = hl._viewscreen_hail_engagement(ctrl)
    assert out is not None
    got_char, factor = out
    assert got_char is char
    assert factor == pytest.approx(hl._VIEWSCREEN_ZOOM_FALLBACK)   # sentinel -> 0.5


def test_no_hail_returns_none(monkeypatch):
    monkeypatch.setattr(hl, "_active_comm_feed", lambda c: None)
    assert hl._viewscreen_hail_engagement(_Controller(None)) is None
