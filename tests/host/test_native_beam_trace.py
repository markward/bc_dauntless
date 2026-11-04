"""The native hull trace vs the Python it ports (native combat phase 2 / K2,
Task 3; native/src/combat/src/beam_trace.cc).

`combat._resolve_hit_point` + `host_io.ray_trace_mesh` (map 1.4, F17, F18)
against `combat_test_resolve_hit_point`, which runs the kernel's
`resolve_hit_point` through the trace hooks the host bindings INSTALL: the
renderer's own compiled `ray_trace_instance_linear` on `g_world`, reached
through the same C++ function the `ray_trace_mesh` binding calls.

A headless host with a real Galaxy instance (tests/host/test_mesh_ray_trace.py)
and real mirrored ships (native combat on). Every float compared BY
float.hex(); seeded random.Random, 3,000 rays per differential.
"""
import hashlib
import importlib
import math
import os
import random
import struct
import sys

import pytest

import App
from tests.helpers import bc_assets

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "ray_trace_mesh"),
    reason="host bindings not built")

from engine.appc import combat  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.systems import frames  # noqa: E402

GALAXY_NIF = bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = bc_assets.GAME_ROOT / "data" / "Models" / "SharedTextures" / "FedShips" / "High"

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
SEED = 20261031
CASES = 3000
NAN = float("nan")
INF = float("inf")
# NIF units -> GU of the instance at ship scale 1: the Galaxy NIF spans a few
# hundred units, so this draws it a few GU across, the size of its sphere.
MODEL_SCALE = 0.01
RADIUS = 3.0


def _need_native():
    if not hasattr(_h, "combat_test_resolve_hit_point"):
        pytest.fail("combat_test_resolve_hit_point is not built")


# ── the scene ────────────────────────────────────────────────────────────────

class Scene:
    pass


def _load_hardpoint(ship, name):
    mod_name = "ships.Hardpoints." + name
    App.g_kModelPropertyManager.ClearLocalTemplates()
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    sys.modules[mod_name].LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()


@pytest.fixture
def host(monkeypatch):
    """Headless host + one Galaxy model; yields (model handle, live iid).
    The headless switch is set for this test only: combat_stress reads it
    (a headless run seeds nominal hull radii), so leaving it set changed
    every later fight in the process
    (tests/helpers/k1_fight.py)."""
    if not GALAXY_NIF.is_file():
        pytest.skip("BC asset not available")
    if not GALAXY_TEX.is_dir():
        pytest.skip("BC texture dir not available")
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    try:
        _h.init(256, 256, "native-beam-trace-tests")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        model = _h.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        iid = _h.create_instance(model)
        yield model, iid
    finally:
        _h.shutdown()


@pytest.fixture
def scene(host):
    model, iid = host
    nc.reset()
    nc.configure(ON)
    assert nc.enabled()
    s = Scene()
    s.model, s.iid = model, iid
    stale = _h.create_instance(model)
    _h.destroy_instance(stale)
    s.stale = stale
    s.set = App.SetClass_Create()
    App.g_kSetManager.AddSet(s.set, "native_beam_trace")
    s.ship = App.ShipClass_Create("Target1")
    _load_hardpoint(s.ship, "galaxy")
    s.set.AddObjectToSet(s.ship, s.ship.GetName())
    try:
        yield s
    finally:
        App.g_kSetManager.DeleteSet("native_beam_trace")
        nc.reset()
        App.g_kModelPropertyManager.ClearLocalTemplates()


def _slot(obj):
    return obj.__dict__["_nslot"]


def _hx(p):
    if p is None:
        return None
    if isinstance(p, TGPoint3):
        return (p.x.hex(), p.y.hex(), p.z.hex())
    return tuple(float(c).hex() for c in p)


def _xyz(p):
    return (p.x, p.y, p.z)


def _rand_rot(rng):
    w, x, y, z = (rng.gauss(0, 1) for _ in range(4))
    n = math.sqrt(w * w + x * x + y * y + z * z)
    w, x, y, z = w / n, x / n, y / n, z / n
    return (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
            2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
            2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y))


