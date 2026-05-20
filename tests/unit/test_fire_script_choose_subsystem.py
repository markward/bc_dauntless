"""FireScript.ChooseTargetSubsystem rating path.

SDK Preprocessors.py:789-947 — `bChooseSubsystemTargets=1` builds
target list via GetTargetableSubsystems + RateSubsystemForTargeting +
picks highest-rated. Skip the priority-list path (lTargetSubsystems
populated) — that's the alternative branch."""
import pytest

import App
from engine.appc.ai import PreprocessingAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, ShieldSubsystem, PhaserSystem, ImpulseEngineSubsystem,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _make_target_with_subsystems():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); pSet.AddObjectToSet(ours, "Ours")

    target = ShipClass(); pSet.AddObjectToSet(target, "Target")
    # Subsystems on the target: hull (heavily de-prioritized), shield
    # (weighted high), phaser (weighted high), impulse engine (mid).
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    target._shield_subsystem = ShieldSubsystem("Shield"); target._shield_subsystem.SetMaxCondition(500.0)
    target._phaser = PhaserSystem("Phaser"); target._phaser.SetMaxCondition(200.0)
    target._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    target._impulse_engine_subsystem.SetMaxCondition(200.0)
    return ours, target


def _wire(ours):
    from AI.Preprocessors import FireScript
    inst = FireScript("Target")
    inst.bChooseSubsystemTargets = 1
    pp = PreprocessingAI_Create(ours, "FirePP")
    inst.pCodeAI = pp
    return inst


def test_choose_target_subsystem_caches_id_when_targets_found():
    """With bChooseSubsystemTargets=1, the rating loop should find at least
    one subsystem and cache its ID on inst.idTargetedSubsystem."""
    ours, target = _make_target_with_subsystems()
    inst = _wire(ours)
    inst.ChooseTargetSubsystem(target)
    # Either picks one or leaves None — we accept None only if
    # GetSubsystems() returned empty. With our fixture it should pick one.
    assert inst.idTargetedSubsystem is not None


def test_choose_target_subsystem_returns_none_for_non_ship_target():
    """SDK Preprocessors.py:791 — early-return for non-ship targets."""
    ours, _target = _make_target_with_subsystems()
    inst = _wire(ours)
    # Pass a non-ship as the target.
    result = inst.ChooseTargetSubsystem("not a ship")
    assert result is None


def test_choose_target_subsystem_clears_cache_when_subsystems_disappear():
    """If a subsystem rated previously no longer appears in the iteration,
    its entry is removed from dTargetSubsystemRating."""
    ours, target = _make_target_with_subsystems()
    inst = _wire(ours)
    # Seed the dict with a stale ID that won't be in the iteration.
    inst.dTargetSubsystemRating[999999] = (0, 100.0)
    inst.ChooseTargetSubsystem(target)
    assert 999999 not in inst.dTargetSubsystemRating
