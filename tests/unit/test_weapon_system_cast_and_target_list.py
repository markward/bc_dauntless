"""App.WeaponSystem_Cast + WeaponSystem.IsInTargetList — heatmap 115/116/167.

AI/PlainAI/StarbaseAttack.py:112-115:
    pWeapSystem = App.WeaponSystem_Cast(pSystem)
    for pTarget in lTargets:
        if not pWeapSystem.IsInTargetList(pTarget):
            pWeapSystem.StartFiring(pTarget)
Both undefined: stub.IsInTargetList() is truthy, `not` is False, StartFiring
is never called. The E7M3 starbases never fired."""
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem
from engine.appc.weapon_subsystems import PhaserSystem, WeaponSystem, TorpedoSystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_cast_is_real_and_accepts_any_weapon_system():
    assert not isinstance(App.WeaponSystem_Cast, App._NamedStub)
    p = PhaserSystem("P"); t = TorpedoSystem("T")
    assert App.WeaponSystem_Cast(p) is p
    assert App.WeaponSystem_Cast(t) is t
    assert App.WeaponSystem_Cast(HullSubsystem("H")) is None
    assert App.WeaponSystem_Cast(None) is None


def test_is_in_target_list_is_a_real_int():
    p = PhaserSystem("P")
    target = ShipClass()
    assert p.IsInTargetList(target) == 0
    p._add_target(target)
    assert p.IsInTargetList(target) == 1


def test_starbase_attack_starts_firing_at_its_target():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    base = ShipClass()
    base._hull = HullSubsystem("H"); base._hull.SetMaxCondition(1000.0)
    phasers = PhaserSystem("P")
    # ⚠️ Task-2 fixture correction: `base._phaser = phasers` is a DEAD
    # attribute on ShipClass. GetPhaserSystem() reads `_phaser_system`,
    # populated only by SetPhaserSystem (which also attaches the parent
    # ship) — StartGetSubsystemMatch(CT_WEAPON_SYSTEM) walks `_phaser_system`
    # (engine/appc/ships.py:1703-1729), so the setter is required for the
    # StarbaseAttack loop to ever see this system.
    base.SetPhaserSystem(phasers)
    pSet.AddObjectToSet(base, "Base")
    enemy = ShipClass(); enemy.SetTranslateXYZ(0, 400, 0)
    enemy._hull = HullSubsystem("H"); enemy._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(enemy, "Enemy")

    calls = []
    original = phasers.StartFiring
    def _record(target, *a, **k):
        calls.append(target)
        return original(target, *a, **k)
    phasers.StartFiring = _record

    plain = PlainAI_Create(base, "SBA")
    plain.SetScriptModule("StarbaseAttack")
    inst = plain.GetScriptInstance()
    inst.SetTargets(["Enemy"])       # StarbaseAttack.py:41 — ObjectGroup_ForceToGroup(lsTargets)
    inst.Update()
    assert calls and calls[0] is enemy, (
        "StarbaseAttack never called StartFiring — WeaponSystem_Cast/IsInTargetList are stubs")
