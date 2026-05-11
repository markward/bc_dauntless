"""Per-family name adapters."""
from pathlib import Path
import sys
import types

import pytest

from engine.missions.tgl_reader import TGLFile
from engine.missions.name_resolver import (
    resolve_family,
    resolve_episode,
    resolve_mission,
)


@pytest.fixture
def fake_tgl(monkeypatch):
    """Make read_tgl return a constructed TGLFile per path."""
    store: dict[str, TGLFile] = {}

    def _fake(path):
        key = Path(path).as_posix()
        for k, tgl in store.items():
            if key.endswith(k):
                return tgl
        from engine.missions.tgl_reader import TGLParseError
        raise TGLParseError(f"no fake for {path}")

    # The resolver caches reads with lru_cache; clear it between fakes.
    import engine.missions.name_resolver as nr
    nr._load_tgl.cache_clear()
    monkeypatch.setattr(nr, "read_tgl", _fake)
    return store


def test_family_known_names_pretty():
    assert resolve_family("Tutorial") == "Tutorial"
    assert resolve_family("Maelstrom") == "Maelstrom"
    assert resolve_family("Multiplayer") == "Multiplayer"
    # Unknown families fall back to their dir name.
    assert resolve_family("Custom") == "Custom"


def test_maelstrom_episode_lookup(fake_tgl):
    fake_tgl["Maelstrom/Maelstrom.tgl"] = TGLFile(strings={
        "Ep1Title": "The Long Night",
    })
    assert resolve_episode("Maelstrom", "Episode1") == "The Long Night"
    # Missing key → dir-name fallback.
    assert resolve_episode("Maelstrom", "Episode9") == "Episode9"


def test_maelstrom_mission_lookup(fake_tgl):
    fake_tgl["Maelstrom/Maelstrom.tgl"] = TGLFile(strings={
        "E1M1Title": "Shakedown",
    })
    assert resolve_mission(
        "Maelstrom", "Episode1", "E1M1",
        "Maelstrom.Episode1.E1M1.E1M1",
    ) == "Shakedown"
    assert resolve_mission(
        "Maelstrom", "Episode2", "E2M99",
        "Maelstrom.Episode2.E2M99.E2M99",
    ) == "E2M99"


def test_multiplayer_mission_uses_module_callback(monkeypatch):
    mod = types.ModuleType("Multiplayer.Episode.MissionX.MissionXName")
    mod.GetMissionName = lambda: "Test Skirmish"
    monkeypatch.setitem(
        sys.modules,
        "Multiplayer.Episode.MissionX.MissionXName",
        mod,
    )
    assert resolve_mission(
        "Multiplayer", "Episode", "MissionX",
        "Multiplayer.Episode.MissionX.MissionX",
    ) == "Test Skirmish"


def test_multiplayer_falls_back_when_module_raises(monkeypatch):
    mod = types.ModuleType("Multiplayer.Episode.MissionBoom.MissionBoomName")
    def boom():
        raise RuntimeError("nope")
    mod.GetMissionName = boom
    monkeypatch.setitem(
        sys.modules,
        "Multiplayer.Episode.MissionBoom.MissionBoomName",
        mod,
    )
    assert resolve_mission(
        "Multiplayer", "Episode", "MissionBoom",
        "Multiplayer.Episode.MissionBoom.MissionBoom",
    ) == "MissionBoom"


def test_tutorial_mission_lookup(fake_tgl):
    fake_tgl["Tutorial/Tutorial.tgl"] = TGLFile(strings={
        "M1Basic": "Basic Maneuvers",
    })
    assert resolve_mission(
        "Tutorial", "Episode", "M1Basic",
        "Custom.Tutorial.Episode.M1Basic.M1Basic",
    ) == "Basic Maneuvers"
