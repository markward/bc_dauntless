import App
from engine.appc.combat import shields_block


def test_rock_class_create_derives_stats_from_size():
    from engine.rocks.rock import RockClass_Create, is_rock
    r = RockClass_Create(1.6, family="icy", seed="x", name="Asteroid 9-1")
    assert is_rock(r)
    assert r.GetName() == "Asteroid 9-1"
    assert r.GetGenus() == App.GENUS_ASTEROID
    assert r.GetRadius() == 1.6
    assert abs(r.GetHull().GetMaxCondition() - 10000.0) < 1e-6
    assert r.GetHull().GetCondition() == r.GetHull().GetMaxCondition()
    assert r.GetHull().IsCritical()
    assert abs(r.GetMass() - 3200.0) < 1e-6
    assert shields_block(r) is False
    assert r._rock_family == "icy"


def test_rock_class_create_explicit_hull_and_mass_win():
    from engine.rocks.rock import RockClass_Create
    r = RockClass_Create(1.6, hull=123.0, mass=7.0, name="p")
    assert r.GetHull().GetMaxCondition() == 123.0
    assert r.GetMass() == 7.0


def test_rock_model_override_is_a_catalogue_fragment():
    from engine.rocks.rock import RockClass_Create, rock_model_override
    r = RockClass_Create(1.2, family="silicate", seed="abc", name="p")
    path, scale = rock_model_override(r)
    assert "/fragments/silicate_" in path.replace("\\", "/")
    assert path.endswith("lod0.gltf")
    # Renders at r GU: glTF metres * (1/1.75) MU * scale * BC_MODEL_SCALE (0.01).
    from engine.rocks import catalogue
    rock = next(r for r in catalogue.load()
                if path.replace("\\", "/").endswith(r.lod_paths[0]))
    assert abs(scale - 1.2 * 175.0 / rock.bound_radius_m) < 1e-9
    assert abs(rock.bound_radius_m / 1.75 * scale * 0.01 - 1.2) < 1e-9


def test_model_override_survives_catalogue_toggle_off():
    from engine.rocks import catalogue
    from engine.rocks.rock import RockClass_Create, rock_model_override
    catalogue.set_enabled(False)
    r = RockClass_Create(1.2, seed="abc", name="p")
    assert rock_model_override(r) is not None


def test_same_seed_same_model():
    from engine.rocks.rock import RockClass_Create, rock_model_override
    a = RockClass_Create(1.2, seed="Asteroid 5-1", name="a")
    b = RockClass_Create(1.2, seed="Asteroid 5-1", name="b")
    assert rock_model_override(a) == rock_model_override(b)


def test_damageable_object_create_asteroid_is_a_rock():
    import ships.Asteroid
    ships.Asteroid.LoadModel()
    obj = App.DamageableObject_Create("Asteroid")
    from engine.rocks.rock import is_rock, rock_model_override
    assert is_rock(obj)
    obj.SetMass(400.0)
    obj.SetScale(4.0)
    assert obj.GetMass() == 400.0
    assert rock_model_override(obj) is not None


def test_radius_is_quantised_but_hull_and_mass_use_the_exact_radius():
    from engine.rocks import stats
    from engine.rocks.rock import RockClass_Create
    r = RockClass_Create(1.2345, seed="q", name="q")
    assert r.GetRadius() == 1.2
    assert r.GetHull().GetRadius() == 1.2
    assert abs(r.GetHull().GetMaxCondition() - stats.size_hull(1.2345)) < 1e-6
    assert abs(r.GetMass() - stats.size_mass(1.2345)) < 1e-6


def test_radii_equal_after_quantisation_share_one_override():
    from engine.rocks.rock import RockClass_Create, rock_model_override
    a = RockClass_Create(1.2345, seed="same", name="a")
    b = RockClass_Create(1.2049, seed="same", name="b")
    assert rock_model_override(a) == rock_model_override(b)


def test_render_scale_constant_matches_host_loop():
    from engine import host_loop
    from engine.rocks import rock
    assert rock._BC_MODEL_SCALE == host_loop.BC_MODEL_SCALE
