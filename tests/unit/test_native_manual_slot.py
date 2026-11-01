"""Manual Aim on a posed target, natively (native-combat posed parts, Task
4b; brief .superpowers/sdd/2026-11-01-native-combat-posed-parts/
task-4b-brief.md).

A Manual Aim pick is a NON-authored point: Python attributes its part by the
box rule (`articulation._live_part(target, None, offset, authored=False)` ->
`part_severance.part_for_point`) on every call. Python resolves that ONCE per
(target, offset) and generation and pushes it as the firing ship's MANUAL
SLOT -- (target handle, offset, slot into the target's pose table, the
part-map generation) -- at the step boundaries (resolve_stale_part_slots).
Natively, an authored=False offset on a posed target is answered through the
firing ship's manual slot when its target and offset are these and its stamp
is current; otherwise it is Python's (NoMount: no slot for it; PartStale: a
slot for it, not current).
"""
import random

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_register"),
    reason="native combat bindings not built")

from engine.appc import articulation  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import subsystems as ss  # noqa: E402
from engine.appc.math import TGPoint3  # noqa: E402
from tests.unit.test_native_part_slots import (  # noqa: E402
    DT, LEAF, _Recorder, _make_scene, _ship)

SEED = 20261101


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    yield
    nc.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


@pytest.fixture
def scene():
    """A Bird of Prey (rigged) and a Galaxy aiming at it, one set."""
    bop, galaxy = _make_scene()
    galaxy.SetTarget(bop)
    try:
        yield bop, galaxy
    finally:
        App.g_kSetManager.DeleteSet("native_part_slots")


def _h_of(obj):
    return obj.__dict__["_nslot"]


def _hx(p):
    return tuple(float(c).hex() for c in (p.x, p.y, p.z)) \
        if isinstance(p, TGPoint3) else tuple(float(c).hex() for c in p)


def _picks(rng, n):
    """Points around the Bird of Prey's part boxes (inside, on the overlaps,
    just outside): the box rule's every answer."""
    boxes = list(articulation.part_boxes_for(LEAF).values())
    assert boxes, "no part boxes for the Bird of Prey headless"
    out = []
    for _ in range(n):
        lo, hi = rng.choice(boxes)
        out.append(tuple(rng.uniform(a - 0.3 * (b - a), b + 0.3 * (b - a))
                         for a, b in zip(lo, hi)))
    return out


def _python(bop, p):
    return ss.target_offset_world(bop, TGPoint3(*p), None)


def _native(bop, p, ship):
    return _h.combat_test_target_offset_world(_h_of(bop), p, None,
                                              _h_of(ship))


def _expected_slot(bop, p):
    names = articulation.posed_part_names(bop)
    found = articulation._live_part(bop, None, p, False, None)
    return names.index(found) if found is not None else -1


def _aim(galaxy, bop, p):
    """Manual Aim on `p` and a step boundary."""
    galaxy.set_manual_target_offset(TGPoint3(*p))
    nc.resolve_stale_part_slots([galaxy, bop])


def test_manual_slot_matches_box_rule(scene):
    """Seeded picks, the wings settled in cruise and mid-transition: the
    pushed slot is the box rule's part, and the native target offset equals
    Python's by .hex()."""
    bop, galaxy = scene
    rng = random.Random(SEED)
    articulation.force_pose(bop, "cruise")
    bop.SetTarget(galaxy)               # red: the wings swing home
    moved = mid = 0
    for i, p in enumerate(_picks(rng, 600)):
        if i % 5 == 0:
            articulation.tick_ship(bop, DT)
            mid += bool(bop.__dict__.get("_articulation_transitions"))
        if not nc._posed_flag(bop):
            articulation.force_pose(bop, "cruise")
        _aim(galaxy, bop, p)
        target, offset, slot, gen = _h.combat_dump(_h_of(galaxy))[
            "manual_slot"]
        assert (target, _hx(offset), gen) == (_h_of(bop), _hx(p),
                                              nc.part_gen())
        assert slot == _expected_slot(bop, p), p
        want = _python(bop, p)
        assert _native(bop, p, galaxy) == (want.x, want.y, want.z) and \
            _hx(_native(bop, p, galaxy)) == _hx(want), p
        moved += tuple(articulation.part_transform_point(
            bop, p, authored=False)) != p
    assert moved > 100, moved
    assert mid > 10, mid


def test_offset_change_reads_absent_until_the_boundary(scene):
    bop, galaxy = scene
    articulation.force_pose(bop, "cruise")
    p, q = _picks(random.Random(SEED + 1), 2)
    _aim(galaxy, bop, p)
    galaxy.set_manual_target_offset(TGPoint3(*q))
    # No slot for q yet: Python's (the box rule).
    with pytest.raises(ValueError, match="no authored mount"):
        _native(bop, q, galaxy)
    nc.resolve_stale_part_slots([galaxy, bop])
    assert _hx(_native(bop, q, galaxy)) == _hx(_python(bop, q))


