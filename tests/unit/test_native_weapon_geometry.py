"""Native weapon geometry vs the Python it ports (native combat phase 1b, Task 2;
native/src/combat/src/weapon_geometry.cc).

Each test builds real ships with native combat on, randomises poses, mounts,
arcs, velocities and scales (seeded random.Random(20261031), 2,000 cases each)
and compares the `combat_test_*` binding with the Python function of the same
name BY float.hex(): no tolerance anywhere. K1M section 3 (F2, F7, F9-F13) is
the specification. The functions only fire control used (the torpedo aim and
cone, the pulse lead, the emitter forward) were deleted with its Python copy
(fire control native only, M3): they are compared with the frozen reference
of them, tests/helpers/k1_reference.py.
"""
import importlib
import math
import random
import sys
import types

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_test_resolve_aim_world"),
    reason="native weapon geometry bindings not built")

from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import subsystems as ss  # noqa: E402
from engine.appc import weapon_subsystems as ws  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.core import step_memo  # noqa: E402
from tests.helpers import k1_reference as ref  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
SEED = 20261031
CASES = 2000
NAN = float("nan")


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
    App.g_kSetManager.AddSet(w.set, "native_geometry")
    w.other_set = App.SetClass_Create()
    App.g_kSetManager.AddSet(w.other_set, "native_geometry_other")
    w.galaxy = _ship("Galaxy1", "galaxy")
    w.vorcha = _ship("Vorcha1", "vorcha", at=(0.0, 400.0, 0.0))
    w.warbird = _ship("Warbird1", "warbird", at=(0.0, 600.0, 0.0))
    w.far = _ship("Warbird2", "warbird", at=(0.0, 900.0, 0.0))
    for ship in (w.galaxy, w.vorcha, w.warbird):
        w.set.AddObjectToSet(ship, ship.GetName())
    w.other_set.AddObjectToSet(w.far, w.far.GetName())
    w.setless = _ship("Setless1", "warbird")
    w.phasers = list(w.galaxy._phaser_system._children)
    w.tubes = list(w.galaxy._torpedo_system._children)
    w.tractors = list(w.galaxy._tractor_beam_system._children)
    w.cannons = list(w.vorcha._pulse_weapon_system._children)
    assert w.phasers and w.tubes and w.cannons
    try:
        yield w
    finally:
        App.g_kSetManager.DeleteSet("native_geometry")
        App.g_kSetManager.DeleteSet("native_geometry_other")


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
    sub._right = _rand_vec(rng, 1.0)


def _leaves(w):
    return w.phasers + w.tubes + w.tractors


# ── Mount position and the native memo ───────────────────────────────────────

def test_mount_position_matches(world):
    w, rng = world, random.Random(SEED)
    leaves = _leaves(w)
    for _ in range(CASES):
        _place(rng, w.galaxy)
        _place(rng, w.warbird)
        sub = rng.choice(leaves)
        _mount_random(rng, sub)
        arg = rng.choice((None, w.galaxy, w.warbird))
        want = ss.subsystem_world_position(sub, arg)
        got = _h.combat_test_subsystem_world_position(
            _slot(sub), _slot(arg), False)
        assert _hx(got) == _hx(want)


def test_mount_position_climbs_the_parent_chain(world):
    w, rng = world, random.Random(SEED + 1)
    for bank in w.phasers:
        _place(rng, w.galaxy)
        saved = bank._parent_ship
        bank._parent_ship = None             # reached through the system
        try:
            want = ss.subsystem_world_position(bank)
            got = _h.combat_test_subsystem_world_position(
                _slot(bank), -1, False)
            assert _hx(got) == _hx(want)
        finally:
            bank._parent_ship = saved
    # No ship at all: the origin.
    bank = w.phasers[0]
    saved_ship, saved_parent = bank._parent_ship, bank._parent_subsystem
    bank._parent_ship = None
    bank._parent_subsystem = None
    try:
        assert _hx(ss.subsystem_world_position(bank)) == _hx((0.0, 0.0, 0.0))
        assert _hx(_h.combat_test_subsystem_world_position(
            _slot(bank), -1, False)) == _hx((0.0, 0.0, 0.0))
    finally:
        bank._parent_ship, bank._parent_subsystem = saved_ship, saved_parent


