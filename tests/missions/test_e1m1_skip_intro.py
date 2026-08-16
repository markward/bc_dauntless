"""E1M1's skip prompt, end to end.

Five independent breaks had to be fixed for this to work (see
docs/engine/e1m1-skip-intro.md). This test drives the SDK's OWN
SkipOpeningSequence through the real input pipeline: nothing in E1M1.py is
stubbed or reimplemented, so it fails if any one of the five regresses.
"""
import sys
import types

import pytest

import App
from engine import dev_mode, dev_tutorial_flag
from engine.appc.actions import TGAction
from engine.appc.input import WC_S, WC_ESCAPE


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
