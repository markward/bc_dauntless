"""The bridge module's LoadSounds() -- a documented deviation from the SDK.

"LiftDoor" (sfx/door.wav) is loaded ONLY by GalaxyBridge.LoadSounds() /
SovereignBridge.LoadSounds(), and NOTHING in the 1228 SDK files calls them:
LoadBridge.Load calls CreateBridgeModel/ConfigureCharacters/PreloadAnimations but
not LoadSounds -- while its UNLOAD path does call UnloadSounds(). The SDK unloads a
sound it never loads. We cannot tell from the SDK whether BC's native engine calls
it or whether this is a shipped BC bug; either way, without it every lift door is
silent, so we call it ourselves.
"""
import sys
import types

from engine.bridge_sounds import load_bridge_module_sounds


class _FakeSet:
    def __init__(self, config):
        self._config = config

    def GetConfig(self):
        return self._config


def _install_fake_bridge_module(monkeypatch, name, calls):
    mod = types.ModuleType("Bridge." + name)
    mod.LoadSounds = lambda: calls.append(name)
    pkg = types.ModuleType("Bridge")
    setattr(pkg, name, mod)
    monkeypatch.setitem(sys.modules, "Bridge", pkg)
    monkeypatch.setitem(sys.modules, "Bridge." + name, mod)


def test_calls_the_configured_bridge_modules_loadsounds(monkeypatch):
    calls = []
    _install_fake_bridge_module(monkeypatch, "GalaxyBridge", calls)
    assert load_bridge_module_sounds(_FakeSet("GalaxyBridge")) is True
    assert calls == ["GalaxyBridge"]


def test_sovereign_bridge_loads_its_own_sounds(monkeypatch):
    calls = []
    _install_fake_bridge_module(monkeypatch, "SovereignBridge", calls)
    assert load_bridge_module_sounds(_FakeSet("SovereignBridge")) is True
    assert calls == ["SovereignBridge"]


def test_missing_config_is_a_no_op():
    assert load_bridge_module_sounds(_FakeSet("")) is False
    assert load_bridge_module_sounds(None) is False


def test_a_module_without_loadsounds_does_not_raise(monkeypatch):
    mod = types.ModuleType("Bridge.CardassianBridge")   # no LoadSounds attribute
    pkg = types.ModuleType("Bridge")
    pkg.CardassianBridge = mod
    monkeypatch.setitem(sys.modules, "Bridge", pkg)
    monkeypatch.setitem(sys.modules, "Bridge.CardassianBridge", mod)
    assert load_bridge_module_sounds(_FakeSet("CardassianBridge")) is False


def test_a_raising_loadsounds_degrades_to_false(monkeypatch):
    def boom():
        raise RuntimeError("no audio device")

    mod = types.ModuleType("Bridge.GalaxyBridge")
    mod.LoadSounds = boom
    pkg = types.ModuleType("Bridge")
    pkg.GalaxyBridge = mod
    monkeypatch.setitem(sys.modules, "Bridge", pkg)
    monkeypatch.setitem(sys.modules, "Bridge.GalaxyBridge", mod)
    assert load_bridge_module_sounds(_FakeSet("GalaxyBridge")) is False
