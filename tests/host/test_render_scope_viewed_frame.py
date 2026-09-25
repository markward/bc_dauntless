"""What is drawn follows ONE scope: the viewed set's frame (system-frames
Plan 3, Task 3).

A star system is one frame; entering it loads every region (Task 1), so the
Ona system has Ona1, Ona2 and Ona3 alive at once, each with its own Sun at the
one map star and its own mapped Planet. From the viewed set:

  * a MAPPED set's Planet objects are never realized (the map draws them,
    Task 4); an unmapped set's planets realize as they always did,
  * ships come from every set in the viewed frame, culled by
    SHIP_DRAW_DISTANCE_GU from the camera eye, and are pushed at their
    position in the VIEWED set's coordinates,
  * exactly one sun and one lens flare: the viewed set's,
  * the dust feed takes the map's bodies in a mapped frame,
  * the hum roster drops ships beyond the hum's audible range.

Fake renderer mirrors tests/unit/test_realize_set.py (realize) and
tests/unit/test_render_transform_binding.py (sync).
"""
import pytest

import App
import engine.host_loop as host_loop
from engine import host_io
from engine.appc.math import TGPoint3
from engine.appc.sets import SetClass_Create
from engine.core.game import Game, _set_current_game
from engine.core.transform_buffer import TransformBuffer
from engine.systems import celestial, frames, region_hooks
from tests.helpers.mapped_regions import load_region


class _FakeRenderer:
    def __init__(self):
        self._next = 1
        self.live = set()
        self.pushed = {}

    def load_model(self, path, search, texture_replacements=None):
        return 100

    def model_aabb(self, h):
        return ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))

    def create_instance(self, h):
        iid = self._next
        self._next += 1
        self.live.add(iid)
        return iid

    def destroy_instance(self, iid):
        self.live.discard(iid)

    def set_world_transform(self, iid, m):
        self.pushed[iid] = m

    def set_rim_eligible(self, iid, b):
        pass

    def set_rim_strength(self, iid, s):
        pass

    def set_emissive_scale(self, iid, s):
        pass

    def set_visible(self, iid, v):
        pass

    def nebula_lightning_enabled(self):
        return False


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    def _clear():
        App.g_kSetManager._sets.clear()
        App.g_kSetManager.ClearRenderedSet()
        _set_current_game(None)
        host_loop._note_camera_eye(None)
    _clear()
    monkeypatch.setattr(host_loop, "_ship_nif_path", lambda ship, **k: "fake.nif")
    monkeypatch.setattr(host_loop, "_planet_nif_path", lambda p, **k: "fake.nif")
    monkeypatch.setattr(host_io, "set_instance_transform_slot",
                        lambda *a: True)
    yield
    _clear()


@pytest.fixture
def ona():
    """Ona1, Ona2, Ona3 loaded through BC's own region modules (mapped)."""
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    ona3 = load_region("Ona", "Ona3")
    for s in (ona1, ona2, ona3):
        assert region_hooks.is_mapped(s), "premise: a mapped region"
    return ona1, ona2, ona3


def _ship(pSet, name, xyz=(0.0, 0.0, 0.0)):
    s = App.ShipClass_Create()
    s.SetName(name)
    pSet.AddObjectToSet(s, name)
    s.SetTranslateXYZ(*xyz)
    return s


def _make_player(pSet, xyz=(0.0, 0.0, 0.0)):
    player = _ship(pSet, "Player", xyz)
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    return player


def _planets_of(pSet):
    from engine.appc.planet import Planet, Sun
    return [o for o in pSet._objects.values()
            if isinstance(o, Planet) and not isinstance(o, Sun)]


def _at_view(view, pSet, view_xyz):
    """The set-local point of `pSet` that sits at `view_xyz` in view coords."""
    off = frames.offset_between(view, pSet)
    return tuple(v - o for v, o in zip(view_xyz, off))


def _translation(m):
    return (m[3], m[7], m[11])


def _sync(r, session, player):
    host_loop._sync_instance_transforms(
        r, session, player, TransformBuffer(), 1.0,
        game_time=1.0, model_scale=1.0)


# ── planets ─────────────────────────────────────────────────────────────────

def test_mapped_set_planets_are_never_realized(ona):
    ona1, *_ = ona
    planets = _planets_of(ona1)
    assert planets, "premise: Ona1 carries its Planet object"
    sess = host_loop.MissionSession(mission_name="t")
    host_loop.realize_set_objects(sess, ona1, _FakeRenderer())
    for p in planets:
        assert p not in sess.planet_instances


