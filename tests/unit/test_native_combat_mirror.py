"""The native combat mirror, written through from Python
(engine/appc/native_combat.py).

Every field the native sensor query reads is a descriptor that pushes each
write into the C++ mirror row of its object, so the mirror can never lag the
Python. These tests write each field through its PUBLIC API and read the row
back with combat_dump. Floats are compared by float.hex(): no tolerance.
"""
import gc
import importlib
import math
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
from tests.helpers.subsystem_stage import tick_subsystem

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    yield
    nc.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


def _load_hardpoint(ship, name, reload=True):
    mod_name = "ships.Hardpoints." + name
    if reload:
        App.g_kModelPropertyManager.ClearLocalTemplates()
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
        else:
            importlib.import_module(mod_name)
    sys.modules[mod_name].LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()


def _warbird(name="Warbird", reload=True):
    """A Warbird through the real hardpoint path: sensors AND a cloak."""
    ship = App.ShipClass_Create(name)
    _load_hardpoint(ship, "warbird", reload=reload)
    return ship


def _slot(obj):
    return obj.__dict__["_nslot"]


def _dump(obj):
    return _h.combat_dump(_slot(obj))


def _expected(value):
    """What the mirror holds for a Python value."""
    if value is None:
        return -1
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, int):
        return value
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, list):
        return list(value)
    # A referenced object: its handle, or -2 when the mirror cannot name it.
    return getattr(value, "__dict__", {}).get("_nslot", -2)


def _assert_mirrored(obj, field):
    value = obj.__dict__[field]
    got = _dump(obj)[field]
    if isinstance(value, float):
        got = float(got).hex()
    assert got == _expected(value), (
        f"{type(obj).__name__}.{field}: mirror {got!r} != python {value!r}")


