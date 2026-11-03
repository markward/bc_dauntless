"""Native projectile geometry vs the Python it ports (native combat phase 3 /
K3, Task 3; native/src/combat/src/projectile_geometry.cc).

Each test builds real ships and torpedoes with native combat on, randomises
poses, velocities, guidance fields, sets and frames (seeded
random.Random(20261101), 2,000 cases each) and compares the `combat_test_*`
binding with the Python function it ports BY float.hex(): no tolerance
anywhere. docs/reference/engine/native-combat/k3-k4-map.md sections A1.1-A1.3
and A3 (B1, G1-G12, A1-A8) are the specification.

Guidance is compared write by write: the native answer lists the fields
`_guide` writes, in its write order; the Python's writes are read back by
identity (every write binds a fresh TGPoint3). Both arms start from the same
can_detect latch and memo, and the latch each leaves must agree.

Frames are real: mapped sets get their system frame through
`frames.frame_of` (region_hooks' flag + resolve's anchor/system lookups,
patched here to a table, as test_native_k4_eligibility does).
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
    _h is None or not hasattr(_h, "combat_test_guide_torpedo"),
    reason="native projectile geometry bindings not built")

from engine.appc import collisions  # noqa: E402,F401
from engine.appc import combat  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import projectiles  # noqa: E402
from engine.appc import sensor_detection  # noqa: E402
from engine.appc import sensor_occlusion  # noqa: E402
from engine.appc import subsystems  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.appc.projectiles import Torpedo  # noqa: E402
from engine.appc.sets import SetClass  # noqa: E402
from engine.core import step_memo  # noqa: E402
from engine.systems import frames, region_hooks, resolve  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
SEED = 20261101
CASES = 2000
NAN = float("nan")
INF = float("inf")

# set name -> (system, anchor_gu); a set in this table is mapped.
ANCHORS = {
    "K3GeoA1": ("K3GeoA", (0.0, 0.0, 0.0)),
    "K3GeoA2": ("K3GeoA", (1000.5, -20.25, 3.0)),
    "K3GeoB": ("K3GeoB", (-7.0, 12.5, 0.125)),
}
SET_NAMES = ("K3GeoA1", "K3GeoA2", "K3GeoB", "K3GeoPlain")
GUIDE_FIELDS = ("_last_seen_target_pos", "_last_target_vel", "_velocity")


@pytest.fixture(autouse=True)
def _switch(monkeypatch):
    nc.reset()
    monkeypatch.setattr(
        resolve, "anchor_of",
        lambda name: ANCHORS[name][1] if name in ANCHORS else None)
    monkeypatch.setattr(
        resolve, "system_of",
        lambda name: ANCHORS[name][0] if name in ANCHORS else None)
    yield
    for t in list(projectiles._active):
        projectiles.expire(t)
    for name in SET_NAMES:
        App.g_kSetManager._sets.pop(name, None)
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


def _make_set(name):
    s = SetClass()
    s.SetName(name)
    App.g_kSetManager._sets[name] = s
    if name in ANCHORS:
        region_hooks.mark_mapped(s)
    return s


def _ship(pSet, name, hardpoint):
    ship = App.ShipClass_Create(name)
    _load_hardpoint(ship, hardpoint)
    if pSet is not None:
        pSet.AddObjectToSet(ship, name)
    return ship


class World:
    pass


@pytest.fixture
def world():
    nc.configure(ON)
    assert nc.enabled()
    nc.torpedo_table_rebuild(projectiles._active)
    w = World()
    w.sets = {name: _make_set(name) for name in SET_NAMES}
    a1, a2, b = (w.sets[n] for n in ("K3GeoA1", "K3GeoA2", "K3GeoB"))
    w.src_a1 = _ship(a1, "K3SrcA1", "galaxy")
    w.src_b = _ship(b, "K3SrcB", "galaxy")
    w.tgt_a1 = _ship(a1, "K3TgtA1", "vorcha")
    w.wb_a1 = _ship(a1, "K3WbA1", "warbird")
    w.tgt_a2 = _ship(a2, "K3TgtA2", "vorcha")
    w.tgt_b = _ship(b, "K3TgtB", "vorcha")
    w.tgt_plain = _ship(w.sets["K3GeoPlain"], "K3TgtPlain", "vorcha")
    w.tgt_none = _ship(None, "K3TgtNone", "vorcha")
    w.ships = (w.src_a1, w.src_b, w.tgt_a1, w.wb_a1, w.tgt_a2, w.tgt_b,
               w.tgt_plain, w.tgt_none)
    w.cloak = w.wb_a1.GetCloakingSubsystem()
    assert w.cloak is not None
    w.torp = Torpedo()
    projectiles.register(w.torp)
    assert "_k3_row" in w.torp.__dict__
    _send_frames(w)
    return w


def _send_frames(w):
    handles = [s.__dict__["_nslot"] for s in w.sets.values()]
    _h.combat_step_frames(nc._step_frames(handles, {}))


def _slot(obj):
    return obj.__dict__["_nslot"] if obj is not None else -1


def _row(t):
    return t.__dict__["_k3_row"]


def _xyz(p):
    return (p.x, p.y, p.z)


def _hx(p):
    if p is None:
        return None
    if isinstance(p, TGPoint3):
        return (p.x.hex(), p.y.hex(), p.z.hex())
    return tuple(float(c).hex() for c in p)


def _mounted(ship):
    """The ship's subsystems with an authored mount (what
    authored_mount_subsystem scans). ShipClass has no
    GetNumChildSubsystems: the TGObject stub would make the list empty."""
    from engine.appc.part_severance import _mounted_subsystems
    subs = [sub for sub, _ in _mounted_subsystems(ship)]
    assert subs
    return subs


def _rand_vec(rng, scale=1.0):
    return TGPoint3(*(rng.uniform(-scale, scale) for _ in range(3)))


def _rand_rot(rng):
    m = TGMatrix3()
    w, x, y, z = (rng.gauss(0, 1) for _ in range(4))
    n = math.sqrt(w * w + x * x + y * y + z * z)
    w, x, y, z = w / n, x / n, y / n, z / n
    m.set_from_tuple((
        1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
        2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
        2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))
    return m


def _reset_sensors():
    """Both arms start from the same can_detect latch and memo."""
    _h.combat_latch_reset()
    step_memo.forget()


def _clocks():
    return nc.now(), sensor_occlusion._now()


def _native_guide(t, dt, use_memo=False):
    """The native guide of `t`, an ASK for the steer point answered by
    Python's _steer_point (the `_mount_key` it writes is put back after,
    so the Python arm starts from the same torpedo). Returns (status, writes as
    [(field, hex xyz)], latch or None, asked, the mount attributed natively
    (a handle, -1 None) or None)."""
    drift, occ = _clocks()
    r = _h.combat_test_guide_torpedo(_row(t), dt, use_memo, drift, occ)
    attributed = r[2] if r[0] == "done" else None
    asked = False
    if r[0] == "steer_point":
        asked = True
        target_h, speed, torp_pos = r[1]
        target = t._target_ship
        assert target_h == _slot(target)
        off = frames.offset_between(frames.containing_set(t),
                                    frames.containing_set(target))
        saved_key = t._mount_key
        p = projectiles._steer_point(t, target, off)
        r = _h.combat_test_guide_torpedo_resume(
            _row(t), dt, target_h, speed, torp_pos, _xyz(p))
        t._mount_key = saved_key
        assert r[0] == "done", r
    if r[0] != "done":
        return r[0], r[1], None, asked, None
    writes = [(name, _hx(v)) for name, v in r[1]]
    return "done", writes, _latch(t), asked, attributed


def _latch(t):
    src, tgt = t._source_ship, t._target_ship
    if src is None or tgt is None:
        return None
    return _h.combat_latched(_slot(src), _slot(tgt))


def _python_guide(t, dt):
    before = {n: getattr(t, n) for n in GUIDE_FIELDS}
    projectiles._guide(t, dt)
    writes = [(n, _hx(getattr(t, n))) for n in GUIDE_FIELDS
              if getattr(t, n) is not before[n]]
    return writes, _latch(t)


def _compare_guide(t, dt, use_memo=False):
    """Native then Python from one starting state; asserts they agree --
    a mount the kernel attributed is the one Python's _steer_point wrote
    into `_mount_key` (round trips, Task 4) -- and returns (native writes,
    asked for the steer point). `_compare_guide.attributed` counts the
    native attributions."""
    _reset_sensors()
    key = t.__dict__.get("_mount_key")
    status, writes, latch, asked, mount = _native_guide(t, dt, use_memo)
    assert status == "done", (status, writes)
    _reset_sensors()
    py_writes, py_latch = _python_guide(t, dt)
    assert writes == py_writes
    assert latch == py_latch
    if mount is not None:
        _compare_guide.attributed += 1
        new = t.__dict__.get("_mount_key")
        assert new is not key and new[0] is t._target_ship
        assert _slot(new[4]) == mount
    return writes, asked


_compare_guide.attributed = 0


# ── B1: bubble_bound_radius ──────────────────────────────────────────────────

def test_bubble_bound_matches(world):
    w, rng = world, random.Random(SEED)
    ships = (w.tgt_a1, w.wb_a1, w.tgt_a2)
    for i in range(CASES):
        ship = rng.choice(ships)
        mode = i % 8
        ship._radius = rng.choice((rng.uniform(0.0, 40.0), 0.0, -3.0, NAN)
                                  ) if mode == 1 else rng.uniform(0.5, 40.0)
        ship._scale = rng.choice((1.0, 0.0, -2.0, NAN, INF,
                                  rng.uniform(0.1, 9.0))
                                 ) if mode in (2, 3) else 1.0
        half = [rng.uniform(0.5, 40.0) for _ in range(3)]
        centre = [rng.uniform(-5.0, 5.0) for _ in range(3)]
        if mode == 4:
            half[rng.randrange(3)] = rng.choice((0.0, -1.0, NAN))
        if mode == 5:
            centre = [rng.uniform(-60.0, 60.0) for _ in range(3)]  # off-centre
        if mode == 6:
            ship._shield_hull_box = None                            # no box
        else:
            ship._shield_hull_box = (tuple(centre), tuple(half))
        want = combat.bubble_bound_radius(ship)
        got = _h.combat_test_bubble_bound_radius(_slot(ship))
        assert got.hex() == float(want).hex(), mode


def test_bubble_bound_unreadable_radius_is_python_inf(world):
    """An unreadable radius makes Python's bound inf -- and the same value
    drops the ship's row (NativeField._push), so the native bound refuses
    (the step scan sends such a step to Python)."""
    w = world
    h = _slot(w.tgt_none)
    w.tgt_none._radius = "unreadable"
    assert combat.bubble_bound_radius(w.tgt_none) == INF
    assert "_nslot" not in w.tgt_none.__dict__
    with pytest.raises(ValueError):
        _h.combat_test_bubble_bound_radius(h)


# ── A8: sphere_hit ───────────────────────────────────────────────────────────

def test_sphere_hit_matches(world):
    rng = random.Random(SEED + 1)
    hits = 0
    for i in range(CASES):
        c = _rand_vec(rng, 50.0)
        r = rng.choice((rng.uniform(0.0, 40.0), 0.0, -5.0, NAN, 10.0))
        p = TGPoint3(c.x + rng.uniform(-30.0, 30.0),
                     c.y + rng.uniform(-30.0, 30.0),
                     c.z + rng.uniform(-30.0, 30.0))
        mode = i % 6
        if mode == 1:
            p = TGPoint3(NAN, p.y, p.z)
        elif mode == 2:                       # exactly on the surface
            p, r = TGPoint3(c.x + 10.0, c.y, c.z), 10.0
        elif mode == 3:
            c = TGPoint3(c.x, NAN, c.z)
        want = combat.sphere_hit(p, c, r)
        got = _h.combat_test_sphere_hit(_xyz(p), _xyz(c), r)
        assert got is want, mode
        hits += want
    assert hits > 100


# ── A1-A6: the advance ───────────────────────────────────────────────────────

def _advance_python(prev, vel, dt, age, ttl):
    """update_all's advance (projectiles.py:912-930), transcribed for the parts
    update_all keeps local (seg, seg_len, aim_unit)."""
    cur = prev + vel * dt
    age = age + dt
    if age >= ttl:
        return cur, age, True, None, None, None
    seg = cur - prev
    seg_len = seg.Length()
    aim = (TGPoint3(seg.x / seg_len, seg.y / seg_len, seg.z / seg_len)
           if seg_len > 1e-9 else None)
    return cur, age, False, seg, seg_len, aim


def test_advance_matches(world):
    w, rng = world, random.Random(SEED + 2)
    t = w.torp
    expired = kept = 0
    for i in range(CASES):
        prev = _rand_vec(rng, rng.choice((10.0, 1e4, 1e16)))
        vel = _rand_vec(rng, rng.choice((1.0, 50.0, 3000.0)))
        dt = rng.choice((1.0 / 60.0, 0.1, 0.0, 1e-12))
        age = rng.uniform(0.0, 61.0)
        ttl = rng.choice((60.0, rng.uniform(0.0, 61.0)))
        mode = i % 8
        if mode == 1:                 # the TTL boundary, exactly
            ttl, dt, age = 1.0, 0.5, 0.5
        elif mode == 2:
            age = NAN
        elif mode == 3:               # seg_len <= 1e-9
            vel = TGPoint3(1e-12, 0.0, 0.0)
            dt = 1.0
        elif mode == 4:
            vel = TGPoint3(NAN, 1.0, 0.0)
        elif mode == 5:
            ttl = NAN
        got = _h.combat_test_advance_torpedo(_xyz(prev), _xyz(vel), dt, age,
                                             ttl)
        want = _advance_python(prev, vel, dt, age, ttl)
        assert _hx(got[0]) == _hx(want[0]), mode
        assert got[1].hex() == want[1].hex() and got[2] is want[2], mode
        if not want[2]:
            assert _hx(got[3]) == _hx(want[3]), mode
            assert got[4].hex() == want[4].hex(), mode
            assert _hx(got[5]) == _hx(want[5]), mode

        # The real code: update_all with no ships moves and ages the
        # torpedo, and expires it at the TTL.
        if t not in projectiles._active:
            t = w.torp = Torpedo()
            projectiles.register(t)
        t._target_ship = None
        t.SetTranslateXYZ(prev.x, prev.y, prev.z)
        t._velocity = vel
        t._age, t._ttl = age, ttl
        projectiles.update_all(dt, [])
        assert _hx(t.GetTranslate()) == _hx(got[0]), mode
        assert t._age.hex() == got[1].hex(), mode
        assert (t not in projectiles._active) is got[2], mode
        expired += got[2]
        kept += not got[2]
    assert expired > 100 and kept > 100


# ── G11/G12: the steer point ─────────────────────────────────────────────────

def test_steer_point_matches(world):
    w, rng = world, random.Random(SEED + 3)
    t = w.torp
    targets = (w.tgt_a1, w.wb_a1, w.tgt_a2)
    for i in range(CASES):
        target = rng.choice(targets)
        target.SetTranslateXYZ(*(rng.uniform(-500.0, 500.0) for _ in range(3)))
        mode = i % 6
        target.SetMatrixRotation(_rand_rot(rng) if mode in (2, 3, 5)
                                 else TGMatrix3())
        target._scale = (rng.choice((rng.uniform(0.1, 5.0), 0.0, -1.0, NAN))
                         if mode in (3, 4) else 1.0)
        off = rng.choice(((0.0, 0.0, 0.0), (-0.0, 0.0, -0.0),
                          (1000.5, -20.25, 3.0), (rng.uniform(-9, 9), 0.0,
                                                  0.0)))
        t._target_ship = target
        t._mount_key = None
        if mode == 0:
            t.SetTargetOffset(None)
        elif mode == 5:               # an authored mount: a real subsystem
            subs = _mounted(target)
            t.SetTargetOffset(rng.choice(subs).GetPositionTG())
        else:
            t.SetTargetOffset(_rand_vec(rng, 3.0))
        # The first call attributes the mount (writes _mount_key); the
        # native function answers for an attributed shot.
        projectiles._steer_point(t, target, off)
        want = projectiles._steer_point(t, target, off)
        offset = t._target_offset
        mount = t._mount_key[4] if t._mount_key is not None else None
        got = _h.combat_test_steer_point(
            _slot(target), None if offset is None else _xyz(offset),
            _slot(mount), off)
        assert _hx(got) == _hx(want), mode


def test_steer_point_posed_pick_matches(world):
    """A picked spot's steer point (fire control native only, M5): Python
    steers at the offset as a plain body point, `pos + R·(scale·offset)`
    with NO part pose and no launch-time bake; native steer_point_native
    equals it by .hex() -- posed and unposed targets, rotated and scaled
    (0, -1, NaN), signed zeros (never an identity pose multiplied), NaN
    offsets, a frame shift."""
    from engine.appc import articulation, part_pose
    w, rng = world, random.Random(SEED + 11)
    t = w.torp
    targets = (w.tgt_a1, w.wb_a1, w.tgt_a2)
    hinge = part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0)
    posed = zeros = 0
    for i in range(CASES):
        target = rng.choice(targets)
        if i % 2:
            articulation.force_part_pose(target, "probe part", hinge)
        else:
            target._articulation_poses = {}
        assert bool(target.__dict__.get("_articulation_poses")) == bool(i % 2)
        mode = i % 10
        if mode == 9:                 # every signed zero kept end to end
            target.SetTranslateXYZ(-0.0, -0.0, -0.0)
            target.SetMatrixRotation(TGMatrix3())
            target._scale = 1.0
            off = (-0.0, -0.0, -0.0)
        else:
            target.SetTranslateXYZ(
                *(rng.uniform(-500.0, 500.0) for _ in range(3)))
            target.SetMatrixRotation(_rand_rot(rng) if mode in (1, 2, 5)
                                     else TGMatrix3())
            target._scale = (rng.choice((rng.uniform(0.1, 5.0), 0.0, -1.0,
                                         NAN))
                             if mode in (2, 3) else 1.0)
            off = rng.choice(((0.0, 0.0, 0.0), (-0.0, 0.0, -0.0),
                              (NAN, 1.0, 2.0), (1000.5, -20.25, 3.0),
                              tuple(rng.uniform(-3, 3) for _ in range(3))))
        shift = rng.choice(((0.0, 0.0, 0.0), (-0.0, 0.0, 0.0),
                            (100.0, -5.0, 0.25)))
        t._target_ship = target
        t.SetTargetOffset(TGPoint3(*off))
        t._mount_key = (target,) + off + (None,)
        want = projectiles._steer_point(t, target, shift)
        got = _h.combat_test_steer_point(_slot(target), off, -1, shift)
        assert _hx(got) == _hx(want), (i, off)
        posed += i % 2
        zeros += _hx(got) == _hx((-0.0, -0.0, -0.0))
    assert posed > 500 and zeros > 50, (posed, zeros)


# ── G1-G12: guidance ─────────────────────────────────────────────────────────

def _place(rng, ship, spread=250.0, at=(0.0, 0.0, 0.0)):
    ship.SetTranslateXYZ(*(a + rng.uniform(-spread, spread) for a in at))
    ship.SetMatrixRotation(_rand_rot(rng))


def _setup_guide_case(w, rng, i):
    t = w.torp
    a1, a2 = w.sets["K3GeoA1"], w.sets["K3GeoA2"]
    mode = i % 16
    w.cloak.InstantDecloak()
    for ship in w.ships:
        _place(rng, ship)
        ship._velocity = _rand_vec(rng, 20.0)
        ship._dead = False
        ship._scale = 1.0
    src, target, tset = w.src_a1, rng.choice((w.tgt_a1, w.wb_a1)), a1
    dt = rng.choice((1.0 / 60.0, 1.0 / 60.0, 1.0 / 60.0, 0.1, 0.0, 1e-10))
    t.SetTranslateXYZ(*(rng.uniform(-250.0, 250.0) for _ in range(3)))
    t._velocity = _rand_vec(rng, 50.0)
    t._age = rng.uniform(0.0, 4.0)
    t.SetGuidanceLifetime(4.0)
    if rng.random() < 0.3:
        t._guidance_initial = rng.uniform(0.5, 6.0)
    t.SetMaxAngularAccel(rng.choice((0.125, 1.0, 1000.0,
                                     rng.uniform(0.0, 3.0))))
    t._last_seen_target_pos = (_rand_vec(rng, 250.0) if rng.random() < 0.5
                               else None)
    t._last_target_vel = _rand_vec(rng, 20.0) if rng.random() < 0.5 else None
    t.SetTargetOffset(None)
    t._mount_key = None

    if mode == 1 or mode == 2:            # an aim offset
        subs = _mounted(target)
        t.SetTargetOffset(rng.choice(subs).GetPositionTG()
                          if rng.random() < 0.5 else _rand_vec(rng, 3.0))
        target._scale = rng.choice((1.0, rng.uniform(0.2, 4.0)))
        if mode == 1:                     # already attributed
            projectiles._steer_point(t, target, (0.0, 0.0, 0.0))
    elif mode == 3 or mode == 4:          # cloaked: the last-seen point
        target = w.wb_a1
        w.cloak.InstantCloak()
        if mode == 4:
            t._last_seen_target_pos = None
        elif rng.random() < 0.2:
            t._last_seen_target_pos = TGPoint3(NAN, 1.0, 2.0)
        elif t._last_seen_target_pos is None:
            t._last_seen_target_pos = _rand_vec(rng, 250.0)
    elif mode == 5:
        target._dead = True
    elif mode == 6:                       # another frame, or no set
        target = rng.choice((w.tgt_b, w.tgt_plain, w.tgt_none, w.tgt_a1))
        if target is w.tgt_a1:
            tset = rng.choice((None, w.sets["K3GeoB"]))
    elif mode == 7:                       # speed < 1e-6, and its edge
        t._velocity = rng.choice((TGPoint3(0.0, 0.0, 0.0),
                                  TGPoint3(0.0, 1e-7, 0.0),
                                  TGPoint3(1e-6, 0.0, 0.0),
                                  TGPoint3(-0.0, 0.0, 5e-7)))
    elif mode == 8:                       # dist < 1e-6 after the writes
        target = w.tgt_a1
        target._velocity = TGPoint3(0.0, 0.0, 0.0)
        t._last_target_vel = None
        p = target.GetWorldLocation()
        t.SetTranslateXYZ(p.x, p.y, p.z)
    elif mode == 9:                       # a NaN aim
        target._velocity = TGPoint3(NAN, 0.0, 1.0)
    elif mode == 10:                      # the guidance window edge
        t._age = rng.choice((4.0, 4.0 + 1e-9, 4.5, 4.0 - 1e-12))
    elif mode == 11:                      # re-emerge: a stale target vel
        t._last_target_vel = _rand_vec(rng, 2000.0)
        dt = 1.0 / 60.0
    elif mode == 12:                      # cross-region: dist_sq_gu
        target = w.tgt_a2
        o = w.src_a1.GetWorldLocation()
        a = ANCHORS["K3GeoA2"][1]
        # Near the source once shifted into A1 (p + off, off = a2 - a1).
        target.SetTranslateXYZ(o.x - a[0] + rng.uniform(-150.0, 150.0),
                               o.y - a[1] + rng.uniform(-150.0, 150.0),
                               o.z - a[2] + rng.uniform(-150.0, 150.0))
        tset = rng.choice((a1, a2))
    elif mode == 13:                      # the source in another frame
        src = w.src_b
        if rng.random() < 0.5:            # out of range: off None still asks
            src.SetTranslateXYZ(1e6, 0.0, 0.0)
    elif mode == 14:                      # no source: visible
        src = None
    elif mode == 15:                      # initial 0 / NaN, and a snap
        t._guidance_initial = rng.choice((0.0, -1.0, NAN, 1e-10))
        t.SetMaxAngularAccel(rng.choice((1e6, 0.0)))
    t._source_ship = src
    t._target_ship = target if (i % 37) else None
    t._containing_set = tset
    return t, dt, mode


def test_guide_matches(world):
    w, rng = world, random.Random(SEED + 4)
    seen = {}
    asked = 0
    _compare_guide.attributed = 0
    for i in range(CASES):
        t, dt, mode = _setup_guide_case(w, rng, i)
        writes, did_ask = _compare_guide(t, dt)
        asked += did_ask
        names = tuple(n for n, _ in writes)
        seen.setdefault(mode, set()).add(names)
    # Every branch the modes aim at really ran.
    full = GUIDE_FIELDS
    assert full in seen[0] and full in seen[12] and full in seen[14]
    assert ("_velocity",) in seen[3]                    # frozen last-seen
    assert () in seen[4] and () in seen[5] and () in seen[6] and () in seen[7]
    assert GUIDE_FIELDS[:2] in seen[8]                  # dist < 1e-6
    print("steer ASKs %d, native attributions %d"
          % (asked, _compare_guide.attributed))
    # No steer-point ASK left: a picked spot is a plain body point with no
    # bake to miss (fire control native only, M5; the "unbaked" ASKs went
    # with it), and every mount here is one the mirror can attribute.
    assert asked == 0
    assert _compare_guide.attributed > 50               # native mounts
    # The source in another frame: can_detect is still asked, both ways.
    assert full in seen[13] and any(n != full for n in seen[13])
    # The cross-region call sees the target (its raw distance is ~1000 GU).
    assert full in seen[12]


def test_guide_missing_frame_asks_first(world):
    """A set with no frame entry: ASK frame(set) before anything is decided
    (no can_detect has run), then the same answer as Python."""
    w = world
    t = w.torp
    t._source_ship = w.src_a1
    t._target_ship = w.tgt_a2
    t._containing_set = w.sets["K3GeoA1"]
    w.tgt_a2.SetTranslateXYZ(-1000.0, 20.0, 0.0)
    t.SetTranslateXYZ(0.0, 0.0, 0.0)
    t._velocity = TGPoint3(0.0, 10.0, 0.0)
    a2 = _slot(w.sets["K3GeoA2"])
    table = [e for e in nc._step_frames(
        [_slot(s) for s in w.sets.values()], {}) if e[0] != a2]
    _h.combat_step_frames(table)
    drift, occ = _clocks()
    assert _h.combat_test_guide_torpedo(_row(t), 1.0 / 60.0, False, drift,
                                        occ) == ("frame", a2)
    _send_frames(w)
    writes, _ = _compare_guide(t, 1.0 / 60.0)
    assert [n for n, _ in writes] == list(GUIDE_FIELDS)


def test_guide_unvouched_inputs_ask_guide(world):
    """A -2 target or source, a target without a real IsDead, or an
    unrepresentable row field: Python's _guide whole, never a silent
    'visible'."""
    w = world
    t = w.torp
    t._source_ship = w.src_a1
    t._target_ship = w.tgt_a1
    t._containing_set = w.sets["K3GeoA1"]
    t._velocity = TGPoint3(0.0, 10.0, 0.0)
    drift, occ = _clocks()

    def ask():
        return _h.combat_test_guide_torpedo(_row(t), 1.0 / 60.0, False,
                                            drift, occ)[0]

    assert ask() == "done"
    t._source_ship = object()                 # a source the mirror cannot name
    assert ask() == "guide"
    t._source_ship = w.src_a1
    t._last_seen_target_pos = (1.0, 2.0, 3.0)  # neither None nor a TGPoint3
    assert ask() == "guide"
    t._last_seen_target_pos = None
    _h.combat_set_i(_slot(w.tgt_a1), nc._fid("has_real_is_dead"), 0)
    assert ask() == "guide"
    _h.combat_set_i(_slot(w.tgt_a1), nc._fid("has_real_is_dead"), 1)
    assert ask() == "done"
    t._target_ship = object()
    assert ask() == "guide"


def test_guide_memo_only_for_same_set(world):
    """map A4: the same-set call reads the step memo; the cross-region one
    (dist_sq_gu) never does. Seed the memo with a now-stale 'visible', move
    the target out of sensor range, and compare inside a combat step."""
    w = world
    t = w.torp
    t._source_ship = w.src_a1
    t._velocity = TGPoint3(0.0, 10.0, 0.0)
    t.SetTranslateXYZ(0.0, 0.0, 0.0)
    w.src_a1.SetTranslateXYZ(0.0, 0.0, 0.0)
    a2 = ANCHORS["K3GeoA2"][1]
    cases = (
        (w.tgt_a1, w.sets["K3GeoA1"], (0.0, 50.0, 0.0), (0.0, 1e6, 0.0)),
        (w.tgt_a2, w.sets["K3GeoA1"], (-a2[0], 50.0 - a2[1], -a2[2]),
         (-a2[0], 1e6, -a2[2])),
    )
    results = []
    for target, tset, near, far in cases:
        t._target_ship = target
        t._containing_set = tset
        arms = []
        for arm in ("native", "python"):
            with step_memo.combat_step():
                _h.combat_latch_reset()
                step_memo.forget()
                target.SetTranslateXYZ(*near)
                sensor_detection.can_detect(w.src_a1, target)   # seeds memo
                target.SetTranslateXYZ(*far)
                if arm == "native":
                    st, writes, _, _, _ = _native_guide(t, 1.0 / 60.0,
                                                     use_memo=True)
                    assert st == "done"
                    arms.append(writes)
                else:
                    arms.append(_python_guide(t, 1.0 / 60.0)[0])
        assert arms[0] == arms[1]
        results.append(tuple(n for n, _ in arms[0]))
    # Same set: the memo's stale 'visible' steered at the far target.
    assert results[0] == GUIDE_FIELDS
    # Cross-region: a fresh, out-of-range answer -- no new last-seen point.
    assert "_last_seen_target_pos" not in results[1]


def test_posed_target_picked_spot_steers_at_body_point(world):
    """An attributed aim offset no mount claims (a picked spot) on a target
    posed off its NIF pose: guidance steers natively at the offset as a
    plain body point (fire control native only, M5) and matches Python, at
    every pose the part takes in flight -- no ASK, no bake. (Was
    test_posed_target_picked_spot_steers_at_its_bake.)"""
    from engine.appc import articulation, part_pose
    w = world
    t = w.torp
    target = w.tgt_a1
    t._source_ship = w.src_a1
    t._target_ship = target
    t._containing_set = w.sets["K3GeoA1"]
    t._velocity = TGPoint3(0.0, 10.0, 0.0)
    pick = (0.5, 1.0, -0.25)
    t.SetTargetOffset(TGPoint3(*pick))
    projectiles._steer_point(t, target, (0.0, 0.0, 0.0))     # attributed
    assert t._mount_key[4] is None
    try:
        drift, occ = _clocks()
        for deg in (15.0, 40.0, -30.0):
            hinge = part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                                         deg)
            articulation.force_part_pose(target, "TestPart", hinge)
            want = subsystems.body_point_world(target, pick)
            got = _h.combat_test_steer_point(
                _slot(target), pick, -1, (0.0, 0.0, 0.0))
            assert _hx(got) == _hx(want), deg
            assert _hx(projectiles._steer_point(
                t, target, (0.0, 0.0, 0.0))) == _hx(want), deg
            _reset_sensors()
            r = _h.combat_test_guide_torpedo(_row(t), 1.0 / 60.0, False,
                                             drift, occ)
            assert r[0] == "done", (deg, r)
            writes, asked = _compare_guide(t, 1.0 / 60.0)
            assert not asked and [n for n, _ in writes] == list(GUIDE_FIELDS)
        # Without an offset the posed target is answered natively.
        t.SetTargetOffset(None)
        _reset_sensors()
        r = _h.combat_test_guide_torpedo(_row(t), 1.0 / 60.0, False, drift,
                                         occ)
        assert r[0] == "done"
        writes, asked = _compare_guide(t, 1.0 / 60.0)
        assert not asked
    finally:
        articulation.force_pose(target, None)
