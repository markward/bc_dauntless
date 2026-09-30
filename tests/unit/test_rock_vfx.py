"""Rock dust sparks and the rock death burst (rock-class spec §2)."""
import pytest

import App
from tests.unit.test_rock_class import _make


@pytest.fixture(autouse=True)
def _clean_lights():
    from engine.appc import explosion_lights
    explosion_lights.reset()
    yield
    explosion_lights.reset()


def _impact(ship, monkeypatch, ship_instances=None):
    from engine.appc import hit_feedback, hit_vfx
    got = []
    monkeypatch.setattr(hit_vfx, "spawn", lambda *a, **k: got.append(k))
    hit_feedback._hull_impact_visual(
        ship=ship, point=App.TGPoint3(0, 0, 0), normal=App.TGPoint3(0, 0, 1),
        severity=hit_feedback.Severity.HULL, weapon_type="torpedo",
        absorbed_hull=hit_feedback.SPARK_HULL_THRESHOLD * 2,
        ship_instances=ship_instances)
    return got


def test_rock_hit_uses_rock_dust_spark_kind(monkeypatch):
    from engine.appc import hit_feedback
    got = _impact(_make(App.GENUS_ASTEROID), monkeypatch)
    assert got and all(k["weapon_kind"] == hit_feedback.SPARK_KIND_ROCK
                       for k in got)


def test_anchored_rock_hit_sparks_rock_dust(monkeypatch):
    """With a hull anchor the burst actually fires (spark_count > 0), and it
    is rock dust, with the rock kind's own base count."""
    from engine.appc import hit_feedback
    monkeypatch.setattr(hit_feedback.host_io, "world_to_body",
                        lambda iid, p, n: ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
    rock = _make(App.GENUS_ASTEROID)
    got = _impact(rock, monkeypatch, ship_instances={rock: 7})
    assert len(got) == 1
    assert got[0]["weapon_kind"] == hit_feedback.SPARK_KIND_ROCK
    assert got[0]["spark_count"] == 10


def test_ship_hit_keeps_hot_torpedo_sparks(monkeypatch):
    from engine.appc import hit_feedback
    got = _impact(_make(App.GENUS_SHIP), monkeypatch)
    assert got and got[0]["weapon_kind"] == hit_feedback.SPARK_KIND_TORPEDO


def test_death_vfx_spec_becomes_flash_dust_and_light(monkeypatch):
    from engine.appc import explosion_lights, hit_vfx
    from engine.rocks import death, vfx
    spawned, lights = [], []
    monkeypatch.setattr(hit_vfx, "spawn", lambda *a, **k: spawned.append((a, k)))
    monkeypatch.setattr(explosion_lights, "register_at",
                        lambda *a, **k: lights.append((a, k)))
    pSet = object()
    death._vfx_specs.append(death.DeathVfxSpec((1.0, 2.0, 3.0), 4.0, pSet))
    vfx.pump()
    assert len(spawned) == 1
    (pos,), kw = spawned[0]
    assert (pos.x, pos.y, pos.z) == (1.0, 2.0, 3.0)
    assert kw["weapon_kind"] == 2 and kw["spark_count"] > 0
    assert kw["instance_id"] is None
    assert kw["severity"] == hit_vfx.Severity.CRITICAL
    assert kw["pSet"] is pSet
    assert len(lights) == 1
    (lpos, lset), lkw = lights[0]
    assert (lpos.x, lpos.y, lpos.z) == (1.0, 2.0, 3.0) and lset is pSet
    assert lkw == {"size_gu": 2.0, "life_s": 0.4}
    assert death.drain_death_vfx() == []


def test_register_at_lights_a_fixed_point_with_no_ship():
    from engine.appc import explosion_lights
    pSet = object()
    explosion_lights.register_at(App.TGPoint3(1.0, 2.0, 3.0), pSet,
                                 size_gu=2.0, life_s=0.4)
    explosion_lights.advance(0.04)          # into the bloom
    out = explosion_lights.render_data()
    assert len(out) == 1
    assert out[0]["position"] == (1.0, 2.0, 3.0)
    assert out[0]["set"] is pSet
    explosion_lights.advance(0.5)           # past its 0.4 s life
    assert explosion_lights.render_data() == []
