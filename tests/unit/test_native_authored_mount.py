"""The native authored-mount lookup vs the Python it ports (native-combat
posed parts, Task 3; spec
docs/superpowers/specs/2026-11-01-native-combat-posed-parts-design.md §4.4,
map docs/reference/engine/native-combat/posed-parts-map.md §3.4 and R3).

`part_severance.authored_mount_subsystem(ship, point)` is a first-match scan
of `combat._iter_subsystems` order (each top-level subsystem, then its
`_children`) with a per-axis `abs(mount - point) <= 1e-5` test. Native walks
the pushed `mount_order` with the same test
(native/src/combat/src/part_pose.cc). Its answer: the subsystem's handle,
-1 (Python None), or -2 when the mirror cannot answer (a subsystem it cannot
name reached before a match, or a target that is not a ShipClass: its
mount order is never pushed). Seeded random.Random(20261101), 2,000 cases.
"""
import importlib
import math
import random
import sys

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_test_mount_position"),
    reason="native posed-part geometry bindings not built")

from engine.appc import articulation, combat  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import part_severance, physical_parents  # noqa: E402
from engine.appc import subsystems as ss  # noqa: E402
from engine.appc.math import TGPoint3  # noqa: E402
from engine.appc.objects import DamageableObject  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
SEED = 20261101
CASES = 2000
EPS = 1e-5
LEAF = "birdofprey"
NO_MOUNT = -1
ASK = -2


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


@pytest.fixture
def scene():
    """A Bird of Prey (rigged) and a Galaxy (no rig), one set, native on."""
    nc.configure(ON)
    assert nc.enabled()
    pset = App.SetClass_Create()
    App.g_kSetManager.AddSet(pset, "native_authored_mount")
    bop = _ship("BoP1", "birdofprey", "ships.BirdOfPrey")
    galaxy = _ship("Galaxy1", "galaxy", "ships.Galaxy", at=(0.0, 300.0, 0.0))
    for ship in (bop, galaxy):
        pset.AddObjectToSet(ship, ship.GetName())
    assert articulation.leaf_for(bop) == LEAF
    try:
        yield bop, galaxy
    finally:
        part_severance.reset_ship(bop)
        physical_parents.clear_preview(LEAF)
        App.g_kSetManager.DeleteSet("native_authored_mount")


def _slot(obj):
    return obj.__dict__["_nslot"] if obj is not None else -1


def _row(obj):
    return _h.combat_dump(_slot(obj))


def _python(ship, point):
    """Python's answer as a handle: the subsystem's, or -1 for None."""
    return _slot(part_severance.authored_mount_subsystem(ship, tuple(point)))


def _native(ship, point):
    return _h.combat_test_authored_mount(_slot(ship), tuple(point))


def _mounts(ship):
    return part_severance._mounted_subsystems(ship)


def _set_pos(sub, p):
    sub._position = TGPoint3(*p)


# ── The differential ─────────────────────────────────────────────────────────

def _within(mount, point):
    return all(abs(mount[i] - point[i]) <= EPS for i in range(3))


def _ulps_around(x, n):
    """x, then 1..n ulps above and below it."""
    out, up, down = [x], x, x
    for _ in range(n):
        up = math.nextafter(up, math.inf)
        down = math.nextafter(down, -math.inf)
        out += [up, down]
    return out


def _offset(rng, mount):
    """A query near `mount` and its kind. Deltas are per axis: an offset
    0.9e-5 off on all three axes is 1.56e-5 away and still matches."""
    kind = rng.choice(("exact", "in", "out", "edge", "nan", "inf", "far",
                       "signed_zero"))
    m = list(mount)
    if kind == "exact":
        return tuple(m), kind
    if kind == "signed_zero":
        return tuple(-c if c == 0.0 else c for c in m), kind
    if kind in ("in", "out"):
        mag = 0.9e-5 if kind == "in" else 1.1e-5
        axes = rng.sample(range(3), rng.randint(1, 3))
        for a in axes:
            m[a] = m[a] + rng.choice((mag, -mag))
        return tuple(m), kind
    if kind == "edge":
        # On or one ulp either side of the 1e-5 bound (`<=`, not `<`).
        # Exactly 1e-5 off is representable only near 0 (a difference of
        # doubles near 0.5 is a multiple of 2**-54; 1e-5 is not): prefer a
        # centre-line axis.
        zeros = [i for i in range(3) if m[i] == 0.0]
        a = rng.choice(zeros) if zeros else rng.randrange(3)
        d = rng.choice((EPS, -EPS))
        p = m[a] - d
        # Walk a few ulps to a p with abs(m - p) exactly 1e-5, if any.
        for cand in _ulps_around(p, 4):
            if abs(m[a] - cand) == EPS:
                p = cand
                break
        step = rng.choice((0, 0, 1, -1))
        if step:
            p = math.nextafter(p, step * math.inf)
        m[a] = p
        return tuple(m), kind
    if kind == "nan":
        m[rng.randrange(3)] = math.nan
        return tuple(m), kind
    if kind == "inf":
        m[rng.randrange(3)] = rng.choice((math.inf, -math.inf))
        return tuple(m), kind
    return tuple(rng.uniform(-10.0, 10.0) for _ in range(3)), kind


