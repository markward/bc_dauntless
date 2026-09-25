"""Every Space-pass feed, camera and mesh query in RENDER space
(system-frames Plan 3, Task 6).

The render origin is the exterior camera eye in the viewed set's coordinates,
set once per frame before any feed is built. Native subtracts it from every
Space-pass instance's double translation (Task 5); Python feeds everything
else -- the camera, suns, flares, dust planets, nebulae, torpedoes, lights,
beams, particles, shockwaves, hit VFX, discharges, the wake, the reticle --
already relative to it, through frames.to_render. Pushed ship matrices stay
VIEW space (native subtracts).

The scene here is placed directly: the player 450,000 GU from its set's
origin, the camera 30 GU behind it, every effect within a few hundred GU. In
render space all of it must sit within a few thousand GU of zero.
"""
import ast
import inspect
import textwrap

import pytest

import App
import engine.host_loop as host_loop
from engine import host_io
from engine.appc import explosion_lights, hit_vfx, projectiles
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.sets import SetClass_Create
from engine.core.game import Game, _set_current_game
from engine.core.transform_buffer import TransformBuffer
from engine.systems import frames
from tests.helpers.mapped_regions import load_region

FAR = 450000.0
P = (FAR, 0.0, 0.0)              # the player, set-local == view
EYE = (FAR, -30.0, 0.0)          # 30 GU behind (ship forward is +Y)
NEAR_ZERO = 3000.0


def _near(p, what):
    assert all(abs(c) < NEAR_ZERO for c in p), f"{what} not in render space: {p}"