def test_every_sensor_field_writes_through():
    nc.configure(ON)
    assert nc.enabled()
    ship = _warbird()
    other = _warbird("Other", reload=False)
    sensors = ship.GetSensorSubsystem()
    cloak = ship.GetCloakingSubsystem()
    assert sensors is not None and cloak is not None

    # The class flags the Python probes with implements / isinstance.
    row = _dump(ship)
    assert row["has_sensor_getter"] == 1
    assert row["has_cloak_getter"] == 1
    assert row["is_rock"] == 0 and row["is_meta_nebula"] == 0
    assert row["obj_id"] == ship.GetObjID()
    assert _dump(sensors)["has_parent_ship_getter"] == 1

    # Object references and the property row (registered lazily).
    for field in ("_sensor_subsystem", "_cloaking_subsystem", "_hull"):
        _assert_mirrored(ship, field)
        assert _dump(ship)[field] != -1
    for field in ("_parent_ship", "_property"):
        _assert_mirrored(sensors, field)
        assert _dump(sensors)[field] != -1
    prop = sensors.GetProperty()
    assert _h.combat_dump(_slot(prop))["MaxCondition"] == float(
        prop.GetMaxCondition())
    assert _h.combat_dump(_slot(prop))["MaxCondition_set"] == 1

    phasers = ship.GetPhaserSystem()
    child = phasers.GetChildSubsystem(0)
    _assert_mirrored(child, "_parent_subsystem")
    assert _dump(child)["_parent_subsystem"] == _slot(phasers)

    # Object fields.
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "native_mirror_set")
    try:
        pSet.AddObjectToSet(ship, "Warbird")
        _assert_mirrored(ship, "_containing_set")
        ship.SetRadius(3.25)
        _assert_mirrored(ship, "_radius")
        ship.SetScale(1.5)
        _assert_mirrored(ship, "_scale")
        ship.SetLifeTime(12.5)
        _assert_mirrored(ship, "_life_time")
        ship.SetDying(1)
        _assert_mirrored(ship, "_dying")
    finally:
        App.g_kSetManager.DeleteSet("native_mirror_set")

    # Damage, repair, max condition, disable threshold, destroyed.
    sensors.SetCondition(sensors.GetMaxCondition() * 0.375)
    _assert_mirrored(sensors, "_condition")
    sensors.SetMaxCondition(sensors._max_condition * 2.0)
    _assert_mirrored(sensors, "_max_condition")
    _assert_mirrored(sensors, "_condition")
    sensors.Repair(10.0)
    _assert_mirrored(sensors, "_condition")
    sensors.SetDisabledPercentage(0.6)
    _assert_mirrored(sensors, "_disabled_percentage")
    sensors.SetRadius(0.75)
    _assert_mirrored(sensors, "_radius")

    # Radiation outage: start, then end.
    from engine.appc.radiation import RadiationDriver

    class _Rng:
        def random(self):
            return 0.0

        def choice(self, pool):
            return sensors if sensors in pool else pool[0]

        def uniform(self, a, b):
            return a

    drv = RadiationDriver(sample_for=lambda s: None, rng=_Rng())
    drv._maybe_start_outage(ship, 1.0e9, 1.0)
    assert sensors._radiation_out is True
    _assert_mirrored(sensors, "_radiation_out")
    drv.reset()
    assert sensors._radiation_out is False
    _assert_mirrored(sensors, "_radiation_out")

    # A power-plant draw rewrites _power_factor.
    from engine.core.loop import TICK_DELTA
    sensors.SetPowerPercentageWanted(0.5)
    plant = ship.GetPowerSubsystem()
    for _ in range(3):
        tick_subsystem(plant, TICK_DELTA)
    _assert_mirrored(sensors, "_power_factor")

    # Base range (SetupProperties and the nebula runtime both use the setter).
    sensors.SetBaseSensorRange(1234.5)
    _assert_mirrored(sensors, "_base_sensor_range")

    # Known objects: add, remove, and the player-left-the-set clear.
    sensors.AddKnownObject(other)
    _assert_mirrored(sensors, "_known_objects")
    assert _dump(sensors)["_known_objects"] == [other.GetObjID()]
    sensors.RemoveKnownObject(other)
    _assert_mirrored(sensors, "_known_objects")
    assert _dump(sensors)["_known_objects"] == []

    # Probes: appended in place, then pruned (rebound) on read.
    sensors.AddProbe(other.GetObjID())
    sensors.AddProbe(987654321)                # resolves to nothing
    _assert_mirrored(sensors, "_probe_ids")
    assert _dump(sensors)["_probe_ids"] == [other.GetObjID(), 987654321]
    sensors.probes()
    _assert_mirrored(sensors, "_probe_ids")
    assert _dump(sensors)["_probe_ids"] == [other.GetObjID()]

    # Cloak, driven to cloaked.
    cloak.StartCloaking()
    _assert_mirrored(cloak, "_cloak_state")
    for _ in range(int(cloak._transition_duration / TICK_DELTA) + 2):
        tick_subsystem(cloak, TICK_DELTA)
    assert cloak.IsCloaked()
    _assert_mirrored(cloak, "_cloak_state")

    # Destroyed last: it fires the destroyed machinery.
    sensors.SetDestroyed(1)
    _assert_mirrored(sensors, "_destroyed")


def test_known_objects_clear_when_player_leaves_set(monkeypatch):
    nc.configure(ON)
    from engine.appc import sensor_contacts
    ship = _warbird()
    other = _warbird("Other", reload=False)
    sensors = ship.GetSensorSubsystem()
    sensors.AddKnownObject(other)
    assert _dump(sensors)["_known_objects"] == [other.GetObjID()]
    monkeypatch.setattr(sensor_contacts, "current_player", lambda: ship)
    sensor_contacts.on_exited_set(None, ship)
    assert sensors._known_objects == set()
    assert _dump(sensors)["_known_objects"] == []


