"""Every world-space render feed carries only the VIEWED frame, expressed in
the viewed set's local coordinates (system-frames Plan 2, Task 5).

The renderer draws in the viewed set's set-local coordinates, but several sets
coexist (the set you warped away from stays alive, and its ships keep
fighting). Each feed below used to hand the renderer positions from EVERY set,
raw. Every test places one item in each of three sets:

  (a) the viewed set                      -> exactly its raw position,
  (b) another region of the same system   -> local + offset_between(view, set),
  (c) an unmapped set (another frame)     -> absent.
"""
import pytest

import App
import engine.host_loop as host_loop
from engine.appc import explosion_lights, hit_vfx, projectiles
from engine.appc.lens_flare import LensFlare_Create, aggregate_lens_flares_for_renderer
from engine.appc.math import TGPoint3
from engine.appc.planet import Planet, Sun
from engine.appc.projectiles import Torpedo, register
from engine.appc.sets import SetClass_Create
from engine.systems import frames
from tests.helpers import bc_assets
from tests.helpers.bc_assets import require_game_asset
from tests.helpers.mapped_regions import load_region


@pytest.fixture(autouse=True)
def _isolate():
    def _clear():
        App.g_kSetManager._sets.clear()
        App.g_kSetManager.ClearRenderedSet()
        projectiles._active.clear()
        explosion_lights.reset()
        hit_vfx._active.clear()
        host_loop._note_camera_eye(None)
    _clear()
    yield
    _clear()


@pytest.fixture
def world():
    """Viewed Ona1, the other Ona region, and an unrelated one-set frame."""
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, "QuickBattle")
    App.g_kSetManager.MakeRenderedSet("Ona1")
    off = frames.offset_between(ona1, ona2)
    assert off is not None and off != (0.0, 0.0, 0.0), "premise: regions differ"
    assert frames.offset_between(ona1, other) is None, "premise: other frame"
    return ona1, ona2, other, off


def _shifted(p, off):
    return (p[0] + off[0], p[1] + off[1], p[2] + off[2])


A, B, C = (1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)


# ── the helpers ─────────────────────────────────────────────────────────────

def test_in_view_same_set_is_the_raw_point_itself(world):
    ona1, ona2, other, off = world
    assert frames.in_view(ona1, ona1, *A) == A
    assert frames.in_view(ona1, ona2, *B) == pytest.approx(_shifted(B, off))
    assert frames.in_view(ona1, other, *C) is None
    assert frames.in_view(None, ona1, *A) is None


def test_shifted_returns_the_same_point_for_a_zero_or_missing_offset():
    p = TGPoint3(1.0, 2.0, 3.0)
    assert frames.shifted(p, (0.0, 0.0, 0.0)) is p
    assert frames.shifted(p, None) is p
    q = frames.shifted(p, (10.0, 20.0, 30.0))
    assert (q.x, q.y, q.z) == (11.0, 22.0, 33.0)
    r = frames.shifted(p, (10.0, 20.0, 30.0), -1.0)
    assert (r.x, r.y, r.z) == (-9.0, -18.0, -27.0)


# ── dust planets ────────────────────────────────────────────────────────────

def _planet(pSet, name, xyz, radius):
    p = Planet(radius, "")
    p.SetWorldLocation(TGPoint3(*xyz))
    pSet.AddObjectToSet(p, name)
    return p


def test_aggregate_planets_by_frame(world):
    ona1, ona2, other, off = world
    _planet(ona1, "pa", A, 111.0)
    _planet(ona2, "pb", B, 222.0)
    _planet(other, "pc", C, 333.0)
    out = host_loop._aggregate_planets(
        list(App.g_kSetManager._sets.values()), view=ona1)
    by_r = {e["radius"]: e["position"] for e in out}
    assert by_r[111.0] == A
    assert by_r[222.0] == pytest.approx(_shifted(B, off))
    assert 333.0 not in by_r


def test_aggregate_planets_with_no_view_is_empty(world):
    ona1, *_ = world
    _planet(ona1, "pa", A, 111.0)
    assert host_loop._aggregate_planets([ona1], view=None) == []


