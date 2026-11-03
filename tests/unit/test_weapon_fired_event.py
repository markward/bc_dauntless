"""ET_WEAPON_FIRED carries its target (event-emitter-gaps #14): the SDK's
WeaponFired handlers (E1M2, E2M1) read the target with
ShipClass_Cast(pEvent.GetObjPtr()) and return when it is None.  Source = the
weapon, Destination = the owning ship, ObjPtr = the target the shot went at.
Pulse weapons post it too (one per shot); tractors never do."""
import pytest

import App
from engine.appc import projectiles
from engine.appc.events import TGEvent
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import TractorBeam, TractorBeamSystem
from tests.helpers.torpedo_fixtures import (
    advance_game_clock_to, make_ship_with_two_tubes)
from tests.unit.test_phaser_canfire_fidelity import make_charged_bank


@pytest.fixture(autouse=True)
def _clean():
    App.g_kTimerManager._time = 0.0
    projectiles._active.clear()
    yield
    App.g_kTimerManager._time = 0.0
    projectiles._active.clear()


@pytest.fixture
def fired():
    """Every ET_WEAPON_FIRED event posted, in order."""
    seen = []
    globals()["_collect"] = lambda _obj, evt: seen.append(evt)
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_WEAPON_FIRED, object(), __name__ + "._collect")
    yield seen
    App.g_kEventManager._broadcast_handlers.pop(App.ET_WEAPON_FIRED, None)


def _Target():
    """A live target ahead (a real ship: fire control is native only, M3,
    and the kernel aims only at objects the mirror names)."""
    target = ShipClass_Create("Target")
    target.SetTranslateXYZ(0.0, 100.0, 0.0)
    return target


def test_weapon_fired_is_an_object_pointer_event(fired):
    """ET_WEAPON_FIRED is a TGObjPtrEvent (the class whose object pointer
    the SDK handlers read); a plain TGEvent has no real object pointer."""
    from engine.appc.actions import TGObjPtrEvent
    bank = make_charged_bank()
    bank.Fire(target=_Target())
    assert len(fired) == 1 and isinstance(fired[0], TGObjPtrEvent)
    assert App.TGObjPtrEvent_Create().GetObjPtr() is None
    assert "GetObjPtr" not in vars(TGEvent)


def test_phaser_first_fire_carries_the_target(fired):
    bank = make_charged_bank()
    target = _Target()
    bank.Fire(target=target)
    assert len(fired) == 1
    assert fired[0].GetObjPtr() is target
    assert fired[0].GetSource() is bank
    assert fired[0].GetDestination() is bank._climb_to_ship()


def test_tube_launch_carries_the_target_and_keeps_its_order(fired):
    ship, system, (t1, _) = make_ship_with_two_tubes()
    order = []
    globals()["_order"] = lambda _o, evt: order.append(evt.GetEventType())
    names = ("ET_TORPEDO_FIRED", "ET_WEAPON_FIRED", "ET_TORPEDO_AMMO_CONSUMED")
    for n in names:
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            getattr(App, n), object(), __name__ + "._order")
    try:
        target = _Target()
        ship._target = target
        t1.Fire(target, None)
    finally:
        for n in names:
            App.g_kEventManager._broadcast_handlers.pop(getattr(App, n), None)
    assert len(fired) == 1 and fired[0].GetObjPtr() is target
    assert order.index(App.ET_TORPEDO_FIRED) < order.index(App.ET_WEAPON_FIRED)


def test_pulse_shot_posts_one_event_per_shot_with_the_target(fired):
    from tests.unit.test_pulse_weapon_fire import _pulse_weapon
    cannon = _pulse_weapon()
    ship = cannon._climb_to_ship()
    target = _Target()
    for i in range(2):
        cannon._cooldown_remaining = 0.0
        cannon._charge_level = cannon._max_charge
        assert cannon.Fire(target, None) is True
    assert len(fired) == 2
    assert all(e.GetObjPtr() is target and e.GetSource() is cannon
               for e in fired)
    assert fired[0].GetDestination() is ship


def test_pulse_shot_with_no_bolt_posts_nothing(fired):
    """No bolt can be made (the projectile module does not resolve): no
    shot happens, so no ET_WEAPON_FIRED -- and, fire control being native
    only (M3, M6), nothing is spent either: the Fire is a counted no-fire,
    its charge and cooldown untouched."""
    from engine.appc import native_combat as nc
    from tests.unit.test_pulse_weapon_fire import _pulse_weapon
    cannon = _pulse_weapon(module_name="k1fx_no_such_pulse_module")
    cannon._cooldown_remaining = 0.0
    cannon._charge_level = cannon._max_charge
    assert cannon.Fire(_Target(), None) is False
    assert fired == []
    assert cannon._charge_level == cannon._max_charge
    assert cannon._cooldown_remaining == 0.0
    assert nc.counts()["k1_no_fire"]["decision"] == 1


def test_tractor_posts_no_weapon_fired(fired):
    ship = ShipClass_Create("Tractor")
    system = TractorBeamSystem("Tractors")
    system.TurnOn()
    system._parent_ship = ship
    beam = TractorBeam("Beam")
    beam._max_charge = 100.0
    beam._charge_level = 100.0
    system.AddChildSubsystem(beam)
    beam.Fire(target=_Target())
    assert fired == []