def test_mount_memo_matches_python_staleness(world):
    """Inside a step the answer is reused until forget(), moved ship or not,
    keyed (sub, ship arg); forget() (the step_memo hook) clears the native one."""
    w, rng = world, random.Random(SEED + 2)
    bank = w.phasers[0]
    _h.combat_memo_clear()
    assert _h.combat_test_mount_memo_size() == 0
    with step_memo.combat_step():
        for _ in range(200):
            _place(rng, w.galaxy)
            arg = rng.choice((None, w.galaxy))
            want = ss.subsystem_world_position(bank, arg)
            got = _h.combat_test_subsystem_world_position(
                _slot(bank), _slot(arg), True)
            assert _hx(got) == _hx(want)
            if rng.random() < 0.2:
                step_memo.forget()
                assert _h.combat_test_mount_memo_size() == 0
        assert _h.combat_test_mount_memo_size() <= 2
    assert _h.combat_test_mount_memo_size() == 0


def test_memo_is_not_used_when_the_session_has_no_memo(world):
    w = world
    bank = w.phasers[0]
    w.galaxy.SetTranslateXYZ(1.0, 2.0, 3.0)
    _h.combat_test_subsystem_world_position(_slot(bank), -1, False)
    assert _h.combat_test_mount_memo_size() == 0
    first = _h.combat_test_subsystem_world_position(_slot(bank), -1, True)
    w.galaxy.SetTranslateXYZ(9.0, 9.0, 9.0)
    stale = _h.combat_test_subsystem_world_position(_slot(bank), -1, True)
    fresh = _h.combat_test_subsystem_world_position(_slot(bank), -1, False)
    assert stale == first and fresh != first
    _h.combat_memo_clear()


# ── Aim vectors ──────────────────────────────────────────────────────────────

def test_bank_aim_world_matches(world):
    w, rng = world, random.Random(SEED + 3)
    targets = (w.vorcha, w.warbird)
    for i in range(CASES):
        _place(rng, w.galaxy)
        bank = rng.choice(w.phasers)
        _mount_random(rng, bank)
        target = rng.choice(targets)
        _place(rng, target)
        mode = i % 8
        if mode == 1:            # coincident: the length <= 1e-6 fallback
            o = ss.subsystem_world_position(bank)
            target.SetTranslateXYZ(o.x, o.y, o.z)
        elif mode == 2:          # a hair away, still under 1e-6
            o = ss.subsystem_world_position(bank)
            target.SetTranslateXYZ(o.x + 5e-7, o.y, o.z)
        elif mode == 3:          # degenerate fallback AND zero rotation
            o = ss.subsystem_world_position(bank)
            target.SetTranslateXYZ(o.x, o.y, o.z)
            z = TGMatrix3()
            z.set_from_tuple([0.0] * 9)
            w.galaxy.SetMatrixRotation(z)
            # (the mount moved with the rotation: re-coincide)
            o = ss.subsystem_world_position(bank)
            target.SetTranslateXYZ(o.x, o.y, o.z)
        elif mode == 4:
            target.SetTranslateXYZ(NAN, 1.0, 2.0)
        want = ws._resolve_bank_aim_world(bank, target)
        got = _h.combat_test_resolve_bank_aim_world(
            _slot(bank), _slot(target), False)
        assert _hx(got) == _hx(want), mode
        # The ship-centre form, with and without a target.
        assert _hx(_h.combat_test_resolve_aim_world(
            _slot(w.galaxy), _slot(target))) == _hx(
                ws._resolve_aim_world(w.galaxy, target))
        assert _hx(_h.combat_test_resolve_aim_world(
            _slot(w.galaxy), -1)) == _hx(ws._resolve_aim_world(w.galaxy, None))
    assert _hx(_h.combat_test_resolve_aim_world(-1, -1)) == _hx(
        ws._resolve_aim_world(None, None))


def test_bank_aim_world_none_arguments(world):
    w = world
    bank = w.phasers[0]
    assert _hx(_h.combat_test_resolve_bank_aim_world(-1, _slot(w.warbird),
                                                     False)) == _hx(
        ws._resolve_bank_aim_world(None, w.warbird))
    assert _hx(_h.combat_test_resolve_bank_aim_world(_slot(bank), -1,
                                                     False)) == _hx(
        ws._resolve_bank_aim_world(bank, None))