# ── lens flares ─────────────────────────────────────────────────────────────

def _flare(pSet, name, xyz, radius):
    sun = Sun(radius=radius, model_path="data/Textures/SunBase.tga")
    sun.SetWorldLocation(xyz)
    pSet.AddObjectToSet(sun, name)
    flare = LensFlare_Create(pSet)
    flare.SetSource(sun, 6)
    flare.AddFlare(8, "data/textures/rays.tga", 0.0, 0.3)
    flare.Build()


def test_lens_flares_by_frame(world):
    require_game_asset("data/textures/rays.tga")
    ona1, ona2, other, off = world
    _flare(ona1, "fa", A, 4001.0)
    _flare(ona2, "fb", B, 4002.0)
    _flare(other, "fc", C, 4003.0)
    out = aggregate_lens_flares_for_renderer(
        bc_assets.GAME_ROOT, [ona1, ona2, other], view=ona1)
    by_r = {e["source_radius"]: e["source_world_pos"] for e in out}
    assert by_r[4001.0] == A
    assert by_r[4002.0] == pytest.approx(_shifted(B, off))
    assert 4003.0 not in by_r


def test_lens_flares_with_no_view_are_empty(world):
    require_game_asset("data/textures/rays.tga")
    ona1, *_ = world
    _flare(ona1, "fa", A, 4001.0)
    assert aggregate_lens_flares_for_renderer(
        bc_assets.GAME_ROOT, [ona1], view=None) == []


# ── torpedoes and their lights ──────────────────────────────────────────────

def _torpedo(pSet, name, xyz):
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


def _three_torpedoes(world):
    ona1, ona2, other, _off = world
    return (_torpedo(ona1, "ta", A), _torpedo(ona2, "tb", B),
            _torpedo(other, "tc", C))


def test_torpedo_render_data_by_frame(world):
    *_, off = world
    ta, tb, tc = _three_torpedoes(world)
    by_id = {e["id"]: e["position"] for e in host_loop._build_torpedo_render_data()}
    assert by_id[int(ta._id)] == A
    assert by_id[int(tb._id)] == pytest.approx(_shifted(B, off))
    assert int(tc._id) not in by_id


def test_torpedo_lights_by_frame(world):
    *_, off = world
    _three_torpedoes(world)
    got = [e["position"] for e in host_loop._build_dynamic_light_render_data()]
    assert len(got) == 2
    assert A in got
    assert any(p == pytest.approx(_shifted(B, off)) for p in got)


def test_torpedo_light_fade_judges_the_converted_position(world):
    """The camera eye is in the viewed set's coordinates; a torpedo that is
    right beside it once converted must not be culled by its raw number."""
    ona1, ona2, _other, off = world
    _torpedo(ona2, "tb", (-off[0], -off[1], -off[2]))   # converts to origin
    host_loop._note_camera_eye((0.0, 0.0, 0.0))
    (entry,) = host_loop._build_dynamic_light_render_data()
    assert entry["position"] == pytest.approx((0.0, 0.0, 0.0))
    assert entry["intensity"] == pytest.approx(host_loop._TORPEDO_LIGHT_INTENSITY)


def test_torpedo_feeds_are_empty_with_no_viewing_set(world, monkeypatch):
    ona1, *_ = world
    App.g_kSetManager.ClearRenderedSet()
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: None)
    assert frames.viewing_set() is None
    _torpedo(ona1, "ta", A)
    assert host_loop._build_torpedo_render_data() == []
    assert host_loop._build_dynamic_light_render_data() == []


def test_render_feeds_follow_the_explicit_rendered_set(monkeypatch):
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    player = App.ShipClass_Create()
    player.SetName("Player")
    ona1.AddObjectToSet(player, "Player")
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: player)
    _torpedo(ona1, "t", (0.0, 0.0, 0.0))
    App.g_kSetManager.MakeRenderedSet("Ona2")      # a cutscene looking at Ona2
    off = frames.offset_between(ona2, ona1)
    (entry,) = host_loop._build_torpedo_render_data()
    assert entry["position"] == pytest.approx(off)  # expressed in Ona2's frame