def test_authored_mount_matches_python(scene):
    bop, galaxy = scene
    rng = random.Random(SEED)
    tally = {}
    found = by_kind_found = 0
    edge_exact = per_axis_only = 0
    collisions = multi = 0
    for case in range(CASES):
        ship = rng.choice((bop, galaxy))
        mounts = _mounts(ship)
        # A quarter of the cases move one subsystem within 1e-5 of another
        # (first match decides) or anywhere (native reads _position live).
        if rng.random() < 0.25:
            (mover, _), (_anchor, at) = rng.sample(mounts, 2)
            if rng.random() < 0.7:
                _set_pos(mover, tuple(c + rng.uniform(-0.8e-5, 0.8e-5)
                                      for c in at))
                collisions += 1
            else:
                _set_pos(mover, tuple(rng.uniform(-5.0, 5.0)
                                      for _ in range(3)))
            mounts = _mounts(ship)
        _sub, mount = rng.choice(mounts)
        point, kind = _offset(rng, mount)
        want = _python(ship, point)
        got = _native(ship, point)
        assert got == want, (case, kind, ship.GetName(), point)
        tally[kind] = tally.get(kind, 0) + 1
        if want != NO_MOUNT:
            found += 1
            by_kind_found += kind in ("in", "edge")
            d = [abs(mount[i] - point[i]) for i in range(3)]
            edge_exact += kind == "edge" and EPS in d
            per_axis_only += math.sqrt(sum(x * x for x in d)) > EPS
            multi += sum(_within(at, point) for _s, at in mounts) > 1
    # Non-vacuous: every kind ran, matches and misses both happened, the
    # bound was hit exactly and matched, and a per-axis-only match (a
    # Euclidean test would reject it) answered.
    assert all(tally.get(k, 0) > 100 for k in (
        "exact", "in", "out", "edge", "nan", "inf", "far", "signed_zero"))
    assert found > 800 and by_kind_found > 200
    assert edge_exact > 10
    assert per_axis_only > 20
    assert collisions > 200
    assert multi > 50   # more than one mount matched: the first one won


# ── Review Focus 4: parent and child sharing a point ─────────────────────────

def _system_with_children(ship):
    for sub in ship.GetSubsystems():
        if sub is not None and sub is not ship.GetHull() \
                and getattr(sub, "_children", None):
            return sub
    raise AssertionError("no subsystem with children")


def test_parent_child_same_point_picks_parent(scene):
    bop, _galaxy = scene
    articulation.force_pose(bop, "cruise")
    assert nc._posed_flag(bop) == 1
    parent = _system_with_children(bop)
    child = parent._children[-1]
    shared = tuple(c for c in _mounts(bop)
                   if c[0] is parent)[0][1]
    _set_pos(child, shared)
    # Different physical parents: the two resolve to different parts, so
    # the wrong pick would pose the offset differently.
    parent.GetProperty().SetPhysicalParent("left wing")
    child.GetProperty().SetPhysicalParent("left wing01")
    nc.resolve_stale_part_slots([bop])
    slots = (_row(parent)["part_slot"], _row(child)["part_slot"])
    names = articulation.posed_part_names(bop)
    assert slots == (names.index("left wing"), names.index("left wing01"))

    assert part_severance.authored_mount_subsystem(bop, shared) is parent
    assert _native(bop, shared) == _slot(parent)
    # Within 1e-5 of both, still the parent.
    near = (shared[0] + 0.5e-5, shared[1], shared[2] - 0.5e-5)
    assert _python(bop, near) == _native(bop, near) == _slot(parent)

    # A child of an EARLIER system sharing a LATER top-level system's
    # point: the walk reaches the child first.
    tops = [s for s in bop.GetSubsystems()
            if s is not None and s is not bop.GetHull()]
    later = tops[tops.index(parent) + 1]
    later_at = tuple(c for c in _mounts(bop) if c[0] is later)[0][1]
    _set_pos(child, later_at)
    assert part_severance.authored_mount_subsystem(bop, later_at) is child
    assert _native(bop, later_at) == _slot(child)


