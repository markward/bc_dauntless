"""The AI driver must mirror a FireScript preprocessor's chosen target
subsystem (inst.idTargetedSubsystem) onto the firing ship via
SetTargetSubsystem, so the aim sites that read ship.GetTargetSubsystem()
(host_loop phaser tick, weapon_subsystems torpedo launch) actually honor
the AI's choice. See docs/superpowers/specs/2026-07-07-npc-subsystem-targeting-design.md.
"""
import pytest

import App
from engine.appc.ai import PreprocessingAI, PreprocessingAI_Create
from engine.appc.ai_driver import tick_ai, _sync_fire_script_target_subsystem
from engine.appc.ships import ShipClass
from engine.appc.subsystems import PowerSubsystem, ShieldSubsystem


class _FireScriptLike:
    """Minimal stand-in for the SDK FireScript: carries the lWeapons marker
    and an idTargetedSubsystem slot, and recomputes it each Update()."""
    def __init__(self, chosen_id):
        self.lWeapons = []               # FireScript marker
        self.idTargetedSubsystem = None  # lives in __dict__
        self.pCodeAI = None
        self._chosen_id = chosen_id
        self.update_calls = 0

    def Update(self, dEndTime):
        self.update_calls += 1
        self.idTargetedSubsystem = self._chosen_id
        return PreprocessingAI.PS_NORMAL


class _NotFireScript:
    """A preprocessor with no lWeapons marker — the hook must ignore it."""
    def __init__(self):
        self.pCodeAI = None

    def Update(self, dEndTime):
        return PreprocessingAI.PS_NORMAL


def _ship_with_target_and_subsystem():
    """ours (attacker) targeting target; target carries an attached shield
    subsystem. Returns (ours, target, shield)."""
    ours = ShipClass()
    target = ShipClass()
    shield = ShieldSubsystem("Shield")
    shield.SetMaxCondition(500.0)
    target.SetShieldSubsystem(shield)   # _attach_subsystem sets _parent_ship
    ours.SetTarget(target)
    return ours, target, shield


def _wire(inst, ours):
    pp = PreprocessingAI_Create(ours, "FirePP")
    # SetPreprocessingMethod(inst, "Update") is the wiring tick_ai actually
    # consults (ai._preprocessing_instance / _preprocessing_method) — it also
    # sets inst.pCodeAI = pp as a side effect (ai.py:587), matching the
    # established convention in test_ai_driver_got_focus.py's _wrap helper.
    pp.SetPreprocessingMethod(inst, "Update")
    return pp


def test_sync_pushes_chosen_subsystem_onto_ship():
    ours, target, shield = _ship_with_target_and_subsystem()
    inst = _FireScriptLike(shield.GetObjID())
    _wire(inst, ours)
    inst.idTargetedSubsystem = shield.GetObjID()
    _sync_fire_script_target_subsystem(inst)
    assert ours.GetTargetSubsystem() is shield


def test_sync_pushes_none_when_no_choice():
    ours, target, shield = _ship_with_target_and_subsystem()
    inst = _FireScriptLike(None)
    _wire(inst, ours)
    inst.idTargetedSubsystem = None
    _sync_fire_script_target_subsystem(inst)
    assert ours.GetTargetSubsystem() is None


def test_sync_is_noop_for_non_firescript_preprocessor():
    ours, target, shield = _ship_with_target_and_subsystem()
    ours.SetTargetSubsystem(shield)          # pre-existing value
    inst = _NotFireScript()
    _wire(inst, ours)
    _sync_fire_script_target_subsystem(inst)
    assert ours.GetTargetSubsystem() is shield  # untouched


def test_sync_clears_stale_subsystem_from_other_ship():
    """idTargetedSubsystem points at a subsystem belonging to a DIFFERENT
    ship than the ship's current target → clear to None (centre aim)."""
    ours, target, shield = _ship_with_target_and_subsystem()
    other = ShipClass()
    other_shield = ShieldSubsystem("OtherShield")
    other.SetShieldSubsystem(other_shield)
    inst = _FireScriptLike(other_shield.GetObjID())
    _wire(inst, ours)
    inst.idTargetedSubsystem = other_shield.GetObjID()
    _sync_fire_script_target_subsystem(inst)
    assert ours.GetTargetSubsystem() is None


def test_sync_clears_dead_or_unresolvable_id():
    ours, target, shield = _ship_with_target_and_subsystem()
    inst = _FireScriptLike(999999999)   # never-registered id
    _wire(inst, ours)
    inst.idTargetedSubsystem = 999999999
    _sync_fire_script_target_subsystem(inst)
    assert ours.GetTargetSubsystem() is None


def test_driver_calls_sync_after_update():
    """End-to-end through tick_ai: ticking the wrapper runs Update (which
    sets idTargetedSubsystem) then the driver pushes it onto the ship."""
    ours, target, shield = _ship_with_target_and_subsystem()
    inst = _FireScriptLike(shield.GetObjID())
    pp = _wire(inst, ours)
    tick_ai(pp, game_time=0.0)
    assert inst.update_calls == 1
    assert ours.GetTargetSubsystem() is shield


def test_sync_only_writes_on_change(monkeypatch):
    ours, target, shield = _ship_with_target_and_subsystem()
    inst = _FireScriptLike(shield.GetObjID())
    _wire(inst, ours)
    inst.idTargetedSubsystem = shield.GetObjID()
    calls = {"n": 0}
    real_set = ours.SetTargetSubsystem
    def counting_set(s):
        calls["n"] += 1
        real_set(s)
    monkeypatch.setattr(ours, "SetTargetSubsystem", counting_set)
    _sync_fire_script_target_subsystem(inst)   # first: writes
    _sync_fire_script_target_subsystem(inst)   # second: no change
    assert calls["n"] == 1


@pytest.fixture(autouse=True)
def _isolate_sets():
    App.g_kSetManager._sets.clear()
    yield
    App.g_kSetManager._sets.clear()


def _make_attacker_and_target_with_warp_core():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ours = ShipClass(); pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); pSet.AddObjectToSet(target, "Target")

    # Warp core: critical + targetable → highest FireScript rating
    # (IsCritical x6 beats the shield's type-rating of 5).
    warp_core = PowerSubsystem("Warp Core")
    warp_core.SetMaxCondition(7000.0)
    warp_core.SetCritical(1)
    warp_core.SetTargetable(1)
    target.SetPowerSubsystem(warp_core)

    shield = ShieldSubsystem("Shield")
    shield.SetMaxCondition(500.0)
    shield.SetTargetable(1)
    target.SetShieldSubsystem(shield)

    ours.SetTarget(target)
    return ours, target, warp_core


def test_real_firescript_choice_reaches_ship_target_subsystem():
    from AI.Preprocessors import FireScript
    ours, target, warp_core = _make_attacker_and_target_with_warp_core()

    inst = FireScript("Target")
    inst.bChooseSubsystemTargets = 1
    pp = PreprocessingAI_Create(ours, "FirePP")
    inst.pCodeAI = pp

    # Run the real rating path, then the driver hook.
    inst.ChooseTargetSubsystem(target)
    assert inst.idTargetedSubsystem is not None      # rating picked something
    _sync_fire_script_target_subsystem(inst)

    chosen = ours.GetTargetSubsystem()
    assert chosen is warp_core                        # critical wins