def test_emitter_forward_world_matches(world):
    w, rng = world, random.Random(SEED + 4)
    emitters = w.tubes + w.cannons
    for _ in range(CASES):
        _place(rng, w.galaxy)
        em = rng.choice(emitters)
        _mount_random(rng, em)
        ship = rng.choice((w.galaxy, None))
        assert _hx(_h.combat_test_emitter_forward_world(
            _slot(em), _slot(ship))) == _hx(
                ref._emitter_forward_world(em, ship))


# ── Arc gate ─────────────────────────────────────────────────────────────────

def _aim(rng, i):
    if i % 17 == 0:
        return TGPoint3(rng.uniform(-1, 1), rng.uniform(-1, 1), NAN)
    if i % 19 == 0:
        return TGPoint3(0.0, 0.0, 0.0)
    v = _rand_vec(rng, 1.0)
    if i % 2:
        n = max(v.Length(), 1e-3)
        v = TGPoint3(v.x / n, v.y / n, v.z / n)
    return v


def test_emitter_in_arc_matches(world):
    w, rng = world, random.Random(SEED + 5)
    emitters = w.phasers + w.tubes + w.tractors
    seen = {True: 0, False: 0}
    for i in range(CASES):
        _place(rng, w.galaxy)
        em = rng.choice(emitters)
        _mount_random(rng, em)
        em._arc_set = bool(rng.getrandbits(1))
        a = rng.uniform(-3.2, 3.2)
        b = rng.uniform(-3.2, 3.2)
        c = rng.uniform(-1.7, 1.7)
        d = rng.uniform(-1.7, 1.7)
        if i % 3 == 0:                       # authored larger-first (reversed)
            a, b = max(a, b), min(a, b)
            c, d = max(c, d), min(c, d)
        if i % 11 == 0:
            a, b = -math.pi, math.pi
            c, d = -math.pi / 2, math.pi / 2
        em._arc_width_lo, em._arc_width_hi = a, b
        em._arc_height_lo, em._arc_height_hi = c, d
        ship = w.galaxy if i % 13 else None
        aim = _aim(rng, i)
        want = ws._emitter_in_arc(em, ship, aim)
        got = _h.combat_test_emitter_in_arc(
            _slot(em), _slot(ship), (aim.x, aim.y, aim.z))
        assert got is want, (i, em._arc_set)
        seen[want] += 1
    assert seen[True] > 100 and seen[False] > 100


def test_emitter_in_arc_nan_up_dot_reads_pitch_half_pi(world):
    """min(1.0, NaN) is 1.0: pitch = asin(1.0), so a NaN up_dot passes any
    pitch band containing pi/2 and nothing else."""
    w = world
    em = w.phasers[0]
    w.galaxy.SetMatrixRotation(TGMatrix3())
    em._arc_set = True
    em._direction = TGPoint3(0.0, 1.0, 0.0)
    em._up = TGPoint3(0.0, 0.0, NAN)
    em._arc_width_lo, em._arc_width_hi = -math.pi, math.pi
    for lo, hi in ((0.0, math.pi / 2), (0.0, 1.0), (math.pi, 0.0)):
        em._arc_height_lo, em._arc_height_hi = lo, hi
        aim = TGPoint3(0.0, 1.0, 0.0)
        want = ws._emitter_in_arc(em, w.galaxy, aim)
        got = _h.combat_test_emitter_in_arc(
            _slot(em), _slot(w.galaxy), (0.0, 1.0, 0.0))
        assert got is want


# ── Torpedo aim point and cone ───────────────────────────────────────────────

def test_torpedo_cone_matches(world):
    w, rng = world, random.Random(SEED + 6)
    seen = {True: 0, False: 0}
    for i in range(CASES):
        _place(rng, w.galaxy)
        tube = rng.choice(w.tubes)
        _mount_random(rng, tube)
        ship = w.galaxy if i % 9 else None
        mount = ss.subsystem_world_position(tube)
        if i % 5 == 0:                       # aim inside or near the cone
            d = tube._direction
            r = tube._right
            k = rng.uniform(0.0, 1.0)
            aim = TGPoint3(mount.x + 10 * (d.x + k * r.x),
                           mount.y + 10 * (d.y + k * r.y),
                           mount.z + 10 * (d.z + k * r.z))
        elif i % 23 == 0:
            aim = TGPoint3(mount.x, mount.y, mount.z)   # Length < 1e-6
        elif i % 29 == 0:
            aim = TGPoint3(NAN, 0.0, 1.0)
        else:
            aim = _rand_vec(rng, 800.0)
        want = ref._in_torpedo_cone(tube, ship, aim)
        got = _h.combat_test_in_torpedo_cone(
            _slot(tube), _slot(ship), (aim.x, aim.y, aim.z), False)
        assert got is want, i
        seen[want] += 1
    assert seen[True] > 50 and seen[False] > 50


