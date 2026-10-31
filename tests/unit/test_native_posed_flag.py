"""A rigged ship at its natural pose runs native (native combat phase 1b,
Task 6b; engine/appc/native_combat.py `_posed_flag`).

Mark's convention: a hull's natural mesh pose IS its red-alert pose. The
Bird of Prey authors "red" as the NIF pose (identity), and an NPC with a
target is in "red" (`articulation.state_for`), so a Bird of Prey in a fight
has every part at identity and its mounts are exactly the unrigged mounts.

The mirror flag K1 and the native geometry read, `has_posed_parts`, is
therefore 1 only while some part's CURRENT pose is off identity, by the very
test `articulation.part_transform_point` uses to skip the transform
(`part_pose.is_identity`). These tests pin:

* the exactness the narrower flag relies on: for a rigged ship at identity
  the Python mount and target-offset transforms are the unrigged ones, bit
  for bit (float.hex(), signed zeros included), so the native identity path
  answers them;
* the flag at identity (0), through a transition (1 from the first tick a
  part leaves identity, 0 only when every part is back), and through every
  pose writer: tick_ship's in-place writes, force_pose, force_part_pose,
  force_state_poses; the mirror audit clean after each.
"""
import importlib
import random
import sys

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_test_subsystem_world_position"),
    reason="native combat bindings not built")

from engine.appc import articulated_part, articulation, part_pose  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import subsystems as ss  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
DT = 1.0 / 60.0
SEED = 20261031


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
    native combat on. The Bird of Prey has the Galaxy as its target: an NPC
    with a target is in "red"."""
    nc.configure(ON)
    assert nc.enabled()
    pset = App.SetClass_Create()
    App.g_kSetManager.AddSet(pset, "native_posed_flag")
    bop = _ship("BoP1", "birdofprey", "ships.BirdOfPrey")
    galaxy = _ship("Galaxy1", "galaxy", "ships.Galaxy", at=(0.0, 300.0, 0.0))
    for ship in (bop, galaxy):
        pset.AddObjectToSet(ship, ship.GetName())
    bop.SetTarget(galaxy)
    # Guard: the rig is real, red is its NIF pose and cruise moves it.
    parts = articulation.parts_for_ship(bop)
    assert [p.GetName() for p in parts] == ["left wing", "left wing01"]
    for p in parts:
        assert articulation.target_pose(p, "red") == part_pose.IDENTITY
        assert not part_pose.is_identity(articulation.target_pose(p, "cruise"))
    assert articulation.state_for(bop) == "red"
    try:
        yield bop, galaxy
    finally:
        App.g_kSetManager.DeleteSet("native_posed_flag")


def _flag(ship):
    return _h.combat_dump(ship.__dict__["_nslot"])["has_posed_parts"]


def _off_identity(ship):
    """Whether any of `ship`'s current poses is off the NIF pose."""
    poses = ship.__dict__.get("_articulation_poses") or {}
    return int(any(not part_pose.is_identity(p) for p in poses.values()))


def _audit_clean():
    nc.audit_mirror()
    assert nc.audit_failures() == []


def _hx(p):
    if isinstance(p, TGPoint3):
        return (p.x.hex(), p.y.hex(), p.z.hex())
    return tuple(float(c).hex() for c in p)


def _slot(obj):
    return obj.__dict__["_nslot"] if obj is not None else -1


def _rand_rot(rng):
    m = TGMatrix3()
    m.set_from_tuple([rng.uniform(-2.0, 2.0) for _ in range(9)])
    return m


def _weapons(ship):
    out = []
    for g in (ship.GetPulseWeaponSystem(), ship.GetTorpedoSystem(),
              ship.GetTractorBeamSystem(), ship.GetPhaserSystem()):
        if g is not None:
            out += [g.GetWeapon(i) for i in range(g.GetNumWeapons())]
    return out


# ── The flag at the NIF pose ─────────────────────────────────────────────────

