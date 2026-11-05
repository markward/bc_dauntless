"""Pose tables, part slots, mount order and the part-map generation in the
native combat mirror (native-combat posed parts, Task 1; spec
docs/superpowers/specs/2026-11-01-native-combat-posed-parts-design.md
§4.1-4.3, map docs/reference/engine/native-combat/posed-parts-map.md §2-3).

Python stays the only resolver of WHICH part a mount sits on. It pushes:

* per ship, the pose table: one entry per `articulation.posed_part_names`
  name, in that order -- R (row-major), t, Python's `is_identity`, and
  `name in _parts_detached`; empty while `_posed_flag` is 0;
* per subsystem, the part slot -- the table index of the part `_live_part`
  resolves for its own mount, detachment ignored -- stamped with the global
  part-map generation at resolution;
* per ship, the mount order (`combat._iter_subsystems`).

Every input of the resolution bumps the generation, so a slot whose inputs
changed reads stale (a fallback), never a wrong part. No kernel reads these
yet; these tests pin the pushes, the triggers and the audit.
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

from engine import host_io  # noqa: E402
from engine.appc import articulated_part, articulation, part_pose  # noqa: E402
from engine.appc import combat  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import part_severance, physical_parents  # noqa: E402
from engine.appc import subsystems as ss  # noqa: E402
from engine.appc.math import TGPoint3  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
DT = 1.0 / 60.0
LEAF = "birdofprey"


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    yield
    nc.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


def _ship(name, hardpoint, script, at=(0.0, 0.0, 0.0)):
    ship = App.ShipClass_Create(name)
    ship.SetScript(script)
    mod_name = "ships.Hardpoints." + hardpoint
    App.g_kModelPropertyManager.ClearLocalTemplates()
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    sys.modules[mod_name].LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()
    ship.SetTranslateXYZ(*at)
    return ship


def _make_scene(native_on=True):
    if native_on:
        nc.configure(ON)
        assert nc.enabled()
    pset = App.SetClass_Create()
    App.g_kSetManager.AddSet(pset, "native_part_slots")
    bop = _ship("BoP1", "birdofprey", "ships.BirdOfPrey")
    galaxy = _ship("Galaxy1", "galaxy", "ships.Galaxy", at=(0.0, 300.0, 0.0))
    for ship in (bop, galaxy):
        pset.AddObjectToSet(ship, ship.GetName())
    # The leaf is resolved (tick_ship would do it on the first tick).
    assert articulation.leaf_for(bop) == LEAF
    assert [p.GetName() for p in articulation.parts_for_ship(bop)] == [
        "left wing", "left wing01"]
    return bop, galaxy


@pytest.fixture
def scene():
    """A Bird of Prey (rigged: both wings) and a Galaxy (no rig), one set,
    native combat on."""
    bop, galaxy = _make_scene()
    try:
        yield bop, galaxy
    finally:
        App.g_kSetManager.DeleteSet("native_part_slots")


def _row(obj):
    return _h.combat_dump(obj.__dict__["_nslot"])


def _hx(values):
    return tuple(float(v).hex() for v in values)


def _walk(ship):
    """Every subsystem of `ship`: its top-level subsystems (hull included)
    and their children, depth first."""
    out, seen = [], set()

    def visit(sub):
        if sub is None or id(sub) in seen:
            return
        seen.add(id(sub))
        out.append(sub)
        for c in getattr(sub, "_children", None) or ():
            visit(c)
    for s in ship.GetSubsystems():
        visit(s)
    return out


def _expected_slot(ship, sub):
    """The slot `_live_part` implies for `sub`'s own mount: the index of
    the part it resolves in posed_part_names, -1 for none."""
    p = sub.GetPosition()
    names = articulation.posed_part_names(ship)
    found = articulation._live_part(ship, None, (p.x, p.y, p.z), True,
                                    physical_parents.property_of(sub))
    return names.index(found) if found is not None else -1


def _cruise(bop):
    articulation.force_pose(bop, "cruise")
    assert nc._posed_flag(bop) == 1


def _audit_clean():
    nc.audit_mirror()
    assert nc.audit_failures() == []


def _wing_cannon(bop):
    """A subsystem whose mount resolves to a wing (non-vacuous slot)."""
    names = articulation.posed_part_names(bop)
    for sub in _walk(bop):
        if _expected_slot(bop, sub) >= 0:
            return sub, names
    raise AssertionError("no BoP subsystem sits on a wing")


# ── The pose table ───────────────────────────────────────────────────────────

def _assert_table_matches(ship):
    names = articulation.posed_part_names(ship)
    table = _row(ship)["part_poses"]
    poses = ship.__dict__.get("_articulation_poses") or {}
    detached = getattr(ship, "_parts_detached", None) or set()
    assert len(table) == len(names)
    for name, (r, t, identity, det) in zip(names, table):
        R, tt = poses.get(name, part_pose.IDENTITY)
        assert _hx(r) == _hx([R[i][j] for i in range(3) for j in range(3)])
        assert _hx(t) == _hx(tt)
        assert identity == part_pose.is_identity((R, tt))
        assert det == (name in detached)


def test_pose_table_matches_articulation_poses(scene):
    bop, _galaxy = scene
    _cruise(bop)
    _assert_table_matches(bop)
    assert all(not e[2] for e in _row(bop)["part_poses"])
    # One part off identity, the other at it: the identity bit is Python's.
    cruise = articulation.target_pose(articulation.parts_for_ship(bop)[0],
                                      "cruise")
    articulation.force_part_pose(bop, "left wing", cruise)
    _assert_table_matches(bop)
    assert [e[2] for e in _row(bop)["part_poses"]] == [False, True]
    # Mid-transition, tick by tick (tick_ship's in-place writes): from
    # cruise, an NPC with a target swings toward red's identity pose.
    articulation.force_pose(bop, "cruise")
    bop.SetTarget(_galaxy)
    assert articulation.state_for(bop) == "red"
    seen_mid = False
    for _ in range(200):
        articulation.tick_ship(bop, DT)
        if nc._posed_flag(bop):
            _assert_table_matches(bop)
            seen_mid = seen_mid or bool(
                bop.__dict__.get("_articulation_transitions"))
        else:
            assert _row(bop)["part_poses"] == []
    assert seen_mid
    _audit_clean()


def test_unposed_ship_pushes_empty_table(scene):
    bop, galaxy = scene
    nc.resolve_stale_part_slots([bop, galaxy])
    assert _row(galaxy)["part_poses"] == []
    # Rigged, but every part at its NIF pose: flag 0, empty table.
    articulation.force_pose(bop, None)
    assert nc._posed_flag(bop) == 0
    assert _row(bop)["part_poses"] == []
    _audit_clean()


def test_detached_bit_pushed_synchronously_on_sever(scene):
    bop, _galaxy = scene
    _cruise(bop)
    nc.resolve_stale_part_slots([bop])
    assert [e[3] for e in _row(bop)["part_poses"]] == [False, False]
    part_severance.sever(bop, None, "left wing01")
    # No step boundary in between: the very next read sees it.
    assert [e[3] for e in _row(bop)["part_poses"]] == [False, True]
    _assert_table_matches(bop)
    part_severance.reset_ship(bop)
    assert [e[3] for e in _row(bop)["part_poses"]] == [False, False]
    _audit_clean()


def test_resync_pushes_tables_and_mount_order():
    bop, _galaxy = _make_scene(native_on=False)
    try:
        _cruise(bop)
        nc.configure(ON)
        assert nc.enabled()
        _assert_table_matches(bop)
        assert _row(bop)["mount_order"] == [
            s.__dict__["_nslot"] for s in combat._iter_subsystems(bop)]
        assert _h.combat_part_gen() == nc.part_gen()
    finally:
        App.g_kSetManager.DeleteSet("native_part_slots")


# ── Part slots ───────────────────────────────────────────────────────────────

def test_slot_matches_live_part(scene):
    bop, galaxy = scene
    _cruise(bop)
    nc.resolve_stale_part_slots([bop, galaxy])
    gen = nc.part_gen()
    assert _h.combat_part_gen() == gen
    on_wing = 0
    for sub in _walk(bop):
        row = _row(sub)
        want = _expected_slot(bop, sub)
        assert (row["part_slot"], row["part_gen"]) == (want, gen), \
            sub.GetName()
        on_wing += want >= 0
    assert on_wing > 0                      # not vacuous
    # Explicit physical parents: the BoP's systems name "birdofprey", not a
    # posable part -> -1 (identity).
    imp = bop.GetImpulseEngineSubsystem()
    assert physical_parents.property_of(imp).GetPhysicalParent() == LEAF
    assert _row(imp)["part_slot"] == -1
    _audit_clean()


def test_unresolved_leaf_is_never_resolved(scene):
    """R5: a ship whose leaf is not known yet is skipped -- never
    `leaf_for` from the resolver (it would cache "" for good)."""
    _bop, _galaxy = scene
    ship = App.ShipClass_Create("NoScript")
    assert ship.__dict__.get("_articulation_leaf") is None
    nc.resolve_stale_part_slots([ship])
    assert ship.__dict__.get("_articulation_leaf") is None


def _set_physical_parent(bop, sub):
    physical_parents.property_of(sub).SetPhysicalParent("left wing")


def _set_preview(bop, sub):
    physical_parents.set_preview(
        LEAF, {physical_parents.property_of(sub).GetName(): "left wing"})


def _clear_preview(bop, sub):
    physical_parents.clear_preview(LEAF)


def _leaf_model_learned(bop, sub, monkeypatch):
    monkeypatch.setattr(host_io, "instance_model", lambda iid: 4242)
    articulation.part_boxes_for(LEAF, 7)
    assert articulation.leaf_model(LEAF) == 4242


def _derived_boxes_learned(bop, sub, monkeypatch):
    monkeypatch.setitem(articulation._leaf_models, "testleaf", 99)
    monkeypatch.setattr(host_io, "model_nodes", lambda iid: [
        {"candidate": True, "name": "x", "bounds_min": (0.0, 0.0, 0.0),
         "bounds_max": (1.0, 1.0, 1.0)}])
    assert articulation.part_boxes_for("testleaf", 5)


def _rig_snapshot(bop, sub, monkeypatch):
    articulated_part.snapshot_for_leaf("testleaf")


def _rig_restore(bop, sub, monkeypatch):
    articulated_part.restore(dict(articulated_part._BY_LEAF))


def _rig_reset(bop, sub, monkeypatch):
    articulated_part.reset()


def _forced_name(bop, sub, monkeypatch):
    # A part the SPV poses by name: posed_part_names gains it.
    cruise = articulation.target_pose(articulation.parts_for_ship(bop)[0],
                                      "cruise")
    articulation.force_state_poses(
        bop, {"left wing": cruise, "left wing01": cruise, "head": cruise})
    assert "head" in articulation.posed_part_names(bop)


def _subsystem_position(bop, sub, monkeypatch):
    p = sub.GetPosition()
    sub._position = TGPoint3(p.x + 0.25, p.y, p.z)


def _subsystem_property(bop, sub, monkeypatch):
    # Only _property is written (SetProperty(None) returns before the mount
    # fields): the bump must come from _property itself.
    p = sub.GetPosition()
    sub.SetProperty(None)
    assert physical_parents.property_of(sub) is None
    q = sub.GetPosition()
    assert (q.x, q.y, q.z) == (p.x, p.y, p.z)


def _property_rename(bop, sub, monkeypatch):
    prop = physical_parents.property_of(sub)
    monkeypatch.setattr(prop, "_name", prop._name)    # restored after
    prop.SetName(str(prop.GetName()) + " renamed")


_TRIGGERS = {
    "set_physical_parent": lambda b, s, m: _set_physical_parent(b, s),
    "set_preview": lambda b, s, m: _set_preview(b, s),
    "clear_preview": lambda b, s, m: _clear_preview(b, s),
    "leaf_model_learned": _leaf_model_learned,
    "derived_boxes_learned": _derived_boxes_learned,
    "rig_snapshot": _rig_snapshot,
    "rig_restore": _rig_restore,
    "rig_reset": _rig_reset,
    "posed_names_change": _forced_name,
    "subsystem_position": _subsystem_position,
    "subsystem_property": _subsystem_property,
    "property_rename": _property_rename,
}


@pytest.mark.parametrize("trigger", sorted(_TRIGGERS))
def test_each_trigger_bumps_generation(scene, trigger, monkeypatch):
    bop, _galaxy = scene
    # Process-wide caches the triggers write: restored after the test.
    monkeypatch.setattr(articulation, "_derived_boxes",
                        dict(articulation._derived_boxes))
    monkeypatch.setattr(articulated_part, "_BY_LEAF",
                        dict(articulated_part._BY_LEAF))
    monkeypatch.setattr(part_severance, "_mount_parts", {})
    _cruise(bop)
    nc.resolve_stale_part_slots([bop])
    sub, _names = _wing_cannon(bop)
    before = nc.part_gen()
    assert _row(sub)["part_gen"] == before          # fresh
    _TRIGGERS[trigger](bop, sub, monkeypatch)
    assert nc.part_gen() > before
    assert _h.combat_part_gen() == nc.part_gen()    # pushed at once
    assert _row(sub)["part_gen"] != _h.combat_part_gen()   # reads stale


def test_slot_resolved_before_model_learned_reads_stale_after(
        scene, monkeypatch):
    """Review Focus 1: a slot resolved by the box rule before the leaf's
    model was learned must read stale once `model_nearest_part` would
    answer differently -- never the old part."""
    bop, _galaxy = scene
    monkeypatch.setattr(part_severance, "_mount_parts", {})
    _cruise(bop)
    nc.resolve_stale_part_slots([bop])
    sub, names = _wing_cannon(bop)
    old = _row(sub)["part_slot"]
    other = names[1 - old]                  # the other wing
    monkeypatch.setattr(host_io, "instance_model", lambda iid: 4242)
    monkeypatch.setattr(host_io, "model_nearest_part",
                        lambda model, point: other)
    articulation.part_boxes_for(LEAF, 7)    # first realize: model learned
    # Python's answer changed...
    assert _expected_slot(bop, sub) == names.index(other)
    # ...and the old slot is no longer current.
    row = _row(sub)
    assert row["part_slot"] == old
    assert row["part_gen"] != _h.combat_part_gen()
    nc.resolve_stale_part_slots([bop])
    row = _row(sub)
    assert (row["part_slot"], row["part_gen"]) == (
        names.index(other), _h.combat_part_gen())
    _audit_clean()


def test_property_rename_under_preview_reads_stale(scene, monkeypatch):
    """The SPV preview overlay keys on prop.GetName(): renaming the
    property changes which part Python resolves, so the slot must read
    stale, and re-resolving gives Python's new answer."""
    bop, _galaxy = scene
    monkeypatch.setattr(part_severance, "_mount_parts", {})
    _cruise(bop)
    nc.resolve_stale_part_slots([bop])
    sub, names = _wing_cannon(bop)
    prop = physical_parents.property_of(sub)
    other = names[1 - _row(sub)["part_slot"]]
    physical_parents.set_preview(LEAF, {str(prop.GetName()): other})
    nc.resolve_stale_part_slots([bop])
    previewed = _row(sub)["part_slot"]
    assert previewed == names.index(other) == _expected_slot(bop, sub)
    monkeypatch.setattr(prop, "_name", prop._name)    # restored after
    prop.SetName(str(prop.GetName()) + " renamed")
    assert _expected_slot(bop, sub) != previewed      # Python's answer moved
    row = _row(sub)
    assert row["part_slot"] == previewed
    assert row["part_gen"] != _h.combat_part_gen()    # ...so the slot is stale
    nc.resolve_stale_part_slots([bop])
    row = _row(sub)
    assert (row["part_slot"], row["part_gen"]) == (
        _expected_slot(bop, sub), _h.combat_part_gen())
    _audit_clean()


