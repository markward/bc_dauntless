"""Native beam geometry vs the Python it ports (native combat phase 2 / K2,
Task 2; native/src/combat/src/beam_geometry.cc).

Each test builds real ships with native combat on, randomises poses, mounts,
arcs, scales and boxes (seeded random.Random(20261031), 2,000 cases each) and
compares the `combat_test_*` binding with the Python function of the same name
BY float.hex(): no tolerance anywhere. docs/reference/engine/native-combat/
k2-beams-map.md sections 1.2-1.5 and F3-F18 are the specification.
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
    _h is None or not hasattr(_h, "combat_test_strip_emit_position"),
    reason="native beam geometry bindings not built")

from engine import host_loop as hl  # noqa: E402
from engine.appc import collisions  # noqa: E402
from engine.appc import combat  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.core import step_memo  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
SEED = 20261031
CASES = 2000
NAN = float("nan")
INF = float("inf")


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


class World:
    pass


@pytest.fixture
def world():
    nc.configure(ON)
    assert nc.enabled()
    w = World()
    w.set = App.SetClass_Create()
    App.g_kSetManager.AddSet(w.set, "native_beam_geometry")
    w.galaxy = _ship("Galaxy1", "galaxy")
    w.vorcha = _ship("Vorcha1", "vorcha", at=(0.0, 400.0, 0.0))
    w.warbird = _ship("Warbird1", "warbird", at=(0.0, 600.0, 0.0))
    for ship in (w.galaxy, w.vorcha, w.warbird):
        w.set.AddObjectToSet(ship, ship.GetName())
    w.phasers = list(w.galaxy._phaser_system._children)
    w.vorcha_banks = list(w.vorcha._phaser_system._children)
    w.warbird_banks = list(w.warbird._phaser_system._children)
    assert w.phasers and w.vorcha_banks and w.warbird_banks
    try:
        yield w
    finally:
        App.g_kSetManager.DeleteSet("native_beam_geometry")


def _slot(obj):
    return obj.__dict__["_nslot"] if obj is not None else -1


def _hx(p):
    if p is None:
        return None
    if isinstance(p, TGPoint3):
        return (p.x.hex(), p.y.hex(), p.z.hex())
    return tuple(float(c).hex() for c in p)


def _rand_rot(rng):
    m = TGMatrix3()
    if rng.random() < 0.5:
        w, x, y, z = (rng.gauss(0, 1) for _ in range(4))
        n = math.sqrt(w * w + x * x + y * y + z * z)
        w, x, y, z = w / n, x / n, y / n, z / n
        m.set_from_tuple((
            1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
            2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
            2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))
    else:
        m.set_from_tuple([rng.uniform(-2.0, 2.0) for _ in range(9)])
    return m


def _place(rng, ship, spread=1500.0):
    ship.SetTranslateXYZ(*(rng.uniform(-spread, spread) for _ in range(3)))
    ship.SetMatrixRotation(_rand_rot(rng))


def _rand_vec(rng, scale=1.0):
    return TGPoint3(*(rng.uniform(-scale, scale) for _ in range(3)))


def _mount_random(rng, sub):
    sub._position = _rand_vec(rng, 3.0)
    sub._direction = _rand_vec(rng, 1.0)
    sub._up = _rand_vec(rng, 1.0)


def _xyz(p):
    return (p.x, p.y, p.z)


# ── Strip emit position (F5-F10) ─────────────────────────────────────────────

def test_strip_emit_matches(world):
    w, rng = world, random.Random(SEED)
    banks = w.phasers + w.vorcha_banks + w.warbird_banks
    for i in range(CASES):
        _place(rng, w.galaxy)
        _place(rng, w.vorcha)
        bank = rng.choice(banks)
        _mount_random(rng, bank)
        mode = i % 12
        bank._length = {
            1: 0.0, 2: -1.5, 3: NAN, 4: -0.0,
        }.get(mode, rng.uniform(0.0, 6.0))
        lo, hi = sorted((rng.uniform(-3.5, 3.5), rng.uniform(-3.5, 3.5)))
        if mode == 5:                    # reversed authored width: always lo
            lo, hi = hi, lo
        if mode == 6:
            lo, hi = -math.pi, math.pi
        bank._arc_width_lo, bank._arc_width_hi = lo, hi
        centre = bank._emitter_world_position()
        tw = TGPoint3(*(rng.uniform(-2000.0, 2000.0) for _ in range(3)))
        if mode == 7:                    # exactly the centre: zero projections
            tw = TGPoint3(centre.x, centre.y, centre.z)
        elif mode == 8:                  # NaN target: atan2 of NaN, then clamp
            tw = TGPoint3(NAN, 1.0, 2.0)
        elif mode == 9:                  # no ship: the centre comes back
            bank._parent_ship = None
            bank._parent_subsystem = None
            tw = TGPoint3(*(rng.uniform(-9.0, 9.0) for _ in range(3)))
        want = bank._strip_emit_position(tw)
        try:
            got = _h.combat_test_strip_emit_position(
                _slot(bank), _xyz(tw), False)
        finally:
            if mode == 9:
                bank._parent_ship = w.galaxy if bank in w.phasers else (
                    w.vorcha if bank in w.vorcha_banks else w.warbird)
        assert _hx(got) == _hx(want), mode


def test_strip_zero_projection_is_positive_zero_yaw(world):
    """F7: with both projections 0.0 (signed zeros included) the yaw is +0.0,
    never atan2(+-0, +-0) = pi or -0.0."""
    w = world
    bank = w.phasers[0]
    bank._length = 2.0
    bank._arc_width_lo, bank._arc_width_hi = -math.pi, math.pi
    # Every forward component negative: fwd_proj is -0.0 and right_proj +0.0,
    # so an un-guarded atan2(+0.0, -0.0) would give pi.
    w.galaxy.SetMatrixRotation(TGMatrix3())
    bank._direction = TGPoint3(-1.0, -1.0, -1.0)
    bank._up = TGPoint3(1.0, 2.0, 4.0)
    centre = bank._emitter_world_position()
    for tw in (TGPoint3(centre.x, centre.y, centre.z),
               TGPoint3(centre.x, centre.y, centre.z + 1.0)):
        want = bank._strip_emit_position(tw)
        got = _h.combat_test_strip_emit_position(_slot(bank), _xyz(tw), False)
        assert _hx(got) == _hx(want)


def test_strip_reversed_width_clamps_to_lo(world):
    w, rng = world, random.Random(SEED + 1)
    bank = w.phasers[0]
    bank._length = 3.0
    bank._arc_width_lo, bank._arc_width_hi = 1.0, -1.0
    for _ in range(300):
        tw = TGPoint3(*(rng.uniform(-500.0, 500.0) for _ in range(3)))
        want = bank._strip_emit_position(tw)
        got = _h.combat_test_strip_emit_position(_slot(bank), _xyz(tw), False)
        assert _hx(got) == _hx(want)


# ── Dwell (F13) ──────────────────────────────────────────────────────────────

def test_dwell_matches(world):
    w, rng = world, random.Random(SEED + 2)
    banks = w.phasers + w.vorcha_banks
    flush = nc._h.combat_dump_globals()["BEAM_DWELL_FLUSH_S"]
    assert flush == 0.5
    for i in range(CASES):
        bank = rng.choice(banks)
        mode = i % 10
        bank._firing = rng.random() < 0.8
        bank._beam_on_countdown = {
            1: 0.0, 2: NAN, 3: -0.0, 4: 1e-300,
        }.get(mode, rng.choice((0.0, -0.1, 0.3, 0.66)))
        bank._dwell = {
            5: 0.5, 6: NAN, 7: math.nextafter(0.5, 1.0),
            8: math.nextafter(0.5, 0.0),
        }.get(mode, rng.uniform(0.0, 1.0))
        dt = rng.choice((1.0 / 60.0, 0.1, 0.0, 0.5, rng.uniform(0.0, 0.3)))
        got = _h.combat_test_accumulate_dwell(_slot(bank), dt)
        want = bank.accumulate_dwell(dt)
        assert (got[0].hex(), got[1].hex()) == (
            float(want).hex(), float(bank._dwell).hex()), mode
        # The binding reports and writes nothing: the row still holds the
        # value the Python wrote LAST iteration's pushes, so re-prime it.
        bank._dwell = rng.choice((0.0, 0.25, 0.5, 0.75, NAN, -0.0))
        got = _h.combat_test_take_dwell(_slot(bank))
        before = bank._dwell
        want = bank.take_dwell()
        assert (got[0].hex(), got[1].hex()) == (
            float(want).hex(), float(bank._dwell).hex())
        assert float(got[0]).hex() == float(before).hex()
        assert got[1].hex() == (0.0).hex()


def test_dwell_exact_boundary(world):
    w = world
    bank = w.phasers[0]
    bank._firing = True
    bank._beam_on_countdown = 0.0
    for dwell in (0.5, math.nextafter(0.5, 1.0), math.nextafter(0.5, 0.0)):
        bank._dwell = dwell
        got = _h.combat_test_accumulate_dwell(_slot(bank), 0.0166)
        want = bank.accumulate_dwell(0.0166)
        assert got[0].hex() == float(want).hex()
        assert got[1].hex() == float(bank._dwell).hex()


def test_dwell_does_not_write(world):
    w = world
    bank = w.phasers[0]
    bank._firing = True
    bank._beam_on_countdown = 0.0
    bank._dwell = 0.7
    _h.combat_test_accumulate_dwell(_slot(bank), 0.1)
    _h.combat_test_take_dwell(_slot(bank))
    assert _h.combat_dump(_slot(bank))["_dwell"] == 0.7


# ── Aim point (map 1.2) ──────────────────────────────────────────────────────

def _aim_case(rng, w, ship, target, sub_pool):
    _place(rng, ship)
    _place(rng, target)
    mode = rng.randrange(6)
    ship.SetTarget(target)                   # also clears the manual offset
    if mode == 0:
        ship.SetTargetSubsystem(None)
    elif mode in (1, 2, 3):
        ship.SetTargetSubsystem(rng.choice(sub_pool))
    elif mode == 4:
        ship.set_manual_target_offset(_rand_vec(rng, 8.0))
        ship.SetTargetSubsystem(rng.choice(sub_pool + [None]))
        if rng.random() < 0.3:
            ship.UseTargetOffsetTG(0)
    else:
        ship.SetTargetSubsystem(rng.choice(sub_pool))
        ship.set_manual_target_offset(_rand_vec(rng, 8.0))
        ship._use_target_offset = False      # stored but not in use
    target.SetScale(rng.choice((1.0, 3.0, rng.uniform(0.0, 6.0))))
    return mode


def test_aim_point_matches(world):
    """The lock is on the target's own ship, or none, or Manual Aim."""
    w, rng = world, random.Random(SEED + 3)
    for _ in range(CASES):
        target = rng.choice((w.vorcha, w.warbird))
        pool = list(target._phaser_system._children)
        _aim_case(rng, w, w.galaxy, target, pool)
        want_p, want_sub = hl._phaser_aim_point(w.galaxy, target)
        got_p, got_sub = _h.combat_test_phaser_aim_point(
            _slot(w.galaxy), _slot(target), False)
        assert _hx(got_p) == _hx(want_p)
        assert got_sub == _slot(want_sub)