def _plus(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


class _Recorder:
    """Fake renderer: records every call, returns benign values."""

    def __init__(self):
        self.calls = []
        self._next = 1

    def __getattr__(self, name):
        def f(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name in ("create_instance",):
                self._next += 1
                return self._next
            if name in ("hdr_lens_flare_enabled", "procedural_sky_enabled",
                        "nebula_lightning_enabled", "volumetric_nebulae_enabled"):
                return True
            return None
        return f

    def named(self, name):
        return [(a, k) for n, a, k in self.calls if n == name]


@pytest.fixture(autouse=True)
def _isolate():
    def _clear():
        App.g_kSetManager._sets.clear()
        App.g_kSetManager.ClearRenderedSet()
        _set_current_game(None)
        projectiles._active.clear()
        explosion_lights.reset()
        hit_vfx._active.clear()
        host_loop._note_camera_eye(None)
        frames.reset_render_origin()
    _clear()
    yield
    _clear()


def _ship(pSet, name, xyz):
    s = App.ShipClass_Create()
    s.SetName(name)
    pSet.AddObjectToSet(s, name)
    s.SetTranslateXYZ(*xyz)
    return s


@pytest.fixture
def far_scene():
    """An unmapped set, the player 450,000 GU from its origin."""
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "Far")
    player = _ship(pSet, "Player", P)
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    assert frames.viewing_set() is pSet
    return pSet, player


# ── the origin and the exterior camera ─────────────────────────────────────

def test_the_origin_is_set_once_to_the_camera_eye_and_the_camera_is_relative(far_scene):
    r = _Recorder()
    host_loop._apply_render_origin(r, EYE)
    host_loop._push_space_camera(r, EYE, P, (0.0, 0.0, 1.0), 0.6, 1.0, 1e6)
    assert r.named("set_render_origin") == [(EYE, {})]
    assert frames.render_origin() == EYE
    ((_a, cam),) = r.named("set_camera")
    assert cam["eye"] == (0.0, 0.0, 0.0)
    assert cam["target"] == (0.0, 30.0, 0.0)
    assert cam["up"] == (0.0, 0.0, 1.0)


def test_at_origin_zero_the_camera_is_pushed_untouched():
    r = _Recorder()
    host_loop._push_space_camera(r, (1.0, 2.0, 3.0), (4.0, 5.0, 6.0),
                                 (0.0, 0.0, 1.0), 0.6, 1.0, 1e6)
    ((_a, cam),) = r.named("set_camera")
    assert cam["eye"] == (1.0, 2.0, 3.0) and cam["target"] == (4.0, 5.0, 6.0)


# ── every Space-pass feed ──────────────────────────────────────────────────

def _torpedo(pSet, name, xyz):
    from engine.appc.projectiles import Torpedo, register
    t = Torpedo()
    c = App.TGColorA()
    c.SetRGBA(1.0, 0.25, 0.0, 1.0)
    t.CreateTorpedoModel(
        "data/Textures/Tactical/TorpedoCore.tga", c, 0.2, 1.2,
        "data/Textures/Tactical/TorpedoGlow.tga", c, 3.0, 0.3, 0.6,
        "data/Textures/Tactical/TorpedoFlares.tga", c, 8, 0.7, 0.4,
    )
    t.SetTranslateXYZ(*xyz)
    pSet.AddObjectToSet(t, name)
    register(t)
    return t


class _Bank:
    def __init__(self, target):
        self._target = target

    def IsFiring(self):
        return True


class _System:
    def __init__(self, ship):
        self._ship = ship

    def GetNumWeapons(self):
        return 1

    def GetWeapon(self, i):
        return _Bank(self._ship)


def _fake_pair(ship, bank, ship_instances):
    p = ship.GetWorldLocation()
    return [{"emitter": (p.x, p.y, p.z), "target": (p.x, p.y + 50.0, p.z),
             "color": (1.0, 1.0, 1.0, 1.0), "width": 1.0}]


def _combat_feeds(pSet, player, monkeypatch):
    from engine.appc import particles, shockwaves
    _torpedo(pSet, "torp", _plus(P, (5.0, 0.0, 0.0)))
    dying = _ship(pSet, "Dying", _plus(P, (10.0, 0.0, 0.0)))
    explosion_lights.register(dying, size_gu=10.0, count=1, spacing_s=1.0,
                              life_s=100.0)
    explosion_lights.advance(1.0 / 60.0)
    hit_vfx.spawn(TGPoint3(*_plus(P, (0.0, 3.0, 0.0))), pSet=pSet)
    shockwaves.reset()
    shockwaves.spawn(TGPoint3(*_plus(P, (0.0, 0.0, 8.0))), 1.0, 5.0, pSet=pSet)
    particles.reset()
    c = particles.AnimTSParticleController()
    c.SetEmitLife(1.0); c.SetEmitFrequency(0.05); c.SetEffectLifeTime(100.0)
    c.CreateTarget("data/Textures/Effects/ExplosionB.tga")
    c.SetEmitPositionAndDirection(_plus(P, (0.0, 0.0, -4.0)), (0.0, -1.0, 0.0))
    c.AttachEffect(pSet.GetEffectRoot())
    particles.EffectAction_Create(c).Start()
    gunner = _ship(pSet, "Gunner", _plus(P, (-20.0, 0.0, 0.0)))
    gunner.GetPhaserSystem = lambda: _System(gunner)
    gunner.GetTractorBeamSystem = lambda: _System(gunner)
    monkeypatch.setattr(host_loop, "_beam_descriptor_pair", _fake_pair)
    return [player, gunner, dying]


def test_every_combat_feed_is_in_render_space(far_scene, monkeypatch):
    from engine.appc import particles, shockwaves
    pSet, player = far_scene
    ships = _combat_feeds(pSet, player, monkeypatch)
    pushed = {}
    for name in ("set_torpedoes", "set_dynamic_lights", "set_shockwaves",
                 "set_hit_vfx", "set_particle_emitters", "set_phaser_beams",
                 "set_tractor_beams"):
        monkeypatch.setattr(host_io, name,
                            lambda lst, _n=name: pushed.__setitem__(_n, lst))
    r = _Recorder()
    host_loop._note_camera_eye(EYE)
    host_loop._apply_render_origin(r, EYE)
    try:
        host_loop._push_combat_render_data(ships, ship_instances={},
                                           ship_emitters={}, player=player)
    finally:
        shockwaves.reset()
        particles.reset()
    positions = {
        "set_torpedoes": [d["position"] for d in pushed["set_torpedoes"]],
        "set_dynamic_lights": [d["position"] for d in pushed["set_dynamic_lights"]],
        "set_shockwaves": [d["world_center"] for d in pushed["set_shockwaves"]],
        "set_hit_vfx": [d["position"] for d in pushed["set_hit_vfx"]],
        "set_particle_emitters": [d["emit_pos"] for d in pushed["set_particle_emitters"]],
        "set_phaser_beams": [p for d in pushed["set_phaser_beams"]
                             for p in (d["emitter"], d["target"])],
        "set_tractor_beams": [p for d in pushed["set_tractor_beams"]
                              for p in (d["emitter"], d["target"])],
    }
    for feed, pts in positions.items():
        assert pts, f"premise: {feed} carried something"
        for p in pts:
            _near(p, feed)
    # torpedo light + explosion light both present
    assert len(positions["set_dynamic_lights"]) == 2
    torp = positions["set_torpedoes"][0]
    assert torp == pytest.approx((5.0, 30.0, 0.0))


def _flare(pSet, sun):
    from engine.appc.lens_flare import LensFlare_Create
    flare = LensFlare_Create(pSet)
    flare.SetSource(sun, 6)
    flare.AddFlare(8, "data/textures/rays.tga", 0.0, 0.3)
    flare.Build()


def test_every_environment_feed_is_in_render_space(far_scene, monkeypatch):
    from tests.helpers.bc_assets import require_game_asset
    require_game_asset("data/Textures/SunBase.tga")
    require_game_asset("data/textures/rays.tga")
    from engine.appc.nebula import MetaNebula_Create
    from engine.appc.planet import Planet, Sun
    pSet, player = far_scene
    sun = Sun(radius=40.0, model_path="data/Textures/SunBase.tga")
    sun.SetWorldLocation(TGPoint3(*_plus(P, (2000.0, 0.0, 0.0))))
    pSet.AddObjectToSet(sun, "Sun")
    _flare(pSet, sun)
    planet = Planet(50.0, "")
    planet.SetWorldLocation(TGPoint3(*_plus(P, (0.0, 1000.0, 0.0))))
    pSet.AddObjectToSet(planet, "Planet")
    neb = MetaNebula_Create(0.5, 0.5, 0.5, 10.0, 1.0, "", "")
    neb.AddNebulaSphere(FAR + 100.0, 0.0, 0.0, 300.0)
    pSet.AddObjectToSet(neb, "Neb")

    class _Discharges:
        def active_discharges(self):
            return [{"world_pos": _plus(P, (1.0, 0.0, 0.0)), "age": 0.0,
                     "life": 1.0, "size": 1.0, "color": (1.0, 1.0, 1.0)}]

    class _Wake:
        def trail_points(self):
            return [{"pos": _plus(P, (0.0, -2.0, 0.0)), "strength": 1.0,
                     "size": 1.0}]

    monkeypatch.setattr(host_loop, "_hull_discharge", _Discharges())
    monkeypatch.setattr(host_loop, "_nebula_wake", _Wake())
    monkeypatch.setattr(host_loop, "_nebula_thunder", None)
    r = _Recorder()
    r.hdr_lens_flare_enabled = lambda: False
    host_loop._apply_render_origin(r, EYE)
    host_loop._push_environment_feeds(r, pSet, warp_streaking=False)

    def only(name):
        ((args, _kw),) = r.named(name)
        return args[0]

    feeds = {
        "set_suns": [d["position"] for d in only("set_suns")],
        "set_dust_planets": [d["position"] for d in only("set_dust_planets")],
        "set_nebulae": [s[:3] for d in only("set_nebulae") for s in d["spheres"]],
        "set_hull_discharges": [d["world_pos"] for d in only("set_hull_discharges")],
        "set_nebula_wake": [d["pos"] for d in only("set_nebula_wake")],
        "set_lens_flares": [d["source_world_pos"] for d in only("set_lens_flares")],
    }
    for feed, pts in feeds.items():
        assert pts, f"premise: {feed} carried something"
        for p in pts:
            _near(p, feed)
    assert feeds["set_suns"][0] == pytest.approx((2000.0, 30.0, 0.0))
    ((sphere,),) = [d["spheres"] for d in only("set_nebulae")]
    assert sphere[3] == 300.0, "a radius is not a position"


def test_the_target_reticle_is_in_render_space(far_scene):
    pSet, player = far_scene
    target = _ship(pSet, "Target", _plus(P, (0.0, 200.0, 0.0)))
    player.SetTarget(target)
    r = _Recorder()
    host_loop._apply_render_origin(r, EYE)
    host_loop._push_target_reticle(r, player)
    ((args, _kw),) = r.named("set_target_reticle")
    payload = args[0]
    assert payload.visible
    assert payload.ship_center == pytest.approx((0.0, 230.0, 0.0))


def test_the_viewscreen_scene_camera_is_in_render_space(far_scene):
    r = _Recorder()
    host_loop._apply_render_origin(r, EYE)
    scene = (_plus(P, (0.0, 5.0, 0.0)), _plus(P, (0.0, 100.0, 0.0)),
             (0.0, 0.0, 1.0), 0.6, 1.0, 1e6)
    assert host_loop._select_viewscreen_source(r, None, scene) == "scene"
    ((args, _kw),) = r.named("set_viewscreen_scene_source")
    _near(args[0], "viewscreen eye")
    _near(args[1], "viewscreen target")
    assert args[0] == pytest.approx((0.0, 35.0, 0.0))
    assert args[2:] == scene[2:]


# ── ship matrices stay VIEW space (native subtracts) ───────────────────────

class _ShipRenderer:
    def __init__(self):
        self.pushed = {}

    def set_world_transform(self, iid, m):
        self.pushed[iid] = m

    def __getattr__(self, name):
        return lambda *a, **k: None


def test_pushed_ship_matrices_are_view_space(far_scene, monkeypatch):
    pSet, player = far_scene
    npc = _ship(pSet, "NPC", _plus(P, (100.0, 0.0, 0.0)))
    frames.set_render_origin(EYE)

    class _Session:
        ship_instances = {npc: 5}
        ship_glow_controllers = {}
        slot_bindings = {}
        scope_hidden = set()
        planet_instances = {}
        celestial_instances = {}

    monkeypatch.setattr(host_loop, "_sync_ship_articulation", lambda *a: None)
    r = _ShipRenderer()
    host_loop._sync_instance_transforms(
        r, _Session(), player, TransformBuffer(), 1.0,
        game_time=1.0, model_scale=1.0)
    m = r.pushed[5]
    assert (m[3], m[7], m[11]) == pytest.approx((FAR + 100.0, 0.0, 0.0))


# ── a sibling-region cutscene: the camera is solved in the VIEWED set ──────

def test_a_sibling_cutscene_solves_the_follow_camera_in_the_viewed_set():
    from engine.cameras import _CameraDirector
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    player = _ship(ona1, "Player", (100.0, 200.0, 300.0))
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    import engine.appc.top_window as top_window
    top_window.reset_for_tests()
    vm = host_loop._ViewModeController()
    vm.toggle()                                    # bridge -> exterior
    assert vm.is_exterior

    # Reference: the follow camera in the PLAYER's own coordinates.
    ref_eye, ref_tgt, _ = host_loop._compute_camera(
        vm, _CameraDirector(), player=player, dt=1.0 / 60)

    App.g_kSetManager.MakeRenderedSet("Ona2")      # a cutscene looking at Ona2
    view = frames.viewing_set()
    assert view is ona2
    off = frames.offset_between(ona2, ona1)
    eye, tgt, _ = host_loop._compute_camera(
        vm, _CameraDirector(), player=player, dt=1.0 / 60,
        pose_of=host_loop._view_pose_of(None, view))
    assert eye == pytest.approx(_plus(ref_eye, off))
    assert tgt == pytest.approx(_plus(ref_tgt, off))

    r = _Recorder()
    host_loop._apply_render_origin(r, eye)
    host_loop._push_space_camera(r, eye, tgt, (0.0, 0.0, 1.0), 0.6, 1.0, 1e6)
    assert r.named("set_render_origin") == [(tuple(eye), {})]
    ((_a, cam),) = r.named("set_camera")
    want = tuple(e - o for e, o in zip(eye, frames.render_origin()))
    assert cam["eye"] == pytest.approx(want)
    assert cam["target"] == pytest.approx(
        tuple(t - o for t, o in zip(tgt, frames.render_origin())))


# ── a mesh query round trip ────────────────────────────────────────────────

class _MeshHost:
    def __init__(self, translation):
        self.translation = translation
        self.traced = []

    def instance_translation(self, iid):
        return self.translation

    def ray_trace_mesh(self, iid, origin, direction, max_dist):
        self.traced.append(origin)
        # hit 2 GU short of the instance's own translation, along -x
        return ((-2.0, 0.0, 0.0), (-1.0, 0.0, 0.0), 8.0)


def test_a_mesh_query_is_instance_relative_and_hands_back_the_targets_set(monkeypatch):
    from engine.appc import combat
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    App.g_kSetManager.MakeRenderedSet("Ona1")
    to_ona2 = frames.offset_between(ona2, ona1)        # Ona1-local -> Ona2-local
    target_view = (FAR, 0.0, 0.0)                      # where it is drawn
    target_local = _plus(target_view, to_ona2)         # its own coordinates
    target = _ship(ona2, "Target", target_local)
    h = _MeshHost(target_view)
    monkeypatch.setattr(host_io, "_h", h)
    ray_origin = TGPoint3(*_plus(target_local, (-10.0, 0.0, 0.0)))
    point, normal = combat._resolve_hit_point(
        {target: 9}, target, ray_origin, TGPoint3(1.0, 0.0, 0.0), 20.0,
        fallback_point=None)
    (sent,) = h.traced
    assert sent == pytest.approx((-10.0, 0.0, 0.0), abs=1e-6)
    got = (point.x, point.y, point.z)
    assert got == pytest.approx(_plus(target_local, (-2.0, 0.0, 0.0)), abs=1e-6)


# ── the frame order, and the passes that are NOT Space ─────────────────────

def _run_source():
    return textwrap.dedent(inspect.getsource(host_loop.run))


def test_the_origin_is_set_before_any_feed_is_pushed():
    src = _run_source()
    o = src.index("_apply_render_origin(")
    for feed in ("_push_combat_render_data(", "_push_environment_feeds(",
                 "_push_space_camera(", "_push_target_reticle(",
                 "_select_viewscreen_source("):
        assert o < src.index(feed), f"{feed} runs before the origin is set"


def test_the_sim_no_longer_pushes_combat_feeds_itself():
    src = _run_source()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_advance_combat"):
            kws = {k.arg: k.value for k in node.keywords}
            assert "push_render_data" in kws, (
                "run() must defer the combat feeds until the origin is set")
            assert isinstance(kws["push_render_data"], ast.Constant)
            assert kws["push_render_data"].value is False


def test_bridge_comm_and_star_map_cameras_are_not_converted():
    """The render origin belongs to the SPACE pass: the bridge interior
    camera, the comm feed and the star map keep their own coordinates."""
    tree = ast.parse(inspect.getsource(host_loop))
    unconverted = {"set_bridge_camera", "set_viewscreen_comm_source",
                   "starmap_set_camera"}
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None)
        if name not in unconverted:
            continue
        seen.add(name)
        names = {getattr(n, "attr", getattr(n, "id", None))
                 for n in ast.walk(node)}
        assert not names & {"view_to_render", "to_render",
                            "_push_space_camera", "render_origin"}, name
    assert seen == unconverted


