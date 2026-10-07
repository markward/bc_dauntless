"""The sky round trip (system-frames Plan 3, Task 7, Review Focus 3).

Pins the reference branch's live bug as a test: a body visible from one
region of a system went missing (or ghosted) after warping to a sibling
region and back. Drives a REAL warp -- _WarpDepartAction /
ChangeRenderedSetAction / _ArriveFinalizeAction, the same primitives
WarpSequence itself plays -- through Ona1 -> tunnel -> Ona2 -> tunnel ->
Ona1, and at every station checks both halves of Task 4's contract:
celestial.draw_list(frames.viewing_set()) is exactly the Ona map's
non-star bodies in that station's own coordinates, and
_reconcile_celestial_instances leaves exactly one render instance per
draw-list key -- no ghost surviving from a set we left, none missing for
one we just entered.

Fake renderer mirrors tests/host/test_celestial_instances.py.
"""
import pytest

import App
import engine.host_loop as host_loop
from engine.appc import warp
from engine.systems import celestial, frames, resolve
from tests.helpers.mapped_regions import load_region

_HALF = 2.0     # the fake model's bound-sphere radius


class _FakeRenderer:
    def __init__(self):
        self._next = 1
        self.live = set()
        self.pushed = {}

    def load_model(self, path, search, texture_replacements=None, decals=None,
                   scale=1.0, geosphere=False):
        return 100

    def model_aabb(self, h):
        return ((0.0, 0.0, 0.0), (_HALF, _HALF, _HALF))

    def create_instance(self, h):
        iid = self._next
        self._next += 1
        self.live.add(iid)
        return iid

    def destroy_instance(self, iid):
        self.live.discard(iid)

    def set_world_transform(self, iid, m):
        self.pushed[iid] = m

    def set_emissive_scale(self, iid, s):
        pass

    def set_rim_eligible(self, iid, b):
        pass

    def set_surface_rock(self, iid, rock):
        pass

    def set_rim_strength(self, iid, s):
        pass

    def nebula_lightning_enabled(self):
        return False

    def set_visible(self, iid, v):
        pass

    def set_instance_atmosphere(self, iid, params):
        pass


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    def _clear():
        App.g_kSetManager._sets.clear()
        App.g_kSetManager.ClearRenderedSet()
        warp.configure_warp_hooks(realize=None, teardown=None)
        host_loop._mapped_body_warned.clear()
    _clear()
    monkeypatch.setattr(host_loop, "_planet_model_path",
                        lambda rel, **k: f"/fake/{rel}")
    yield
    _clear()


def _ship_in(pSet, name):
    ship = App.ShipClass_Create()
    ship.SetName(name)
    pSet.AddObjectToSet(ship, name)
    return ship


def _reconcile(sess, r):
    host_loop._reconcile_celestial_instances(sess, r)


def _assert_station(view_set, sess, r):
    """The draw list of view_set is exactly Ona's three planets in
    view_set's own coordinates, and reconciling leaves one live instance per
    key -- no ghost from a sibling region, none missing for this one."""
    assert frames.viewing_set() is view_set
    drawn = celestial.draw_list(view_set)
    m = resolve.map_of("Ona")
    non_star = [b for b in m.bodies if b.orbits is not None]
    assert len(non_star) == 3, "premise: Ona's three planets"
    assert len(drawn) == 3

    ax, ay, az = resolve.anchor_of(view_set.GetName())
    got = {b.key: b.position for b in drawn}
    expect = {
        (m.system, b.owner_region or "", b.name):
            (b.position_gu[0] - ax, b.position_gu[1] - ay, b.position_gu[2] - az)
        for b in non_star
    }
    assert got.keys() == expect.keys()
    for k in got:
        assert got[k] == pytest.approx(expect[k])

    _reconcile(sess, r)
    assert set(sess.celestial_instances) == {b.key for b in drawn}
    assert len(set(sess.celestial_instances.values())) == len(drawn), (
        "no two keys sharing one instance -- the ghost shape of the bug")
    for iid in sess.celestial_instances.values():
        assert iid in r.live


def _assert_tunnel(sess, r):
    view = frames.viewing_set()
    assert view is not None and view.GetName() == warp._WARP_TRANSIT_SET_NAME
    assert celestial.draw_list(view) == ()
    _reconcile(sess, r)
    assert sess.celestial_instances == {}


def test_the_sky_round_trip_ona1_ona2_ona1(monkeypatch):
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    ship = _ship_in(ona1, "player")
    # The player's warp: an NPC's leaves the rendered set alone.
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: ship)
    App.g_kSetManager.MakeRenderedSet("Ona1")

    sess = host_loop.MissionSession(mission_name="t")
    r = _FakeRenderer()

    _assert_station(ona1, sess, r)

    # Ona1 -> tunnel.
    warp._WarpDepartAction(ona1, ship).Play()
    _assert_tunnel(sess, r)
    assert App.g_kSetManager.GetSet("Ona1") is ona1, "departure never deletes"

    # tunnel -> Ona2 (adopts the already-loaded region, no re-Initialize).
    warp.ChangeRenderedSetAction_Create("Systems.Ona.Ona2").Play()
    warp._ArriveFinalizeAction(ona1, ship).Play()
    assert App.g_kSetManager.GetSet("Ona2") is ona2
    _assert_station(ona2, sess, r)

    # Ona2 -> tunnel.
    warp._WarpDepartAction(ona2, ship).Play()
    _assert_tunnel(sess, r)
    assert App.g_kSetManager.GetSet("Ona2") is ona2, "departure never deletes"

    # tunnel -> Ona1 (still standing since the first departure -- Plan 3
    # Task 2 -- so this is an adoption too, and the reference branch's bug is
    # exactly here: a ghost or a gap in Ona1's sky on the way back).
    warp.ChangeRenderedSetAction_Create("Systems.Ona.Ona1").Play()
    warp._ArriveFinalizeAction(ona2, ship).Play()
    assert App.g_kSetManager.GetSet("Ona1") is ona1
    _assert_station(ona1, sess, r)


def _translation(m):
    return (m[3], m[7], m[11])


def test_the_frame_that_changes_the_view_pushes_bodies_in_the_new_view():
    """REGRESSION (final review I2). host_loop._reconcile_scene is the block
    the frame runs AFTER its sim section (ordering pinned by
    tests/host/test_scene_reconcile_ordering.py). Run after a sim step that
    moves the player Ona1 -> Ona2, every map body it pushes is in Ona2's
    coordinates THAT frame -- not Ona1's, ~50,000 GU away, which is what the
    frame drew while the reconcile ran before the sim."""
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    ship = _ship_in(ona1, "player")
    App.g_kSetManager.MakeRenderedSet("Ona1")
    sess = host_loop.MissionSession(mission_name="t")
    r = _FakeRenderer()
    host_loop._reconcile_scene(sess, r)
    assert frames.viewing_set() is ona1

    # The frame's sim changes the view: the warp primitives WarpSequence
    # plays, departure through arrival.
    warp._WarpDepartAction(ona1, ship).Play()
    warp.ChangeRenderedSetAction_Create("Systems.Ona.Ona2").Play()
    warp._ArriveFinalizeAction(ona1, ship).Play()
    assert frames.viewing_set() is ona2

    r.pushed.clear()
    host_loop._reconcile_scene(sess, r)
    drawn = {b.key: b.position for b in celestial.draw_list(ona2)}
    assert drawn and set(sess.celestial_instances) == set(drawn)
    for key, iid in sess.celestial_instances.items():
        assert _translation(r.pushed[iid]) == pytest.approx(drawn[key]), key
