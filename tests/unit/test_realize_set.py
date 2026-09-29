import pytest

import App
from engine.appc.sets import SetClass_Create


class _FakeRenderer:
    def __init__(self):
        self._next = 1
        self.live = set()

    def load_model(self, path, search, texture_replacements=None, decals=None):
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
        pass

    def set_rim_eligible(self, iid, b):
        pass

    def set_rim_strength(self, iid, s):
        pass


def test_realize_then_teardown(monkeypatch):
    from engine import host_loop as hl
    # Force a NIF path so the ship is realizable without real assets.
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")
    sess = hl.MissionSession(mission_name="t")
    r = _FakeRenderer()
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    ship = App.ShipClass_Create()
    ship.SetName("rock")
    s.AddObjectToSet(ship, "rock")

    hl.realize_set_objects(sess, s, r)
    assert ship in sess.ship_instances and len(r.live) == 1
    # idempotent
    hl.realize_set_objects(sess, s, r)
    assert len(r.live) == 1

    hl.teardown_set_objects(sess, s, r)
    assert ship not in sess.ship_instances and len(r.live) == 0


def test_rerealize_after_departure_uses_the_current_radius(monkeypatch):
    """Warping back into a set you left: departure tore its instances down,
    arrival re-realizes them. planet_natural_scale is cached per realize, so
    the re-realized planet must be scaled from its CURRENT radius -- the map's
    -- never a stale one. The failure this guards is a body DRAWN at one
    radius and TARGETED at another."""
    from engine import host_loop as hl
    monkeypatch.setattr(hl, "_planet_nif_path", lambda planet, **k: "fake.nif")
    sess = hl.MissionSession(mission_name="t")
    r = _FakeRenderer()
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    planet = App.Planet_Create(90.0, "data/models/environment/RedPlanet.nif")
    s.AddObjectToSet(planet, "Ona 1")

    hl.realize_set_objects(sess, s, r)
    scale_at_90 = sess.planet_natural_scale[planet]
    hl.teardown_set_objects(sess, s, r)
    assert planet not in sess.planet_instances

    planet.SetRadius(1800.0)
    hl.realize_set_objects(sess, s, r)
    assert sess.planet_natural_scale[planet] == pytest.approx(20.0 * scale_at_90)