def test_lock_on_other_ship_aim_matches(world):
    """Map 1.2: the lock is ship-wide and never checked against the bank's
    target -- the aim point is the lock's OWN ship's mount."""
    w, rng = world, random.Random(SEED + 4)
    for _ in range(CASES):
        target = rng.choice((w.vorcha, w.warbird))
        other = w.warbird if target is w.vorcha else w.vorcha
        pool = list(other._phaser_system._children) + list(
            w.galaxy._phaser_system._children)
        _place(rng, w.galaxy)
        _place(rng, target)
        _place(rng, other)
        w.galaxy.SetTarget(target)
        sub = rng.choice(pool)
        if rng.random() < 0.15:              # a lock with no ship at all
            saved = (sub._parent_ship, sub._parent_subsystem)
            sub._parent_ship = None
            sub._parent_subsystem = None
        else:
            saved = None
        w.galaxy.SetTargetSubsystem(sub)
        try:
            want_p, want_sub = hl._phaser_aim_point(w.galaxy, target)
            got_p, got_sub = _h.combat_test_phaser_aim_point(
                _slot(w.galaxy), _slot(target), False)
            assert want_sub is sub
            assert _hx(got_p) == _hx(want_p)
            assert got_sub == _slot(sub)
        finally:
            if saved is not None:
                sub._parent_ship, sub._parent_subsystem = saved