def test_target_change_never_uses_the_old_slot(scene):
    bop, galaxy = scene
    other = _ship("BoP2", "birdofprey", "ships.BirdOfPrey",
                  at=(0.0, -300.0, 0.0))
    articulation.leaf_for(other)
    for b in (bop, other):
        articulation.force_pose(b, "cruise")
    p = _picks(random.Random(SEED + 2), 1)[0]
    _aim(galaxy, bop, p)
    galaxy.SetTarget(other)             # clears the pick (old frame)
    galaxy.set_manual_target_offset(TGPoint3(*p))
    # The slot still names `bop`: never read for `other`.
    with pytest.raises(ValueError, match="no authored mount"):
        _native(other, p, galaxy)
    nc.resolve_stale_part_slots([galaxy, bop, other])
    assert _h.combat_dump(_h_of(galaxy))["manual_slot"][0] == _h_of(other)
    assert _hx(_native(other, p, galaxy)) == _hx(_python(other, p))


def test_generation_bump_reads_stale_then_fresh(scene):
    bop, galaxy = scene
    articulation.force_pose(bop, "cruise")
    p = _picks(random.Random(SEED + 3), 1)[0]
    _aim(galaxy, bop, p)
    nc.bump_part_gen()                  # e.g. the leaf's boxes learned
    with pytest.raises(ValueError, match="part_stale"):
        _native(bop, p, galaxy)
    nc.resolve_stale_part_slots([galaxy, bop])
    assert _hx(_native(bop, p, galaxy)) == _hx(_python(bop, p))


def test_unposed_target_path_unchanged(scene):
    """At the NIF pose (flag 0) the offset itself, whatever the slot: a
    garbage current slot is never read."""
    bop, galaxy = scene
    articulation.force_pose(bop, None)
    assert nc._posed_flag(bop) == 0
    for p in _picks(random.Random(SEED + 4), 50):
        _h.combat_set_manual_slot(_h_of(galaxy), _h_of(bop), p, 7,
                                  nc.part_gen())
        assert _hx(_native(bop, p, galaxy)) == _hx(_python(bop, p))


def test_unknown_leaf_target_gets_no_slot(scene):
    """R5: a target whose leaf is not cached is never resolved (no
    leaf_for): no slot, so Python answers."""
    _bop, galaxy = scene
    blind = App.ShipClass_Create("Blind")
    galaxy.SetTarget(blind)
    galaxy.set_manual_target_offset(TGPoint3(0.5, 0.5, 0.0))
    nc.resolve_stale_part_slots([galaxy, blind])
    assert nc._leaf_known(blind) is None
    assert _h.combat_dump(_h_of(galaxy))["manual_slot"][0] == -1


def test_audit_compares_the_manual_slot(scene):
    bop, galaxy = scene
    articulation.force_pose(bop, "cruise")
    p = _picks(random.Random(SEED + 5), 1)[0]
    _aim(galaxy, bop, p)
    nc.audit_mirror()
    assert nc.audit_failures() == []
    target, offset, slot, gen = _h.combat_dump(_h_of(galaxy))["manual_slot"]
    _h.combat_set_manual_slot(_h_of(galaxy), target, offset,
                              (slot + 1) % 2 if slot >= 0 else 0, gen)
    nc.audit_mirror()
    assert ("ShipClass", "manual_slot") in [f[:2] for f in
                                            nc.audit_failures()]


def test_switch_off_pushes_nothing(monkeypatch):
    bop, galaxy = _make_scene(native_on=False)
    try:
        rec = _Recorder(_h)
        monkeypatch.setattr(nc, "_h", rec)
        galaxy.SetTarget(bop)
        articulation.force_pose(bop, "cruise")
        galaxy.set_manual_target_offset(TGPoint3(0.5, 0.5, 0.0))
        nc.resolve_stale_part_slots([galaxy, bop])
        galaxy.UseTargetOffsetTG(0)
        nc.resolve_stale_part_slots([galaxy, bop])
        assert rec.names == []
    finally:
        App.g_kSetManager.DeleteSet("native_part_slots")


def test_heal_never_drops_a_row(scene):
    """The mid-walk heal (run_k2, after an ASK answer moved the generation)
    re-resolves without the "unrepresentable" drop: a pose table it cannot
    encode leaves the row in place and its slots stale (the kernels'
    fallback). A step boundary still drops it."""
    bop, galaxy = scene
    articulation.force_pose(bop, "cruise")
    nc.resolve_stale_part_slots([galaxy, bop])
    h = _h_of(bop)
    name = articulation.posed_part_names(bop)[0]
    R, t = bop._articulation_poses[name]
    bop.__dict__["_articulation_poses"][name] = (R, ("x", 0.0, 0.0))
    gen = nc.part_gen()
    nc.bump_part_gen()
    nc._heal_part_slots([galaxy, bop], gen)
    assert bop.__dict__.get("_nslot") == h
    wing = next(s for s in bop.GetPulseWeaponSystem()._children)
    assert _h.combat_dump(_h_of(wing))["part_gen"] != nc.part_gen()
    nc.resolve_stale_part_slots([galaxy, bop])
    assert "_nslot" not in bop.__dict__
