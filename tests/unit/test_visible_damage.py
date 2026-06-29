"""Tests for the BC visible-damage API -> hull-carve path
(engine/appc/visible_damage.py + DamageableObject delegators)."""
import pytest

from engine.appc import visible_damage
from engine.appc.hull_carve import MIN_CARVE_RADIUS_GU
from engine.appc.math import TGMatrix3, TGPoint3


class _Ship:
    def __init__(self, loc=None, rot=None, radius_mod=None):
        self._loc = loc or TGPoint3(0.0, 0.0, 0.0)
        self._rot = rot or TGMatrix3()  # identity
        if radius_mod is not None:
            self._vis_dmg_radius_mod = radius_mod

    def GetWorldLocation(self):  return self._loc
    def GetWorldRotation(self):  return self._rot


class _Host:
    def __init__(self):
        self.carves = []  # (iid, point, normal, radius, time)

    def hull_carve_add(self, iid, point, normal, radius, time):
        self.carves.append((iid, point, normal, radius, time))


@pytest.fixture(autouse=True)
def _clean():
    visible_damage.reset()
    yield
    visible_damage.reset()


# ── Body-frame authored volumes ─────────────────────────────────────────────

def test_body_volume_emits_world_point_and_floored_radius():
    ship = _Ship()
    host = _Host()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    visible_damage.advance(0.0, host, {ship: 7})

    assert len(host.carves) == 1
    iid, point, normal, radius, _t = host.carves[0]
    assert iid == 7
    # Identity rotation, ship at origin -> world point == body point.
    assert point == pytest.approx((1.0, 0.0, 0.0))
    # Outward radial normal (unit).
    assert normal == pytest.approx((1.0, 0.0, 0.0))
    # radius = max(floor, influRad).
    assert radius == pytest.approx(max(MIN_CARVE_RADIUS_GU, 0.5))


def test_body_volume_respects_ship_position_and_rotation():
    # 90 deg about Z: body (1,0,0) -> world (0,1,0), offset by ship location.
    rot = TGMatrix3().MakeZRotation(3.14159265358979 / 2.0)
    ship = _Ship(loc=TGPoint3(10.0, -5.0, 2.0), rot=rot)
    host = _Host()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    visible_damage.advance(0.0, host, {ship: 1})

    _iid, point, normal, _r, _t = host.carves[0]
    assert point == pytest.approx((10.0, -4.0, 2.0))   # loc + R.(1,0,0)
    assert normal == pytest.approx((0.0, 1.0, 0.0))


def test_radius_modifier_scales_emitted_radius():
    ship = _Ship(radius_mod=2.0)
    host = _Host()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    visible_damage.advance(0.0, host, {ship: 1})

    _iid, _p, _n, radius, _t = host.carves[0]
    assert radius == pytest.approx(max(MIN_CARVE_RADIUS_GU, 0.5) * 2.0)


# ── Deferral until the render instance is realized ──────────────────────────

def test_defers_until_instance_realized_then_emits_once():
    ship = _Ship()
    host = _Host()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)

    # Not yet realized: kept, no emit.
    visible_damage.advance(0.1, host, {})
    assert host.carves == []
    assert len(visible_damage._pending) == 1

    # Realized: emits exactly once...
    visible_damage.advance(0.1, host, {ship: 4})
    assert len(host.carves) == 1
    # ...and is not re-emitted on the next tick.
    visible_damage.advance(0.1, host, {ship: 4})
    assert len(host.carves) == 1
    assert visible_damage._pending == []


def test_unrealized_entry_ages_out():
    ship = _Ship()
    host = _Host()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    # Never realized; age past MAX_PENDING_AGE -> dropped, never emitted.
    visible_damage.advance(visible_damage.MAX_PENDING_AGE + 1.0, host, {})
    assert host.carves == []
    assert visible_damage._pending == []


def test_no_host_or_no_binding_is_safe():
    ship = _Ship()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    visible_damage.advance(0.1, host=None, ship_instances={ship: 1})  # no host
    visible_damage.advance(0.1, host=object(), ship_instances={ship: 1})  # no binding
    assert len(visible_damage._pending) == 1  # still waiting, nothing emitted


# ── Runtime world-space carve (AddDamage / DeathExplosionDamage) ────────────

def test_world_carve_passes_point_through_with_radial_normal():
    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0))
    host = _Host()
    visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.0), 0.6, 600.0)
    visible_damage.advance(0.0, host, {ship: 2})

    _iid, point, normal, radius, _t = host.carves[0]
    assert point == pytest.approx((13.0, 4.0, 0.0))   # already world-space
    assert normal == pytest.approx((0.6, 0.8, 0.0))   # unit (point - loc)
    assert radius == pytest.approx(max(MIN_CARVE_RADIUS_GU, 0.6))


# ── clear / reset ───────────────────────────────────────────────────────────

def test_clear_for_drops_only_that_ships_pending():
    a, b = _Ship(), _Ship()
    visible_damage.queue_body_volume(a, 1, 0, 0, 0.5, 1)
    visible_damage.queue_body_volume(b, 1, 0, 0, 0.5, 1)
    visible_damage.clear_for(a)
    assert len(visible_damage._pending) == 1
    assert visible_damage._pending[0]["ship"] is b


def test_none_ship_is_ignored():
    visible_damage.queue_body_volume(None, 1, 0, 0, 0.5, 1)
    visible_damage.queue_world_carve(None, TGPoint3(0, 0, 0), 0.5, 1)
    assert visible_damage._pending == []


# ── DamageableObject delegators ─────────────────────────────────────────────

def test_damageable_object_methods_route_to_visible_damage():
    from engine.appc.objects import DamageableObject

    obj = DamageableObject()
    obj.SetTranslateXYZ(0.0, 0.0, 0.0)

    obj.AddObjectDamageVolume(1.0, 0.0, 0.0, 0.5, 300.0)
    assert len(visible_damage._pending) == 1

    obj.SetVisibleDamageRadiusModifier(2.0)
    assert obj._vis_dmg_radius_mod == pytest.approx(2.0)
    obj.SetVisibleDamageStrengthModifier(3.0)
    assert obj._vis_dmg_strength_mod == pytest.approx(3.0)

    obj.DamageRefresh()          # no-op, must not raise
    obj.AddDamage(TGPoint3(1.0, 2.0, 3.0), 0.4, 600.0)
    assert len(visible_damage._pending) == 2

    obj.RemoveVisibleDamage()    # clears this object's pending volumes
    assert visible_damage._pending == []