def test_manual_aim_point_matches(world):
    w, rng = world, random.Random(SEED + 5)
    for i in range(CASES):
        target = rng.choice((w.vorcha, w.warbird))
        _place(rng, w.galaxy)
        _place(rng, target)
        target.SetScale(rng.choice((1.0, 3.0, 0.0, -2.0, rng.uniform(0.0, 6.0))))
        w.galaxy.set_manual_target_offset(_rand_vec(rng, 12.0))
        w.galaxy.SetTargetSubsystem(rng.choice(
            [None] + list(target._phaser_system._children)))
        want_p, want_sub = hl._phaser_aim_point(w.galaxy, target)
        got_p, got_sub = _h.combat_test_phaser_aim_point(
            _slot(w.galaxy), _slot(target), False)
        assert want_sub is None and got_sub == -1
        assert _hx(got_p) == _hx(want_p)


def test_aim_point_memo_matches_python_staleness(world):
    w, rng = world, random.Random(SEED + 6)
    sub = w.vorcha_banks[0]
    w.galaxy.SetTarget(w.vorcha)
    w.galaxy.SetTargetSubsystem(sub)
    _h.combat_memo_clear()
    with step_memo.combat_step():
        first, _ = _h.combat_test_phaser_aim_point(
            _slot(w.galaxy), _slot(w.vorcha), True)
        _place(rng, w.vorcha)
        stale, _ = _h.combat_test_phaser_aim_point(
            _slot(w.galaxy), _slot(w.vorcha), True)
        fresh, _ = _h.combat_test_phaser_aim_point(
            _slot(w.galaxy), _slot(w.vorcha), False)
    assert _hx(stale) == _hx(first) and _hx(fresh) != _hx(first)