def test_subsystem_moved_to_another_ship_reads_stale(scene):
    """A subsystem resolved on ship A, then attached to ship B: its slot
    was computed with A's leaf and names, so it must read stale."""
    bop, galaxy = scene
    _cruise(bop)
    nc.resolve_stale_part_slots([bop, galaxy])
    sub, _names = _wing_cannon(bop)
    assert _row(sub)["part_gen"] == _h.combat_part_gen()
    galaxy.GetPhaserSystem().AddChildSubsystem(sub)
    assert sub._climb_to_ship() is not bop
    assert _row(sub)["part_gen"] != _h.combat_part_gen()


# ── Mount order ──────────────────────────────────────────────────────────────

def _handles(subs):
    return [s.__dict__["_nslot"] for s in subs]


def test_mount_order_matches_iter_subsystems(scene):
    bop, galaxy = scene
    for ship in (bop, galaxy):
        assert _row(ship)["mount_order"] == _handles(
            combat._iter_subsystems(ship))
    # Attaching a child changes the order: pushed at once.
    extra = ss.ShipSubsystem("Extra")
    system = galaxy.GetPhaserSystem()
    system.AddChildSubsystem(extra)
    order = _row(galaxy)["mount_order"]
    assert order == _handles(combat._iter_subsystems(galaxy))
    assert extra.__dict__["_nslot"] in order
    # A new top-level subsystem (a cloak on the Galaxy).
    cloak = ss.ShipSubsystem("Cloak")
    galaxy.SetCloakingSubsystem(cloak)
    assert _row(galaxy)["mount_order"] == _handles(
        combat._iter_subsystems(galaxy))
    _audit_clean()


