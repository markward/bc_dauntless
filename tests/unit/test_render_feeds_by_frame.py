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
    def IsFiring(self):
        return True


class _System:
    def GetNumWeapons(self):
        return 1

    def GetWeapon(self, i):
        return _Bank()


def _beam_ship(pSet, name, xyz):
    s = App.ShipClass_Create()
    s.SetName(name)
    pSet.AddObjectToSet(s, name)
    s.SetTranslateXYZ(*xyz)
    s.GetPhaserSystem = lambda: _System()
    s.GetTractorBeamSystem = lambda: _System()
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
