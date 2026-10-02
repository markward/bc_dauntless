"""Large scenery rocks (the rock-fields near band) collide with the player
(rock-fields plan Task 8, spec section 2). The native near band reports a
swept touch; engine.rocks.scenery_contact bounces and damages the player.

Fixture geometry: hull box half-extents (0.5, 1.0, 0.25), so the shield
bubble's forward semi-axis is sqrt(3) = 1.732. The contact rock sits at
(0, 3, 0): with radius 2 its centre is OUTSIDE that bubble and touching it
(3 - 1.732 < 2), so the shielded fixture bounces at the bubble.
"""
import App
import pytest

from engine.appc import combat
from engine.appc.math import TGPoint3
from engine.rocks import scenery_contact as sc, far_dials
from tests.helpers.viewed_set import place_in_viewed_set, release_viewed_set
from tests.unit.test_rock_shield_collision import _ship

HALF = (0.5, 1.0, 0.25)


@pytest.fixture(autouse=True)
def _reset():
    App.g_kSetManager._sets.clear()
    sc.reset(); far_dials.reset()
    yield
    sc.reset(); far_dials.reset()
    release_viewed_set()
    App.g_kSetManager._sets.clear()


def _player(vy, shields_up=False):
    ship = _ship(name="Player %d" % id(object()), shields_up=shields_up,
                 half=HALF)
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ship.SetVelocity(TGPoint3(0.0, vy, 0.0))
    return place_in_viewed_set(ship)


@pytest.fixture
def player_factory():
    return lambda vy=6.0: _player(vy)


@pytest.fixture
def player_moving_up():
    return _player(6.0)


@pytest.fixture
def player_moving_up_shielded():
    return _player(6.0, shields_up=True)


@pytest.fixture
def player_moving_down():
    return _player(-6.0)


@pytest.fixture
def calls(monkeypatch):
    out = []

    def _apply_hit(ship, damage, hit_point, source, **kw):
        out.append(dict(kw, ship=ship, damage=damage, point=hit_point,
                        source=source))

    monkeypatch.setattr(combat, "apply_hit", _apply_hit)
    return out


def _contact(normal=(0.0, -1.0, 0.0), pen=0.1, radius=2.0):
    return {"point": (0.0, 1.0, 0.0), "normal": normal, "rock_centre": (0.0, 3.0, 0.0),
            "rock_radius": radius, "rel_speed": 6.0, "pen": pen}


def test_hull_hit_bounces_and_damages(player_moving_up, calls):
    out = sc.respond(player_moving_up, _contact())
    assert out is not None and out["shielded"] is False
    assert out["impulse"][1] < 0.0                     # pushed back down -Y
    (hit,) = calls
    assert hit["bypass_shields"] is True and hit["weapon_type"] == "collision"
    assert hit["damage"] > 0.0
    assert hit["source"] is None and hit["single_impact"] is True
    # The overlay carries the impulse; the ship de-penetrated along -Y.
    cv = player_moving_up.__dict__["_collision_velocity"]
    assert cv.y == pytest.approx(out["impulse"][1])
    assert player_moving_up.GetTranslate().y == pytest.approx(-0.1)


def test_shield_up_bounces_at_the_bubble(player_moving_up_shielded, calls):
    out = sc.respond(player_moving_up_shielded, _contact())
    assert out["shielded"] is True
    (hit,) = calls
    assert hit["bypass_shields"] is False and hit["shield_point"] is not None


def test_receding_does_nothing(player_moving_down, calls):
    assert sc.respond(player_moving_down, _contact()) is None
    assert calls == []


def test_damage_scales_with_speed_and_size(player_factory, calls):
    slow = sc.respond(player_factory(vy=2.0), _contact(radius=5.0))["damage"]
    fast = sc.respond(player_factory(vy=6.0), _contact(radius=5.0))["damage"]
    small = sc.respond(player_factory(vy=6.0), _contact(radius=1.0))["damage"]
    assert fast == pytest.approx(slow * 9.0, rel=1e-6)
    assert small == pytest.approx(fast / 5.0, rel=1e-6)


def test_player_outside_the_viewed_set_is_ignored(calls):
    ship = _ship(name="Elsewhere", shields_up=False, half=HALF)
    ship.SetVelocity(TGPoint3(0.0, 6.0, 0.0))
    other = App.SetClass_Create()
    App.g_kSetManager.AddSet(other, "Elsewhere")
    other.AddObjectToSet(ship, "Elsewhere")
    place_in_viewed_set(_ship(name="Someone", half=HALF))
    assert sc.respond(ship, _contact()) is None
    assert calls == []


def test_muted_while_dashing_or_in_warp(player_moving_up, calls, monkeypatch):
    monkeypatch.setattr("engine.rocks.minor_contact._muted", lambda p: True)
    assert sc.pump(player_moving_up, contacts=[_contact()]) == []
    assert calls == []


def test_pump_responds_to_each_contact(player_moving_up, calls, monkeypatch):
    monkeypatch.setattr("engine.rocks.minor_contact._muted", lambda p: False)
    out = sc.pump(player_moving_up, contacts=[_contact()])
    assert len(out) == 1 and len(calls) == 1


def test_shield_inflate_follows_shields(player_moving_up, player_moving_up_shielded):
    from engine.appc.combat import SHIELD_ELLIPSOID_AXIS_SCALE
    assert sc.shield_inflate(player_moving_up) == 0.0
    assert sc.shield_inflate(player_moving_up_shielded) == pytest.approx(SHIELD_ELLIPSOID_AXIS_SCALE)


def test_far_tier_reconcile_pushes_the_shield_inflate(player_moving_up_shielded):
    from engine.appc.combat import SHIELD_ELLIPSOID_AXIS_SCALE
    from engine.rocks import far_tier
    pushed = []

    class _R:
        def __getattr__(self, name):
            return lambda *a, **k: None

        def rockfield_set_shield_inflate(self, scale):
            pushed.append(scale)

    class _Session:
        player = player_moving_up_shielded
        ship_instances = {}
        scope_hidden = ()

    try:
        far_tier.reconcile(_Session(), _R())
    finally:
        far_tier.reset()
    assert pushed == [pytest.approx(SHIELD_ELLIPSOID_AXIS_SCALE)]