def test_property_max_condition_shared_template():
    nc.configure(ON)
    from engine.appc.properties import SensorProperty
    from engine.appc.subsystems import SensorSubsystem
    prop = SensorProperty("Sensor Array")
    a, b = SensorSubsystem("A"), SensorSubsystem("B")
    a.SetProperty(prop)
    b.SetProperty(prop)
    assert _dump(a)["_property"] == _dump(b)["_property"] == _slot(prop)
    a.GetProperty().SetMaxCondition(300)
    for sub in (a, b):
        row = _h.combat_dump(_dump(sub)["_property"])
        assert row["MaxCondition"] == 300.0
        assert row["MaxCondition_set"] == 1
        assert sub.GetMaxCondition() == 300.0


def test_rock_reclassify_pushes():
    nc.configure(ON)
    from engine.rocks.rock import maybe_become_rock, RockClass_Create
    ship = App.ShipClass_Create("Rock 1")
    assert _dump(ship)["is_rock"] == 0
    ship.SetGenus(App.GENUS_ASTEROID)
    assert maybe_become_rock(ship)
    assert _dump(ship)["is_rock"] == 1
    rock = RockClass_Create(2.0, name="Rock 2")
    assert _dump(rock)["is_rock"] == 1


def test_finalize_unregisters():
    from engine.appc.subsystems import SensorSubsystem
    from engine.appc.objects import ObjectClass
    from engine.core import ids
    sub = SensorSubsystem("Gone")
    obj = ObjectClass()
    handles = [_slot(sub), _slot(obj)]
    for o in (sub, obj):
        ids.unregister(o.GetObjID())
    del sub, obj, o
    gc.collect()
    # Recorded by the finalizers, freed at the next drain point (spec
    # 2026-11-03-kernels-off-the-lock, ruling R2).
    nc.drain()
    for h in handles:
        with pytest.raises(ValueError):
            _h.combat_dump(h)


def test_stale_handle_after_clear_unregisters_silently():
    """R2: after a test's combat_clear() every handle is stale. A push or the
    finalizer's unregister must drop the object's slot, never raise."""
    nc.configure(ON)
    from engine.appc.subsystems import SensorSubsystem
    from engine.core import ids
    sub = SensorSubsystem("Stale")
    _h.combat_clear()
    sub.SetCondition(0.5)                       # must not raise
    assert "_nslot" not in sub.__dict__
    sub.SetBaseSensorRange(10.0)                # no slot: no push at all
    other = SensorSubsystem("Stale 2")
    _h.combat_clear()
    ids.unregister(other.GetObjID())
    del other
    gc.collect()                                # finalizer records it
    nc.drain()                                  # the drain swallows it


def test_unconfigured_pushes_nothing_then_resync_catches_up():
    """Before configure() (a fresh process; here, after reset()) objects
    register but nothing is pushed; configure() resyncs every row. The
    switch no longer stops the pushes: fire control reads the mirror
    whatever it says (fire control native only, M9)."""
    from engine.appc.subsystems import SensorSubsystem
    assert not nc._enabled                      # reset(): the mirror is off
    sub = SensorSubsystem("Off")
    assert "_nslot" in sub.__dict__             # registered even when off
    sub.SetBaseSensorRange(777.25)
    sub.SetCondition(0.5)
    row = _dump(sub)
    assert row["_base_sensor_range"] != 777.25
    assert row["_condition"] != 0.5
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "0"})
    assert nc.fire_control_native() and not nc.enabled()
    row = _dump(sub)
    assert row["_base_sensor_range"] == 777.25
    assert row["_condition"] == 0.5
    assert row["has_parent_ship_getter"] == 1
    sub.SetBaseSensorRange(555.5)               # =0 still pushes
    assert _dump(sub)["_base_sensor_range"] == 555.5


def test_configure_switch_values():
    nc.configure({})
    assert nc.enabled() and not nc.audit_enabled()
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "0"})
    assert not nc.enabled()
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    assert nc.enabled() and not nc.audit_enabled()
    nc.configure({"DAUNTLESS_NATIVE_AUDIT": "1"})
    assert nc.enabled() and nc.audit_enabled()
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "0",
                  "DAUNTLESS_NATIVE_AUDIT": "1"})
    assert nc.enabled() and nc.audit_enabled()      # the audit implies on