def test_mapped_set_planets_are_not_offered_to_mission_load(ona):
    """_MissionLoader._realize_session instances what _iter_planets yields."""
    ona1, *_ = ona
    _make_player(ona1)
    assert list(host_loop._iter_planets()) == []


def test_unmapped_set_planets_realize_as_today():
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "Plain")
    planet = App.Planet_Create(90.0, "data/models/environment/RedPlanet.nif")
    s.AddObjectToSet(planet, "P")
    assert not region_hooks.is_mapped(s)
    sess = host_loop.MissionSession(mission_name="t")
    host_loop.realize_set_objects(sess, s, _FakeRenderer())
    assert planet in sess.planet_instances


# ── ships ───────────────────────────────────────────────────────────────────

def test_ships_from_every_set_in_the_viewed_frame_are_realized(ona):
    ona1, ona2, _ona3 = ona
    player = _make_player(ona1)
    local = _ship(ona1, "Local", (50.0, 0.0, 0.0))
    sibling = _ship(ona2, "Sibling", _at_view(ona1, ona2, (100.0, 0.0, 0.0)))
    sb12 = SetClass_Create()
    App.g_kSetManager.AddSet(sb12, "Starbase12")
    stranger = _ship(sb12, "Stranger")
    host_loop._note_camera_eye((0.0, 0.0, 0.0))

    sess = host_loop.MissionSession(mission_name="t")
    host_loop._reconcile_runtime_instances(sess, _FakeRenderer())

    assert player in sess.ship_instances
    assert local in sess.ship_instances
    assert sibling in sess.ship_instances
    assert stranger not in sess.ship_instances


def test_ships_beyond_the_draw_distance_are_not_realized(ona):
    ona1, ona2, _ona3 = ona
    _make_player(ona1)
    d = host_loop.SHIP_DRAW_DISTANCE_GU
    far = _ship(ona2, "Far", _at_view(ona1, ona2, (3.0 * d, 0.0, 0.0)))
    host_loop._note_camera_eye((0.0, 0.0, 0.0))
    sess = host_loop.MissionSession(mission_name="t")
    host_loop._reconcile_runtime_instances(sess, _FakeRenderer())
    assert far not in sess.ship_instances


def test_the_draw_distance_has_hysteresis(ona):
    """Realized at <= D, removed only past 1.1 D: a ship on the line does not
    load and destroy its model every tick."""
    ona1, ona2, _ona3 = ona
    _make_player(ona1)
    d = host_loop.SHIP_DRAW_DISTANCE_GU
    host_loop._note_camera_eye((0.0, 0.0, 0.0))
    s = _ship(ona2, "Edge", _at_view(ona1, ona2, (0.95 * d, 0.0, 0.0)))
    sess = host_loop.MissionSession(mission_name="t")
    r = _FakeRenderer()
    host_loop._reconcile_runtime_instances(sess, r)
    assert s in sess.ship_instances

    s.SetTranslateXYZ(*_at_view(ona1, ona2, (1.05 * d, 0.0, 0.0)))
    host_loop._reconcile_runtime_instances(sess, r)
    assert s in sess.ship_instances, "inside the 10% band: kept"

    s.SetTranslateXYZ(*_at_view(ona1, ona2, (1.15 * d, 0.0, 0.0)))
    host_loop._reconcile_runtime_instances(sess, r)
    assert s not in sess.ship_instances, "past the band: removed"

    s.SetTranslateXYZ(*_at_view(ona1, ona2, (1.05 * d, 0.0, 0.0)))
    host_loop._reconcile_runtime_instances(sess, r)
    assert s not in sess.ship_instances, "inside the band: not re-realized"


def test_the_player_is_never_culled_by_distance(ona):
    ona1, *_ = ona
    player = _make_player(ona1)
    host_loop._note_camera_eye((10.0 * host_loop.SHIP_DRAW_DISTANCE_GU, 0.0, 0.0))
    sess = host_loop.MissionSession(mission_name="t")
    host_loop._reconcile_runtime_instances(sess, _FakeRenderer())
    assert player in sess.ship_instances


def test_a_sibling_ship_is_pushed_at_its_view_position(ona):
    ona1, ona2, _ona3 = ona
    player = _make_player(ona1)
    sib = _ship(ona2, "Sibling", (0.0, 0.0, 0.0))
    r = _FakeRenderer()
    sess = host_loop.MissionSession(mission_name="t")
    sess.ship_instances[player] = 1
    sess.ship_instances[sib] = 2
    sess.player = player
    _sync(r, sess, player)
    assert _translation(r.pushed[2]) == pytest.approx(
        frames.offset_between(ona1, ona2))


