"""The state the K2 beam kernel reads, written through from Python (native
combat phase 2, Task 1; engine/appc/native_combat.py).

Each test drives a field through its PUBLIC API and reads the row back with
combat_dump; floats compare by float.hex(), never with a tolerance. The
switch-off case needs no test body of its own: the existing phaser tests run
with native off (Step 4 of the brief) are the proof.
"""
import importlib
import sys

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_register"),
    reason="native combat bindings not built")

from engine.appc import native_combat as nc  # noqa: E402
from engine.appc.math import TGPoint3  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    yield
    nc.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


def _load_hardpoint(ship, name):
    mod_name = "ships.Hardpoints." + name
    App.g_kModelPropertyManager.ClearLocalTemplates()
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    sys.modules[mod_name].LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()


def _ship(name, hardpoint, at=(0.0, 0.0, 0.0)):
    ship = App.ShipClass_Create(name)
    _load_hardpoint(ship, hardpoint)
    ship.SetTranslateXYZ(*at)
    return ship


@pytest.fixture
def arena():
    """A Galaxy and a Bird of Prey in one set, native combat on."""
    nc.configure(ON)
    assert nc.enabled()
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "native_k2_mirror")
    galaxy = _ship("Galaxy1", "galaxy")
    bop = _ship("BoP1", "birdofprey", at=(0.0, 300.0, 0.0))
    for ship in (galaxy, bop):
        pSet.AddObjectToSet(ship, ship.GetName())
    try:
        yield galaxy, bop
    finally:
        App.g_kSetManager.DeleteSet("native_k2_mirror")


def _slot(obj):
    return obj.__dict__["_nslot"]


def _dump(obj):
    return _h.combat_dump(_slot(obj))


def _hex(*xs):
    return tuple(float(x).hex() for x in xs)


def _vec(v):
    return None if v is None else _hex(*v)


def _first_bank(ship):
    return ship.GetPhaserSystem().GetWeapon(0)


