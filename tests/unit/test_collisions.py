import App
import pytest
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.planet import Planet_Create


def _reset_app_state():
    App.g_kSetManager._sets.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _ship(x, mass, vx, radius=1.0):
    s = ShipClass()
    s.SetTranslateXYZ(x, 0.0, 0.0)
    s.SetRadius(radius)
    s.SetMass(mass)
    s.SetVelocity(TGPoint3(vx, 0.0, 0.0))
    return s


def test_resolve_body_ship_is_movable_with_inverse_mass():
    from engine.appc.collisions import _resolve_body
    b = _resolve_body(_ship(5.0, 1000.0, 3.0))
    assert b.is_movable is True
    assert b.inv_mass == pytest.approx(1.0 / 1000.0)
    assert b.center.x == pytest.approx(5.0)
    assert b.radius == pytest.approx(1.0)
    assert b.velocity.x == pytest.approx(3.0)


def test_resolve_body_zero_mass_ship_uses_fallback():
    from engine.appc.collisions import _resolve_body, COLLISION_FALLBACK_MASS
    s = ShipClass(); s.SetRadius(1.0)  # mass defaults to 0.0
    b = _resolve_body(s)
    assert b.inv_mass == pytest.approx(1.0 / COLLISION_FALLBACK_MASS)


def test_resolve_body_planet_is_immovable():
    from engine.appc.collisions import _resolve_body
    p = Planet_Create(170.0, "")
    p.SetTranslateXYZ(0.0, 0.0, 0.0)
    b = _resolve_body(p)
    assert b.is_movable is False
    assert b.inv_mass == 0.0
    assert b.velocity.x == 0.0 and b.velocity.y == 0.0 and b.velocity.z == 0.0


def test_resolve_body_includes_collision_overlay_in_velocity():
    from engine.appc.collisions import _resolve_body
    s = _ship(0.0, 1000.0, 2.0)
    s._collision_velocity = TGPoint3(5.0, 0.0, 0.0)
    b = _resolve_body(s)
    assert b.velocity.x == pytest.approx(7.0)  # 2.0 thrust + 5.0 overlay


def test_ke_damage_scales_with_velocity_squared():
    from engine.appc.collisions import _ke_damage
    inv_sum = 1.0 / 500.0  # mu = 500
    d1 = _ke_damage(inv_sum, -10.0)
    d2 = _ke_damage(inv_sum, -20.0)
    assert d2 == pytest.approx(4.0 * d1)