class _At:
    """A target that is only a world point (the lock's mount)."""

    def __init__(self, p):
        self._p = p

    def GetWorldLocation(self):
        return TGPoint3(*self._p)


def test_resolve_bank_aim_world_at_matches(world):
    """The arc gate's aim with a world POINT target (the lock's mount)."""
    from engine.appc import weapon_subsystems as ws
    w, rng = world, random.Random(SEED + 7)
    for i in range(CASES):
        _place(rng, w.galaxy)
        _place(rng, w.vorcha)
        bank = rng.choice(w.phasers)
        _mount_random(rng, bank)
        mode = i % 6
        o = bank._emitter_world_position()
        if mode == 1:                        # coincident: ship-forward fallback
            point = (o.x, o.y, o.z)
        elif mode == 2:                      # a hair away, under 1e-6
            point = (o.x + 5e-7, o.y, o.z)
        elif mode == 3:
            point = (NAN, 1.0, 2.0)
        else:
            point = _xyz(rng.choice(w.vorcha_banks).GetWorldLocation())
        want = ws._resolve_bank_aim_world(bank, _At(point))
        got = _h.combat_test_resolve_bank_aim_world_at(
            _slot(bank), point, False)
        assert _hx(got) == _hx(want), mode


def test_posed_lock_ship_throws(world):
    """The pose flag that matters is the LOCK's own ship, not the target's."""
    w = world
    from engine.appc import articulation, part_pose
    hinge = part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0)
    w.galaxy.SetTarget(w.vorcha)
    # A lock on the WARBIRD's mount, target the Vorcha; pose the warbird.
    w.galaxy.SetTargetSubsystem(w.warbird_banks[0])
    articulation.force_part_pose(w.warbird, "TestPart", hinge)
    try:
        with pytest.raises(ValueError):
            _h.combat_test_phaser_aim_point(
                _slot(w.galaxy), _slot(w.vorcha), False)
    finally:
        articulation.force_pose(w.warbird, None)
    _h.combat_test_phaser_aim_point(_slot(w.galaxy), _slot(w.vorcha), False)

    # Posing the TARGET (not the lock's ship) does not matter for a lock on
    # another ship, or for the hull-centre aim.
    w.galaxy.SetTargetSubsystem(w.vorcha_banks[0])
    articulation.force_part_pose(w.warbird, "TestPart", hinge)
    try:
        want_p, _ = hl._phaser_aim_point(w.galaxy, w.warbird)
        got_p, got_sub = _h.combat_test_phaser_aim_point(
            _slot(w.galaxy), _slot(w.warbird), False)
        assert _hx(got_p) == _hx(want_p)
        w.galaxy.SetTargetSubsystem(None)
        want_p, _ = hl._phaser_aim_point(w.galaxy, w.warbird)
        got_p, got_sub = _h.combat_test_phaser_aim_point(
            _slot(w.galaxy), _slot(w.warbird), False)
        assert _hx(got_p) == _hx(want_p) and got_sub == -1
        # Manual Aim on a posed target: a pick no mount claims is a plain
        # body point, answered natively (fire control native only, M5).
        w.galaxy.set_manual_target_offset(TGPoint3(1.0, 2.0, 3.0))
        want_p, _ = hl._phaser_aim_point(w.galaxy, w.warbird)
        got_p, got_sub = _h.combat_test_phaser_aim_point(
            _slot(w.galaxy), _slot(w.warbird), False)
        assert _hx(got_p) == _hx(want_p) and got_sub == -1
    finally:
        articulation.force_pose(w.warbird, None)