# ── a mission swap starts at origin zero ───────────────────────────────────

def test_a_mission_swap_resets_the_render_origin(monkeypatch):
    pushed = []
    monkeypatch.setattr(host_loop.r, "set_render_origin",
                        lambda *xyz: pushed.append(xyz))
    frames.set_render_origin(EYE)
    host_loop.reset_sdk_globals()
    assert frames.render_origin() == (0.0, 0.0, 0.0)
    assert pushed == [(0.0, 0.0, 0.0)], "native must follow, or a frozen " \
        "first frame pushes a camera relative to 0 into an old origin"


# ── every mesh-query caller: target-set points in, view-relative out ──────

class _NativeRecorder:
    """A fake native module behind host_io: the instance sits at `t` (VIEW
    space, what host_loop pushed), every mesh query records its (relative)
    point, the trace hits 1 GU short of the instance along -x."""

    def __init__(self, t):
        self.t = t
        self.points = []

    def instance_translation(self, iid):
        return self.t

    def ray_trace_mesh(self, iid, origin, direction, max_dist):
        self.points.append(("ray_trace_mesh", origin))
        return ((-1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), 1.0)

    def __getattr__(self, name):
        def f(iid, point, *rest):
            self.points.append((name, point))
            if name == "world_to_body":
                return ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
            return None
        return f