# ── The mount order follows attach / _children ───────────────────────────────

def test_mount_order_change_is_pushed(scene):
    bop, galaxy = scene
    fresh = (123.25, -45.5, 6.75)
    assert _python(galaxy, fresh) == _native(galaxy, fresh) == NO_MOUNT
    extra = ss.ShipSubsystem("Extra")
    _set_pos(extra, fresh)
    galaxy.GetPhaserSystem().AddChildSubsystem(extra)
    assert _python(galaxy, fresh) == _native(galaxy, fresh) == _slot(extra)

    # The ORDER is pushed, not just membership: a child added to the first
    # system at a later subsystem's point now wins.
    first = [s for s in bop.GetSubsystems()
             if s is not None and s is not bop.GetHull()][0]
    last_sub, last_at = _mounts(bop)[-1]
    assert last_sub is not first
    assert _native(bop, last_at) == _slot(last_sub)
    early = ss.ShipSubsystem("Early")
    _set_pos(early, last_at)
    first.AddChildSubsystem(early)
    assert _python(bop, last_at) == _native(bop, last_at) == _slot(early)

    # A new top-level slot.
    cloak_at = (-77.0, 8.5, 0.125)
    cloak = ss.ShipSubsystem("Cloak")
    _set_pos(cloak, cloak_at)
    assert _native(galaxy, cloak_at) == NO_MOUNT
    galaxy.SetCloakingSubsystem(cloak)
    assert _python(galaxy, cloak_at) == _native(galaxy, cloak_at) \
        == _slot(cloak)


# ── Rulings: what the mirror cannot answer ───────────────────────────────────

class _Unnamed:
    """A mounted subsystem the mirror cannot name (no row): -2 in the
    mount order."""

    def __init__(self, p):
        self._p = p

    def GetPosition(self):
        return TGPoint3(*self._p)


def test_unnamed_subsystem_before_a_match_asks(scene):
    _bop, galaxy = scene
    tops = [s for s in galaxy.GetSubsystems()
            if s is not None and s is not galaxy.GetHull()]
    first = tops[0]
    first_at = _mounts(galaxy)[0][1]
    assert _mounts(galaxy)[0][0] is first
    ghost_at = (31.5, 32.5, 33.5)
    ghost = _Unnamed(ghost_at)
    first._children.insert(0, ghost)
    nc.push_mount_order(galaxy)
    order = _row(galaxy)["mount_order"]
    assert order[0] == _slot(first) and order[1] == ASK

    # A match before the unnamed entry: native answers.
    assert _python(galaxy, first_at) == _native(galaxy, first_at) \
        == _slot(first)
    # The unnamed entry itself, a match after it, and no match at all
    # (the unnamed one might have matched): unknown, never None.
    assert part_severance.authored_mount_subsystem(galaxy, ghost_at) \
        is ghost
    assert _native(galaxy, ghost_at) == ASK
    later_sub, later_at = _mounts(galaxy)[-1]
    assert _python(galaxy, later_at) == _slot(later_sub)
    assert _native(galaxy, later_at) == ASK
    assert _python(galaxy, (1e6, 1e6, 1e6)) == NO_MOUNT
    assert _native(galaxy, (1e6, 1e6, 1e6)) == ASK


def test_non_ship_target_asks(scene):
    _bop, galaxy = scene
    pset = galaxy.GetContainingSet()
    planet = App.Planet_Create(5.0, "")
    pset.AddObjectToSet(planet, "Planet")
    hulk = DamageableObject()
    pset.AddObjectToSet(hulk, "Hulk")
    for obj in (planet, hulk):
        assert _row(obj)["is_ship_class"] == 0
        assert _row(obj)["mount_order"] == []
        assert _native(obj, (0.0, 0.0, 0.0)) == ASK


def test_unmatched_point_is_no_mount_and_bad_handle_raises(scene):
    bop, _galaxy = scene
    assert _row(bop)["is_ship_class"] == 1
    sub = _mounts(bop)[0][0]
    with pytest.raises(ValueError):
        _h.combat_test_authored_mount(_slot(sub), (0.0, 0.0, 0.0))
    # Every mount order entry is walked: a point no mount claims is None.
    assert _python(bop, (9e9, 0.0, 0.0)) == NO_MOUNT
    assert _native(bop, (9e9, 0.0, 0.0)) == NO_MOUNT
    # The order is the iteration Python walks.
    assert _row(bop)["mount_order"] == [
        _slot(s) for s, _ in _mounts(bop)]
    assert [s for s, _ in _mounts(bop)] == [
        s for s in combat._iter_subsystems(bop)]