def _instance_mat(rot, scale, t):
    r = rot
    return [r[0] * scale, r[1] * scale, r[2] * scale, t[0],
            r[3] * scale, r[4] * scale, r[5] * scale, t[1],
            r[6] * scale, r[7] * scale, r[8] * scale, t[2],
            0.0, 0.0, 0.0, 1.0]


def _pose(rng, s, view_shift=None, spread=2000.0):
    """A random ship pose, its instance drawn where the ship is (moved into
    view coordinates by `view_shift`). Returns the ship's world position."""
    pos = tuple(rng.uniform(-spread, spread) for _ in range(3))
    rot = _rand_rot(rng)
    scale = rng.choice((1.0, 1.0, 2.5, 0.5))
    s.ship.SetTranslateXYZ(*pos)
    m = TGMatrix3()
    m.set_from_tuple(rot)
    s.ship.SetMatrixRotation(m)
    s.ship.SetScale(scale)
    s.ship._radius = RADIUS
    t = pos if view_shift is None else tuple(
        p + o for p, o in zip(pos, view_shift))
    _h.set_world_transform(s.iid, _instance_mat(rot, MODEL_SCALE * scale, t))
    return pos


def _ray(rng, centre):
    """(origin, direction or None, max_dist) the way cb.phasers forms them,
    plus the edges: inside the sphere, a zero or tiny direction, bad reach."""
    reach = rng.choice((rng.uniform(0.0, 4.0), rng.uniform(0.0, 12.0),
                        rng.uniform(4.0, 40.0)))
    u = [rng.gauss(0, 1) for _ in range(3)]
    n = math.sqrt(sum(c * c for c in u)) or 1.0
    origin = TGPoint3(*(c + reach * x / n for c, x in zip(centre, u)))
    aim = TGPoint3(*(c + rng.uniform(-4.0, 4.0) for c in centre))
    dx, dy, dz = aim.x - origin.x, aim.y - origin.y, aim.z - origin.z
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    kind = rng.random()
    if kind < 0.02:
        d = None
    elif kind < 0.04:
        d = TGPoint3(0.0, 0.0, 0.0)
    elif kind < 0.05:
        d = TGPoint3(1e-12, 0.0, 0.0)
    elif dist <= 1e-6:
        d = None
    else:
        d = TGPoint3(dx / dist, dy / dist, dz / dist)
    max_dist = rng.choice((dist * 1.5,) * 12 + (
        NAN, INF, 0.0, -1.0, 1e300, rng.uniform(0.0, 2.0)))
    return origin, d, max_dist, aim


def _python(ship_instances, ship, origin, d, max_dist, fallback):
    point, normal = combat._resolve_hit_point(
        ship_instances, ship, origin, d, max_dist, fallback)
    if point is origin:
        tier = "origin"
    elif point is fallback:
        tier = "fallback"
    elif normal is not None:
        tier = "mesh"
    else:
        tier = "sphere"
    return _hx(point), _hx(normal), tier


def _native(ship, iid, origin, d, max_dist, fallback, off):
    point, normal, tier = _h.combat_test_resolve_hit_point(
        _slot(ship), iid, _xyz(origin), None if d is None else _xyz(d),
        max_dist, _xyz(fallback), off)
    return _hx(point), _hx(normal), tier


# ── the differential ─────────────────────────────────────────────────────────

def test_trace_matches_python(scene):
    _need_native()
    s, rng = scene, random.Random(SEED)
    assert frames.view_offset(frames.containing_set(s.ship)) is None
    tiers = {}
    for i in range(CASES):
        centre = _pose(rng, s)
        origin, d, max_dist, aim = _ray(rng, centre)
        want = _python({s.ship: s.iid}, s.ship, origin, d, max_dist, aim)
        got = _native(s.ship, s.iid, origin, d, max_dist, aim, None)
        assert got == want, (i, want, got)
        tiers[want[2]] = tiers.get(want[2], 0) + 1
    # The draw reaches every tier the trace has, each many times.
    assert all(tiers.get(t, 0) >= 100 for t in
               ("mesh", "sphere", "fallback", "origin")), tiers


