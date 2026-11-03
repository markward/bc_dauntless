"""The state the K3 projectile and K4 eligibility kernels read, written
through from Python (native combat phase 3, Task 1;
engine/appc/native_combat.py).

Two things: every Object row carries its Python object's ``id()``
(``py_id``), and in-flight torpedoes get rows in a TORPEDO TABLE kept in
``projectiles._active`` order -- added at append, dropped at remove, and
rebuilt from Python after any other list mutation (the TorpedoScan sync).

Each test drives a field through its public API and reads the row back with
``combat_torp_dump``; floats compare by ``float.hex()``, never a tolerance.
"""
import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_torp_add"),
    reason="native combat torpedo table bindings not built")

from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import projectiles  # noqa: E402
from engine.appc.math import TGPoint3  # noqa: E402
from engine.appc.projectiles import Torpedo  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    yield
    for t in list(projectiles._active):
        projectiles.expire(t)
    nc.reset()


@pytest.fixture
def on():
    """Native on, with a clean (rebuilt) torpedo table."""
    nc.configure(ON)
    assert nc.enabled()
    nc.torpedo_table_rebuild(projectiles._active)
    assert not nc._k3_dirty


@pytest.fixture
def scene():
    """A set holding one ship, the way a mission set does."""
    from engine.appc.sets import SetClass
    from engine.appc.ships import ShipClass
    kset = SetClass()
    kset.SetName("K3MirrorSystem")
    App.g_kSetManager._sets["K3MirrorSystem"] = kset
    ship = ShipClass()
    kset.AddObjectToSet(ship, "Shooter")
    yield kset, ship
    App.g_kSetManager._sets.pop("K3MirrorSystem", None)


def _hex(*xs):
    return tuple(float(x).hex() for x in xs)


def _vec(v):
    return None if v is None else _hex(*v)


def _fire(source=None) -> Torpedo:
    t = Torpedo()
    if source is not None:
        t._source_ship = source
    projectiles.register(t)
    return t


def _row(t):
    return _h.combat_torp_dump(t.__dict__["_k3_row"])


def _order():
    return list(_h.combat_torp_handles())


def _active_rows():
    return [t.__dict__["_k3_row"] for t in projectiles._active]


# ── py_id ────────────────────────────────────────────────────────────────────

def test_py_id_matches_id():
    from engine.appc.ships import ShipClass
    before = ShipClass()           # registered with the switch off
    nc.configure(ON)
    after = ShipClass()            # registered with it on
    for ship in (before, after):
        assert _h.combat_dump(ship.__dict__["_nslot"])["py_id"] == id(ship)
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()


# ── Rows follow _active ──────────────────────────────────────────────────────

def test_append_adds_row_in_list_order(on):
    torps = [_fire() for _ in range(3)]
    assert _order() == [t.__dict__["_k3_row"] for t in torps]
    assert _h.combat_torp_size() == 3
    for t in torps:
        assert _row(t)["xform"] == tuple(t._xform)


def test_remove_drops_row(on):
    a, b, c = (_fire() for _ in range(3))
    hb = b.__dict__["_k3_row"]
    projectiles.expire(b)
    assert "_k3_row" not in b.__dict__
    assert _order() == [a.__dict__["_k3_row"], c.__dict__["_k3_row"]]
    with pytest.raises(ValueError):
        _h.combat_torp_dump(hb)
    # pop() drops too.
    projectiles._active.pop(0)
    assert "_k3_row" not in a.__dict__
    assert _order() == [c.__dict__["_k3_row"]]