# ── explosion lights ────────────────────────────────────────────────────────

def _dying_ship(pSet, name, xyz):
    s = App.ShipClass_Create()
    s.SetName(name)
    pSet.AddObjectToSet(s, name)
    s.SetTranslateXYZ(*xyz)
    explosion_lights.register(s, size_gu=10.0, count=1, spacing_s=1.0,
                              life_s=100.0)
    return s


def test_explosion_lights_by_frame(world):
    ona1, ona2, other, off = world
    _dying_ship(ona1, "a", A)
    _dying_ship(ona2, "b", B)
    _dying_ship(other, "c", C)
    explosion_lights.advance(1.0 / 60.0)
    out = host_loop._build_explosion_light_render_data()
    got = [e["position"] for e in out]
    assert len(got) == 2
    assert A in got
    assert any(p == pytest.approx(_shifted(B, off)) for p in got)
    for e in out:
        assert set(e) == {"position", "color", "radius", "intensity"}, (
            "the birth set is engine-side bookkeeping; it never reaches "
            "the renderer")


# ── hit VFX ─────────────────────────────────────────────────────────────────

def test_hit_vfx_by_frame(world):
    ona1, ona2, other, off = world
    hit_vfx.spawn(TGPoint3(*A), pSet=ona1, instance_id=3)
    hit_vfx.spawn(TGPoint3(*B), pSet=ona2)
    hit_vfx.spawn(TGPoint3(*C), pSet=other)
    out = host_loop._build_hit_vfx_render_data()
    got = [e["position"] for e in out]
    assert len(got) == 2
    assert A in got
    assert any(p == pytest.approx(_shifted(B, off)) for p in got)
    assert "set" not in out[0]


def test_a_hull_hit_records_the_ships_set(world, monkeypatch):
    from engine.appc import hit_feedback
    ona1, ona2, *_ = world
    ship = App.ShipClass_Create()
    ship.SetName("S")
    ona2.AddObjectToSet(ship, "S")
    hit_feedback._hull_impact_visual(
        ship=ship, point=TGPoint3(*B), normal=None,
        severity=hit_feedback.Severity.HULL, weapon_type="phaser",
        absorbed_hull=1.0, ship_instances=None)
    (entry,) = hit_vfx._active
    assert entry["set"] is ona2


# ── beams ───────────────────────────────────────────────────────────────────

class _Bank:
    """A firing bank aimed at its own ship: both beam ends in one set (the
    cross-set case runs the real descriptor path, further down)."""
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


def _beam_ship(pSet, name, xyz):
    s = App.ShipClass_Create()
    s.SetName(name)
    pSet.AddObjectToSet(s, name)
    s.SetTranslateXYZ(*xyz)
    s.GetPhaserSystem = lambda: _System(s)
    s.GetTractorBeamSystem = lambda: _System(s)
    return s


def _fake_pair(ship, bank, ship_instances):
    p = ship.GetWorldLocation()
    return [{"emitter": (p.x, p.y, p.z), "target": (p.x, p.y + 1.0, p.z),
             "color": (1.0, 1.0, 1.0, 1.0), "width": 1.0}]


@pytest.mark.parametrize("builder", [
    "_build_phaser_beam_render_data", "_build_tractor_beam_render_data"])
def test_beams_by_frame(world, monkeypatch, builder):
    ona1, ona2, other, off = world
    monkeypatch.setattr(host_loop, "_beam_descriptor_pair", _fake_pair)
    ships = [_beam_ship(ona1, "a", A), _beam_ship(ona2, "b", B),
             _beam_ship(other, "c", C)]
    out = getattr(host_loop, builder)(ships)
    emitters = [d["emitter"] for d in out]
    targets = [d["target"] for d in out]
    assert len(out) == 2
    assert A in emitters and (A[0], A[1] + 1.0, A[2]) in targets
    bx = _shifted(B, off)
    assert any(e == pytest.approx(bx) for e in emitters)
    assert any(t == pytest.approx((bx[0], bx[1] + 1.0, bx[2])) for t in targets)