def test_game_loop_reads_the_switch(monkeypatch):
    from engine.core.loop import GameLoop
    monkeypatch.setenv("DAUNTLESS_NATIVE_COMBAT", "0")
    GameLoop()
    assert not nc.enabled() and nc.fire_control_native()
    monkeypatch.delenv("DAUNTLESS_NATIVE_COMBAT")
    GameLoop()
    assert nc.enabled() and nc.fire_control_native()


def test_self_check_passes_on_this_interpreter():
    assert nc._self_check() is None


def test_self_check_names_the_mismatch(monkeypatch):
    real = math.dist
    monkeypatch.setattr(math, "dist",
                        lambda a, b: math.nextafter(real(a, b), math.inf))
    with pytest.raises(RuntimeError, match="dist3"):
        nc.configure(ON)
    assert not nc.enabled() and not nc._enabled
    reason = nc._self_check()
    assert reason is not None and "dist3" in reason


def test_failed_self_check_leaves_the_audit_off(monkeypatch):
    """DAUNTLESS_NATIVE_AUDIT=1 on an interpreter whose math.dist differs:
    configure raises and the audit stays off -- else GameLoop.tick audits
    never-pushed rows every tick and records every field as a failure."""
    real = math.dist
    monkeypatch.setattr(math, "dist",
                        lambda a, b: math.nextafter(real(a, b), math.inf))
    with pytest.raises(RuntimeError, match="self-check"):
        nc.configure({"DAUNTLESS_NATIVE_AUDIT": "1"})
    assert not nc.enabled()
    assert not nc.audit_enabled()


def test_audit_mirror_flags_a_bypassed_write():
    nc.configure(ON)
    from engine.appc.subsystems import SensorSubsystem
    sub = SensorSubsystem("Bypassed")
    nc.audit_mirror()
    assert nc.audit_failures() == []
    sub.__dict__["_condition"] = 0.123
    nc.audit_mirror()
    assert ("SensorSubsystem", "_condition") in nc.audit_failures()


def test_game_loop_tick_audits_the_mirror_under_the_audit(monkeypatch):
    """Under DAUNTLESS_NATIVE_AUDIT=1 every GameLoop.tick ends with
    audit_mirror(); with the switch on but no audit, it does not."""
    from engine.appc.subsystems import SensorSubsystem
    from engine.core.loop import GameLoop
    sub = SensorSubsystem("Bypassed")
    monkeypatch.setenv("DAUNTLESS_NATIVE_COMBAT", "1")
    loop = GameLoop()
    sub.__dict__["_condition"] = 0.123
    loop.tick()
    assert nc.audit_failures() == []
    monkeypatch.setenv("DAUNTLESS_NATIVE_AUDIT", "1")
    loop = GameLoop()
    loop.tick()
    assert ("SensorSubsystem", "_condition") in nc.audit_failures()


def test_unencodable_value_unregisters_the_object():
    """A value the mirror cannot hold must not leave a registered row with
    the previous value: the object is unregistered (Python path)."""
    nc.configure(ON)
    from engine.appc.subsystems import SensorSubsystem
    sub = SensorSubsystem("Unencodable")
    h = _slot(sub)
    sub._condition = "not a float"
    assert "_nslot" not in sub.__dict__
    with pytest.raises(ValueError):
        _h.combat_dump(h)
    sub._condition = 0.5                        # no slot: nothing to push


def test_unencodable_property_max_condition_unregisters_the_property():
    nc.configure(ON)
    from engine.appc.properties import SensorProperty
    from engine.appc.subsystems import SensorSubsystem
    prop = SensorProperty("Sensor Array")
    sub = SensorSubsystem("S")
    sub.SetProperty(prop)
    h = _slot(prop)
    prop.SetMaxCondition("not a float")
    assert "_nslot" not in prop.__dict__
    with pytest.raises(ValueError):
        _h.combat_dump(h)