@pytest.mark.parametrize("mutate", [
    lambda lst, ts: lst.clear() or [lst.append(t) for t in ts],
    lambda lst, ts: lst.insert(0, Torpedo()),
    lambda lst, ts: lst.__setitem__(slice(0, 2), [ts[1], ts[0]]),
    lambda lst, ts: lst.sort(key=lambda t: -t._id),
    lambda lst, ts: lst.reverse(),
    lambda lst, ts: lst.__delitem__(1),
], ids=["clear", "insert", "slice", "sort", "reverse", "del"])
def test_dirty_table_rebuilds_from_python(on, mutate):
    torps = [_fire() for _ in range(3)]
    mutate(projectiles._active, torps)
    assert nc._k3_dirty
    # A dirty table holds nothing a kernel could read in the wrong order.
    assert _h.combat_torp_size() == 0
    # Writes while dirty do not raise; the rebuild reads them from Python.
    torps[1]._age = 2.5
    nc.torpedo_table_rebuild(projectiles._active)
    assert not nc._k3_dirty
    assert _order() == _active_rows()
    for t in projectiles._active:
        assert _row(t)["age"].hex() == float(t._age).hex()
    # A torpedo no longer in the list keeps no row.
    for t in torps:
        if t not in projectiles._active:
            assert "_k3_row" not in t.__dict__ or \
                t.__dict__["_k3_row"] not in _order()
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()


def test_append_twice_marks_dirty(on):
    t = _fire()
    projectiles._active.append(t)
    assert nc._k3_dirty
    nc.torpedo_table_rebuild(projectiles._active)
    assert nc._k3_dirty                     # see the duplicate test below
    assert _h.combat_torp_size() == 0


def test_duplicate_in_active_leaves_the_table_dirty(on):
    """While a torpedo is in `_active` twice (Python's update_all advances
    it twice a tick), the table cannot stand for the list: the rebuild
    leaves it dirty and empty, so K3 hands the step to Python. Once one copy
    is removed, the next rebuild succeeds."""
    a, t = _fire(), _fire()
    projectiles._active.insert(0, t)        # [t, a, t]
    nc.torpedo_table_rebuild(projectiles._active)
    assert nc._k3_dirty
    assert _h.combat_torp_size() == 0
    assert "_k3_row" not in t.__dict__ and "_k3_row" not in a.__dict__
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()
    projectiles._active.remove(t)           # [a, t]: one copy left
    nc.torpedo_table_rebuild(projectiles._active)
    assert not nc._k3_dirty
    assert _order() == [a.__dict__["_k3_row"], t.__dict__["_k3_row"]]


def test_mark_dirty_and_rebuild_are_public(on):
    a, b = _fire(), _fire()
    nc.torpedo_table_mark_dirty()
    assert nc._k3_dirty
    nc.torpedo_table_rebuild(projectiles._active)
    assert _order() == _active_rows()


# ── Every writer pushes ──────────────────────────────────────────────────────

