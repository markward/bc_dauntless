"""A viewscreen hail engages the bridge maincamera zoom (forward, fallback FOV)."""
import pytest
import engine.host_loop as hl
from engine.appc.bridge_set import ZoomCameraObjectClass
from engine.appc.character_position_zoom import POSITION_ZOOM_SENTINEL
from engine.appc.characters import CharacterClass as _CharacterClass


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


# ── _hailed_character ────────────────────────────────────────────────────────
# MissionLib.ViewscreenOn(pcName) only runs HideCharacters + the SetHidden(0)
# un-hide when pcName is truthy; ViewscreenOn(None, "Set") (real SDK usage,
# e.g. E4M5/E4M6/E3M1) leaves the set's un-hidden count at whatever it already
# was. _hailed_character must treat "exactly one un-hidden" as the only
# unambiguous single-hailer signal.

class _Char(_CharacterClass):
    """A minimal realized CharacterClass, so GetClassObjectList(CharacterClass)
    (the real isinstance-filtered enumeration _iter_set_characters uses) picks
    it up."""
    def __init__(self, hidden, has_instance=True):
        super().__init__()
        self.SetHidden(1 if hidden else 0)
        self._render_instance = 1 if has_instance else None


def _set_up_comm_set(monkeypatch, characters):
    import App as _App
    from engine.appc.sets import SetClass
    _App.g_kSetManager._sets.clear()
    s = SetClass()
    s.SetName("CommSet")
    for i, ch in enumerate(characters):
        s.AddObjectToSet(ch, "char%d" % i)
    _App.g_kSetManager.AddSet(s, "CommSet")

    class _C:
        comm_set_ids = {"CommSet": 5}
    monkeypatch.setattr(hl, "_active_comm_feed", lambda c: (5, object()))
    return _C()


def test_hailed_character_exactly_one_unhidden_returns_it(monkeypatch):
    liu = _Char(hidden=0)
    others = [_Char(hidden=1), _Char(hidden=1)]
    ctrl = _set_up_comm_set(monkeypatch, [liu] + others)
    assert hl._hailed_character(ctrl) is liu


def test_hailed_character_two_unhidden_returns_none(monkeypatch):
    a = _Char(hidden=0)
    b = _Char(hidden=0)
    ctrl = _set_up_comm_set(monkeypatch, [a, b])
    assert hl._hailed_character(ctrl) is None


def test_hailed_character_zero_unhidden_returns_none(monkeypatch):
    ctrl = _set_up_comm_set(monkeypatch, [_Char(hidden=1), _Char(hidden=1)])
    assert hl._hailed_character(ctrl) is None
