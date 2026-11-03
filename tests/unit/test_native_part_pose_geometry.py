"""The native posed mount and target-offset geometry vs the Python it ports
(native-combat posed parts, Task 2; spec
docs/superpowers/specs/2026-11-01-native-combat-posed-parts-design.md §4.4,
map docs/reference/engine/native-combat/posed-parts-map.md §4 P1-P4).

Python resolves WHICH part a mount sits on and pushes the slot (Task 1);
native/src/combat/src/part_pose.cc applies the pose: before the ship
rotation for a mount, before the scale for a target offset. Compared BY
float.hex() against `subsystems._subsystem_world_position` and
`subsystems.target_offset_world`, seeded random.Random(20261101), 2,000
cases each: no tolerance anywhere.
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

from engine.appc import articulation, part_pose  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import part_severance, physical_parents  # noqa: E402
from engine.appc import subsystems as ss  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
SEED = 20261101
CASES = 2000
DT = 1.0 / 60.0
LEAF = "birdofprey"
WINGS = ("left wing", "left wing01")


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
    """A Bird of Prey (rigged: both wings) and a Galaxy (no rig), one set,
    native combat on, the BoP's leaf known."""
    nc.configure(ON)
    assert nc.enabled()
    pset = App.SetClass_Create()
    App.g_kSetManager.AddSet(pset, "native_part_pose_geometry")
    bop = _ship("BoP1", "birdofprey", "ships.BirdOfPrey")
    galaxy = _ship("Galaxy1", "galaxy", "ships.Galaxy", at=(0.0, 300.0, 0.0))
    for ship in (bop, galaxy):
        pset.AddObjectToSet(ship, ship.GetName())
    assert articulation.leaf_for(bop) == LEAF
    assert articulation.posed_part_names(bop) == WINGS
    try:
        yield bop, galaxy
    finally:
        part_severance.reset_ship(bop)
        physical_parents.clear_preview(LEAF)
        App.g_kSetManager.DeleteSet("native_part_pose_geometry")


def _slot(obj):
    return obj.__dict__["_nslot"] if obj is not None else -1


def _row(obj):
    return _h.combat_dump(_slot(obj))


def _hx(p):
    if isinstance(p, TGPoint3):
        return (p.x.hex(), p.y.hex(), p.z.hex())
    return tuple(float(c).hex() for c in p)


def _walk(ship):
    """Every subsystem of `ship`: top-level (hull included), then children."""
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


def _rand_rot(rng):
    """A rotation (half the time) or an arbitrary matrix, as row tuples."""
    if rng.random() < 0.5:
        w, x, y, z = (rng.gauss(0, 1) for _ in range(4))
        n = math.sqrt(w * w + x * x + y * y + z * z)
        w, x, y, z = w / n, x / n, y / n, z / n
        return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w),
                 2 * (x * z + y * w)),
                (2 * (x * y + z * w), 1 - 2 * (x * x + z * z),
                 2 * (y * z - x * w)),
                (2 * (x * z - y * w), 2 * (y * z + x * w),
                 1 - 2 * (x * x + y * y)))
    return tuple(tuple(rng.uniform(-2.0, 2.0) for _ in range(3))
                 for _ in range(3))


def _rand_pose(rng):
    return (_rand_rot(rng), tuple(rng.uniform(-1.0, 1.0) for _ in range(3)))


def _near_identity(rng):
    """Within is_identity's 1e-9 and not exactly identity: Python returns the
    point itself, a multiply would move it."""
    e = rng.choice((5e-10, -5e-10, 9e-10))
    return (((1.0 + e, 0.0, 0.0), (0.0, 1.0, e), (0.0, 0.0, 1.0)),
            (e, 0.0, -e))


def _place(rng, ship, spread=1500.0):
    ship.SetTranslateXYZ(*(rng.uniform(-spread, spread) for _ in range(3)))
    m = TGMatrix3()
    m.set_from_tuple(tuple(c for row in _rand_rot(rng) for c in row))
    ship.SetMatrixRotation(m)