def test_aim_point_falls_back_for_a_non_ship_firer(world):
    w = world
    obj = App.ObjectClass_Create("plain") if hasattr(App, "ObjectClass_Create") \
        else None
    if obj is None:
        pytest.skip("no ObjectClass_Create")
    nc.register(obj, "Object")
    with pytest.raises(ValueError):
        _h.combat_test_phaser_aim_point(_slot(obj), _slot(w.vorcha), False)


# ── Sphere tier (F18) and world_radius ───────────────────────────────────────

def test_sphere_entry_matches(world):
    rng = random.Random(SEED + 8)
    for i in range(CASES):
        centre = TGPoint3(*(rng.uniform(-50.0, 50.0) for _ in range(3)))
        radius = rng.choice((rng.uniform(0.1, 30.0), 0.0, -1.0, NAN, 5.0))
        d = _rand_vec(rng, 1.0)
        n = math.sqrt(d.x * d.x + d.y * d.y + d.z * d.z) or 1.0
        d = TGPoint3(d.x / n, d.y / n, d.z / n)
        mode = i % 8
        if mode == 1:        # inside the sphere: Python returns the origin
            origin = TGPoint3(centre.x + 0.1, centre.y, centre.z)
            radius = 5.0
        elif mode == 2:      # on the surface: c == 0 exactly
            origin = TGPoint3(centre.x + 5.0, centre.y, centre.z)
            radius = 5.0
        elif mode == 3:      # tangent: disc == 0
            origin = TGPoint3(centre.x - 20.0, centre.y + 5.0, centre.z)
            d = TGPoint3(1.0, 0.0, 0.0)
            radius = 5.0
        elif mode == 4:      # behind: pointing away
            origin = TGPoint3(centre.x + 20.0, centre.y, centre.z)
            d = TGPoint3(1.0, 0.0, 0.0)
            radius = 5.0
        elif mode == 5:      # NaN origin
            origin = TGPoint3(NAN, 1.0, 2.0)
        else:
            origin = TGPoint3(*(rng.uniform(-100.0, 100.0) for _ in range(3)))
        max_dist = rng.choice((rng.uniform(0.0, 200.0), 0.0, 1e9, NAN, 15.0))
        want = combat.ray_sphere_entry(origin, d, max_dist, centre, radius)
        got = _h.combat_test_ray_sphere_entry(
            _xyz(origin), _xyz(d), max_dist, _xyz(centre), radius)
        if want is None:
            assert got is None, mode
        elif want is origin:
            assert got == "origin", mode
        else:
            assert got != "origin" and _hx(got) == _hx(want), mode