def test_stale_and_absent_instance_outcomes(scene):
    """map 8.3.6: no iid -> the fallback point, NO sphere tier; a stale iid
    -> the trace throws -> the sphere tier; a live iid that misses -> the
    sphere tier."""
    _need_native()
    s, rng = scene, random.Random(SEED + 1)
    seen = {"absent": set(), "stale": set()}
    for i in range(CASES // 3):
        centre = _pose(rng, s)
        origin, d, max_dist, aim = _ray(rng, centre)
        for label, table, iid in (("absent", None, None),
                                  ("absent", {}, None),
                                  ("stale", {s.ship: s.stale}, s.stale)):
            want = _python(table, s.ship, origin, d, max_dist, aim)
            got = _native(s.ship, iid, origin, d, max_dist, aim, None)
            assert got == want, (i, label, want, got)
            seen[label].add(got[2])
    assert seen["absent"] == {"fallback"}
    assert {"sphere", "origin", "fallback"} <= seen["stale"]
    assert "mesh" not in seen["stale"]

    # The same ray, three outcomes: inside nothing, aimed at the centre.
    s.ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    s.ship.SetScale(1.0)
    s.ship._radius = RADIUS
    _h.set_world_transform(s.iid, _instance_mat(
        (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0), MODEL_SCALE,
        (0.0, 0.0, 0.0)))
    o, d, fb = (TGPoint3(0.0, -20.0, 0.0), TGPoint3(0.0, 1.0, 0.0),
                TGPoint3(0.0, 0.0, 0.0))
    assert _native(s.ship, None, o, d, 30.0, fb, None)[2] == "fallback"
    assert _native(s.ship, s.stale, o, d, 30.0, fb, None)[2] == "sphere"
    assert _native(s.ship, s.iid, o, d, 30.0, fb, None)[2] == "mesh"
    with pytest.raises(RuntimeError):
        _h.ray_trace_mesh(s.stale, (0.0, -20.0, 0.0), (0.0, 1.0, 0.0), 30.0)


def test_scaled_ship_matches(scene):
    _need_native()
    s, rng = scene, random.Random(SEED + 2)
    tiers = {}
    for i in range(CASES // 3):
        centre = _pose(rng, s)
        # The sphere's scale (world_radius's rules: <= 0 / NaN / inf -> 1),
        # apart from the drawn instance's (_pose: 0.5, 1 or 2.5).
        s.ship.SetScale(rng.choice((3.0, 8.5, 0.25, 0.0, -2.0, NAN, INF)))
        origin, d, max_dist, aim = _ray(rng, centre)
        want = _python({s.ship: s.iid}, s.ship, origin, d, max_dist, aim)
        got = _native(s.ship, s.iid, origin, d, max_dist, aim, None)
        assert got == want, (i, want, got)
        tiers[want[2]] = tiers.get(want[2], 0) + 1
    assert all(tiers.get(t, 0) >= 30 for t in
               ("mesh", "sphere", "fallback", "origin")), tiers


def test_view_shift_matches(scene, monkeypatch):
    """frames.shifted (FR:166): the ray goes into view coordinates by +off,
    the mesh hit comes back by -1.0 * off; None, (0, 0, 0) and (-0.0, ...)
    are no shift at all (a tuple compare)."""
    _need_native()
    s, rng = scene, random.Random(SEED + 3)
    offs = [None, (0.0, 0.0, 0.0), (-0.0, 0.0, -0.0)]
    current = {}
    monkeypatch.setattr(frames, "view_offset", lambda pSet: current["off"])
    tiers = {}
    for i in range(CASES):
        k = rng.random()
        if k < 0.15:
            off = rng.choice(offs)
        elif k < 0.17:
            off = (NAN, 0.0, 0.0)
        elif k < 0.6:
            off = tuple(rng.uniform(-500000.0, 500000.0) for _ in range(3))
        else:
            off = tuple(rng.uniform(-50.0, 50.0) for _ in range(3))
        current["off"] = off
        shift = None if off is None or off == (0.0, 0.0, 0.0) else off
        centre = _pose(rng, s, view_shift=shift)
        origin, d, max_dist, aim = _ray(rng, centre)
        want = _python({s.ship: s.iid}, s.ship, origin, d, max_dist, aim)
        got = _native(s.ship, s.iid, origin, d, max_dist, aim, off)
        assert got == want, (i, off, want, got)
        tiers[want[2]] = tiers.get(want[2], 0) + 1
    assert tiers.get("mesh", 0) >= 300, tiers


def test_view_shift_of_a_real_sibling_region(scene):
    """The offset frames computes for a target in Ona2 viewed from Ona1."""
    _need_native()
    from tests.helpers.mapped_regions import load_region
    s, rng = scene, random.Random(SEED + 4)
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    try:
        App.g_kSetManager.MakeRenderedSet("Ona1")
        s.set.RemoveObjectFromSet(s.ship.GetName())
        ona2.AddObjectToSet(s.ship, s.ship.GetName())
        off = frames.view_offset(frames.containing_set(s.ship))
        assert off is not None and off != (0.0, 0.0, 0.0)
        assert frames.containing_set(s.ship) is ona2 and ona1 is not ona2
        meshes = 0
        for i in range(500):
            centre = _pose(rng, s, view_shift=off)
            origin, d, max_dist, aim = _ray(rng, centre)
            want = _python({s.ship: s.iid}, s.ship, origin, d, max_dist, aim)
            got = _native(s.ship, s.iid, origin, d, max_dist, aim, off)
            assert got == want, (i, want, got)
            meshes += want[2] == "mesh"
        assert meshes >= 50
    finally:
        ona2.RemoveObjectFromSet(s.ship.GetName())
        App.g_kSetManager.ClearRenderedSet()
        App.g_kSetManager.DeleteSet("Ona1")
        App.g_kSetManager.DeleteSet("Ona2")


def test_trace_uses_the_sim_pose_when_a_source_is_set(scene):
    """Phase 3a: with the ship's sim source set the way production sets it
    (host_loop._mark_sim_source), the instance DRAWN 2000 GU off its store
    pose, Python and the K2/K3 hooks both trace the SIM hull, and agree."""
    _need_native()
    from engine import host_loop
    s, rng = scene, random.Random(SEED + 5)
    _c, half = _h.model_aabb(s.model)
    reach = math.sqrt(sum(h * h for h in half)) + math.sqrt(
        sum(c * c for c in _c))
    meshes = 0
    try:
        for i in range(500):
            centre = _pose(rng, s, view_shift=(2000.0, 0.0, 0.0))
            host_loop._mark_sim_source(host_loop.MissionSession("t"), s.ship,
                                       s.iid, MODEL_SCALE)
            origin, d, max_dist, aim = _ray(rng, centre)
            want = _python({s.ship: s.iid}, s.ship, origin, d, max_dist, aim)
            got = _native(s.ship, s.iid, origin, d, max_dist, aim, None)
            assert got == want, (i, want, got)
            if want[2] == "mesh":
                meshes += 1
                p = [float.fromhex(c) for c in want[0]]
                hull = reach * MODEL_SCALE * s.ship.GetScale()
                assert math.dist(p, centre) <= hull + 1e-6, (i, p, centre)
        assert meshes >= 50
    finally:
        _h.set_instance_sim_source(s.iid, -1, 0, 1.0, (0.0, 0.0, 0.0))


# ── pybind's narrowing, reproduced ───────────────────────────────────────────

def _bits(x):
    return struct.pack("<f", x) if math.isfinite(x) else repr(x)


def test_narrowing_is_pybinds_for_every_value_class(scene):
    """The kernel narrows each double as pybind narrows a float argument
    ((float)PyFloat_AsDouble): round to nearest even, inf for overflow,
    NaN stays NaN, signed zeros and subnormals kept."""
    _need_native()
    fmax = struct.unpack("<f", b"\xff\xff\x7f\x7f")[0]
    one_ulp_f = 2.0 ** -23
    values = [0.0, -0.0, 1.0, -1.0, NAN, -NAN, INF, -INF, 1e300, -1e300,
              1e-300, -1e-300, 1e-45, 1.4e-45, 7e-46, 1e-40, fmax,
              fmax * (1 + 2 ** -25), fmax * (1 + 2 ** -24), 3.4028236e38,
              1.0 + one_ulp_f / 2, 1.0 + 3 * one_ulp_f / 2,
              -(1.0 + one_ulp_f / 2), 0.1, 450000.3, 1e6 + 0.3]
    rng = random.Random(SEED + 5)
    values += [rng.uniform(-1e7, 1e7) for _ in range(500)]
    values += [struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))[0]
               for _ in range(500)]
    for v in values:
        want = _h.combat_test_pybind_narrow(v)
        got = _h.combat_test_narrow(v)
        if math.isnan(want):
            assert math.isnan(got), v
            continue
        assert struct.pack("<d", got) == struct.pack("<d", want), (v, got, want)