def test_rigged_ship_at_identity_reads_unposed(scene):
    bop, galaxy = scene
    assert articulation.posed_part_names(bop)        # it IS rigged
    assert _flag(bop) == 0
    for _ in range(30):                               # red: nothing moves
        articulation.tick_ship(bop, DT)
        assert _flag(bop) == 0
    assert all(part_pose.is_identity(p)
               for p in bop._articulation_poses.values())
    assert _flag(galaxy) == 0
    _audit_clean()


# ── Exactness: identity is the unrigged path, bit for bit ────────────────────

def test_identity_mounts_are_exact(scene):
    """Python's mount transform at identity returns the authored point
    itself (part_transform_point skips the transform), so the native
    identity path (ship_pos + R . local) gives the same floats. Wing-mounted
    cannons, the body torpedo, and a mount of signed zeros."""
    bop, galaxy = scene
    rng = random.Random(SEED)
    leaves = _weapons(bop)
    assert {articulation._live_part(bop, None, _hx_point(w), True, None)
            for w in leaves} >= {"left wing", "left wing01"}
    zero = leaves[0]
    for i in range(600):
        bop.SetTranslateXYZ(*(rng.uniform(-900.0, 900.0) for _ in range(3)))
        bop.SetMatrixRotation(_rand_rot(rng) if i % 4 else TGMatrix3())
        sub = rng.choice(leaves)
        if sub is zero and i % 2:
            p = sub.GetPosition()
            sub._position = TGPoint3(-0.0, p.y, -0.0)
        point = _hx_point(sub)
        assert articulation.part_transform_point(
            bop, point, prop=None) is point
        arg = rng.choice((None, bop))
        want = ss.subsystem_world_position(sub, arg)
        got = _h.combat_test_subsystem_world_position(
            _slot(sub), _slot(arg), False)
        assert _hx(got) == _hx(want)
    assert _flag(bop) == 0


def _hx_point(sub):
    p = sub.GetPosition()
    return (p.x, p.y, p.z)


def test_identity_target_offset_is_exact(scene):
    """target_offset_world on a rigged target at identity: subsystem locks
    (authored mounts, on a wing and on the body), arbitrary picks, signed
    zeros and scales, native == Python by float.hex()."""
    bop, galaxy = scene
    rng = random.Random(SEED + 1)
    mounts = [s.GetPosition() for s in _weapons(bop)]
    for i in range(600):
        bop.SetTranslateXYZ(*(rng.uniform(-900.0, 900.0) for _ in range(3)))
        bop.SetMatrixRotation(_rand_rot(rng) if i % 4 else TGMatrix3())
        bop.SetScale(rng.choice((1.0, 3.0, rng.uniform(0.0, 6.0))))
        roll = i % 3
        if roll == 0:
            offset = rng.choice(mounts)
        elif roll == 1:
            offset = TGPoint3(*(rng.uniform(-2.0, 2.0) for _ in range(3)))
        else:
            offset = TGPoint3(-0.0, rng.uniform(-1.0, 1.0), -0.0)
        want = ss.target_offset_world(bop, offset)
        got = _h.combat_test_target_offset_world(
            _slot(bop), (offset.x, offset.y, offset.z))
        assert _hx(got) == _hx(want)


# ── The flag follows every pose writer ───────────────────────────────────────

