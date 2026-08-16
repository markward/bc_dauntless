"""E1M1's skip prompt, end to end.

Five independent breaks had to be fixed for this to work (see
docs/engine/e1m1-skip-intro.md). This test drives the SDK's OWN
SkipOpeningSequence through the real input pipeline: nothing in E1M1.py is
stubbed or reimplemented, so it fails if any one of the five regresses.
"""
import pytest

import App
from engine import dev_mode, dev_tutorial_flag, host_io, host_loop
from engine.appc.input import WC_S, WC_ESCAPE
from engine.input_map import InputMap


@pytest.fixture
def skip_module(monkeypatch):
    """A stand-in for the E1M1 module exposing the real SkipOpeningSequence.

    We import the SDK function itself rather than copying it, so the test
    tracks the SDK. Its two mission-side collaborators (UndockCutscene and the
    banner lookup) are replaced with recorders -- they need a live mission,
    and what we are asserting is that the handler REACHES the skip branch.
    """
    import Maelstrom.Episode1.E1M1.E1M1 as e1m1

    calls = {"undock": [], "killed": []}
    monkeypatch.setattr(e1m1, "UndockCutscene",
                        lambda skipped: calls["undock"].append(skipped))

    db = App.g_kLocalizationManager.Load(
        "data/TGL/Maelstrom/Episode 1/E1M1.TGL")
    monkeypatch.setattr(e1m1, "g_pMissionDatabase", db)
    monkeypatch.setattr(e1m1, "g_idTextBanner", 0)

    real_kill = App.TGActionManager_KillActions

    def recording_kill(name=None):
        calls["killed"].append(name)
        real_kill(name)

    monkeypatch.setattr(App, "TGActionManager_KillActions", recording_kill)
    return e1m1, calls


def _register(e1m1):
    App.g_kRootWindow.AddPythonFuncHandlerForInstance(
        App.ET_KEYBOARD,
        "Maelstrom.Episode1.E1M1.E1M1.SkipOpeningSequence")


def _unregister(e1m1):
    App.g_kRootWindow.RemoveHandlerForInstance(
        App.ET_KEYBOARD,
        "Maelstrom.Episode1.E1M1.E1M1.SkipOpeningSequence")


def test_tgl_strings_are_the_ones_the_feature_depends_on():
    db = App.g_kLocalizationManager.Load(
        "data/TGL/Maelstrom/Episode 1/E1M1.TGL")
    assert str(db.GetString("SkipKey")) == "s"
    assert str(db.GetString("CutsceneTextBar")) == \
        "Press 's' to skip introduction"


def test_pressing_s_reaches_the_sdk_skip_branch(skip_module):
    e1m1, calls = skip_module
    import KeyConfig
    KeyConfig.MapScancodes()
    _register(e1m1)
    try:
        App.g_kInputManager.OnKeyDown(WC_S)
    finally:
        _unregister(e1m1)
    assert calls["undock"] == [1], "UndockCutscene(TRUE) was not called"
    assert calls["killed"] == ["CharacterIntros"]


class _FakeKeys:
    KEY_S = ord("S")
    KEY_LEFT_ALT, KEY_RIGHT_ALT = 342, 346
    KEY_LEFT_CONTROL, KEY_RIGHT_CONTROL = 341, 345
    KEY_LEFT_SHIFT, KEY_RIGHT_SHIFT = 340, 344


class _FakeHost:
    keys = _FakeKeys()

    def __init__(self):
        self.down = set()

    def key_state(self, key):
        return key in self.down


def test_pressing_s_on_the_host_reaches_the_sdk_skip_branch(skip_module,
                                                            monkeypatch):
    """The REAL path: a physical key held for one frame.

    test_pressing_s_reaches_the_sdk_skip_branch above enters one layer lower,
    at OnKeyDown — which is exactly the layer that was missing in the game.
    Nothing forwarded 's' from the host into g_kInputManager, so the prompt
    was dead in-game while the unit test passed.
    """
    e1m1, calls = skip_module
    import KeyConfig
    KeyConfig.MapScancodes()
    host_loop._fn_key_prev.clear()
    host_loop._raw_key_pairs_host = None
    host = _FakeHost()
    monkeypatch.setattr(host_io, "_h", host)
    _register(e1m1)
    try:
        host.down.add(_FakeKeys.KEY_S)
        host_loop._poll_raw_keyboard(host, InputMap())
    finally:
        _unregister(e1m1)
        host_loop._fn_key_prev.clear()
        host_loop._raw_key_pairs_host = None
    assert calls["undock"] == [1], "UndockCutscene(TRUE) was not called"
    assert calls["killed"] == ["CharacterIntros"]


def test_holding_shift_while_pressing_s_does_not_reach_the_sdk_skip_branch(
        skip_module, monkeypatch):
    """THE DEFECT: BC registers the shifted variant of every letter as a
    separate WC code with its own label (KeyConfig.py:70/195 -- WC_S -> "s",
    WC_CAPS_S -> "S"), so Shift+S produces the label "S", which fails
    E1M1's comparison against its lowercase SkipKey "s". BC does not skip
    the intro on Shift+S.

    Drives the SAME two pollers host_loop runs every frame, in the SAME
    order (chords, then the general raw stream) -- not OnKeyDown directly.
    That is the point: the previous unit tests all passed while holding
    Shift and pressing S skipped the intro in the actual game, because the
    raw poller kept forwarding the bare (unshifted) WC_S underneath the
    chord poller's correct WC_CAPS_S.
    """
    e1m1, calls = skip_module
    import KeyConfig
    KeyConfig.MapScancodes()
    host_loop._fn_key_prev.clear()
    host_loop._chord_prev.clear()
    host_loop._raw_key_pairs_host = None
    host = _FakeHost()
    monkeypatch.setattr(host_io, "_h", host)
    _register(e1m1)
    try:
        host.down.add(_FakeKeys.KEY_S)
        host.down.add(_FakeKeys.KEY_LEFT_SHIFT)
        host_loop._poll_modifier_chords(host)
        host_loop._poll_raw_keyboard(host, InputMap())
    finally:
        _unregister(e1m1)
        host_loop._fn_key_prev.clear()
        host_loop._chord_prev.clear()
        host_loop._raw_key_pairs_host = None
    assert calls["undock"] == [], "Shift+S incorrectly skipped the intro"
    assert calls["killed"] == []


def test_pressing_a_different_key_does_not_skip(skip_module):
    e1m1, calls = skip_module
    import KeyConfig
    KeyConfig.MapScancodes()
    _register(e1m1)
    try:
        App.g_kInputManager.OnKeyDown(WC_ESCAPE)
    finally:
        _unregister(e1m1)
    assert calls["undock"] == []
    assert calls["killed"] == []


def test_the_played_tutorial_gate_opens_under_developer_mode(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    App.g_kVarManager.SetFloatVariable("global", "PlayedTutorial", 0.0)
    dev_tutorial_flag.apply_played_tutorial_flag()
    assert App.g_kVarManager.GetFloatVariable(
        "global", "PlayedTutorial") == 1.0
