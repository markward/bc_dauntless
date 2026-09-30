import App
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import ShipProperty, HullProperty, ShieldProperty


def _make(genus):
    ship = ShipClass_Create("Test")
    ps = ship.GetPropertySet()
    sp = ShipProperty("Mass")
    sp.SetGenus(genus)
    sp.SetMass(400.0)
    ps.AddToSet("Scene Root", sp)
    hp = HullProperty("Hull")
    hp.SetMaxCondition(2500.0)
    hp.SetCritical(1)
    hp.SetPrimary(1)
    hp.SetRadius(0.8)
    ps.AddToSet("Scene Root", hp)
    ship.SetupProperties()
    return ship


def _make_with_shields(genus, max_shield=100.0):
    """Mirrors a stock hardpoint's ShieldGenerator (see e.g.
    sdk/.../ships/Hardpoints/asteroid.py), but with a NON-zero MaxShields on
    every face -- the modded-rock case the fix targets."""
    ship = ShipClass_Create("Test")
    ps = ship.GetPropertySet()
    sp = ShipProperty("Mass")
    sp.SetGenus(genus)
    sp.SetMass(400.0)
    ps.AddToSet("Scene Root", sp)
    hp = HullProperty("Hull")
    hp.SetMaxCondition(2500.0)
    hp.SetCritical(1)
    hp.SetPrimary(1)
    hp.SetRadius(0.8)
    ps.AddToSet("Scene Root", hp)
    shp = ShieldProperty("Shield Generator")
    shp.SetMaxCondition(200.0)
    shp.SetCritical(0)
    shp.SetTargetable(0)
    shp.SetPrimary(1)
    for face in range(ShieldProperty.NUM_SHIELDS):
        shp.SetMaxShields(face, max_shield)
        shp.SetShieldChargePerSecond(face, 1.0)
    ps.AddToSet("Scene Root", shp)
    ship.SetupProperties()
    return ship


def test_genus_asteroid_becomes_rock():
    from engine.rocks.rock import RockClass, is_rock
    rock = _make(App.GENUS_ASTEROID)
    assert isinstance(rock, RockClass)
    assert is_rock(rock)
    assert rock.GetGenus() == App.GENUS_ASTEROID


def test_other_genus_stays_ship():
    from engine.rocks.rock import is_rock
    ship = _make(App.GENUS_SHIP)
    assert not is_rock(ship)


def test_setup_properties_twice_is_idempotent():
    from engine.rocks.rock import RockClass
    rock = _make(App.GENUS_ASTEROID)
    rock._rock_family = "icy"
    rock.SetupProperties()
    assert type(rock) is RockClass
    assert rock._rock_family == "icy"      # _become_rock must not reset state


def test_rock_passes_sdk_casts():
    rock = _make(App.GENUS_ASTEROID)
    assert App.ShipClass_Cast(rock) is rock
    assert App.DamageableObject_Cast(rock) is rock
    assert App.ObjectClass_Cast(rock) is rock


def test_rock_keeps_authored_hull_and_mass():
    rock = _make(App.GENUS_ASTEROID)
    assert rock.GetHull().GetMaxCondition() == 2500.0
    assert rock.GetMass() == 400.0


def test_rock_shields_do_not_block():
    from engine.appc.combat import shields_block
    rock = _make(App.GENUS_ASTEROID)
    assert shields_block(rock) is False


def test_rock_with_nonzero_shield_hardpoint_still_unshielded():
    """Spec §1: 'Shield maxima are zeroed so shields_block is false' --
    unconditionally, even when a genus-3 hardpoint (a modded rock) declares
    a ShieldProperty with real non-zero MaxShields on every face."""
    from engine.appc.combat import shields_block
    rock = _make_with_shields(App.GENUS_ASTEROID, max_shield=100.0)
    assert shields_block(rock) is False
    shields = rock.GetShields()
    assert shields is not None
    for face in range(ShieldProperty.NUM_SHIELDS):
        assert shields.GetMaxShields(face) == 0.0


def test_set_ai_on_rock_is_inert():
    rock = _make(App.GENUS_ASTEROID)
    rock.SetAI(object())
    assert rock.GetAI() is None


def test_loops_skip_rocks(monkeypatch):
    from engine.appc import ship_iter
    rock = _make(App.GENUS_ASTEROID)
    ship = _make(App.GENUS_SHIP)
    monkeypatch.setattr(ship_iter, "iter_ships", lambda **kw: iter([rock, ship]))
    assert list(ship_iter.iter_non_rock_ships()) == [ship]
    assert list(ship_iter.iter_rocks()) == [rock]