def test_torpedo_cone_boundary_at_exactly_the_literal(world):
    w = world
    tube = w.tubes[0]
    w.galaxy.SetTranslateXYZ(0.0, 0.0, 0.0)
    w.galaxy.SetMatrixRotation(TGMatrix3())
    tube._position = TGPoint3(0.0, 0.0, 0.0)
    tube._direction = TGPoint3(0.0, 1.0, 0.0)
    tube._right = TGPoint3(1.0, 0.0, 0.0)
    c = ws._TORPEDO_CONE_HALF_ANGLE
    x = math.tan(c)
    outcomes = {"yaw": set(), "pitch": set()}
    for axis in ("yaw", "pitch"):         # right is +x, up = dir x right = -z
        for step in range(-6, 7):
            xx = x
            for _ in range(abs(step)):
                xx = math.nextafter(xx, math.inf if step > 0 else -math.inf)
            aim = TGPoint3(xx, 1.0, 0.0) if axis == "yaw" else TGPoint3(
                0.0, 1.0, xx)
            want = ref._in_torpedo_cone(tube, w.galaxy, aim)
            got = _h.combat_test_in_torpedo_cone(
                _slot(tube), _slot(w.galaxy), (aim.x, aim.y, aim.z), False)
            assert got is want, (axis, step)
            outcomes[axis].add(want)
    # each scan crosses its boundary, and one point sits exactly ON it
    assert outcomes == {"yaw": {True, False}, "pitch": {True, False}}


def test_torpedo_aim_point_matches(world):
    w, rng = world, random.Random(SEED + 7)
    for i in range(CASES):
        _place(rng, w.galaxy)
        _place(rng, w.warbird)
        w.warbird.SetScale(rng.choice((1.0, 3.0, rng.uniform(0.2, 5.0))))
        tube = rng.choice(w.tubes + w.cannons)
        if i % 4 == 0:
            tube._target_offset = None
        elif i % 4 == 1:                    # a subsystem mount of the target
            hull = rng.choice(list(w.warbird._phaser_system._children))
            tube._target_offset = hull.GetPosition()
        else:
            tube._target_offset = _rand_vec(rng, 4.0)
        target = w.warbird if i % 31 else None
        if i % 37 == 0:
            w.warbird.SetDead()
        else:
            w.warbird._dead = False
        want = ref._resolve_torpedo_aim_point(tube, target)
        got = _h.combat_test_resolve_torpedo_aim_point(
            _slot(tube), _slot(target))
        assert _hx(got) == _hx(want), i


def test_target_offset_world_matches(world):
    w, rng = world, random.Random(SEED + 8)
    for i in range(CASES):
        _place(rng, w.warbird)
        w.warbird.SetScale(rng.choice((1.0, 3.0, rng.uniform(0.0, 6.0))))
        if i % 3 == 0:
            sub = rng.choice(list(w.warbird._phaser_system._children))
            offset = sub.GetPosition()
        else:
            offset = _rand_vec(rng, 5.0)
        want = ss.target_offset_world(w.warbird, offset)
        got = _h.combat_test_target_offset_world(
            _slot(w.warbird), (offset.x, offset.y, offset.z))
        assert _hx(got) == _hx(want)


# ── Pulse lead solve ─────────────────────────────────────────────────────────

def _fake_mod(speed, lifetime):
    return types.SimpleNamespace(GetLaunchSpeed=lambda: speed,
                                 GetLifetime=lambda: lifetime)