def _pose_wings(rng, bop):
    """Pose the wings at random: both, or one with the other at (near)
    identity. Returns once the BoP reads posed."""
    mode = rng.randrange(3)
    if mode == 0:
        poses = {WINGS[0]: _rand_pose(rng), WINGS[1]: _rand_pose(rng)}
    else:
        posed, other = (WINGS if mode == 1 else WINGS[::-1])
        poses = {posed: _rand_pose(rng),
                 other: (_near_identity(rng) if rng.random() < 0.5
                         else part_pose.IDENTITY)}
    articulation.force_state_poses(bop, poses)
    assert nc._posed_flag(bop) == 1


def _python_mount(sub, ship):
    return ss._subsystem_world_position(sub, ship)


def _unposed_mount(sub, ship):
    """The mount with no part transform: what a pose must change."""
    if ship is None:
        ship = sub._climb_to_ship()
    if ship is None:
        return TGPoint3(0.0, 0.0, 0.0)
    p = sub.GetPosition()
    o = TGPoint3(p.x, p.y, p.z)
    o.MultMatrixLeft(ship.GetWorldRotation())
    pos = ship.GetWorldLocation()
    return TGPoint3(pos.x + o.x, pos.y + o.y, pos.z + o.z)


# ── P3: the mount ────────────────────────────────────────────────────────────

def _compare_mounts(bop, subs):
    """Every subsystem, read on its own ship and with the ship passed in. The
    hull climbs to its owner (SetHull attaches it), so both reads agree.
    Returns how many answers the pose moved."""
    moved = 0
    for sub in subs:
        for ship_arg in (None, bop):
            want = _python_mount(sub, ship_arg)
            got = _h.combat_test_mount_position(_slot(sub), _slot(ship_arg))
            assert _hx(got) == _hx(want), (sub.GetName(), ship_arg)
            moved += _hx(want) != _hx(_unposed_mount(sub, ship_arg))
    return moved


def test_mount_matches_subsystem_world_position(scene):
    bop, galaxy = scene
    rng = random.Random(SEED)
    subs = _walk(bop)
    moved = detached_cases = 0

    # Mid-transition, tick by tick: from cruise, an NPC with a target swings
    # its wings toward red's identity pose.
    articulation.force_pose(bop, "cruise")
    bop.SetTarget(galaxy)
    mid = 0
    for _ in range(120):
        articulation.tick_ship(bop, DT)
        nc.resolve_stale_part_slots([bop])
        if nc._posed_flag(bop):
            moved += _compare_mounts(bop, subs)
            mid += bool(bop.__dict__.get("_articulation_transitions"))
    assert mid > 0
    bop.SetTarget(None)

    for case in range(CASES):
        _place(rng, bop)
        _pose_wings(rng, bop)
        sever = rng.random() < 0.2
        if sever:
            part_severance.sever(bop, None, rng.choice(WINGS))
            assert any(e[3] for e in _row(bop)["part_poses"])
            detached_cases += 1
        nc.resolve_stale_part_slots([bop])
        # One random subsystem per case (every one on a tenth of them).
        pick = subs if case % 10 == 0 else [rng.choice(subs)]
        moved += _compare_mounts(bop, pick)
        if sever:
            part_severance.reset_ship(bop)
    assert detached_cases > 0
    assert moved > CASES // 4, moved          # the pose is not vacuous


def test_identity_mount_keeps_negative_zero(scene):
    """Review Focus 3: a mount on a part at identity is the point ITSELF
    (a branch, never a multiply): -0.0 stays -0.0 through to the world
    point."""
    bop, _galaxy = scene
    sub = next(s for s in _walk(bop) if physical_parents.property_of(s)
               is not None and s is not bop.GetHull())
    physical_parents.set_preview(
        LEAF, {physical_parents.property_of(sub).GetName(): WINGS[0]})
    sub._position = TGPoint3(-0.0, -0.0, -0.0)
    bop.SetTranslateXYZ(-0.0, -0.0, -0.0)
    bop.SetMatrixRotation(TGMatrix3())
    for ident in (part_pose.IDENTITY,
                  (part_pose.IDENTITY[0], (5e-10, 0.0, 0.0))):
        articulation.force_state_poses(
            bop, {WINGS[0]: ident,
                  WINGS[1]: part_pose.hinge_pose((0.0, 0.0, 0.0),
                                                 (1.0, 0.0, 0.0), 15.0)})
        nc.resolve_stale_part_slots([bop])
        assert _row(sub)["part_slot"] == 0          # on the identity wing
        want = _python_mount(sub, None)
        assert all(math.copysign(1.0, c) == -1.0
                   for c in (want.x, want.y, want.z))
        got = _h.combat_test_mount_position(_slot(sub), -1)
        assert _hx(got) == _hx(want)