def test_new_subsystem_slot_is_stale_until_resolved(scene):
    bop, _galaxy = scene
    _cruise(bop)
    nc.resolve_stale_part_slots([bop])
    extra = ss.ShipSubsystem("Extra")
    bop.GetPulseWeaponSystem().AddChildSubsystem(extra)
    assert _row(extra)["part_gen"] != _h.combat_part_gen()
    nc.resolve_stale_part_slots([bop])
    assert _row(extra)["part_gen"] == _h.combat_part_gen()
    assert _row(extra)["part_slot"] == _expected_slot(bop, extra)


# ── Switch off and the audit ─────────────────────────────────────────────────

class _Recorder:
    """Stands in for the bindings module and records every name read."""

    def __init__(self, real):
        self._real = real
        self.names = []

    def __getattr__(self, name):
        self.names.append(name)
        return getattr(self._real, name)


def test_switch_off_pushes_nothing(monkeypatch):
    bop, galaxy = _make_scene(native_on=False)
    try:
        extra = ss.ShipSubsystem("Extra")
        cloak = ss.ShipSubsystem("Cloak")
        monkeypatch.setattr(part_severance, "_mount_parts", {})
        monkeypatch.setattr(articulated_part, "_BY_LEAF",
                            dict(articulated_part._BY_LEAF))
        rec = _Recorder(_h)
        monkeypatch.setattr(nc, "_h", rec)
        _cruise(bop)
        articulation.tick_ship(bop, DT)
        nc.resolve_stale_part_slots([bop, galaxy])
        nc.resolve_part_slots(bop)
        nc.push_mount_order(bop)
        sub, _names = _wing_cannon(bop)
        _set_physical_parent(bop, sub)
        _set_preview(bop, sub)
        _clear_preview(bop, sub)
        _subsystem_position(bop, sub, monkeypatch)
        _subsystem_property(bop, sub, monkeypatch)
        _rig_restore(bop, sub, monkeypatch)
        galaxy.GetPhaserSystem().AddChildSubsystem(extra)
        galaxy.SetCloakingSubsystem(cloak)
        part_severance.sever(bop, None, "left wing01")
        part_severance.reset_ship(bop)
        assert rec.names == []
    finally:
        App.g_kSetManager.DeleteSet("native_part_slots")