def test_sphere_entry_origin_marker_is_distinct(world):
    c = TGPoint3(0.0, 0.0, 0.0)
    o = TGPoint3(1.0, 0.0, 0.0)
    d = TGPoint3(1.0, 0.0, 0.0)
    assert combat.ray_sphere_entry(o, d, 10.0, c, 5.0) is o
    assert _h.combat_test_ray_sphere_entry(
        _xyz(o), _xyz(d), 10.0, _xyz(c), 5.0) == "origin"
    # The point (1, 0, 0) as a real entry is NOT the marker.
    o2 = TGPoint3(-10.0, 0.0, 0.0)
    got = _h.combat_test_ray_sphere_entry(
        _xyz(o2), _xyz(d), 100.0, _xyz(c), 5.0)
    assert got != "origin" and _hx(got) == _hx(
        combat.ray_sphere_entry(o2, d, 100.0, c, 5.0))


def test_world_radius_matches(world):
    w, rng = world, random.Random(SEED + 9)
    for i in range(CASES):
        ship = rng.choice((w.galaxy, w.vorcha, w.warbird))
        ship._radius = rng.choice((rng.uniform(0.0, 40.0), 0.0, -3.0, NAN))
        ship._scale = rng.choice((1.0, 0.0, -2.0, NAN, INF, -INF,
                                  rng.uniform(0.0, 9.0)))
        want = collisions.world_radius(ship)
        got = _h.combat_test_world_radius(_slot(ship))
        assert got.hex() == float(want).hex()


# ── shields_block (map 1.5) ──────────────────────────────────────────────────

class _FakeGame:
    def __init__(self, player):
        self._p = player

    def GetPlayer(self):
        return self._p


def test_shields_block_matches(world, monkeypatch):
    import engine.dev_combat_cheats as cheats
    w, rng = world, random.Random(SEED + 10)
    cloak = w.warbird.GetCloakingSubsystem()
    assert cloak is not None
    for i in range(CASES):
        target = rng.choice((w.galaxy, w.vorcha, w.warbird))
        shields = target.GetShields()
        for f in range(6):
            shields.SetMaxShields(f, 0.0 if rng.random() < 0.1 else 1000.0)
        if rng.random() < 0.1:
            for f in range(6):
                shields.SetMaxShields(f, 0.0)
        if rng.random() < 0.8:
            shields.TurnOn()
        else:
            shields.TurnOff()
        shields._condition = rng.choice((shields._max_condition, 0.0,
                                         shields._max_condition * 0.1))
        shields._destroyed = rng.random() < 0.1
        if target is w.warbird:
            cloak._cloak_state = rng.choice((0, 1, 2, 3))
        npc_off = rng.random() < 0.5
        player = rng.choice((None, w.galaxy, target, w.warbird))
        monkeypatch.setattr(cheats, "disable_npc_shields_active",
                            lambda: npc_off)
        monkeypatch.setattr(App, "Game_GetCurrentGame",
                            lambda: _FakeGame(player))
        want = combat.shields_block(target)
        got = _h.combat_test_shields_block(
            _slot(target), npc_off, _slot(player))
        assert got is want, (i, npc_off)