# ── P4: the target offset ────────────────────────────────────────────────────

def _mounted(ship):
    return [(s, p) for s, p in part_severance._mounted_subsystems(ship)
            if s.__dict__.get("_nslot") is not None]


def test_target_offset_matches_python(scene):
    bop, galaxy = scene
    rng = random.Random(SEED + 1)
    mounts = _mounted(bop)
    articulation.force_pose(bop, "cruise")
    nc.resolve_stale_part_slots([bop])
    on_wing = [(s, p) for s, p in mounts if _row(s)["part_slot"] >= 0]
    assert mounts and on_wing
    moved = scaled = unposed = 0
    for case in range(CASES):
        mode = rng.randrange(4)
        scale = 1.0 if rng.random() < 0.3 else rng.uniform(0.1, 4.0)
        if mode < 3:
            # A posed (often scaled) target, the offset an authored mount
            # given as the mount: Python's subsystem-lock path.
            target = bop
            _place(rng, bop)
            _pose_wings(rng, bop)
            sever = rng.random() < 0.15
            if sever:
                part_severance.sever(bop, None, rng.choice(WINGS))
            bop.SetScale(scale)
            nc.resolve_stale_part_slots([bop])
            sub, point = rng.choice(on_wing if rng.random() < 0.7
                                    else mounts)
            off = TGPoint3(*point)
            want = ss.target_offset_world(bop, off, sub)
            got = _h.combat_test_target_offset_world(
                _slot(bop), point, _slot(sub))
            unmoved = _unposed_offset(bop, point)
            moved += _hx(want) != _hx(unmoved)
            scaled += scale != 1.0
            if sever:
                part_severance.reset_ship(bop)
        else:
            # An unposed target, the mount given or not: the offset as is.
            target = rng.choice((galaxy, bop))
            if target is bop:
                articulation.force_pose(bop, None)
                assert nc._posed_flag(bop) == 0
            _place(rng, target)
            target.SetScale(scale)
            if rng.random() < 0.5:
                sub, point = rng.choice(_mounted(target))
            else:
                sub, point = None, tuple(rng.uniform(-3.0, 3.0)
                                         for _ in range(3))
            want = ss.target_offset_world(target, TGPoint3(*point), sub)
            got = _h.combat_test_target_offset_world(
                _slot(target), point, _slot(sub) if sub else None)
            unposed += 1
        assert _hx(got) == _hx(want), (case, mode)
    bop.SetScale(1.0)
    galaxy.SetScale(1.0)
    assert moved > CASES // 4, moved
    assert scaled > CASES // 4 and unposed > CASES // 8


def _unposed_offset(target, point):
    s = float(target.GetScale())
    o = TGPoint3(point[0] * s, point[1] * s, point[2] * s)
    o.MultMatrixLeft(target.GetWorldRotation())
    pos = target.GetWorldLocation()
    return TGPoint3(pos.x + o.x, pos.y + o.y, pos.z + o.z)


def test_scaled_posed_target_poses_before_scale(scene):
    """Review Focus 5: SetScale on a posed target scales the POSED point."""
    bop, _galaxy = scene
    articulation.force_pose(bop, "cruise")
    bop.SetScale(3.0)
    nc.resolve_stale_part_slots([bop])
    sub, point = next((s, p) for s, p in _mounted(bop)
                      if _row(s)["part_slot"] >= 0)
    want = ss.target_offset_world(bop, TGPoint3(*point), sub)
    # Pose after the scale would differ: the pose's t is unscaled.
    R, t = articulation.pose_for_part(bop, WINGS[_row(sub)["part_slot"]])
    wrong = part_pose.apply((R, t), tuple(c * 3.0 for c in point))
    pos = bop.GetWorldLocation()
    assert _hx(want) != _hx(TGPoint3(pos.x + wrong[0], pos.y + wrong[1],
                                     pos.z + wrong[2]))
    got = _h.combat_test_target_offset_world(_slot(bop), point, _slot(sub))
    assert _hx(got) == _hx(want)
    bop.SetScale(1.0)