def test_audit_mirror_compares_pose_table(scene):
    bop, galaxy = scene
    _cruise(bop)
    nc.resolve_stale_part_slots([bop, galaxy])
    _audit_clean()
    h = bop.__dict__["_nslot"]
    table = _row(bop)["part_poses"]
    r, t, identity, det = table[0]
    bad = [(tuple(r[:8]) + (r[8] + 1e-12,), t, identity, det)] + table[1:]
    _h.combat_set_part_poses(h, bad)
    nc.audit_mirror()
    assert ("ShipClass", "part_poses") in nc.audit_failures()


def test_audit_mirror_compares_slots_and_mount_order(scene):
    bop, galaxy = scene
    _cruise(bop)
    nc.resolve_stale_part_slots([bop, galaxy])
    sub, _names = _wing_cannon(bop)
    sh = sub.__dict__["_nslot"]
    _h.combat_set_part_slot(sh, -1, nc.part_gen())      # fresh, wrong
    _h.combat_set_mount_order(galaxy.__dict__["_nslot"], [])
    nc.audit_mirror()
    failures = nc.audit_failures()
    assert (type(sub).__name__, "part_slot") in failures
    assert ("ShipClass", "mount_order") in failures


# ── The pending set (phase 6 A3): resolve_stale_part_slots is O(1) when no
# ship is stale. Every way a ship's slots go stale lands it in the pending
# state (nc._part_pending, or every leafed handle while the generation moved
# since the last sweep); a sweep is today's full scan of `ships`, then a
# prune by state. One test per way.