def test_shields_block_no_shield_subsystem(world):
    w = world
    w.galaxy._shield_subsystem = None
    assert combat.shields_block(w.galaxy) is False
    assert _h.combat_test_shields_block(_slot(w.galaxy), False, -1) is False


def test_shields_block_dev_cheat_player_exemption(world, monkeypatch):
    import engine.dev_combat_cheats as cheats
    w = world
    monkeypatch.setattr(cheats, "disable_npc_shields_active", lambda: True)
    monkeypatch.setattr(App, "Game_GetCurrentGame",
                        lambda: _FakeGame(w.galaxy))
    assert combat.shields_block(w.galaxy) is True
    assert _h.combat_test_shields_block(
        _slot(w.galaxy), True, _slot(w.galaxy)) is True
    assert combat.shields_block(w.vorcha) is False
    assert _h.combat_test_shields_block(
        _slot(w.vorcha), True, _slot(w.galaxy)) is False
    assert _h.combat_test_shields_block(
        _slot(w.galaxy), True, -1) is False


def test_shields_block_throws_for_unrepresentable_targets(world):
    w = world
    obj = App.ObjectClass_Create("plain") if hasattr(App, "ObjectClass_Create") \
        else None
    if obj is not None:
        nc.register(obj, "Object")
        with pytest.raises(ValueError):
            _h.combat_test_shields_block(_slot(obj), False, -1)
    _h.combat_set_i(_slot(w.vorcha), nc._fid("has_real_get_shields"), 0)
    with pytest.raises(ValueError):
        _h.combat_test_shields_block(_slot(w.vorcha), False, -1)
    with pytest.raises(ValueError):
        _h.combat_test_shields_block(_slot(w.phasers[0]), False, -1)


# ── The shield bubble (F15-F16) ──────────────────────────────────────────────

def _bubble_case(rng, w, i):
    ship = rng.choice((w.galaxy, w.vorcha, w.warbird))
    _place(rng, ship)
    mode = i % 14
    half = [rng.uniform(0.5, 40.0) for _ in range(3)]
    centre = [rng.uniform(-5.0, 5.0) for _ in range(3)]
    if mode == 1:
        half[rng.randrange(3)] = rng.choice((0.0, -1.0))
    if mode == 2:
        half[0] = NAN
    ship._shield_hull_box = (tuple(centre), tuple(half))
    ship._scale = rng.choice((1.0, 3.0, 0.0, -1.0, NAN, rng.uniform(0.1, 5.0))
                             ) if mode in (3, 4, 5) else 1.0
    pos = ship.GetWorldLocation()
    d = _rand_vec(rng, 1.0)
    n = math.sqrt(d.x * d.x + d.y * d.y + d.z * d.z) or 1.0
    d = TGPoint3(d.x / n, d.y / n, d.z / n)
    origin = TGPoint3(pos.x + rng.uniform(-300.0, 300.0),
                      pos.y + rng.uniform(-300.0, 300.0),
                      pos.z + rng.uniform(-300.0, 300.0))
    max_dist = rng.uniform(0.0, 600.0)
    if mode == 6:                        # inside the bubble
        origin = TGPoint3(pos.x, pos.y, pos.z)
    elif mode == 7:                      # NaN origin: a NaN-coordinate point
        origin = TGPoint3(NAN, pos.y, pos.z)
    elif mode == 8:                      # d_len < 1e-12
        d = TGPoint3(0.0, 0.0, 0.0)
    elif mode == 9:                      # t beyond max_dist * d_len
        max_dist = 1e-3
    elif mode == 10:                     # NaN direction
        d = TGPoint3(NAN, 0.0, 1.0)
    elif mode == 11:                     # aimed at the centre from outside
        origin = TGPoint3(pos.x + 500.0, pos.y, pos.z)
        d = TGPoint3(-1.0, 0.0, 0.0)
        max_dist = 1e6
    elif mode == 12:
        max_dist = NAN
    return ship, origin, d, max_dist