# ── the binding, unchanged by the refactor ───────────────────────────────────

# sha256 of _binding_transcript() from the PRE-refactor binary (HEAD
# cc8fdd4f0, Debug build, this Galaxy.nif and its mesh fix). The digest pins
# the ray_trace_mesh binding's every output bit, None and raise across the
# extraction of its body into trace_instance_for_python. It is only
# meaningful against the inputs it was recorded on, so the test SKIPS on
# another build type, another Galaxy.nif or another mesh fix for it
# (_golden_env_mismatch). A legitimate change to any of those inputs, or to
# the binding, needs a re-record (RERECORD).
BINDING_GOLDEN = "565fcc8a1be26dee3afd78c5a5e75fe0bb078ea401ab65d86213268d2374e35c"
BINDING_GOLDEN_HITS = 520
# What it was recorded on: CMAKE_BUILD_TYPE of the build the bindings came
# from, the Galaxy.nif's FNV-1a 64 content hash (the mesh-fix key), and the
# sha256 of native/assets/mesh_fixes/<that hash>.json (None: no fix file).
BINDING_GOLDEN_BUILD_TYPE = "Debug"
BINDING_GOLDEN_GALAXY_FNV = "996af4fb0d158c5b"
BINDING_GOLDEN_FIX_SHA = (
    "b4f175b47051e62a6302c1b487fd3a3211f1f621676b97fc8344c3f039a75558")