class _CountingShips(list):
    iterations = 0

    def __iter__(self):
        type(self).iterations += 1
        return super().__iter__()


@pytest.fixture
def resolved(monkeypatch, scene):
    """The ships resolve_part_slots is called for, in order, that it can
    resolve (a known leaf: for one without, the call is a no-op). The
    scene's Galaxy has its leaf learned too."""
    assert articulation.leaf_for(scene[1]) == "galaxy"
    calls = []
    real = nc.resolve_part_slots

    def spy(ship, drop=True):
        if nc._leaf_known(ship) is not None:
            calls.append(ship)
        return real(ship, drop)
    monkeypatch.setattr(nc, "resolve_part_slots", spy)
    return calls


def _settle(*ships):
    """Resolve everything stale (two passes: a resolution may bump)."""
    nc.resolve_stale_part_slots(list(ships))
    nc.resolve_stale_part_slots(list(ships))


def test_nothing_stale_scans_no_ship(scene, resolved):
    bop, galaxy = scene
    _settle(bop, galaxy)
    ships = _CountingShips([bop, galaxy])
    _CountingShips.iterations = 0
    for _ in range(4):
        nc.resolve_stale_part_slots(ships)
    assert _CountingShips.iterations == 0


def test_a_generation_bump_resolves_every_ship_once(scene, resolved):
    bop, galaxy = scene
    _settle(bop, galaxy)
    resolved.clear()
    nc.bump_part_gen()
    nc.resolve_stale_part_slots([bop, galaxy])
    nc.resolve_stale_part_slots([bop, galaxy])
    assert resolved == [bop, galaxy]