# ═════ Fix round 1 ═══════════════════════════════════════════════════════════

# ── (1) the bridge is not a space scene ─────────────────────────────────────

def _bridge():
    from engine.appc.bridge_set import BridgeSet_Create
    b = BridgeSet_Create()
    App.g_kSetManager.AddSet(b, "bridge")
    return b


def test_feeds_survive_a_cutscene_that_ends_on_the_bridge(monkeypatch):
    """E6M1:1651 & co end cutscenes with ChangeRenderedSet("bridge"), and only
    a warp resets it -- the tactical view must keep drawing the player's set."""
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    _bridge()
    player = App.ShipClass_Create()
    player.SetName("Player")
    ona1.AddObjectToSet(player, "Player")
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: player)
    _torpedo(ona1, "t", A)

    App.g_kSetManager.MakeRenderedSet("bridge")
    (entry,) = host_loop._build_torpedo_render_data()
    assert entry["position"] == A                  # Ona1's own coordinates

    App.g_kSetManager.MakeRenderedSet("Ona2")      # a space cutscene
    (entry,) = host_loop._build_torpedo_render_data()
    assert entry["position"] == pytest.approx(
        _shifted(A, frames.offset_between(ona2, ona1)))


# ── (2) beams: each endpoint in its own set, real descriptor path ──────────

def _tractor_pair(shooter_set, shooter_xyz, target_set, target_xyz):
    from unittest.mock import patch
    from tests.unit.test_tractor_beam_render_data import (
        _ship_with_tractor, _target)
    ship, parent = _ship_with_tractor()
    target = _target()
    shooter_set.AddObjectToSet(ship, "Source")
    target_set.AddObjectToSet(target, "Target")
    # Engage at the helpers' in-range positions, THEN place the pair: the
    # weapon's range gate is not what this file tests, the drawn beam is.
    # The interim cross-set weapon guard (system-frames Plan 2 Ruling 5)
    # would refuse a cross-set engagement; bypass it for the same reason.
    from engine.appc.weapon_subsystems import TractorBeamSystem
    with patch("engine.audio.tg_sound.TGSoundManager.instance"), \
         patch.object(TractorBeamSystem, "_can_engage",
                      lambda self, s, t: True):
        parent.StartFiring(target, None)
    assert parent.IsFiring()
    ship.SetTranslateXYZ(*shooter_xyz)
    target.SetTranslateXYZ(*target_xyz)
    return ship


def test_a_beam_across_regions_draws_each_end_in_its_own_set(world):
    ona1, ona2, _other, off = world
    # The same geometry built in ONE set: the target where Ona2's (0,50,0)
    # sits in Ona1's coordinates.
    base_ship = _tractor_pair(ona1, (0.0, 0.0, 0.0),
                              ona1, _shifted((0.0, 50.0, 0.0), off))
    baseline = host_loop._build_tractor_beam_render_data([base_ship])
    ona1.RemoveObjectFromSet("Source")
    ona1.RemoveObjectFromSet("Target")
    assert len(baseline) == 2

    ship = _tractor_pair(ona1, (0.0, 0.0, 0.0), ona2, (0.0, 50.0, 0.0))
    out = host_loop._build_tractor_beam_render_data([ship])
    assert len(out) == 2
    for got, want in zip(out, baseline):
        assert got["emitter"] == pytest.approx(want["emitter"])
        assert got["target"] == pytest.approx(want["target"])
    assert out[0]["target"] == pytest.approx(_shifted((0.0, 50.0, 0.0), off))

    # Viewed from Ona2 the TARGET end is raw and the emitter end shifts.
    App.g_kSetManager.MakeRenderedSet("Ona2")
    back = frames.offset_between(ona2, ona1)
    out2 = host_loop._build_tractor_beam_render_data([ship])
    assert out2[0]["target"] == pytest.approx((0.0, 50.0, 0.0))
    assert out2[0]["emitter"] == pytest.approx(
        _shifted(baseline[0]["emitter"], back))


