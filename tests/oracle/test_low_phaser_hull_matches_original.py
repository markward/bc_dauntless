"""A LOW-intensity phaser hit damages the hull only when no subsystem is in
its footprint, as in the original game (stbc-oracle mechanics reference §1.5,
6 samples).

Sovereign -> Galaxy front, the footprint covering the sensor array and four
tubes: the hull took nothing while the sensor array lost 406 and the tubes
501-549. Galaxy -> Sovereign front, no subsystem in the footprint: the hull
took the half-strength hits (-317, against -680 at High). Four more aimed at
the Sovereign: two footprints holding a tractor projector spared the hull, two
holding no subsystem damaged it (-225, -224).
"""
import App
import pytest

from engine.appc import combat


def _no_repair(ship):
    bay = ship.GetRepairSubsystem()
    if bay is not None:
        bay.GetProperty().SetMaxRepairPoints(0.0)
        assert bay.GetMaxRepairPoints() == 0.0


def _point(x, y, z):
    p = App.TGPoint3()
    p.SetXYZ(x, y, z)
    return p


def _bare_hull_point(ship, radius):
    """A point on the Galaxy's hull plane whose footprint reaches no
    targetable subsystem's damage point."""
    subs = list(combat._weapon_damageable_subsystems(ship))
    for x in range(-8, 9):
        for y in range(-12, 13):
            p = (x / 4.0, y / 4.0, 0.0)
            clear = True
            for s in subs:
                w = combat._subsystem_world_position(ship, s, damage=True)
                d = ((p[0] - w.x) ** 2 + (p[1] - w.y) ** 2 + (p[2] - w.z) ** 2) ** 0.5
                if d < s.GetRadius() + radius + 0.05:
                    clear = False
                    break
            if clear:
                return _point(*p)
    raise AssertionError("no bare hull point on the grid")


def _low_hit(s, point, damage=30.0, radius=0.15, damage_hull=False):
    combat.apply_hit(s.tgt, damage, point, s.atk, splash_radius=radius,
                     bypass_shields=True, weapon_type="phaser",
                     damage_hull=damage_hull)


def _sensor(ship):
    return next(x for x in combat._weapon_damageable_subsystems(ship)
                if x.GetName() == "Sensor Array")


@pytest.fixture
def galaxy(oracle):
    s = oracle(attacker="Sovereign", target="Galaxy", range_gu=3000.0)
    _no_repair(s.tgt)
    return s


def test_low_with_no_subsystem_in_reach_damages_the_hull(galaxy):
    hull = galaxy.tgt.GetHull()
    p = _bare_hull_point(galaxy.tgt, 0.15)
    before = hull.GetCondition()
    _low_hit(galaxy, p)
    assert before - hull.GetCondition() == pytest.approx(30.0)


def test_low_over_a_subsystem_spares_the_hull(galaxy):
    hull, sensor = galaxy.tgt.GetHull(), _sensor(galaxy.tgt)
    w = combat._subsystem_world_position(galaxy.tgt, sensor, damage=True)
    h0, s0 = hull.GetCondition(), sensor.GetCondition()
    _low_hit(galaxy, _point(w.x, w.y, w.z))
    assert hull.GetCondition() == h0
    assert s0 - sensor.GetCondition() == pytest.approx(30.0)


def test_high_still_damages_the_hull_over_a_subsystem(galaxy):
    hull, sensor = galaxy.tgt.GetHull(), _sensor(galaxy.tgt)
    w = combat._subsystem_world_position(galaxy.tgt, sensor, damage=True)
    h0 = hull.GetCondition()
    _low_hit(galaxy, _point(w.x, w.y, w.z), damage_hull=True)
    assert h0 - hull.GetCondition() == pytest.approx(30.0)


def test_low_on_bare_hull_stays_cosmetic_for_plating(galaxy, monkeypatch):
    """The hull's condition takes the hit; the plating wear and severance gate
    (hit_feedback._structural_hit) still sees a LIGHT phaser hit. Read at the
    delivery, which the Python and the native path share."""
    from engine.appc import effect_queue, hit_feedback
    seen = []
    real = hit_feedback.present

    def spy(**kw):
        seen.append((kw["weapon_type"], kw["allow_structural_wear"]))
        return real(**kw)

    monkeypatch.setattr(hit_feedback, "present", spy)
    hull = galaxy.tgt.GetHull()
    before = hull.GetCondition()
    _low_hit(galaxy, _bare_hull_point(galaxy.tgt, 0.15))
    effect_queue.flush()
    assert before - hull.GetCondition() == pytest.approx(30.0)
    assert seen == [("phaser", False)]
    assert hit_feedback._structural_hit(*seen[0]) is False