def test_a_ship_left_out_of_a_sweep_stays_pending(scene, resolved):
    bop, galaxy = scene
    _settle(bop, galaxy)
    resolved.clear()
    nc.bump_part_gen()
    nc.resolve_stale_part_slots([galaxy])
    nc.resolve_stale_part_slots([galaxy])
    nc.resolve_stale_part_slots([bop])
    assert resolved == [galaxy, bop]


def test_a_bump_during_a_sweep_leaves_the_earlier_ships_pending(
        scene, resolved, monkeypatch):
    bop, galaxy = scene
    _settle(bop, galaxy)
    resolved.clear()
    real = nc.resolve_part_slots       # the spy
    bumped = []

    def bump_on_galaxy(ship, drop=True):
        real(ship, drop)        # the spy, recording
        if ship is galaxy and not bumped:
            bumped.append(1)
            nc.bump_part_gen()
    monkeypatch.setattr(nc, "resolve_part_slots", bump_on_galaxy)
    nc.bump_part_gen()
    nc.resolve_stale_part_slots([bop, galaxy])   # bop fresh, then a bump
    nc.resolve_stale_part_slots([bop, galaxy])   # both again
    nc.resolve_stale_part_slots([bop, galaxy])   # nothing
    assert resolved == [bop, galaxy, bop, galaxy]


def test_a_leaf_learned_after_register_is_resolved(scene, resolved):
    bop, galaxy = scene
    _settle(bop, galaxy)
    late = _ship("BoP2", "birdofprey", "ships.BirdOfPrey",
                 at=(0.0, -300.0, 0.0))
    assert late.__dict__.get("_articulation_leaf") is None
    _settle(bop, galaxy, late)          # no leaf: nothing to resolve yet
    resolved.clear()
    assert articulation.leaf_for(late) == LEAF
    nc.resolve_stale_part_slots([bop, galaxy, late])
    nc.resolve_stale_part_slots([bop, galaxy, late])
    assert resolved == [late]
    assert nc._resolved_gen[late.__dict__["_nslot"]] == nc.part_gen()


def test_a_leaf_assigned_directly_is_resolved(scene, resolved):
    bop, galaxy = scene
    _settle(bop, galaxy)
    late = _ship("BoP3", "birdofprey", "ships.BirdOfPrey",
                 at=(0.0, -300.0, 0.0))
    _settle(bop, galaxy, late)
    resolved.clear()
    late._articulation_leaf = LEAF
    nc.resolve_stale_part_slots([bop, galaxy, late])
    assert resolved == [late]