def test_bubble_matches(world):
    w, rng = world, random.Random(SEED + 11)
    hits = nans = 0
    for i in range(CASES):
        ship, origin, d, max_dist = _bubble_case(rng, w, i)
        want = combat.shield_bubble_entry(ship, origin, d, max_dist)
        got = _h.combat_test_shield_bubble_entry(
            _slot(ship), _xyz(origin), _xyz(d), max_dist)
        assert _hx(got) == _hx(want), i % 14
        if want is not None:
            hits += 1
            nans += any(math.isnan(c) for c in _xyz(want))
    assert hits > 100            # the random cases really hit the bubble
    assert nans > 0              # ... and the NaN-point branch ran


def test_bubble_nan_point_is_a_point_not_none(world):
    """With NaN in the origin every compare is False: a NaN-coordinate point
    comes back, not None (map F16)."""
    w = world
    ship = w.galaxy
    ship._shield_hull_box = ((0.0, 0.0, 0.0), (10.0, 10.0, 10.0))
    origin = TGPoint3(NAN, 100.0, 0.0)
    d = TGPoint3(0.0, -1.0, 0.0)
    want = combat.shield_bubble_entry(ship, origin, d, 1000.0)
    assert want is not None
    got = _h.combat_test_shield_bubble_entry(
        _slot(ship), _xyz(origin), _xyz(d), 1000.0)
    assert got is not None and _hx(got) == _hx(want)


def test_bubble_without_a_box_is_none(world):
    w = world
    w.galaxy._shield_hull_box = None
    o, d = TGPoint3(0.0, 500.0, 0.0), TGPoint3(0.0, -1.0, 0.0)
    assert combat.shield_bubble_entry(w.galaxy, o, d, 1000.0) is None
    assert _h.combat_test_shield_bubble_entry(
        _slot(w.galaxy), _xyz(o), _xyz(d), 1000.0) is None
    w.galaxy._shield_hull_box = "malformed"
    assert _h.combat_test_shield_bubble_entry(
        _slot(w.galaxy), _xyz(o), _xyz(d), 1000.0) is None


def test_deleting_the_hull_box_unsets_the_row(world):
    """`del ship._shield_hull_box` (test_shield_bubble_entry does it) removes
    the attribute AND clears the mirrored box, so the kernel reads no box."""
    w = world
    o, d = TGPoint3(0.0, 5000.0, 0.0), TGPoint3(0.0, -1.0, 0.0)
    w.galaxy._shield_hull_box = ((0.0, 0.0, 0.0), (10.0, 10.0, 10.0))
    assert combat.shield_bubble_entry(w.galaxy, o, d, 10000.0) is not None
    assert _h.combat_test_shield_bubble_entry(
        _slot(w.galaxy), _xyz(o), _xyz(d), 10000.0) is not None
    del w.galaxy._shield_hull_box
    assert not hasattr(w.galaxy, "_shield_hull_box")
    assert combat.shield_bubble_entry(w.galaxy, o, d, 10000.0) is None
    assert _h.combat_test_shield_bubble_entry(
        _slot(w.galaxy), _xyz(o), _xyz(d), 10000.0) is None
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()
    with pytest.raises(AttributeError):
        del w.galaxy._shield_hull_box


def test_stale_handle_throws(world):
    w = world
    with pytest.raises(ValueError):
        _h.combat_test_strip_emit_position(_slot(w.galaxy), (0.0, 0.0, 0.0),
                                           False)     # an Object, not a Sub
    with pytest.raises(ValueError):
        _h.combat_test_shield_bubble_entry(
            _slot(w.phasers[0]), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 1.0)
