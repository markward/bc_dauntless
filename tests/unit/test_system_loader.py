"""Entering a system loads all its regions (system-frames spec §3)."""
import sys

import pytest

import App
from engine.appc.sets import SetClass_Create
from engine.systems import region_hooks, system_loader
from tests.helpers.mapped_regions import load_region


def setup_function(_):
    App.g_kSetManager._sets.clear()
    system_loader.reset()


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    system_loader.reset()


def _player_in(pSet):
    p = App.ShipClass_Create()
    p.SetName("player")
    pSet.AddObjectToSet(p, "player")
    return p


def test_entering_a_region_loads_its_siblings_mapped():
    player = _player_in(load_region("Ona", "Ona1"))
    created = system_loader.ensure_loaded(player)
    assert sorted(created) == ["Ona2", "Ona3"]
    for name in ("Ona1", "Ona2", "Ona3"):
        pSet = App.g_kSetManager.GetSet(name)
        assert pSet is not None and region_hooks.is_mapped(pSet)
    assert system_loader.loaded_system() == "Ona"


def test_it_is_idempotent_and_adopts_existing_sets():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")          # a mission already made it
    player = _player_in(ona1)
    assert system_loader.ensure_loaded(player) == ["Ona3"]
    assert App.g_kSetManager.GetSet("Ona2") is ona2
    assert system_loader.ensure_loaded(player) == []


def test_an_unmapped_set_loads_nothing():
    qb = SetClass_Create()
    App.g_kSetManager.AddSet(qb, "QuickBattle")
    assert system_loader.ensure_loaded(_player_in(qb)) == []
    assert system_loader.loaded_system() is None


def test_moving_to_another_system_loads_it_and_unloads_nothing():
    player = _player_in(load_region("Ona", "Ona1"))
    system_loader.ensure_loaded(player)
    xi = load_region("XiEntrades", "XiEntrades4")
    App.g_kSetManager.GetSet("Ona1").RemoveObjectFromSet("player")
    xi.AddObjectToSet(player, "player")
    created = system_loader.ensure_loaded(player)
    assert "XiEntrades4" not in created and len(created) >= 1
    assert App.g_kSetManager.GetSet("Ona2") is not None   # nothing unloaded


def test_one_broken_region_does_not_stop_the_rest(monkeypatch, capsys):
    """Review Focus 2."""
    import importlib
    real = importlib.import_module
    def flaky(name, *a, **k):
        if name == "Systems.Ona.Ona2":
            raise ImportError("simulated broken region module")
        return real(name, *a, **k)
    monkeypatch.setattr(importlib, "import_module", flaky)
    player = _player_in(load_region("Ona", "Ona1"))
    created = system_loader.ensure_loaded(player)
    assert "Ona3" in created and "Ona2" not in created
    assert "Ona2" in capsys.readouterr().out            # logged loudly


def test_a_mission_reinitializing_a_loaded_region_wins():
    """Review Focus 1: BC's Initialize replaces the set; the new one is mapped
    and is what GetSet returns."""
    player = _player_in(load_region("Ona", "Ona1"))
    system_loader.ensure_loaded(player)
    ours = App.g_kSetManager.GetSet("Ona2")
    theirs = load_region("Ona", "Ona2")                  # the mission's own call
    assert App.g_kSetManager.GetSet("Ona2") is theirs is not ours
    assert region_hooks.is_mapped(theirs)