def test_a_leaf_on_a_class_without_the_descriptor_is_polled(
        scene, resolved):
    """A class shadowing the leaf descriptor (a test double's class
    attribute): its instance write is not seen, so its row is polled."""
    from engine.appc.ships import ShipClass

    class Shadowed(ShipClass):
        _articulation_leaf = None

    bop, galaxy = scene
    _settle(bop, galaxy)
    odd = Shadowed()
    odd.SetName("Odd")
    _settle(bop, galaxy, odd)
    resolved.clear()
    odd._articulation_leaf = "galaxy"
    assert odd.__dict__["_articulation_leaf"] == "galaxy"
    nc.resolve_stale_part_slots([bop, galaxy, odd])
    nc.resolve_stale_part_slots([bop, galaxy, odd])
    assert resolved == [odd]


def test_a_re_registered_ship_is_resolved(scene, resolved):
    bop, galaxy = scene
    _settle(bop, galaxy)
    resolved.clear()
    nc._drop(galaxy)
    nc.drain()
    nc.register(galaxy, "Object")
    assert "_nslot" in galaxy.__dict__
    nc.resolve_stale_part_slots([bop, galaxy])
    assert galaxy in resolved


def _late_bop(name, *settled):
    """A Bird of Prey added after the scene, everything settled, then its
    leaf learned: its row alone is pending, at the current generation (no
    bump involved)."""
    late = _ship(name, "birdofprey", "ships.BirdOfPrey",
                 at=(0.0, -300.0, 0.0))
    _settle(*settled, late)
    gen = nc.part_gen()
    assert articulation.leaf_for(late) == LEAF
    assert nc.part_gen() == gen
    return late


def test_a_resolution_that_raised_is_retried_without_a_bump(
        scene, resolved, monkeypatch):
    bop, galaxy = scene
    late = _late_bop("BoP5", bop, galaxy)
    sub, _names = _wing_cannon(late)
    gen = nc.part_gen()
    real = part_severance.part_for_mount

    def boom(leaf, point):
        raise RuntimeError("probe")
    monkeypatch.setattr(part_severance, "part_for_mount", boom)
    monkeypatch.setattr(physical_parents, "property_of", lambda s: None)
    nc.resolve_stale_part_slots([bop, galaxy, late])
    assert _row(sub)["part_gen"] != _h.combat_part_gen()     # left stale
    monkeypatch.setattr(part_severance, "part_for_mount", real)
    resolved.clear()
    nc.resolve_stale_part_slots([bop, galaxy, late])
    assert nc.part_gen() == gen         # no bump in between
    assert resolved == [late]
    assert _row(sub)["part_gen"] == _h.combat_part_gen()


def test_a_pose_table_that_cannot_be_pushed_is_retried(
        scene, resolved, monkeypatch):
    """The mid-walk heal (drop=False) leaves an unencodable table's ship
    stale, row kept: the next sweep retries it."""
    bop, galaxy = scene
    late = _late_bop("BoP6", bop, galaxy)
    _cruise(late)
    gen = nc.part_gen()
    real = nc._pose_table

    def bad(ship, names):
        raise TypeError("probe")
    monkeypatch.setattr(nc, "_pose_table", bad)
    nc._heal_part_slots([bop, galaxy, late], gen - 1)
    assert "_nslot" in late.__dict__
    monkeypatch.setattr(nc, "_pose_table", real)
    resolved.clear()
    nc.resolve_stale_part_slots([bop, galaxy, late])
    assert nc.part_gen() == gen
    assert resolved == [late]


def test_forgotten_caches_resolve_every_ship(scene, resolved):
    bop, galaxy = scene
    _settle(bop, galaxy)
    resolved.clear()
    nc._forget_part_caches()
    nc.resolve_stale_part_slots([bop, galaxy])
    assert resolved == [bop, galaxy]


def test_a_mount_order_push_resolves_its_ship(scene, resolved):
    bop, galaxy = scene
    _settle(bop, galaxy)
    resolved.clear()
    nc.push_mount_order(galaxy)
    nc.resolve_stale_part_slots([bop, galaxy])
    assert galaxy in resolved
