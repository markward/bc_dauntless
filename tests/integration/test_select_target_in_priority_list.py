"""Integration: SelectTarget under a PriorityListAI containing 2
candidate AI branches. Validates dispatch + target propagation across
multiple ticks + damage-event re-rating."""
import pytest

import App
from engine.appc.ai import (
    PreprocessingAI_Create, PlainAI_Create, PriorityListAI_Create,
    ArtificialIntelligence,
)
from engine.appc.ai_driver import tick_ai
from engine.appc.events import TGEvent_Create, WeaponHitEvent
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _kitted_ship(x, y, z):
    """ShipClass at (x,y,z) with hull + empty shield subsystem. Mirrors the
    unit-dispatch test pattern so SelectTarget.GetTargetRating's
    unconditional pShip.GetShields().GetShieldPercentage() lookup doesn't
    NPE on Phase-1 ships that don't auto-populate subsystems."""
    s = ShipClass(); s.SetTranslateXYZ(x, y, z)
    s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    s._shield_subsystem = ShieldSubsystem("Shd")
    return s


def _build_scene():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = _kitted_ship(0, 0, 0)
    pSet.AddObjectToSet(ours, "Ours")
    a = _kitted_ship(0, 100, 0)
    pSet.AddObjectToSet(a, "Alpha")
    b = _kitted_ship(0, 500, 0)
    pSet.AddObjectToSet(b, "Bravo")
    return ours, a, b


def _build_tree(ours):
    from AI.Preprocessors import SelectTarget
    branch_alpha = PlainAI_Create(ours, "BranchAlpha")
    branch_bravo = PlainAI_Create(ours, "BranchBravo")

    recvA, recvB = [], []
    class _AInst:
        def SetTarget(self, name): recvA.append(name)
    class _BInst:
        def SetTarget(self, name): recvB.append(name)
    branch_alpha._script_instance = _AInst()
    branch_bravo._script_instance = _BInst()
    branch_alpha.RegisterExternalFunction(
        "SetTarget", {"FunctionName": "SetTarget"})
    branch_bravo.RegisterExternalFunction(
        "SetTarget", {"FunctionName": "SetTarget"})

    pList = PriorityListAI_Create(ours, "Choices")
    pList.AddAI(branch_alpha, priority=1)
    pList.AddAI(branch_bravo, priority=2)

    pp = PreprocessingAI_Create(ours, "SelectPP")
    grp = ObjectGroup()
    grp.AddName("Alpha"); grp.AddName("Bravo")
    inst = SelectTarget(grp); inst.pCodeAI = pp
    pp.SetPreprocessingMethod(inst, "Update")
    pp.SetContainedAI(pList)
    return inst, pp, recvA, recvB


def test_first_tick_dispatches_chosen_to_all_branches():
    """Both leaves are registered for SetTarget -> both receive the
    same chosen name on first Update."""
    ours, _a, _b = _build_scene()
    inst, pp, recvA, recvB = _build_tree(ours)
    tick_ai(pp, game_time=0.0)
    # Default weights -> Alpha (closer) wins.
    assert recvA == ["Alpha"]
    assert recvB == ["Alpha"]


def test_target_change_re_dispatches_to_branches():
    """When SelectTarget picks a different target on a subsequent
    Update, branches receive the new name."""
    ours, _a, b = _build_scene()
    inst, pp, recvA, recvB = _build_tree(ours)
    # Force initial pick.
    tick_ai(pp, game_time=0.0)
    # Now boost Bravo via simulated damage so it outweighs Alpha's
    # distance advantage.
    inst.dDamageReceived = {b.GetObjID(): 100.0}
    inst.pCodeAI.ForceUpdate()
    tick_ai(pp, game_time=10.0)
    assert recvA[-1] == "Bravo"
    assert recvB[-1] == "Bravo"


def test_damage_event_accumulates_via_broadcast_handler():
    """When a WeaponHitEvent is broadcast with the firing object being
    a target in our group, SelectTarget.DamageEvent records the
    damage into dDamageReceived for that source's ObjID."""
    ours, _a, b = _build_scene()
    inst, pp, _recvA, _recvB = _build_tree(ours)
    # First tick wires the broadcast handler.
    tick_ai(pp, game_time=0.0)

    evt = WeaponHitEvent()
    evt.SetEventType(App.ET_WEAPON_HIT)
    evt.SetSource(b)
    # Destination = ship that got hit; SelectTarget's broadcast filter
    # is keyed on pCodeAI.GetShip() so the handler only fires when our
    # ship is the one taking damage. Mirrors engine.appc.combat.apply_hit.
    evt.SetDestination(ours)
    evt.SetDamage(150.0)
    App.g_kEventManager.AddEvent(evt)

    # Damage gets recorded — expressed as fraction of hull max.
    expected = 150.0 / ours._hull.GetMaxCondition()
    assert b.GetObjID() in inst.dDamageReceived
    assert abs(inst.dDamageReceived[b.GetObjID()] - expected) < 1e-9
