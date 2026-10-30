"""DAUNTLESS_COMBAT_IDLE=1 gives combat_stress a quiet scene: the same ships
and the same attack AI, but every ship hunts a target name nothing carries, so
nobody fires. It exists to measure upkeep when fleets are parked rather than
fighting (the passive-state design's target case).
"""
import importlib

import pytest


@pytest.fixture
def combat_stress(monkeypatch):
    monkeypatch.delenv("DAUNTLESS_COMBAT_IDLE", raising=False)
    return importlib.import_module("engine.dev_missions.combat_stress")


def test_idle_is_off_by_default(combat_stress):
    assert combat_stress.idle_enabled() is False


def test_idle_switches_on(combat_stress, monkeypatch):
    monkeypatch.setenv("DAUNTLESS_COMBAT_IDLE", "1")
    assert combat_stress.idle_enabled() is True


def test_idle_targets_name_no_ship(combat_stress):
    import App
    group = combat_stress.idle_target_group()
    assert group.IsNameInGroup(combat_stress.IDLE_TARGET_NAME)
    assert combat_stress.IDLE_TARGET_NAME not in (
        combat_stress._FRIEND_TYPES + combat_stress._ENEMY_TYPES)
