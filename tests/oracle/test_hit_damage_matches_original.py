"""What a weapon hit damages matches the original game (stbc-oracle measurements;
mechanics reference §1.2, §1.3, §3).

* Damage points: a subsystem whose position lies outside the hull is hit from a
  point just inside it (engine/appc/damage_point.py). The values below are the
  original's own ShipSubsystem.GetDamagePoint, read in the running game
  (stbc-oracle catalogue). Phaser banks are not listed: their runtime position
  (the middle of the firing arc on the strip) is a separate rule.
* Footprint: only targetable subsystems are damaged, the hull's children (the
  Galaxy's Bridge) included.
* Overflow: a hit's excess over a subsystem it destroys lands again as a new
  hit at the same point.
* Thresholds are strict: a subsystem exactly at its disabled percentage still
  works.
"""
import math

import pytest

BC_DAMAGE_POINTS = {
    "Galaxy": {
        "Aft Tractor 1": (0.0, 0.1609, 0.5094), "Forward Tractor 1": (0.0, 2.32, 0.5027),
        "Forward Tractor 2": (0.0, 0.0069, 0.0002),
    },
    "Sovereign": {
        "Aft Tractor 1": (0.0, -0.016, -0.0055), "Aft Tractor 2": (0.0, -1.6764, -0.1425),
        "Forward Tractor 1": (0.0, 3.0062, 0.0679), "Forward Tractor 2": (0.0, 2.741, -0.0731),
    },
}


def _subs(ship):
    from engine.appc.combat import _iter_subsystems
    out = {s.GetName(): s for s in _iter_subsystems(ship)}
    hull = ship.GetHull()
    out.update({c.GetName(): c for c in hull._children})
    out[hull.GetName()] = hull
    return out


def _no_repair(ship):
    # The repair rate is read from the bay's property (RepairSubsystem.
    # GetMaxRepairPoints); the subsystem itself has no setter.
    bay = ship.GetRepairSubsystem()
    if bay is not None:
        bay.GetProperty().SetMaxRepairPoints(0.0)
        assert bay.GetMaxRepairPoints() == 0.0


def _hit(s, ship, damage, point, radius=0.13):
    import App
    from engine.appc import combat
    p = App.TGPoint3()
    p.SetXYZ(point.x, point.y, point.z)
    combat.apply_hit(ship, damage, p, s.atk, splash_radius=radius, bypass_shields=True)


@pytest.mark.parametrize("cls", ["Galaxy", "Sovereign"])
def test_damage_points_match_the_original(oracle, cls):
    s = oracle(attacker="Sovereign" if cls == "Galaxy" else "Galaxy", target=cls, range_gu=3000.0)
    subs = _subs(s.tgt)
    for name, want in BC_DAMAGE_POINTS[cls].items():
        p = subs[name].GetDamagePoint()
        assert math.dist((p.x, p.y, p.z), want) < 0.005, (name, (p.x, p.y, p.z), want)


def test_a_subsystem_inside_the_hull_keeps_its_position(oracle):
    s = oracle(attacker="Sovereign", target="Galaxy", range_gu=3000.0)
    sensor = _subs(s.tgt)["Sensor Array"]
    p, q = sensor.GetDamagePoint(), sensor.GetPositionTG()
    assert (p.x, p.y, p.z) == (q.x, q.y, q.z)


def test_a_hit_at_a_tractors_position_misses_it_at_its_damage_point(oracle):
    """The Galaxy's Forward Tractor 2 sits on the skin at (0, 1.7, 0.06); the
    original measures its footprint from (0, 0.0069, 0.0002), deep inside, so
    a small hit on the skin there leaves it alone."""
    from engine.appc.subsystems import subsystem_world_position
    s = oracle(attacker="Sovereign", target="Galaxy", range_gu=3000.0)
    _no_repair(s.tgt)
    tractor = _subs(s.tgt)["Forward Tractor 2"]
    c0 = tractor.GetCondition()
    _hit(s, s.tgt, 50.0, subsystem_world_position(tractor, s.tgt), radius=0.05)
    s.run(0.1)
    assert tractor.GetCondition() == c0
    _hit(s, s.tgt, 50.0, subsystem_world_position(tractor, s.tgt, damage=True), radius=0.05)
    s.run(0.1)
    assert tractor.GetCondition() < c0


def test_untargetable_parents_are_never_damaged(oracle):
    s = oracle(attacker="Sovereign", target="Galaxy", range_gu=3000.0)
    _no_repair(s.tgt)
    subs = _subs(s.tgt)
    parents = [n for n in ("Phasers", "Torpedoes", "Tractors", "Impulse Engines",
                           "Warp Engines", "Engineering") if n in subs]
    assert parents
    before = {n: subs[n].GetCondition() for n in parents}
    from engine.appc.subsystems import subsystem_world_position
    for n in parents:
        _hit(s, s.tgt, 300.0, subsystem_world_position(subs[n], s.tgt), radius=0.6)
    s.run(0.1)
    assert {n: subs[n].GetCondition() for n in parents} == before


def test_a_hit_on_the_bridge_damages_it(oracle):
    s = oracle(attacker="Sovereign", target="Galaxy", range_gu=3000.0)
    _no_repair(s.tgt)
    bridge = _subs(s.tgt)["Bridge"]
    c0 = bridge.GetCondition()
    from engine.appc.subsystems import subsystem_world_position
    _hit(s, s.tgt, 200.0, subsystem_world_position(bridge, s.tgt, damage=True))
    s.run(0.1)
    assert c0 - bridge.GetCondition() == pytest.approx(200.0)


def test_overflow_lands_as_a_second_hit(oracle):
    """One 550 hit centred on a sensor array at 100 HP, shields bypassed: the
    hull takes 550, then the 450 excess (the original: 1000 in all)."""
    s = oracle(attacker="Sovereign", target="Galaxy", range_gu=3000.0)
    _no_repair(s.tgt)
    from engine.appc.combat import _weapon_damageable_subsystems
    from engine.appc.subsystems import subsystem_world_position
    for x in _weapon_damageable_subsystems(s.tgt):
        x.SetCondition(x.GetMaxCondition())
    sensor = _subs(s.tgt)["Sensor Array"]
    sensor.SetCondition(100.0)
    hull = s.tgt.GetHull()
    h0 = hull.GetCondition()
    _hit(s, s.tgt, 550.0, subsystem_world_position(sensor, s.tgt, damage=True))
    assert sensor.GetCondition() == 0.0
    assert h0 - hull.GetCondition() == pytest.approx(1000.0)


@pytest.mark.parametrize("name", ["Shield Generator", "Sensor Array"])
def test_exactly_at_the_threshold_still_works(oracle, name):
    s = oracle(attacker="Sovereign", target="Galaxy", range_gu=3000.0)
    _no_repair(s.tgt)
    sub = _subs(s.tgt)[name]
    t = sub.GetDisabledPercentage() * sub.GetMaxCondition()
    sub.SetCondition(t)
    assert not sub.IsDisabled()
    sub.SetCondition(t * 0.998)
    assert sub.IsDisabled()