def test_flag_follows_transition(scene):
    """red (identity) -> cruise (wings swung) -> red, through tick_ship's
    in-place writes: 1 from the first tick a part leaves identity, 0 only
    once every part is back."""
    bop, galaxy = scene
    articulation.tick_ship(bop, DT)
    assert _flag(bop) == 0

    bop.SetTarget(None)                          # cruise: the wings swing up
    assert articulation.state_for(bop) == "cruise"
    articulation.tick_ship(bop, DT)
    assert _off_identity(bop) == 1
    assert _flag(bop) == 1
    _audit_clean()
    for _ in range(200):                         # settles at cruise
        articulation.tick_ship(bop, DT)
        assert _flag(bop) == 1
    assert not bop._articulation_transitions
    _audit_clean()

    bop.SetTarget(galaxy)                        # red: back to the NIF pose
    flags = []
    for _ in range(200):
        articulation.tick_ship(bop, DT)
        flags.append(_flag(bop))
        assert flags[-1] == _off_identity(bop)
    first0 = flags.index(0)
    assert first0 > 0
    assert flags == [1] * first0 + [0] * (len(flags) - first0)
    assert all(p == part_pose.IDENTITY
               for p in bop._articulation_poses.values())
    _audit_clean()


def test_one_part_off_identity_is_enough(scene):
    """Mid-transition with one wing home and one still swung reads 1."""
    bop, galaxy = scene
    left, right = articulation.parts_for_ship(bop)
    articulation.force_state_poses(
        bop, {"left wing01": right.pose_for("cruise")})
    assert _flag(bop) == 1
    _audit_clean()
    articulation.tick_ship(bop, DT)              # red: left stays home
    assert bop._articulation_poses["left wing"] == part_pose.IDENTITY
    assert _flag(bop) == 1


def test_flag_follows_the_force_writers(scene):
    bop, galaxy = scene
    hinge = part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0)
    steps = (
        (lambda: articulation.force_pose(bop, "cruise"), 1),
        (lambda: articulation.force_pose(bop, None), 0),
        (lambda: articulation.force_pose(bop, "yellow"), 1),
        (lambda: articulation.force_pose(bop, "red"), 0),
        (lambda: articulation.force_part_pose(bop, "left wing", hinge), 1),
        (lambda: articulation.force_part_pose(
            bop, "left wing", part_pose.IDENTITY), 0),
        # A part no rig names (the SPV posing the head by name).
        (lambda: articulation.force_part_pose(bop, "head", hinge), 1),
        (lambda: articulation.force_part_pose(
            bop, "head", part_pose.IDENTITY), 0),
        (lambda: articulation.force_state_poses(
            bop, {"left wing": hinge}), 1),
        (lambda: articulation.force_state_poses(bop, {}), 0),
        # The unrigged Galaxy, posed by name only.
        (lambda: articulation.force_part_pose(
            galaxy, "TestPart", part_pose.IDENTITY), 0),
        (lambda: articulation.force_part_pose(galaxy, "TestPart", hinge), 1),
        (lambda: articulation.force_pose(galaxy, None), 0),
    )
    for write, want in steps:
        write()
        for ship in (bop, galaxy):
            assert _flag(ship) == _off_identity(ship)
        assert max(_flag(bop), _flag(galaxy)) == want
        _audit_clean()


def test_a_hull_that_authors_a_non_identity_red_stays_posed(scene):
    """A rig whose red pose is not the NIF pose (registered in-test) reads 1
    once its parts reach red, and keeps reading 1 there: it runs through
    Python, just not sped up."""
    bop, galaxy = scene
    saved = dict(articulated_part._BY_LEAF)
    try:
        part = articulated_part.ArticulatedPartProperty("fin")
        part.SetAnchor(0.0, 0.0, 0.0)
        part.SetTransitionSeconds(0.5)
        part.SetStatePose("red", 0.0, 0.0, 0.1, 0.0, 0.0, 10.0)
        galaxy._articulation_leaf = "posed_red_leaf"
        articulated_part.restore({"posed_red_leaf": (part,)})
        galaxy.SetTarget(bop)
        assert articulation.state_for(galaxy) == "red"
        articulation.tick_ship(galaxy, DT)
        assert _flag(galaxy) == 1
        for _ in range(60):
            articulation.tick_ship(galaxy, DT)
        assert not galaxy._articulation_transitions
        assert _flag(galaxy) == 1
        _audit_clean()
    finally:
        articulated_part.restore(saved)
