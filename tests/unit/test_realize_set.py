import pytest

import App
from engine.appc.sets import SetClass_Create


class _FakeRenderer:
    def __init__(self):
        self._next = 1
        self.live = set()
        self.atmospheres = []

    def load_model(self, path, search, texture_replacements=None, decals=None,
                   scale=1.0, geosphere=False):
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

    def set_surface_rock(self, iid, rock):
        pass

    def set_instance_atmosphere(self, iid, params):
        self.atmospheres.append((iid, params))


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
    first_iid = sess.planet_instances[planet]
    assert any(iid == first_iid for iid, _params in r.atmospheres)
    hl.teardown_set_objects(sess, s, r)
    assert planet not in sess.planet_instances

    planet.SetRadius(1800.0)
    hl.realize_set_objects(sess, s, r)
    assert sess.planet_natural_scale[planet] == pytest.approx(20.0 * scale_at_90)


def test_realize_marks_rock_surface_rock_true(monkeypatch):
    """set_surface_rock is called for a genus-3 rock (rock-class spec §2); a
    normal ship must never receive the call."""
    from tests.unit.test_rock_class import _make
    from engine import host_loop as hl

    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")

    class _Recording(_FakeRenderer):
        def __init__(self):
            super().__init__()
            self.surface_rock_calls = []

        def set_surface_rock(self, iid, rock):
            self.surface_rock_calls.append((iid, rock))

    sess = hl.MissionSession(mission_name="t")
    r = _Recording()
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")

    rock = _make(App.GENUS_ASTEROID)
    normal_ship = App.ShipClass_Create()
    normal_ship.SetName("normal")
    s.AddObjectToSet(rock, "rock")
    s.AddObjectToSet(normal_ship, "normal")

    hl.realize_set_objects(sess, s, r)

    rock_iid = sess.ship_instances[rock]
    normal_iid = sess.ship_instances[normal_ship]
    assert (rock_iid, True) in r.surface_rock_calls
    assert not any(iid == normal_iid for iid, _ in r.surface_rock_calls)


def test_script_less_rock_realises_its_catalogue_fragment(monkeypatch):
    """A RockClass_Create rock has no ship script, so _ship_nif_path finds no
    model for it; realize_set_objects must load its catalogue fragment
    (rock_model_override) and create an instance of that model instead of
    skipping it."""
    from engine import host_loop as hl
    from engine.rocks.rock import RockClass_Create, rock_model_override
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: None)

    class _Recording(_FakeRenderer):
        def __init__(self):
            super().__init__()
            self.handles = {}
            self.instanced = []

        def load_model(self, path, search, texture_replacements=None, decals=None, **kw):
            h = 200 + len(self.handles)
            self.handles[h] = (path, kw)
            return h

        def create_instance(self, h):
            self.instanced.append(self.handles[h])
            return super().create_instance(h)

    sess = hl.MissionSession(mission_name="t")
    r = _Recording()
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    rock = RockClass_Create(1.5, seed="Asteroid 1-1", name="Asteroid 1-1")
    s.AddObjectToSet(rock, "Asteroid 1-1")

    hl.realize_set_objects(sess, s, r)

    frag_path, frag_scale = rock_model_override(rock)
    assert rock in sess.ship_instances
    assert r.instanced == [(frag_path, {"scale": frag_scale})]
    assert frag_path.endswith("lod0.gltf") and frag_scale != 1.0
    assert rock.GetRadius() == 1.5


def test_script_less_rock_realises_in_mission_loader_session(monkeypatch):
    """Seam 2 (_MissionLoader._realize_session, the mission-load path) takes
    the same rock_model_override branch as realize_set_objects."""
    from engine import host_loop as hl
    from engine.rocks.rock import RockClass_Create, rock_model_override
    rock = RockClass_Create(1.5, seed="Asteroid 1-1", name="Asteroid 1-1")
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: None)
    monkeypatch.setattr(hl, "_iter_active_ships", lambda **k: [rock])
    monkeypatch.setattr(hl, "_iter_active_planets", lambda **k: [], raising=False)

    loaded = []

    class _Recording(_FakeRenderer):
        def load_model(self, path, search, texture_replacements=None, decals=None, **kw):
            loaded.append(path)
            return 100

    controller = hl.HostController()
    controller.renderer = _Recording()
    controller.loader = hl._MissionLoader(controller, verbose=False)
    sess = controller.loader._realize_session(hl.MissionSession(mission_name="t"))

    assert rock in sess.ship_instances
    assert loaded == [rock_model_override(rock)[0]]