def test_pulse_launch_matches(world):
    w, rng = world, random.Random(SEED + 9)
    outcomes = {"none": 0, "dir": 0}
    reasons = set()
    for i in range(CASES):
        _place(rng, w.vorcha, spread=300.0)
        _place(rng, w.warbird, spread=300.0)
        w.vorcha.SetVelocity(_rand_vec(rng, 6.0))
        w.warbird.SetVelocity(_rand_vec(rng, 6.0 if i % 5 else 60.0))
        w.warbird.SetScale(rng.choice((1.0, 3.0)))
        cannon = rng.choice(w.cannons)
        _mount_random(rng, cannon)
        if i % 3 == 0:
            cannon._target_offset = _rand_vec(rng, 2.0)
        else:
            cannon._target_offset = None
        speed = rng.choice((0.0, -1.0, rng.uniform(0.5, 30.0), 3.0))
        lifetime = rng.choice((8.0, rng.uniform(0.01, 20.0), 100.0))
        _h.combat_set_f(_slot(cannon), nc._fid("launch_speed"), speed)
        _h.combat_set_f(_slot(cannon), nc._fid("lifetime"), lifetime)
        _h.combat_set_i(_slot(cannon), nc._fid("module_ok"), 1)
        mod = _fake_mod(speed, lifetime)
        if i % 41 == 0:                      # target on the muzzle: dist < 1e-6
            m = ss.subsystem_world_position(cannon)
            w.warbird.SetTranslateXYZ(m.x, m.y, m.z)
            cannon._target_offset = None
        want = ref._solve_pulse_launch_direction(cannon, w.vorcha, w.warbird, mod)
        got = _h.combat_test_solve_pulse_launch_direction(
            _slot(cannon), _slot(w.vorcha), _slot(w.warbird), False)
        assert _hx(got) == _hx(want), i
        outcomes["none" if want is None else "dir"] += 1
    assert outcomes["none"] > 100 and outcomes["dir"] > 100


def test_pulse_launch_edges(world):
    """v_eff <= 0, t > lifetime and the 30 x v_eff range gate, each pinned."""
    w = world
    cannon = w.cannons[0]
    w.vorcha.SetTranslateXYZ(0.0, 0.0, 0.0)
    w.vorcha.SetMatrixRotation(TGMatrix3())
    w.vorcha.SetVelocity(TGPoint3(0.0, 0.0, 0.0))
    cannon._position = TGPoint3(0.0, 0.0, 0.0)
    cannon._target_offset = None
    w.warbird.SetScale(1.0)
    w.warbird.SetTranslateXYZ(0.0, 100.0, 0.0)
    cases = (
        # (speed, lifetime, target velocity y): v_eff <= 0
        (5.0, 8.0, 5.0),
        (5.0, 8.0, 9.0),
        # t > lifetime: dist 100 / v_eff 5 = 20 s
        (5.0, 8.0, 0.0),
        (5.0, 20.0, 0.0),
        (5.0, 20.5, 0.0),
        # the 30 x v_eff gate: an APPROACHING target (vy -9) the lead pulls in
        (5.0, 1000.0, -9.0),
        (5.0, 1000.0, 4.5),
        (5.0, 1000.0, 4.99),
    )
    kinds = set()
    for speed, lifetime, vy in cases:
        w.warbird.SetVelocity(TGPoint3(0.0, vy, 0.0))
        _h.combat_set_f(_slot(cannon), nc._fid("launch_speed"), speed)
        _h.combat_set_f(_slot(cannon), nc._fid("lifetime"), lifetime)
        _h.combat_set_i(_slot(cannon), nc._fid("module_ok"), 1)
        want = ref._solve_pulse_launch_direction(
            cannon, w.vorcha, w.warbird, _fake_mod(speed, lifetime))
        got = _h.combat_test_solve_pulse_launch_direction(
            _slot(cannon), _slot(w.vorcha), _slot(w.warbird), False)
        assert _hx(got) == _hx(want), (speed, lifetime, vy)
        kinds.add(want is None)
    assert kinds == {True, False}


def test_pulse_launch_without_a_resolved_module_falls_back(world):
    w = world
    cannon = w.cannons[0]
    _h.combat_set_i(_slot(cannon), nc._fid("module_ok"), 0)
    with pytest.raises(ValueError):
        _h.combat_test_solve_pulse_launch_direction(
            _slot(cannon), _slot(w.vorcha), _slot(w.warbird), False)


