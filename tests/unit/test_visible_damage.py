"""Tests for the BC visible-damage API -> hull-carve path
(engine/appc/visible_damage.py + DamageableObject delegators).

The carve emit routes through engine.host_io.hull_carve_add; these tests patch
that wrapper with a call-capturing spy (host_io owns the single guard point)
rather than injecting a raw host= module (Task 4 of the host_io façade
refactor). advance() no longer takes a host arg."""
import pytest

from engine import host_io
from engine.appc import visible_damage
from engine.appc.hull_carve import MIN_CARVE_RADIUS_GU
from engine.appc.math import TGMatrix3, TGPoint3


class _Ship:
    def __init__(self, loc=None, rot=None, radius_mod=None, radius=3.0):
        self._loc = loc or TGPoint3(0.0, 0.0, 0.0)
        self._rot = rot or TGMatrix3()  # identity
        self._radius = radius
        if radius_mod is not None:
            self._vis_dmg_radius_mod = radius_mod

    def GetWorldLocation(self):  return self._loc
    def GetWorldRotation(self):  return self._rot
    def GetRadius(self):         return self._radius


class _CarveSpy:
    """Positional-arg capture matching host_io.hull_carve_add's signature."""

    def __init__(self):
        self.carves = []  # (iid, point, normal, influ, strength, time, floor, ref)

    def __call__(self, iid, point, normal, influ, strength, time,
                 floor_radius=0.0, radius_modifier=1.0):
        self.carves.append((iid, point, normal, influ, strength, time,
                            floor_radius, radius_modifier))


@pytest.fixture
def host(monkeypatch):
    """Patch host_io.hull_carve_add with a call-capturing spy; return the spy
    (kept named `host` so the existing assertions read `host.carves`)."""
    spy = _CarveSpy()
    monkeypatch.setattr(host_io, "hull_carve_add", spy)
    return spy


@pytest.fixture(autouse=True)
def _clean():
    visible_damage.reset()
    yield
    visible_damage.reset()


# ── Body-frame authored volumes ─────────────────────────────────────────────

def test_body_volume_emits_world_point_and_floored_radius(host):
    ship = _Ship()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    visible_damage.advance(0.0, {ship: 7})

    assert len(host.carves) == 1
    iid, point, normal, influ, strength, _t, floor, _ref = host.carves[0]
    assert iid == 7
    # Identity rotation, ship at origin -> world point == body point.
    assert point == pytest.approx((1.0, 0.0, 0.0))
    # Outward radial normal (unit).
    assert normal == pytest.approx((1.0, 0.0, 0.0))
    # influRad passed through; authored strength carried; floor = max(MIN, influRad).
    assert influ == pytest.approx(0.5)
    assert strength == pytest.approx(300.0)
    assert floor == pytest.approx(max(MIN_CARVE_RADIUS_GU, 0.5))


def test_body_volume_respects_ship_position_and_rotation(host):
    # 90 deg about Z: body (1,0,0) -> world (0,1,0), offset by ship location.
    rot = TGMatrix3().MakeZRotation(3.14159265358979 / 2.0)
    ship = _Ship(loc=TGPoint3(10.0, -5.0, 2.0), rot=rot)
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    visible_damage.advance(0.0, {ship: 1})

    _iid, point, normal, _influ, _s, _t, _floor, _ref = host.carves[0]
    assert point == pytest.approx((10.0, -4.0, 2.0))   # loc + R.(1,0,0)
    assert normal == pytest.approx((0.0, 1.0, 0.0))


def test_radius_modifier_scales_emitted_floor(host):
    ship = _Ship(radius_mod=2.0)
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    visible_damage.advance(0.0, {ship: 1})

    _iid, _p, _n, _influ, _s, _t, floor, _ref = host.carves[0]
    assert floor == pytest.approx(max(MIN_CARVE_RADIUS_GU, 0.5) * 2.0)


# ── Deferral until the render instance is realized ──────────────────────────

def test_defers_until_instance_realized_then_emits_once(host):
    ship = _Ship()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)

    # Not yet realized: kept, no emit.
    visible_damage.advance(0.1, {})
    assert host.carves == []
    assert len(visible_damage._pending) == 1

    # Realized: emits exactly once...
    visible_damage.advance(0.1, {ship: 4})
    assert len(host.carves) == 1
    # ...and is not re-emitted on the next tick.
    visible_damage.advance(0.1, {ship: 4})
    assert len(host.carves) == 1
    assert visible_damage._pending == []


def test_unrealized_entry_ages_out(host):
    ship = _Ship()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    # Never realized; age past MAX_PENDING_AGE -> dropped, never emitted.
    visible_damage.advance(visible_damage.MAX_PENDING_AGE + 1.0, {})
    assert host.carves == []
    assert visible_damage._pending == []


def test_unrealized_ship_keeps_pending_and_never_raises():
    # No ship_instances mapping (unrealized render instance): the entry is kept,
    # nothing is emitted, and advance never raises even without any host_io
    # wrapper patched (the real host_io.hull_carve_add no-ops when the native
    # module is absent — the single guard point).
    ship = _Ship()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    visible_damage.advance(0.1, ship_instances={})            # unmapped ship
    visible_damage.advance(0.1, ship_instances=None)          # no map at all
    assert len(visible_damage._pending) == 1  # still waiting, nothing emitted


# ── Runtime world-space carve (AddDamage / DeathExplosionDamage) ────────────

def test_world_carve_passes_point_through_with_radial_normal(host):
    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0))
    visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.0), 0.6, 600.0)
    visible_damage.advance(0.0, {ship: 2})

    _iid, point, normal, influ, strength, _t, floor, _ref = host.carves[0]
    assert point == pytest.approx((13.0, 4.0, 0.0))   # already world-space
    assert normal == pytest.approx((0.6, 0.8, 0.0))   # unit (point - loc)
    assert influ == pytest.approx(0.6)
    assert strength == pytest.approx(600.0)           # fDamage carried as strength
    assert floor == pytest.approx(max(MIN_CARVE_RADIUS_GU, 0.6))


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