@pytest.fixture
def sibling_target(monkeypatch):
    """Viewed Ona1; a target ship in Ona2, drawn at view (FAR, 0, 0)."""
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    App.g_kSetManager.MakeRenderedSet("Ona1")
    to_ona2 = frames.offset_between(ona2, ona1)
    target_view = (FAR, 0.0, 0.0)
    target_local = _plus(target_view, to_ona2)
    target = _ship(ona2, "Target", target_local)
    native = _NativeRecorder(target_view)
    monkeypatch.setattr(host_io, "_h", native)
    return target, target_local, native


def _small(points):
    for name, p in points:
        assert all(abs(c) < 50.0 for c in p), f"{name} got {p}: not relative"


def test_hit_feedback_hands_every_query_a_relative_point(sibling_target, monkeypatch):
    from engine.appc import damage_decals, damage_eligibility, hit_feedback
    target, local, native = sibling_target
    monkeypatch.setattr(damage_decals, "current_game_time", lambda: 1.0)
    monkeypatch.setattr(damage_eligibility, "is_eligible", lambda s: True)
    hit = TGPoint3(*_plus(local, (-3.0, 0.0, 0.0)))
    hit_feedback.dispatch(
        ship=target, source=None, point=hit, normal=TGPoint3(-1.0, 0.0, 0.0),
        damage=10.0, subsystem=None, absorbed_shields=5.0,
        absorbed_subsystem=0.0, absorbed_hull=5.0, sub_transition=None,
        ship_instances={target: 3}, weapon_type="torpedo", radius=0.2)
    names = {n for n, _ in native.points}
    assert {"shield_hit", "damage_decal_add", "hull_carve_add",
            "world_to_body"} <= names, names
    _small(native.points)
    decal = dict(native.points)["damage_decal_add"]
    assert decal == pytest.approx((-3.0, 0.0, 0.0), abs=1e-6)


