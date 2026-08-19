"""The hull-impact flash rides the hull, like the sparks beside it.

hit_vfx_pass resolved the spark burst against the live instance matrix
(`inst->world * body_point`, hit_vfx_pass.cc:257) but drew the flash billboard
at a frozen `world_pos`. The flash lives 0.7 s, so at 6.3 GU/s it slid ~4.4 GU
— more than a Galaxy's whole 3.7 GU length — while the sparks in the same
descriptor stayed put.

It also only ever HAD a body anchor when sparks fired: dispatch gated the
world->body conversion on `spark_count > 0`, and a flash-only hit (every phaser
tick, and any torpedo under the spark threshold) carried instance_id=None. So
the anchor has to be resolved for every hit that can have one, and the spark
count kept as its own separate gate.
"""
import pytest

from engine.appc import hit_feedback, hit_vfx
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    hit_vfx._active.clear()
    # The decal / carve emitters are a separate concern and need a live
    # renderer; stub them for every test in this file.
    monkeypatch.setattr(hit_feedback.host_io, "damage_decal_add",
                        lambda *a, **k: None)
    monkeypatch.setattr(hit_feedback.host_io, "hull_carve_add",
                        lambda *a, **k: None)
    yield
    hit_vfx._active.clear()


def _ship():
    s = ShipClass_Create("Target")
    s._hull = HullSubsystem("Hull")
    s._hull.SetMaxCondition(10000.0)
    ss = ShieldSubsystem("Shield Generator")
    ss.TurnOff()                      # let damage reach the hull
    s.SetShieldSubsystem(ss)
    return s


def _dispatch_hull_hit(monkeypatch, *, absorbed_hull, ship=None):
    """Run a HULL-severity dispatch with a working world->body conversion."""
    ship = ship or _ship()
    monkeypatch.setattr(
        hit_feedback.host_io, "world_to_body",
        lambda iid, p, n: ((p[0] - 100.0, p[1], p[2]), n))
    hit_feedback.dispatch(
        ship=ship, source=None,
        point=TGPoint3(110.0, 0.0, 0.0), normal=TGPoint3(1.0, 0.0, 0.0),
        damage=absorbed_hull, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=absorbed_hull, sub_transition=None,
        ship_instances={ship: 7}, weapon_type="phaser", radius=0.15)
    assert len(hit_vfx._active) == 1
    return hit_vfx._active[0]


def test_flash_only_hit_still_carries_a_hull_anchor(monkeypatch):
    """A light phaser tick is under SPARK_HULL_THRESHOLD, so no sparks — but
    the flash still needs somewhere to hang."""
    entry = _dispatch_hull_hit(monkeypatch, absorbed_hull=5.0)

    assert entry["spark_count"] == 0, "premise: this hit is below the spark bar"
    assert entry["instance_id"] == 7
    assert entry["body_point"] == (10.0, 0.0, 0.0)
    assert entry["body_normal"] == (1.0, 0.0, 0.0)


def test_spark_bearing_hit_keeps_its_anchor(monkeypatch):
    """Unchanged for the heavy-hit path that already worked."""
    entry = _dispatch_hull_hit(
        monkeypatch, absorbed_hull=hit_feedback.SPARK_HULL_THRESHOLD + 1.0)

    assert entry["spark_count"] > 0
    assert entry["instance_id"] == 7
    assert entry["body_point"] == (10.0, 0.0, 0.0)


def test_no_anchor_without_a_surface_normal(monkeypatch):
    """Sphere-entry fallbacks have no normal, so there is nothing to convert;
    the flash falls back to its world position."""
    ship = _ship()
    monkeypatch.setattr(hit_feedback.host_io, "world_to_body",
                        lambda iid, p, n: ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
    hit_feedback.dispatch(
        ship=ship, source=None,
        point=TGPoint3(110.0, 0.0, 0.0), normal=None,
        damage=5.0, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=5.0, sub_transition=None,
        ship_instances={ship: 7}, weapon_type="phaser", radius=0.15)

    entry = hit_vfx._active[0]
    assert entry["instance_id"] is None
    assert entry["body_point"] is None


def test_failed_conversion_drops_the_anchor(monkeypatch):
    """A stale instance id returns None from world_to_body — the descriptor
    must not claim an anchor it cannot resolve."""
    ship = _ship()
    monkeypatch.setattr(hit_feedback.host_io, "world_to_body",
                        lambda iid, p, n: None)
    hit_feedback.dispatch(
        ship=ship, source=None,
        point=TGPoint3(110.0, 0.0, 0.0), normal=TGPoint3(1.0, 0.0, 0.0),
        damage=5.0, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=5.0, sub_transition=None,
        ship_instances={ship: 7}, weapon_type="phaser", radius=0.15)

    entry = hit_vfx._active[0]
    assert entry["instance_id"] is None
    assert entry["body_point"] is None
    assert entry["spark_count"] == 0