def test_pulse_launch_no_target_is_none(world):
    w = world
    cannon = w.cannons[0]
    _h.combat_set_i(_slot(cannon), nc._fid("module_ok"), 1)
    assert _h.combat_test_solve_pulse_launch_direction(
        _slot(cannon), _slot(w.vorcha), -1, False) is None


# ── Range gate ───────────────────────────────────────────────────────────────

def test_range_gate_matches(world):
    w, rng = world, random.Random(SEED + 10)
    seen = {True: 0, False: 0}
    others = (w.warbird, w.vorcha, w.far, w.setless, None)
    for i in range(CASES):
        _place(rng, w.galaxy, spread=800.0)
        ship = w.galaxy if i % 43 else None
        target = rng.choice(others)
        if target is not None:
            _place(rng, target, spread=800.0)
        limit = 700.0 if i % 2 else 120.0
        if i % 7 == 0 and target is not None and ship is not None:
            # exactly on the boundary along one axis
            p = w.galaxy.GetWorldLocation()
            target.SetTranslateXYZ(p.x + limit, p.y, p.z)
        if i % 53 == 0 and target is not None:
            target.SetTranslateXYZ(NAN, 0.0, 0.0)
        want = ws._target_within_range_gu(ship, target, limit)
        got = _h.combat_test_target_within_range_gu(
            _slot(ship), _slot(target), limit)
        assert got is want, i
        seen[want] += 1
    assert seen[True] > 50 and seen[False] > 50


def test_range_gate_cross_set_and_setless(world):
    w = world
    w.galaxy.SetTranslateXYZ(0.0, 0.0, 0.0)
    w.far.SetTranslateXYZ(0.0, 1.0, 0.0)      # close, but in another set
    assert ws._target_within_range_gu(w.galaxy, w.far, 700.0) is False
    assert _h.combat_test_target_within_range_gu(
        _slot(w.galaxy), _slot(w.far), 700.0) is False
    w.setless.SetTranslateXYZ(0.0, 1.0, 0.0)
    assert _h.combat_test_target_within_range_gu(
        _slot(w.setless), _slot(w.setless), 700.0) is False
    assert _h.combat_test_target_within_range_gu(
        _slot(w.setless), _slot(w.galaxy), 700.0) is False


# ── Posed ships fall back ────────────────────────────────────────────────────

def test_posed_ship_throws(world):
    w = world
    from engine.appc import articulation, part_pose
    bank = w.phasers[0]
    # Off identity: at identity a posed ship answers natively (Task 6b).
    hinge = part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0)
    articulation.force_part_pose(w.galaxy, "TestPart", hinge)
    articulation.force_part_pose(w.warbird, "TestPart", hinge)
    try:
        with pytest.raises(ValueError):
            _h.combat_test_subsystem_world_position(_slot(bank), -1, False)
        with pytest.raises(ValueError):
            _h.combat_test_subsystem_world_position(
                _slot(w.phasers[1]), _slot(w.galaxy), True)
        # An offset no mount claims on a posed target is a plain body
        # point, not a throw (fire control native only, M5).
        want = ss.target_offset_world(w.warbird, TGPoint3(1.0, 2.0, 3.0))
        got = _h.combat_test_target_offset_world(_slot(w.warbird),
                                                 (1.0, 2.0, 3.0))
        assert _hx(got) == _hx(want)
        with pytest.raises(ValueError):
            _h.combat_test_resolve_bank_aim_world(
                _slot(bank), _slot(w.vorcha), False)
        with pytest.raises(ValueError):
            _h.combat_test_in_torpedo_cone(
                _slot(w.tubes[0]), _slot(w.galaxy), (1.0, 2.0, 3.0), False)
        # A throw leaves nothing in the memo.
        assert _h.combat_test_mount_memo_size() == 0
    finally:
        articulation.force_pose(w.galaxy, None)
        articulation.force_pose(w.warbird, None)
    # Unposed again: it answers.
    _h.combat_test_subsystem_world_position(_slot(bank), -1, False)


def test_stale_handle_throws(world):
    w = world
    with pytest.raises(ValueError):
        _h.combat_test_subsystem_world_position(
            _slot(w.galaxy), -1, False)      # an Object, not a Subsystem
    with pytest.raises(ValueError):
        _h.combat_test_target_within_range_gu(
            _slot(w.phasers[0]), _slot(w.warbird), 700.0)