def test_visible_damage_probe_and_carve_are_relative(sibling_target):
    from engine.appc import visible_damage
    target, local, native = sibling_target
    visible_damage._pending.clear()
    visible_damage.queue_world_carve(
        target, TGPoint3(*_plus(local, (-2.0, 0.0, 0.0))), 0.5)
    try:
        visible_damage.advance(0.0, {target: 3})
    finally:
        visible_damage._pending.clear()
    names = [n for n, _ in native.points]
    assert "ray_trace_mesh" in names and "hull_carve_add" in names, names
    _small(native.points)


def test_manual_aim_offset_is_taken_in_the_targets_own_set(sibling_target,
                                                           monkeypatch):
    from engine import manual_aim
    from engine.appc.math import TGMatrix3
    target, local, native = sibling_target

    class _Player:
        offset = None

        def is_using_target_offset(self):
            return False

        def GetTarget(self):
            return target

        def set_manual_target_offset(self, p):
            _Player.offset = p

        def UseTargetOffsetTG(self, on):
            pass

    class _Tcw:
        def GetMousePickFire(self):
            return 1

    class _Cam:
        far = 1e5

    target.SetMatrixRotation(TGMatrix3())
    view_origin = (FAR - 10.0, 0.0, 0.0)                # the cursor ray, view
    # cursor_ray is pure camera maths (tested in test_manual_aim); hand
    # update() a ray already in view coordinates, as cursor_ray would.
    monkeypatch.setattr(manual_aim, "cursor_ray",
                        lambda c, v, cam: (view_origin, (1.0, 0.0, 0.0)))
    ok = manual_aim.update(player=_Player(), tcw=_Tcw(),
                           ship_instances={target: 3}, is_exterior=True,
                           cursor_fb=(0, 0), viewport_fb=(1, 1), cam=_Cam())
    assert ok is True
    (name, sent), = native.points
    assert sent == pytest.approx((-10.0, 0.0, 0.0), abs=1e-6)
    off = _Player.offset
    # The hit is 1 GU short of the hull centre along -x, body frame = world.
    assert (off.x, off.y, off.z) == pytest.approx((-1.0, 0.0, 0.0), abs=1e-6)