class _FakeSensors:
    """Not a ShipSubsystem: never registered."""


def test_unregistered_referent_is_unrepresentable_not_none():
    """R6: a non-None referent the mirror cannot name pushes -2, never -1
    (None): a ship whose sensors are a fake must not read as sensorless."""
    nc.configure(ON)
    ship = App.ShipClass_Create("Faked")
    ship._sensor_subsystem = _FakeSensors()
    assert _dump(ship)["_sensor_subsystem"] == -2
    ship._sensor_subsystem = object()           # no __dict__ at all
    assert _dump(ship)["_sensor_subsystem"] == -2
    ship._sensor_subsystem = None
    assert _dump(ship)["_sensor_subsystem"] == -1
    ship._cloaking_subsystem = _FakeSensors()
    nc.audit_mirror()
    assert nc.audit_failures() == []


def test_containing_set_is_the_set_or_unrepresentable():
    """Sets register at SetClass init (Task 4), so an object in a set names
    its row; a set whose row was dropped reads -2 on its members."""
    nc.configure(ON)
    ship = App.ShipClass_Create("InSet")
    assert _dump(ship)["_containing_set"] == -1
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "native_mirror_set_2")
    try:
        pSet.AddObjectToSet(ship, "InSet")
        assert _dump(ship)["_containing_set"] == _slot(pSet)
        nc._drop(pSet)
        assert _dump(ship)["_containing_set"] == -2
    finally:
        App.g_kSetManager.DeleteSet("native_mirror_set_2")


def test_wrong_kind_referent_is_unrepresentable():
    nc.configure(ON)
    ship = App.ShipClass_Create("WrongKind")
    other = App.ShipClass_Create("AnObject")
    ship._sensor_subsystem = other              # an Object, not a Subsystem
    assert _dump(ship)["_sensor_subsystem"] == -2


# ── A mirrored field hidden by a subclass (final review, Important 2) ────────
#
# A subclass that redefines a mirrored attribute (Torpedo's _containing_set
# and _radius are properties) hides the Native descriptor: its writes never
# reach the row. The mirror must then never read as a valid value natively.

def _registered_bases():
    import pkgutil

    import engine.appc
    import engine.rocks
    for pkg in (engine.appc, engine.rocks):
        for info in pkgutil.iter_modules(pkg.__path__):
            try:
                importlib.import_module(pkg.__name__ + "." + info.name)
            except Exception:  # noqa: BLE001 - "currently importable" only
                pass
    from engine.appc.objects import ObjectClass
    from engine.appc.properties import TGModelProperty
    from engine.appc.sets import SetClass
    from engine.appc.subsystems import ShipSubsystem
    from engine.appc.weapon_subsystems import TorpedoAmmoType
    return (ObjectClass, ShipSubsystem, SetClass, TGModelProperty,
            TorpedoAmmoType)


def _all_subclasses(base):
    out, todo = {base}, [base]
    while todo:
        for sub in todo.pop().__subclasses__():
            if sub not in out:
                out.add(sub)
                todo.append(sub)
    return out


def _is_native(attr):
    # NativeWrapped: the frozen / wake / thaw descriptors that also push.
    return isinstance(attr, (nc.NativeField, nc.NativeWrapped))


def _hidden_by_lookup(cls):
    """Mirrored names (a Native descriptor somewhere in the MRO) that
    attribute lookup on `cls` resolves to something else -- computed with
    inspect.getattr_static, independently of native_combat's own walk."""
    import inspect
    names = {name for klass in cls.__mro__
             for name, attr in vars(klass).items() if _is_native(attr)}
    return {name for name in names
            if not _is_native(inspect.getattr_static(cls, name))}