def test_k2_fields_write_through(arena):
    galaxy, bop = arena
    # _target_subsystem: a ref to a Subsystem row, -1 for None, -2 for an
    # object the mirror cannot name.
    sensors = bop.GetSensorSubsystem()
    galaxy.SetTargetSubsystem(sensors)
    assert _dump(galaxy)["_target_subsystem"] == _slot(sensors)
    galaxy.SetTargetSubsystem(None)
    assert _dump(galaxy)["_target_subsystem"] == -1
    galaxy.SetTargetSubsystem(object())
    assert _dump(galaxy)["_target_subsystem"] == nc.REF_UNREPRESENTABLE
    galaxy.SetTargetSubsystem(sensors)

    # Manual aim offset: unset, set, cleared by UseTargetOffsetTG(0) and by
    # SetTarget (the old target's frame no longer applies).
    d = _dump(galaxy)
    assert d["_manual_target_offset"] is None and d["_use_target_offset"] == 0
    galaxy.set_manual_target_offset(TGPoint3(1.5, -2.25, 0.125))
    d = _dump(galaxy)
    assert _vec(d["_manual_target_offset"]) == _hex(1.5, -2.25, 0.125)
    assert d["_use_target_offset"] == 1
    galaxy.UseTargetOffsetTG(0)
    d = _dump(galaxy)
    assert d["_manual_target_offset"] is None and d["_use_target_offset"] == 0
    galaxy.set_manual_target_offset(TGPoint3(0.1, 0.2, 0.3))
    galaxy.SetTarget(bop)
    d = _dump(galaxy)
    assert d["_manual_target_offset"] is None and d["_use_target_offset"] == 0
    galaxy.set_manual_target_offset(TGPoint3(0.1, 0.2, 0.3))
    galaxy.UseTargetOffsetTG(1)
    assert _dump(galaxy)["_use_target_offset"] == 1

    # _shield_subsystem
    shields = galaxy.GetShields()
    assert _dump(galaxy)["_shield_subsystem"] == _slot(shields)
    galaxy.SetShieldSubsystem(None)
    assert _dump(galaxy)["_shield_subsystem"] == -1
    galaxy.SetShieldSubsystem(shields)
    assert _dump(galaxy)["_shield_subsystem"] == _slot(shields)

    # Hull box: exactly ((3),(3)) is set; anything else reads unset.
    from engine import host_loop
    assert _dump(galaxy)["hull_box_set"] == 0
    host_loop._cache_shield_hull_box(galaxy, (0.5, -1.0, 0.25), (3.0, 7.0, 1.5))
    d = _dump(galaxy)
    c, hh = galaxy._shield_hull_box
    assert d["hull_box_set"] == 1
    assert _vec(d["_shield_hull_box_center"]) == _hex(*c)
    assert _vec(d["_shield_hull_box_half"]) == _hex(*hh)
    for bad in (None, ((1.0, 2.0), (3.0, 4.0, 5.0)), (1.0, 2.0),
                ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)),
                ((1.0, "x", 3.0), (4.0, 5.0, 6.0))):
        galaxy._shield_hull_box = bad
        assert _dump(galaxy)["hull_box_set"] == 0, bad
    galaxy._shield_hull_box = ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))
    assert _dump(galaxy)["hull_box_set"] == 1

    # Class flags
    g = _dump(galaxy)
    assert g["is_ship_class"] == 1 and g["has_real_get_shields"] == 1

    # Bank: _length (SetProperty), countdown (StartFiring, UpdateCharge),
    # dwell (accumulate / take).
    bank = _first_bank(galaxy)
    assert bank._length != 0.0
    assert _dump(bank)["_length"].hex() == bank._length.hex()
    system = galaxy.GetPhaserSystem()
    galaxy.SetAlertLevel(galaxy.RED_ALERT)
    system.TurnOn()
    for i in range(system.GetNumWeapons()):
        system.GetWeapon(i)._charge_level = system.GetWeapon(i)._max_charge
    galaxy.SetTarget(bop)
    system.StartFiring(bop)
    from engine import host_loop
    host_loop._advance_weapons([galaxy, bop], 1.0 / 60.0)
    lit = [system.GetWeapon(i) for i in range(system.GetNumWeapons())
           if system.GetWeapon(i)._firing]
    assert lit, "the pump lit no bank"
    bank = lit[0]
    assert _dump(bank)["_beam_on_countdown"].hex() == \
        bank._beam_on_countdown.hex() != (0.0).hex()
    bank.UpdateCharge(0.1)
    assert _dump(bank)["_beam_on_countdown"].hex() == \
        bank._beam_on_countdown.hex()
    from tests.helpers import beams
    assert beams.prime_lit_banks(system) >= 1
    assert _dump(bank)["_beam_on_countdown"].hex() == (0.0).hex()
    assert _dump(bank)["_dwell"].hex() == bank._dwell.hex() != (0.0).hex()
    bank.take_dwell()
    assert _dump(bank)["_dwell"].hex() == (0.0).hex()
    bank._beam_on_countdown = 0.0
    bank.accumulate_dwell(0.0166)
    assert _dump(bank)["_dwell"].hex() == bank._dwell.hex() != (0.0).hex()
    bank.StopFiring()
    assert _dump(bank)["_beam_on_countdown"].hex() == (0.0).hex()

    # Globals are Python's own values.
    from engine.appc import combat, weapon_subsystems
    got = _h.combat_dump_globals()
    assert float(got["BEAM_DWELL_FLUSH_S"]).hex() == \
        float(weapon_subsystems.BEAM_DWELL_FLUSH_S).hex()
    assert float(got["SHIELD_ELLIPSOID_AXIS_SCALE"]).hex() == \
        float(combat.SHIELD_ELLIPSOID_AXIS_SCALE).hex()
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()


def test_class_flags_for_non_ship_objects(arena):
    galaxy, bop = arena
    # A bare ObjectClass is not a ShipClass and its GetShields is a stub.
    obj = App.ObjectClass_Create("plain") if hasattr(App, "ObjectClass_Create") \
        else None
    if obj is None:
        pytest.skip("no ObjectClass_Create")
    nc.register(obj, "Object")
    d = _dump(obj)
    assert d["is_ship_class"] == 0 and d["has_real_get_shields"] == 0


def test_set_max_shields_pushes_has_shields(arena):
    galaxy, bop = arena
    shields = galaxy.GetShields()
    assert shields.HasShields() == 1
    assert _dump(shields)["has_shields"] == 1
    for face in range(shields.NUM_SHIELDS):
        shields.SetMaxShields(face, 0)
    assert shields.HasShields() == 0
    assert _dump(shields)["has_shields"] == 0
    shields.SetMaxShields(2, 100.0)
    assert _dump(shields)["has_shields"] == 1
    shields.SetMaxShields(2, 0)
    assert _dump(shields)["has_shields"] == 0
    # A rebind of the whole list is a descriptor write.
    shields._max_shields = [5.0] * shields.NUM_SHIELDS
    assert _dump(shields)["has_shields"] == 1
    shields._max_shields = [0.0] * shields.NUM_SHIELDS
    assert _dump(shields)["has_shields"] == 0
    # A fresh generator is registered before __init__ gives it a list.
    from engine.appc.subsystems import ShieldSubsystem
    fresh = ShieldSubsystem("fresh")
    assert _dump(fresh)["has_shields"] == 0
    fresh.SetMaxShields(0, 3.0)
    assert _dump(fresh)["has_shields"] == 1
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()