def test_sdk_setters_push(on, scene):
    kset, ship = scene
    target = App.ShipClass_Create("K3Target")
    t = _fire(ship)
    d = _row(t)
    # Constructor defaults, captured at add.
    assert _hex(d["age"], d["ttl"], d["guidance_lifetime"],
                d["guidance_initial"], d["max_angular_accel"]) == \
        _hex(0.0, 60.0, 4.0, 4.0, 0.125)
    assert _vec(d["vel"]) == _hex(0.0, 0.0, 0.0)
    assert d["target"] == -1 and d["target_offset"] is None
    assert d["last_seen"] is None and d["last_tvel"] is None
    assert d["mount_sub"] == -1 and d["mount_attributed"] == 0
    # register joined the source's set: _source_ship and _containing_set.
    assert d["source"] == ship.__dict__["_nslot"]
    assert d["cset"] == kset.__dict__["_nslot"]

    t.SetLifetime(12.5)
    t.SetGuidanceLifetime(3.0)
    t.SetMaxAngularAccel(0.25)
    d = _row(t)
    assert _hex(d["ttl"], d["guidance_lifetime"], d["guidance_initial"],
                d["max_angular_accel"]) == _hex(12.5, 3.0, 3.0, 0.25)

    t.SetTargetOffset(TGPoint3(1.5, -2.0, 0.375))
    assert _vec(_row(t)["target_offset"]) == _hex(1.5, -2.0, 0.375)
    t.SetTargetOffset(None)
    assert _row(t)["target_offset"] is None

    t._target_ship = target
    assert _row(t)["target"] == target.__dict__["_nslot"]
    t._target_ship = object()
    assert _row(t)["target"] == nc.REF_UNREPRESENTABLE
    t._target_ship = None
    assert _row(t)["target"] == -1

    t._source_ship = None
    assert _row(t)["source"] == -1
    t._source_ship = target
    assert _row(t)["source"] == target.__dict__["_nslot"]

    kset.RemoveObjectFromSet(t.GetName())
    assert _row(t)["cset"] == -1

    t._velocity = TGPoint3(0.5, 7.25, -3.0)
    assert _vec(_row(t)["vel"]) == _hex(0.5, 7.25, -3.0)

    t._last_seen_target_pos = TGPoint3(10.0, 20.0, 30.0)
    t._last_target_vel = TGPoint3(-1.0, 0.0, 0.0625)
    d = _row(t)
    assert _vec(d["last_seen"]) == _hex(10.0, 20.0, 30.0)
    assert _vec(d["last_tvel"]) == _hex(-1.0, 0.0, 0.0625)
    t._last_seen_target_pos = None
    t._last_target_vel = None
    d = _row(t)
    assert d["last_seen"] is None and d["last_tvel"] is None

    # _mount_key: attributed only while its target IS the torpedo's target.
    from engine.appc.subsystems import ShipSubsystem
    sub = ShipSubsystem("K3Mount")
    t._target_ship = target
    t._mount_key = (target, 1.0, 2.0, 3.0, sub)
    d = _row(t)
    assert d["mount_attributed"] == 1
    assert d["mount_sub"] == sub.__dict__["_nslot"]
    assert _vec(d["mount_offset"]) == _hex(1.0, 2.0, 3.0)
    t._target_ship = ship
    assert _row(t)["mount_attributed"] == 0
    t._target_ship = target
    assert _row(t)["mount_attributed"] == 1
    t._mount_key = (target, 1.0, 2.0, 3.0, None)
    assert _row(t)["mount_sub"] == -1
    t._mount_key = None
    d = _row(t)
    assert d["mount_attributed"] == 0 and d["mount_sub"] == -1

    t._age = 1.75
    assert _row(t)["age"].hex() == (1.75).hex()

    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()


def _guided(scene):
    """A torpedo fired from the scene's ship at a target in the same set,
    aimed at a target-local offset, its nose off the target line."""
    kset, ship = scene
    target = App.ShipClass_Create("K3Guided")
    kset.AddObjectToSet(target, "K3Guided")
    target.SetTranslateXYZ(0.0, 100.0, 50.0)
    t = Torpedo()
    t._source_ship = ship
    t._velocity = TGPoint3(0.0, 10.0, 0.0)
    t._target_ship = target
    t.SetTargetOffset(TGPoint3(0.5, 1.0, -0.25))
    projectiles.register(t)
    return t, target


def test_update_all_pushes_age_and_velocity(on, scene):
    """The production writers: update_all's `_age += dt`, and _guide's and
    _steer_point's `_velocity`, `_last_seen_target_pos`, `_last_target_vel`
    and `_mount_key` (a guided shot at a live, visible target)."""
    t, target = _guided(scene)
    assert t._last_seen_target_pos is None and t._mount_key is None
    projectiles.update_all(1.0 / 60.0, [])
    # _guide really ran: every writer below fired.
    assert _hex(t._velocity.x, t._velocity.y, t._velocity.z) != \
        _hex(0.0, 10.0, 0.0)
    assert isinstance(t._last_seen_target_pos, TGPoint3)
    assert isinstance(t._last_target_vel, TGPoint3)
    assert t._mount_key is not None and t._mount_key[0] is target
    d = _row(t)
    assert d["age"].hex() == float(t._age).hex() != (0.0).hex()
    assert _vec(d["vel"]) == _hex(t._velocity.x, t._velocity.y,
                                  t._velocity.z)
    p = t._last_seen_target_pos
    assert _vec(d["last_seen"]) == _hex(p.x, p.y, p.z)
    v = t._last_target_vel
    assert _vec(d["last_tvel"]) == _hex(v.x, v.y, v.z)
    assert d["mount_attributed"] == 1
    assert _vec(d["mount_offset"]) == _hex(0.5, 1.0, -0.25)
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()