def test_weapon_constants_are_pushed_from_python(world):
    g = _h.combat_dump_globals()
    assert float(g["TORPEDO_CONE_HALF_ANGLE"]).hex() == float(
        ws._TORPEDO_CONE_HALF_ANGLE).hex()
    assert float(g["PULSE_RANGE_GATE_SECONDS"]).hex() == float(
        ws._PULSE_RANGE_GATE_SECONDS).hex()


# ── Added in fix round 1: mutation-killing cases ─────────────────────────────

def test_pulse_launch_with_no_ship_uses_zero_velocity(world):
    w, rng = world, random.Random(SEED + 11)
    cannon = w.cannons[0]
    _h.combat_set_i(_slot(cannon), nc._fid("module_ok"), 1)
    _h.combat_set_f(_slot(cannon), nc._fid("launch_speed"), 7.0)
    _h.combat_set_f(_slot(cannon), nc._fid("lifetime"), 50.0)
    got_dirs = 0
    for _ in range(200):
        _place(rng, w.vorcha, spread=100.0)
        _place(rng, w.warbird, spread=100.0)
        w.vorcha.SetVelocity(_rand_vec(rng, 6.0))     # must be ignored
        w.warbird.SetVelocity(_rand_vec(rng, 3.0))
        cannon._target_offset = None
        mod = _fake_mod(7.0, 50.0)
        want = ref._solve_pulse_launch_direction(cannon, None, w.warbird, mod)
        got = _h.combat_test_solve_pulse_launch_direction(
            _slot(cannon), -1, _slot(w.warbird), False)
        assert _hx(got) == _hx(want)
        got_dirs += want is not None
    assert got_dirs > 50


def test_pulse_launch_n_below_epsilon_is_none(world):
    """The predicted intercept lands on the muzzle: n < 1e-6 (dist is large,
    so the earlier dist < 1e-6 gate does not fire)."""
    w = world
    cannon = w.cannons[0]
    _h.combat_set_i(_slot(cannon), nc._fid("module_ok"), 1)
    w.vorcha.SetTranslateXYZ(0.0, 0.0, 0.0)
    w.vorcha.SetMatrixRotation(TGMatrix3())
    w.vorcha.SetVelocity(TGPoint3(0.0, 0.0, 0.0))
    cannon._position = TGPoint3(0.0, 0.0, 0.0)
    cannon._target_offset = None
    w.warbird.SetScale(1.0)
    w.warbird.SetTranslateXYZ(0.0, 10.0, 0.0)
    # speed 0, target velocity -10 along y: v_eff = 10, t = 1, pred.y =
    # 10 + (-10)(1) = 0 exactly: the muzzle itself.
    kinds = set()
    for speed, vy in ((0.0, -10.0), (0.0, -20.0), (5.0, -10.0), (10.0, -1.0)):
        w.warbird.SetVelocity(TGPoint3(0.0, vy, 0.0))
        _h.combat_set_f(_slot(cannon), nc._fid("launch_speed"), speed)
        _h.combat_set_f(_slot(cannon), nc._fid("lifetime"), 100.0)
        want = ref._solve_pulse_launch_direction(
            cannon, w.vorcha, w.warbird, _fake_mod(speed, 100.0))
        got = _h.combat_test_solve_pulse_launch_direction(
            _slot(cannon), _slot(w.vorcha), _slot(w.warbird), False)
        assert _hx(got) == _hx(want), (speed, vy)
        kinds.add(want is None)
    assert True in kinds and False in kinds


def test_bank_aim_world_with_memo_matches(world):
    w, rng = world, random.Random(SEED + 12)
    _h.combat_memo_clear()
    with step_memo.combat_step():
        for i in range(300):
            _place(rng, w.galaxy)
            _place(rng, w.warbird)
            bank = rng.choice(w.phasers)
            want = ws._resolve_bank_aim_world(bank, w.warbird)
            got = _h.combat_test_resolve_bank_aim_world(
                _slot(bank), _slot(w.warbird), True)
            assert _hx(got) == _hx(want), i
            if i % 7 == 0:
                step_memo.forget()
    assert _h.combat_test_mount_memo_size() == 0