def test_a_same_set_ship_is_pushed_at_its_raw_position(ona):
    ona1, *_ = ona
    player = _make_player(ona1)
    other = _ship(ona1, "Other", (1.0, 2.0, 3.0))
    r = _FakeRenderer()
    sess = host_loop.MissionSession(mission_name="t")
    sess.ship_instances[player] = 1
    sess.ship_instances[other] = 2
    sess.player = player
    _sync(r, sess, player)
    assert _translation(r.pushed[2]) == (1.0, 2.0, 3.0)
    assert 1 not in r.pushed, "the player in the viewed set stays store-bound"


# ── suns and flares ─────────────────────────────────────────────────────────

def test_only_the_viewed_sets_sun_is_drawn(ona):
    ona1, *_ = ona
    _make_player(ona1)
    suns = host_loop._aggregate_suns()
    assert len(suns) == 1
    sun = ona1._objects["Sun"].GetWorldLocation()
    assert suns[0]["position"] == pytest.approx((sun.x, sun.y, sun.z))


def test_only_the_viewed_sets_lens_flare_is_drawn(ona):
    from tests.helpers.bc_assets import require_game_asset
    require_game_asset("data/textures/rays.tga")
    ona1, ona2, ona3 = ona
    for s in ona:
        assert getattr(s, "_lens_flares", []), "premise: each region built one"
    _make_player(ona1)
    flares = host_loop._aggregate_lens_flares()
    assert len(flares) == 1
    sun = ona1._objects["Sun"].GetWorldLocation()
    assert flares[0]["source_world_pos"] == pytest.approx((sun.x, sun.y, sun.z))


def test_a_sibling_region_cutscene_draws_one_consistent_scene(ona):
    """Review Focus 4: a cutscene rendered at Ona2 while the player stays in
    Ona1 -- one sun (Ona2's) and the player in Ona2's coordinates."""
    ona1, ona2, _ona3 = ona
    player = _make_player(ona1, (5.0, 6.0, 7.0))
    App.g_kSetManager.MakeRenderedSet("Ona2")
    assert host_loop._live_sets() == [ona2]

    (sun,) = host_loop._aggregate_suns()
    s2 = ona2._objects["Sun"].GetWorldLocation()
    assert sun["position"] == pytest.approx((s2.x, s2.y, s2.z))

    r = _FakeRenderer()
    sess = host_loop.MissionSession(mission_name="t")
    sess.ship_instances[player] = 1
    sess.player = player
    _sync(r, sess, player)
    off = frames.offset_between(ona2, ona1)
    assert _translation(r.pushed[1]) == pytest.approx(
        (5.0 + off[0], 6.0 + off[1], 7.0 + off[2]))


# ── dust ────────────────────────────────────────────────────────────────────

def test_dust_in_a_mapped_frame_comes_from_the_map(ona):
    ona1, *_ = ona
    _make_player(ona1)
    got = host_loop._aggregate_dust_planets(ona1)
    want = [{"position": b.position, "radius": b.radius_gu}
            for b in celestial.draw_list(ona1)]
    assert want, "premise: the Ona map has bodies"
    assert got == want


def test_dust_in_an_unmapped_frame_is_unchanged():
    from engine.appc.planet import Planet
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "Plain")
    p = Planet(123.0, "")
    p.SetWorldLocation(TGPoint3(1.0, 2.0, 3.0))
    s.AddObjectToSet(p, "P")
    assert host_loop._aggregate_dust_planets(s) == [
        {"position": (1.0, 2.0, 3.0), "radius": 123.0}]


# ── hum ─────────────────────────────────────────────────────────────────────

def test_hum_roster_drops_ships_beyond_audible_range(ona):
    from engine.audio import hum_allocator
    ona1, ona2, _ona3 = ona
    App.g_kSetManager.MakeRenderedSet("Ona1")
    near = _ship(ona1, "Near", (10.0, 0.0, 0.0))
    far = _ship(ona2, "Far", _at_view(ona1, ona2, (40000.0, 0.0, 0.0)))
    names = {s.GetName()
             for s in hum_allocator._roster(listener_pos=(0.0, 0.0, 0.0))}
    assert names == {"Near"}
    # No listener: the unfiltered roster (the frame scope alone).
    assert {s.GetName() for s in hum_allocator._roster()} == {"Near", "Far"}
    assert far is not None