def test_a_beam_at_a_target_in_another_frame_is_not_drawn(world):
    ona1, _ona2, other, _off = world
    ship = _tractor_pair(ona1, (0.0, 0.0, 0.0), other, (0.0, 50.0, 0.0))
    assert host_loop._build_tractor_beam_render_data([ship]) == []


# ── (3) shockwaves ──────────────────────────────────────────────────────────

def test_shockwaves_by_frame(world):
    from engine.appc import shockwaves
    ona1, ona2, other, off = world
    shockwaves.reset()
    try:
        shockwaves.spawn(TGPoint3(*A), 1.0, 5.0, pSet=ona1)
        shockwaves.spawn(TGPoint3(*B), 2.0, 5.0, pSet=ona2)
        shockwaves.spawn(TGPoint3(*C), 3.0, 5.0, pSet=other)
        out = host_loop._build_shockwave_render_data()
    finally:
        shockwaves.reset()
    by_r = {e["max_radius"]: e["world_center"] for e in out}
    assert by_r[1.0] == A
    assert by_r[2.0] == pytest.approx(_shifted(B, off))
    assert 3.0 not in by_r
    for e in out:
        assert set(e) == {"world_center", "max_radius", "age", "lifetime"}


def test_a_breach_shockwave_records_the_ships_set(world, monkeypatch):
    from engine.appc import shockwaves, warp_core_breach, core_breach_carve
    ona1, ona2, *_ = world
    monkeypatch.setattr(core_breach_carve, "schedule", lambda ship: None)
    ship = App.ShipClass_Create()
    ship.SetName("Doomed")
    ona2.AddObjectToSet(ship, "Doomed")
    seen = []
    monkeypatch.setattr(shockwaves, "spawn",
                        lambda c, r, l, pSet=None: seen.append(pSet))
    monkeypatch.setattr(ship, "GetPowerSubsystem", lambda: object())
    import engine.appc.subsystems as subs
    monkeypatch.setattr(subs, "subsystem_world_position",
                        lambda core, s: TGPoint3(*B))
    warp_core_breach.detonate(ship)
    assert seen == [ona2]


# ── (3) world-anchored particles ────────────────────────────────────────────

def _world_smoke(pSet, xyz):
    from engine.appc import particles as P
    c = P.AnimTSParticleController()
    c.SetEmitLife(1.0); c.SetEmitFrequency(0.05); c.SetEffectLifeTime(100.0)
    c.CreateTarget("data/Textures/Effects/ExplosionB.tga")
    c.SetEmitPositionAndDirection(xyz, (0.0, -1.0, 0.0))
    c.AttachEffect(pSet.GetEffectRoot())
    P.EffectAction_Create(c).Start()
    return c


def test_world_anchored_particles_by_frame(world):
    from engine.appc import particles as P
    ona1, ona2, other, off = world
    P.reset()
    try:
        _world_smoke(ona1, A)
        _world_smoke(ona2, B)
        _world_smoke(other, C)
        got = [d["emit_pos"] for d in host_loop._build_particle_render_data({})]
    finally:
        P.reset()
    assert len(got) == 2
    assert A in got
    assert any(p == pytest.approx(_shifted(B, off)) for p in got)


def test_a_particle_on_an_unrealized_ship_is_placed_by_the_ships_set(world):
    """The wreck-site branch: an emit-from ship with no render instance --
    every ship in a left-behind set -- is drawn at its GetWorldLocation."""
    from engine.appc import particles as P
    ona1, ona2, other, off = world
    P.reset()
    try:
        for pSet, name, xyz in ((ona1, "a", A), (ona2, "b", B), (other, "c", C)):
            s = App.ShipClass_Create()
            s.SetName(name)
            pSet.AddObjectToSet(s, name)
            s.SetTranslateXYZ(*xyz)
            c = _world_smoke(pSet, (0.0, 0.0, 0.0))
            c.SetEmitFromObject(s)
        got = [d["emit_pos"] for d in host_loop._build_particle_render_data({})]
    finally:
        P.reset()
    assert len(got) == 2
    assert A in got
    assert any(p == pytest.approx(_shifted(B, off)) for p in got)