def _wing_pick(bop, part=WINGS[0], frac=(0.5, 0.5, 0.5)):
    """A point inside `part`'s box that the box rule gives to that part and
    that is no subsystem's mount: a Manual Aim pick on the wing."""
    lo, hi = articulation.part_boxes_for(LEAF)[part]
    p = tuple(a + f * (b - a) for a, b, f in zip(lo, hi, frac))
    assert part_severance.part_for_point(LEAF, p) == part, p
    assert part_severance.authored_mount_subsystem(bop, p) is None, p
    return p


def test_non_mount_offset_on_posed_target_is_body_point(scene):
    """D5 (fire control native only, M5): an offset no mount claims is a
    plain body-frame xyz on a posed target, in both copies -- the box rule
    no longer carries it with the wing it falls in."""
    bop, _galaxy = scene
    articulation.force_pose(bop, "cruise")
    _place(random.Random(SEED + 3), bop)
    bop.SetScale(1.5)
    nc.resolve_stale_part_slots([bop])
    picks = [_wing_pick(bop, w, f) for w in WINGS
             for f in ((0.5, 0.5, 0.5), (0.25, 0.75, 0.5))]
    for p in picks:
        # The box rule would have moved it: the test is not vacuous.
        assert tuple(articulation.part_transform_point(
            bop, p, authored=False)) != p
        want = ss.body_point_world(bop, p)
        for mount in (ss._RESOLVE, None):
            assert _hx(ss.target_offset_world(bop, TGPoint3(*p), mount)) \
                == _hx(want), (p, mount)
        got = _h.combat_test_target_offset_world(_slot(bop), p, None)
        assert _hx(got) == _hx(want), p
    # An authored mount handed in as no mount is a plain point too.
    for _sub, point in _mounted(bop):
        want = ss.body_point_world(bop, point)
        assert _hx(ss.target_offset_world(bop, TGPoint3(*point), None)) \
            == _hx(want)
        got = _h.combat_test_target_offset_world(_slot(bop), point, None)
        assert _hx(got) == _hx(want)
    bop.SetScale(1.0)


def test_mount_on_posed_part_still_follows_pose(scene):
    """A subsystem mount on a posed wing is still aimed at its posed
    position, in both copies (M5)."""
    bop, _galaxy = scene
    articulation.force_pose(bop, "cruise")
    _place(random.Random(SEED + 4), bop)
    nc.resolve_stale_part_slots([bop])
    on_wing = [(s, p) for s, p in _mounted(bop) if _row(s)["part_slot"] >= 0]
    assert on_wing
    moved = 0
    for sub, point in on_wing:
        posed = articulation.part_transform_point(
            bop, point, prop=physical_parents.property_of(sub))
        want = ss.body_point_world(bop, tuple(posed))
        moved += tuple(posed) != tuple(point)
        for mount in (ss._RESOLVE, sub):
            assert _hx(ss.target_offset_world(bop, TGPoint3(*point), mount)) \
                == _hx(want), (sub.GetName(), mount)
        got = _h.combat_test_target_offset_world(_slot(bop), point,
                                                 _slot(sub))
        assert _hx(got) == _hx(want), sub.GetName()
    assert moved > 0


def test_near_mount_offset_is_plain_point(scene):
    """M8.5: an offset within 1e-5 of a mount but not bit-equal to it is a
    plain point in both copies (native no longer hands it back)."""
    bop, _galaxy = scene
    articulation.force_pose(bop, "cruise")
    nc.resolve_stale_part_slots([bop])
    sub, point = next((s, p) for s, p in _mounted(bop)
                      if _row(s)["part_slot"] >= 0)
    near = (point[0] + 1e-6, point[1], point[2])
    assert part_severance.authored_mount_subsystem(bop, near) is sub
    want = ss.body_point_world(bop, near)
    # The mount's own point is posed, so a plain point is a real change.
    assert _hx(ss.target_offset_world(bop, TGPoint3(*point), sub)) \
        != _hx(ss.body_point_world(bop, point))
    for mount in (ss._RESOLVE, sub):
        assert _hx(ss.target_offset_world(bop, TGPoint3(*near), mount)) \
            == _hx(want), mount
    got = _h.combat_test_target_offset_world(_slot(bop), near, _slot(sub))
    assert _hx(got) == _hx(want)
    # A NaN never matches a mount: a plain point (NaN through) too.
    nan = (math.nan, point[1], point[2])
    got = _h.combat_test_target_offset_world(_slot(bop), nan, _slot(sub))
    assert _hx(got) == _hx(ss.body_point_world(bop, nan))


