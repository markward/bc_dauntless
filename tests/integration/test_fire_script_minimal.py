"""Integration: SelectTarget + FireScript on the same ship, ticked
under tick_ai. Verifies the slice's end-to-end goal:
  AI sees target -> weapon fires.

Builds a minimal tree: PreprocessingAI(SelectTarget) -> PriorityListAI ->
PreprocessingAI(FireScript) with phaser+torpedo. SelectTarget propagates
the chosen target name to FireScript via the existing
CallExternalFunction(SetTarget) dispatch (Slice B Task 8).
"""
import pytest

import App
from engine.appc.ai import (
    PreprocessingAI_Create, PriorityListAI_Create,
)
from engine.appc.ai_driver import tick_ai
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, PhaserSystem, TorpedoSystem, TorpedoAmmoType


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _kitted_target():
    """Target with a hull subsystem so it can absorb damage."""
    target = ShipClass(); target.SetTranslateXYZ(0, 100, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    return target


def _kitted_attacker_with_weapons():
    """Attacker with phaser + torpedo for FireScript to cycle through.

    Both weapon systems must be powered on for StartFiring to dispatch —
    PoweredSubsystem defaults _is_on=False and StartFiring early-returns
    on !IsOn().
    """
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    phaser = PhaserSystem("P"); phaser._parent_ship = ours; phaser.TurnOn()
    torp   = TorpedoSystem("T"); torp._parent_ship = ours;   torp.TurnOn()
    # FireScript.GetWeaponInfo reads GetCurrentAmmoType().GetLaunchSpeed();
    # seed slot 0 with photon ammo (matches Task 2 TorpedoRun fixture).
    torp._ammo_by_slot = {0: TorpedoAmmoType("Photon", launch_speed=19.0)}
    return ours, phaser, torp


def _object_group_with_name(name):
    """Helper: ObjectGroup containing a single target name."""
    grp = ObjectGroup()
    grp.AddName(name)
    return grp


def _wire_select_target_and_fire_script(ours, phaser, torp, target_name):
    """Tree: PreprocessingAI(SelectTarget) -> PriorityListAI ->
    PreprocessingAI(FireScript)."""
    from AI.Preprocessors import SelectTarget, FireScript
    # FireScript leaf.
    fs = FireScript(target_name)
    fs.AddWeaponSystem(phaser)
    fs.AddWeaponSystem(torp)
    pp_fire = PreprocessingAI_Create(ours, "FirePP")
    fs.pCodeAI = pp_fire
    pp_fire.SetPreprocessingMethod(fs, "Update")
    # PriorityListAI holding the fire branch.
    plist = PriorityListAI_Create(ours, "Branches")
    plist.AddAI(pp_fire, priority=1)
    # SelectTarget wrapping the list.
    st = SelectTarget(_object_group_with_name(target_name))
    pp_select = PreprocessingAI_Create(ours, "SelectPP")
    st.pCodeAI = pp_select
    pp_select.SetPreprocessingMethod(st, "Update")
    pp_select.SetContainedAI(plist)
    return st, pp_select, fs


def test_select_target_plus_fire_script_starts_weapon_firing():
    """Wire SelectTarget + FireScript on the same ship. Tick enough times
    to walk the iLastUpdate cycle (-2 visibility, -1 subsystem, 0..N-1
    fire). Assert at least one weapon reaches StartFiring (the WeaponSystem
    contract — _currently_firing non-empty / IsFiring()==1)."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours, phaser, torp = _kitted_attacker_with_weapons()
    pSet.AddObjectToSet(ours, "Ours")
    target = _kitted_target()
    pSet.AddObjectToSet(target, "Target")

    st, pp_select, fs = _wire_select_target_and_fire_script(
        ours, phaser, torp, "Target")

    # 6 ticks: SelectTarget picks (tick 1), then FireScript cycle
    # iLastUpdate -2 -> -1 -> 0 -> 1 -> -2 -> -1.
    #
    # Step 0.25s (> FireScript's 0.2s GetNextUpdateTime cadence) so each tick
    # unambiguously clears the gate and FireScript's Update advances every tick.
    # A 0.2s stride would land exactly on the cadence boundary and be
    # floating-point fragile now that ai_driver._tick_preprocessing gates the
    # preprocessor's own Update. (SelectTarget runs once at t=0 then gates on
    # its 5s cadence; the target never changes, so that's fine.)
    for i in range(6):
        tick_ai(pp_select, game_time=float(i) * 0.25)

    # Some firing must have happened on at least one weapon system.
    # PhaserSystem.StartFiring sets _fire_held=True and appends to
    # _currently_firing (when an emitter accepts the dispatch).
    # TorpedoSystem inherits WeaponSystem.StartFiring which only
    # populates _currently_firing.  IsFiring() unifies both.
    fired = bool(phaser.IsFiring()) or bool(torp.IsFiring()) \
            or phaser._fire_held
    assert fired, (
        "no weapon ever started firing — "
        "phaser._fire_held=%s phaser._currently_firing=%s "
        "torp._currently_firing=%s fs.iLastUpdate=%s fs.bTargetVisible=%s"
        % (phaser._fire_held, phaser._currently_firing,
           torp._currently_firing, fs.iLastUpdate, fs.bTargetVisible)
    )


def test_fire_script_receives_set_target_dispatch_from_select_target():
    """SelectTarget's dispatch loop must reach FireScript's SetTarget via
    the registered external function. After two ticks, FireScript.sTarget
    should match what SelectTarget picked.

    Two ticks are required because the engine's CodeAISet analog for
    FireScript (registering SetTarget on its pCodeAI) runs lazily on the
    first time pp_fire itself is ticked — see
    engine/appc/ai_driver._ensure_fire_script_initialized. SelectTarget's
    CallSetTargetFunctions on tick 1 fires before pp_fire is reached, so
    the registration isn't in place yet; tick 2's target re-confirmation
    propagates after FireScript has registered."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours, phaser, _torp = _kitted_attacker_with_weapons()
    pSet.AddObjectToSet(ours, "Ours")
    target = _kitted_target()
    pSet.AddObjectToSet(target, "Target")

    bare_torp = TorpedoSystem("T")
    bare_torp._ammo_by_slot = {0: TorpedoAmmoType("Photon", launch_speed=19.0)}
    st, pp_select, fs = _wire_select_target_and_fire_script(
        ours, phaser, bare_torp, "Target")

    # Tick 1: pp_select runs Update -> SelectTarget picks "Target",
    # CallSetTargetFunctions walks the tree but pp_fire hasn't run its
    # FireScript CodeAISet analog yet -> registration deferred.
    # Then PS_NORMAL -> tick the contained AI (plist) -> pp_fire ticks
    # -> _ensure_fire_script_initialized registers SetTarget on pp_fire.
    tick_ai(pp_select, game_time=0.0)
    # Clear FireScript's target so we can prove tick 2's dispatch wrote
    # to it (rather than relying on residual init state).
    fs.sTarget = ""
    # Tick 2: pp_select sees the same target (no change -> no dispatch).
    # Force a re-dispatch by clearing sCurrentTarget so the inequality
    # check in SelectTarget.Update triggers CallSetTargetFunctions.
    st.sCurrentTarget = None
    tick_ai(pp_select, game_time=10.0)
    assert fs.sTarget == "Target"
