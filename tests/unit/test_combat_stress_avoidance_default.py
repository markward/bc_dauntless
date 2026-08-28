"""combat_stress must default to the avoidance configuration it imitates.

The mission is a QuickBattle stand-in (it reuses QuickBattleRegion and the AI
QuickBattle attaches). QuickBattle's own `QuickBattleAI.CreateAI` wraps its
whole tree — BasicAttack inside a PriorityList — in an `AvoidObstacles`
PreprocessingAI (sdk/Build/scripts/QuickBattle/QuickBattleAI.py:83-92), so every
QuickBattle enemy runs avoidance. combat_stress attaches `BasicAttack` directly,
which installs none, so WITHOUT the wrapper its captures exercise no avoidance
at all and understate real-mission cost.
"""
import importlib
import os

import pytest


@pytest.fixture
def combat_stress(monkeypatch):
    monkeypatch.delenv("DAUNTLESS_COMBAT_AVOID", raising=False)
    return importlib.import_module("engine.dev_missions.combat_stress")


def test_avoidance_is_on_by_default(combat_stress):
    assert combat_stress.avoidance_enabled() is True


def test_avoidance_can_be_switched_off_for_isolation(combat_stress, monkeypatch):
    """The knob still exists in both directions: a capture that wants to
    isolate non-avoidance cost asks for it explicitly."""
    monkeypatch.setenv("DAUNTLESS_COMBAT_AVOID", "0")
    assert combat_stress.avoidance_enabled() is False


def test_avoidance_can_be_asked_for_explicitly(combat_stress, monkeypatch):
    monkeypatch.setenv("DAUNTLESS_COMBAT_AVOID", "1")
    assert combat_stress.avoidance_enabled() is True


def test_quickbattle_really_does_wrap_its_tree_in_avoid_obstacles():
    """The SDK claim this default rests on, read off the SDK rather than
    asserted in a comment. `AI/Compound/BasicAttack.py` installs no
    AvoidObstacles of its own; QuickBattleAI adds one around it."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "sdk" / "Build" / "scripts"
    qb = (root / "QuickBattle" / "QuickBattleAI.py").read_text()
    assert "AI.Preprocessors.AvoidObstacles()" in qb
    assert 'PreprocessingAI_Create(pShip, "AvoidObstacles")' in qb
    assert "SetContainedAI(pPriorityList)" in qb

    basic = (root / "AI" / "Compound" / "BasicAttack.py").read_text()
    assert "AvoidObstacles" not in basic, (
        "BasicAttack now installs its own AvoidObstacles; combat_stress's "
        "explicit wrapper would double it")