# ── Stale slots ──────────────────────────────────────────────────────────────

def test_stale_slot_raises_part_stale(scene):
    bop, _galaxy = scene
    articulation.force_pose(bop, "cruise")
    sub, point = next((s, p) for s, p in _mounted(bop))
    # Never resolved: every slot is stamped 0.
    with pytest.raises(ValueError, match="part_stale"):
        _h.combat_test_mount_position(_slot(sub), -1)
    nc.resolve_stale_part_slots([bop])
    _h.combat_test_mount_position(_slot(sub), -1)
    _h.combat_test_target_offset_world(_slot(bop), point, _slot(sub))
    # A trigger bumps the generation: stale until re-resolved.
    nc.bump_part_gen()
    with pytest.raises(ValueError, match="part_stale"):
        _h.combat_test_mount_position(_slot(sub), -1)
    with pytest.raises(ValueError, match="part_stale"):
        _h.combat_test_target_offset_world(_slot(bop), point, _slot(sub))
    # The mount memo keeps nothing from a throw.
    assert _h.combat_test_mount_memo_size() == 0
    nc.resolve_stale_part_slots([bop])
    want = _python_mount(sub, None)
    assert _hx(_h.combat_test_mount_position(_slot(sub), -1)) == _hx(want)


def test_slot_past_the_table_raises_part_stale(scene):
    """The table can be empty (flag 0) while slots keep their old indices;
    once posed again, an index past the table never reads blindly."""
    bop, _galaxy = scene
    articulation.force_pose(bop, "cruise")
    nc.resolve_stale_part_slots([bop])
    sub, _point = next((s, p) for s, p in _mounted(bop)
                       if _row(s)["part_slot"] >= 0)
    _h.combat_set_part_slot(_slot(sub), 7, _h.combat_part_gen())
    with pytest.raises(ValueError, match="part_stale"):
        _h.combat_test_mount_position(_slot(sub), -1)


# ── has_posed_parts 0: no slot is read ───────────────────────────────────────

def test_unposed_path_unchanged(scene):
    bop, galaxy = scene
    rng = random.Random(SEED + 2)
    articulation.force_pose(bop, None)
    assert nc._posed_flag(bop) == 0 and nc._posed_flag(galaxy) == 0
    assert _row(bop)["part_poses"] == []
    gen = _h.combat_part_gen()
    # Garbage, CURRENT slots everywhere: read, they would be stale (past the
    # empty table) and raise.
    subs = _walk(bop) + _walk(galaxy)
    for sub in subs:
        _h.combat_set_part_slot(_slot(sub), 5, gen)
    mounts = _mounted(bop) + _mounted(galaxy)
    for case in range(CASES):
        ship = rng.choice((bop, galaxy))
        _place(rng, ship)
        ship.SetScale(1.0 if rng.random() < 0.5 else rng.uniform(0.1, 4.0))
        sub = rng.choice(subs)
        ship_arg = rng.choice((None, ship))
        if sub._climb_to_ship() not in (None, ship):
            ship_arg = None
        want = _python_mount(sub, ship_arg)
        got = _h.combat_test_mount_position(_slot(sub), _slot(ship_arg))
        assert _hx(got) == _hx(want), case
        msub, point = rng.choice(mounts)
        target = msub._climb_to_ship() or ship
        given = msub if rng.random() < 0.5 else None
        want = ss.target_offset_world(target, TGPoint3(*point), given)
        got = _h.combat_test_target_offset_world(
            _slot(target), point, _slot(given) if given else None)
        assert _hx(got) == _hx(want), case
    bop.SetScale(1.0)
    galaxy.SetScale(1.0)