RERECORD = (
    "re-record: DAUNTLESS_RECORD_TRACE_GOLDEN=1 uv run pytest "
    "tests/host/test_native_beam_trace.py -k binding_unchanged -s, then "
    "paste the printed BINDING_GOLDEN* values over the ones in this file -- "
    "only after confirming the change is legitimate (on the binary BEFORE "
    "a binding change, the new one must still match)")


def _golden_env() -> dict:
    """The recorded inputs as they are now (see BINDING_GOLDEN_*)."""
    from tools import gen_mesh_fixes
    build_type = None
    cache = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(_h.__file__))), "CMakeCache.txt")
    if os.path.isfile(cache):
        with open(cache, encoding="utf-8") as f:
            for line in f:
                if line.startswith("CMAKE_BUILD_TYPE:"):
                    build_type = line.split("=", 1)[1].strip()
    fnv = gen_mesh_fixes.fnv1a64_hex(GALAXY_NIF.read_bytes())
    fix = os.path.join(str(bc_assets.PROJECT_ROOT), "native", "assets",
                       "mesh_fixes", fnv + ".json")
    sha = None
    if os.path.isfile(fix):
        with open(fix, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
    return {"build_type": build_type, "galaxy_fnv": fnv, "fix_sha": sha}


def _golden_env_mismatch(env) -> str:
    """Why the recorded digest does not apply to `env`, or ""."""
    want = {"build_type": BINDING_GOLDEN_BUILD_TYPE,
            "galaxy_fnv": BINDING_GOLDEN_GALAXY_FNV,
            "fix_sha": BINDING_GOLDEN_FIX_SHA}
    diff = ["%s %r (recorded %r)" % (k, env[k], want[k])
            for k in want if env[k] != want[k]]
    if not diff:
        return ""
    return ("the binding golden was recorded on other inputs: %s; %s"
            % (", ".join(diff), RERECORD))


def test_golden_env_guard_names_the_difference(monkeypatch):
    env = {"build_type": BINDING_GOLDEN_BUILD_TYPE,
           "galaxy_fnv": BINDING_GOLDEN_GALAXY_FNV,
           "fix_sha": BINDING_GOLDEN_FIX_SHA}
    assert _golden_env_mismatch(env) == ""
    why = _golden_env_mismatch(dict(env, build_type="Release"))
    assert "build_type 'Release' (recorded 'Debug')" in why
    assert "DAUNTLESS_RECORD_TRACE_GOLDEN=1" in why
    assert "galaxy_fnv" in _golden_env_mismatch(dict(env, galaxy_fnv="0"))
    assert "fix_sha" in _golden_env_mismatch(dict(env, fix_sha=None))


def _binding_transcript(h, iid, stale):
    rng = random.Random(SEED + 6)
    lines, hits = [], 0
    poses = [
        (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        _rand_rot(rng),
        _rand_rot(rng),
    ]
    for p, rot in enumerate(poses):
        scale = (1.0, 0.0055, 2.0)[p]
        t = ((0.0, 0.0, 0.0), (1e6 + 0.3, -250.0, 3.0),
             (-4500.25, 120000.0, 0.5))[p]
        h.set_world_transform(iid, _instance_mat(rot, scale, t))
        reach = 400.0 * scale
        for i in range(400):
            o = tuple(rng.uniform(-reach, reach) for _ in range(3))
            aim = tuple(rng.uniform(-reach / 4, reach / 4) for _ in range(3))
            d = tuple(a - b for a, b in zip(aim, o))
            k = rng.random()
            if k < 0.03:
                d = (0.0, 0.0, 0.0)
            elif k < 0.05:
                d = (1e-10, 0.0, 0.0)
            elif k < 0.07:
                d = (NAN, 1.0, 0.0)
            md = rng.choice((reach * 3,) * 10 + (NAN, INF, -INF, 0.0, -1.0,
                                                 1e300, reach / 8))
            kw = {"rest_pose": True} if rng.random() < 0.1 else {}
            try:
                r = h.ray_trace_mesh(iid, o, d, md, **kw)
            except Exception as e:      # noqa: BLE001 -- the transcript
                lines.append(f"raise {type(e).__name__}: {e}")
                continue
            if r is None:
                lines.append("None")
                continue
            hits += 1
            (px, py, pz), (nx, ny, nz), tt = r
            lines.append(" ".join(v.hex() for v in
                                  (px, py, pz, nx, ny, nz, tt)))
    for bad in (stale,):
        try:
            h.ray_trace_mesh(bad, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 10.0)
            lines.append("no raise")
        except Exception as e:          # noqa: BLE001
            lines.append(f"raise {type(e).__name__}: {e}")
    return lines, hits


def test_binding_unchanged(scene):
    s = scene
    env = _golden_env()
    lines, hits = _binding_transcript(_h, s.iid, s.stale)
    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    if os.environ.get("DAUNTLESS_RECORD_TRACE_GOLDEN"):
        print(f"\nBINDING_GOLDEN = {digest!r}\nBINDING_GOLDEN_HITS = {hits}"
              f"\nBINDING_GOLDEN_BUILD_TYPE = {env['build_type']!r}"
              f"\nBINDING_GOLDEN_GALAXY_FNV = {env['galaxy_fnv']!r}"
              f"\nBINDING_GOLDEN_FIX_SHA = {env['fix_sha']!r}")
    why = _golden_env_mismatch(env)
    if why:
        pytest.skip(why)
    assert hits == BINDING_GOLDEN_HITS, (
        "ray_trace_mesh's hit count moved (%d, recorded %d); if the change "
        "is legitimate, %s" % (hits, BINDING_GOLDEN_HITS, RERECORD))
    assert digest == BINDING_GOLDEN, (
        "ray_trace_mesh's transcript moved (an output bit, a None or a "
        "raise); if the change is legitimate, %s" % RERECORD)
    # The documented outcomes, by name.
    assert lines[-1] == "raise RuntimeError: ray_trace_mesh: invalid InstanceId"
    no_model = _h.create_instance(0)
    with pytest.raises(RuntimeError, match="instance has no model"):
        _h.ray_trace_mesh(no_model, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 10.0)
    for o, d, md in (((0.0, -900.0, 0.0), (0.0, 0.0, 0.0), 2000.0),
                     ((0.0, -900.0, 0.0), (0.0, 1.0, 0.0), NAN),
                     ((0.0, -900.0, 0.0), (0.0, 1.0, 0.0), 0.0)):
        assert _h.ray_trace_mesh(s.iid, o, d, md) is None