def test_instance_attached_particles_pass_through_untouched(world):
    """Resolved in C++ through inst->world (particle_pass.cc:185-189): the
    body-frame emit_pos must not be shifted."""
    from engine.appc import particles as P
    ona1, *_ = world
    P.reset()
    try:
        s = App.ShipClass_Create()
        s.SetName("a")
        ona1.AddObjectToSet(s, "a")
        c = _world_smoke(ona1, (0.0, 1.0, 0.0))
        c.SetEmitFromObject(s)
        (d,) = host_loop._build_particle_render_data({s: 7})
    finally:
        P.reset()
    assert d["instance_id"] == 7
    assert d["emit_pos"] == (0.0, 1.0, 0.0)


# ── (3) debris chunks ───────────────────────────────────────────────────────

class _ChunkRenderer:
    def __init__(self):
        self.transforms, self.visible = {}, {}

    def set_world_transform(self, iid, mat):
        self.transforms[iid] = mat

    def set_visible(self, iid, v):
        self.visible[iid] = v

    def destroy_instance(self, iid):
        pass


def test_debris_chunks_by_frame(world, monkeypatch):
    from engine.appc import debris_chunk as dc
    ona1, ona2, other, off = world
    monkeypatch.setattr(host_loop, "_world_matrix_from",
                        lambda o, rot, scale: (o.x, o.y, o.z))
    r = _ChunkRenderer()
    dc.clear(r)
    try:
        chunks = []
        for iid, (pSet, name, xyz) in enumerate(
                ((ona1, "a", A), (ona2, "b", B), (other, "c", C)), start=1):
            s = App.ShipClass_Create()
            s.SetName(name)
            pSet.AddObjectToSet(s, name)
            s.SetTranslateXYZ(*xyz)
            chunks.append(dc.spawn(iid, s, 100, (0.0, 0.0, 0.0), 0.5,
                                   parent_mass=100.0, parent_occupied_cells=1000))
        origins = {c.iid: c._mesh_origin() for c in chunks}
        dc.tick(0.0, r)
    finally:
        dc.clear(r)
    oa, ob = origins[1], origins[2]
    assert r.transforms[1] == (oa.x, oa.y, oa.z)
    assert 1 not in r.visible, "a same-set chunk makes no visibility call"
    assert r.transforms[2] == pytest.approx(_shifted((ob.x, ob.y, ob.z), off))
    assert 3 not in r.transforms
    assert r.visible[3] is False


# ── (3) emitter-light fade on the converted hull position ──────────────────

def test_emitter_light_fade_judges_the_converted_hull_position(world):
    from tests.unit.test_dynamic_light_camera_fade import _point_prop, _Sub
    from engine.appc import light_emitters
    ona1, ona2, other, off = world
    host_loop._note_camera_eye((0.0, 0.0, 0.0))
    ships, emitters = {}, {}
    placements = ((ona1, "a", (20.0, 0.0, 0.0)),
                  (ona2, "b", (-off[0], -off[1], -off[2])),   # -> the origin
                  (other, "c", (0.0, 0.0, 0.0)))
    for iid, (pSet, name, xyz) in enumerate(placements, start=1):
        s = App.ShipClass_Create()
        s.SetName(name)
        pSet.AddObjectToSet(s, name)
        s.SetTranslateXYZ(*xyz)
        prop = _point_prop(intensity=2.0)
        spec = light_emitters.baked_emitters(prop)[0]
        ships[s] = iid
        emitters[iid] = [(_Sub(prop), False, False, 0.0, spec,
                          light_emitters.emitter_spec_to_struct(spec))]
    out = host_loop._build_emitter_light_render_data(ships, emitters)
    assert sorted(d["instance_id"] for d in out) == [1, 2]
    assert all(d["intensity"] == pytest.approx(2.0) for d in out)