def test_dropped_target_row_reads_unrepresentable(on, scene):
    """A target whose own row is dropped (it took the Python path) is still
    the torpedo's target: the row reads -2, never None (which would fly the
    torpedo ballistic)."""
    t, target = _guided(scene)
    assert _row(t)["target"] == target.__dict__["_nslot"]
    nc._drop(target)
    assert _row(t)["target"] == nc.REF_UNREPRESENTABLE
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()


def test_unrepresentable_value_flags_the_field(on):
    t = _fire()
    t._ttl = "not a number"
    assert "_ttl" in _row(t)["unrepresentable"]
    t.SetLifetime(5)
    d = _row(t)
    assert d["unrepresentable"] == [] and d["ttl"].hex() == (5.0).hex()
    t._last_seen_target_pos = (1.0, 2.0, 3.0)   # not None, not a TGPoint3
    assert "_last_seen_target_pos" in _row(t)["unrepresentable"]
    t._last_seen_target_pos = None
    assert _row(t)["unrepresentable"] == []


def test_no_baked_offset_field(on):
    """Fire control native only, M5: a picked spot is a plain body point
    with no launch-time bake, so neither the torpedo, its encoding nor the
    native table carries `_baked_offset` any more."""
    assert "_baked_offset" not in vars(Torpedo)
    assert "_baked_offset" not in nc._TORP_FIELDS
    assert "_baked_offset" not in dict(_h.combat_torp_field_names())
    assert "baked" not in _row(_fire())


# ── Audit ────────────────────────────────────────────────────────────────────

def test_audit_compares_torpedo_rows(on):
    a, b = _fire(), _fire()
    nc.audit_mirror()
    assert nc.audit_failures() == []
    a.__dict__["_age"] = 9.0             # bypasses the descriptor
    nc.audit_mirror()
    assert ("Torpedo", "_age") in nc.audit_failures()
    nc.audit_failures().clear()
    a._age = 9.0
    list.append(projectiles._active, Torpedo())   # bypasses the hook
    nc.audit_mirror()
    assert ("Torpedo", "order") in nc.audit_failures()


def test_lead_accel_k_global_pushed(on):
    got = _h.combat_dump_globals()["LEAD_ACCEL_K"]
    assert float(got).hex() == float(projectiles._LEAD_ACCEL_K).hex()


# ── Switch off ───────────────────────────────────────────────────────────────

def test_switch_off_registers_nothing():
    """K3's torpedo table follows the switch, not the mirror: with =0 the
    mirror is live (fire control native only, M9) and no torpedo gets a
    row."""
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "0"})
    assert not nc.enabled() and nc.fire_control_native()
    before = _h.combat_torp_size()
    nc.torpedo_table_rebuild(projectiles._active)
    t = _fire()
    t._age = 1.0
    t.SetLifetime(3.0)
    t._velocity = TGPoint3(1.0, 0.0, 0.0)
    assert "_k3_row" not in t.__dict__
    assert _h.combat_torp_size() == before == 0
    nc.torpedo_table_rebuild(projectiles._active)   # with t in flight
    assert "_k3_row" not in t.__dict__
    assert _h.combat_torp_size() == 0
    projectiles.expire(t)