def test_unrepresentable_has_shields_at_row_build_drops_the_row():
    """A row built (here: resync when native comes on) for a shield
    generator whose HasShields() answers something int() rejects is dropped
    -- the Python path from then on -- as push_has_shields does, rather than
    the build raising."""
    from engine.appc.subsystems import ShieldSubsystem

    class OddShields(ShieldSubsystem):
        def HasShields(self):
            return "yes"

    odd = OddShields("odd")
    odd.SetMaxShields(0, 3.0)
    good = ShieldSubsystem("good")
    good.SetMaxShields(0, 3.0)
    nc.configure(ON)
    assert nc.enabled()
    assert "_nslot" not in odd.__dict__
    assert _dump(good)["has_shields"] == 1
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()


def test_tracked_instances_version_bumps():
    from engine.core.tracked_instances import TrackedInstances
    t = TrackedInstances()
    assert isinstance(t, dict) and isinstance(t.version, int)
    seen = [t.version]

    def moved():
        v = t.version
        ok = v > seen[-1]
        seen.append(v)
        return ok

    t["a"] = 1
    assert moved()
    t["a"] = 2                       # overwrite counts: the iid changed
    assert moved()
    del t["a"]
    assert moved()
    t["b"] = 3
    moved()
    assert t.pop("b") == 3
    assert moved()
    assert t.pop("zz", None) is None   # a miss changes nothing, but must not raise
    t.update({"c": 1}, d=2)
    assert moved()
    assert t.setdefault("e", 5) == 5
    assert moved()
    t.setdefault("e", 6)             # present: no mutation
    t["f"] = 1
    moved()
    t.popitem()
    assert moved()
    t |= {"g": 1}
    assert moved()
    t.clear()
    assert moved()
    # An ordinary dict in every other way.
    t["x"] = 9
    assert dict(t) == {"x": 9} and t.get("x") == 9 and "x" in t and len(t) == 1
    assert list(t.items()) == [("x", 9)] and t == {"x": 9}


def test_tracked_instances_survive_pickle_and_copy():
    """Unpickling (and copy / deepcopy, the same reduce path) fills the
    dict through __setitem__ BEFORE the instance __dict__ (and so
    `version`) is restored: the copy must come back an int version that
    still moves on the next mutation."""
    import copy
    import pickle
    from engine.core.tracked_instances import TrackedInstances
    t = TrackedInstances({"a": 1, "b": 2})
    t["c"] = 3
    for clone in (pickle.loads(pickle.dumps(t)), copy.copy(t),
                  copy.deepcopy(t)):
        assert type(clone) is TrackedInstances
        assert dict(clone) == {"a": 1, "b": 2, "c": 3}
        assert isinstance(clone.version, int)
        v = clone.version
        clone["d"] = 4
        assert clone.version > v


def test_session_ship_instances_is_tracked():
    from engine import host_loop
    from engine.core.tracked_instances import TrackedInstances
    s = host_loop.MissionSession(mission_name="x")
    assert isinstance(s.ship_instances, TrackedInstances)
    assert isinstance(s.ship_instances, dict)


def test_audit_clean_on_combat_stress(monkeypatch, tmp_path):
    """120 ticks of the busiest dev scene, K2 fields included."""
    from tests.helpers import bc_assets, headless_mission
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    monkeypatch.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
    monkeypatch.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", "6")
    nc.reset()
    App.g_kTimerManager._time = 0.0
    import random
    random.seed(0)
    headless_mission.load("engine.dev_missions.combat_stress")
    from engine import host_loop
    from engine.appc.ship_iter import iter_ships
    from engine.core import loop as game_loop
    from engine.core import step_memo
    from engine.core.loop import TICK_DELTA
    host_loop._reset_sensor_state()
    step_memo.forget()
    nc.configure(ON)
    assert nc.enabled()
    player = App.Game_GetCurrentPlayer()
    ships = list(iter_ships())
    assert len(ships) == 7
    rng = random.Random(20261031)
    for tick in range(120):
        if tick % 7 == 0:
            ship = rng.choice(ships)
            foes = [s for s in ships if s is not ship]
            for system in (ship.GetPhaserSystem(), ship.GetPulseWeaponSystem(),
                           ship.GetTorpedoSystem()):
                if system is not None:
                    system.StartFiring(rng.choice(foes))
        App.g_kTimerManager._time += TICK_DELTA
        game_loop._update_ship_subsystems()
        live = list(iter_ships())
        host_loop._advance_weapons(live, TICK_DELTA)
        host_loop._advance_combat(live, TICK_DELTA, player=player,
                                  push_render_data=False)
        nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()
    assert any(_dump(b)["_dwell"] != 0.0 or _dump(b)["_beam_on_countdown"] != 0.0
               for s in ships if s.GetPhaserSystem() is not None
               for b in (s.GetPhaserSystem().GetWeapon(i)
                         for i in range(s.GetPhaserSystem().GetNumWeapons())))