def test_every_hidden_mirrored_field_is_caught():
    """Guard: every class of every registered kind that hides a mirrored
    field is one the mechanism catches (its plan names the field). A new
    override the mechanism would miss fails here."""
    seen_torpedo = False
    for base in _registered_bases():
        for cls in _all_subclasses(base):
            hidden = _hidden_by_lookup(cls)
            refs, scalars = nc._hidden_fields(cls)
            caught = {name for name, _ in refs} | set(scalars)
            assert hidden == caught, (
                f"{cls.__module__}.{cls.__qualname__} hides {sorted(hidden)}"
                f" but the mirror catches {sorted(caught)}")
            if cls.__name__ == "Torpedo":
                seen_torpedo = True
                assert caught == {"_containing_set", "_radius"}
    assert seen_torpedo        # the walk reached the real projectile class


def _ref_hider():
    from engine.appc.ships import ShipClass

    class RefHider(ShipClass):
        """Hides ONLY a ref field: its row stays, the field reads -2."""
        @property
        def _containing_set(self):
            return self.__dict__.get("_cs")

        @_containing_set.setter
        def _containing_set(self, value):
            self.__dict__["_cs"] = value
    return RefHider


def test_hidden_ref_field_reads_unrepresentable():
    nc.configure(ON)
    ship = _ref_hider()()
    assert _dump(ship)["_containing_set"] == nc.REF_UNREPRESENTABLE
    pSet = App.SetClass_Create()
    pSet.AddObjectToSet(ship, "RefHider")
    assert ship.GetContainingSet() is pSet
    assert _dump(ship)["_containing_set"] == nc.REF_UNREPRESENTABLE
    nc.audit_mirror()
    assert nc.audit_failures() == []           # -2 is right: no false failure
    _h.combat_set_ref(_slot(ship), nc._fid("_containing_set"), _slot(pSet))
    nc.audit_mirror()                          # a real handle: no false pass
    assert ("RefHider", "_containing_set") in nc.audit_failures()


def test_hidden_ref_field_reads_unrepresentable_after_resync():
    ship = _ref_hider()()                      # registered while off
    nc.configure(ON)
    assert _dump(ship)["_containing_set"] == nc.REF_UNREPRESENTABLE


def test_hidden_scalar_field_takes_no_row():
    """A hidden scalar has no "cannot name" value: like an unencodable value
    (NativeField._push), the object gets no row and takes the Python path."""
    from engine.appc.projectiles import Torpedo
    for env in ({}, ON):
        nc.configure(env)
        torp = Torpedo()
        assert "_nslot" not in torp.__dict__
        assert nc.slot(torp) is None
        nc.reset()


def test_forget_rows_drops_every_stale_handle_at_once():
    """After combat_clear() every handle is stale: forget_rows() strips them
    all, so the next switch-on's resync pushes no stale row (one stale push
    at a time was a quadratic drop/re-push cascade: the gate hung on it)."""
    ships = [_warbird("Stale %d" % i, reload=(i == 0)) for i in range(3)]
    assert all("_nslot" in s.__dict__ for s in ships)
    _h.combat_clear()
    nc.forget_rows()
    assert not any("_nslot" in s.__dict__ for s in ships)
    assert len(nc._registry) == 0
    nc.configure(ON)
    assert nc.enabled()


def test_self_check_runs_once_per_set_of_compared_objects(monkeypatch):
    """The verdict is cached for the exact objects it compared: a repeat
    configure after reset() (the per-test reset's) skips it, and swapping
    one of them (math.dist here) runs it again."""
    nc.configure(ON)                      # passes, and caches the verdict
    ran = []
    real_check = nc._self_check
    monkeypatch.setattr(nc, "_self_check",
                        lambda: ran.append(1) or real_check())
    nc.reset()
    nc.configure(ON)
    assert ran == []
    real = math.dist
    monkeypatch.setattr(math, "dist", lambda a, b: real(a, b))
    nc.reset()
    nc.configure(ON)
    assert ran == [1]
