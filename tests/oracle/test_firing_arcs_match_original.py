"""Firing arcs, weapon positions and rough directions match the original.

The values below are the original game's own answers, read with stbc-oracle
on ships placed as this module's `oracle` fixture places them (azimuth from
the nose, 90 = starboard; elevation up; points 150 GU from the ship's centre
in its own frame). tests/oracle/survey_arcs_vs_original.py compares every
weapon of twelve classes against the full captures.

* A phaser bank's position is the middle of its firing arc on its strip, not
  its hardpoint (the Galaxy's four ventral banks share one hardpoint).
* An arc is the range between its two angles in either order (the Akira's
  ventral banks author theirs descending), and a height arc running past the
  vertical also covers the directions "over the top" (Kessok and Cardassian
  dorsal beams, the Marauder's ventral phaser).
* MaxDamageDistance is no limit on CanHit.
* A tube's CanHit / IsInArc is the square +/-30 deg cone of the targeted-fire
  gate (a direction 25 deg right and 25 deg up, 34.8 deg off the tube, is in).
* CalculateRoughDirection: a phaser bank points at the middle of its arcs, a
  pulse weapon or tractor at min/2 + middle on each axis, a tube along itself.
"""
import math

import pytest


def _all_subs(ship):
    from engine.appc.combat import _iter_subsystems
    hull = ship.GetHull()
    out = list(_iter_subsystems(ship)) + [hull]
    out += [hull.GetChildSubsystem(i) for i in range(hull.GetNumChildSubsystems())]
    return {s.GetName(): s for s in out if s is not None}


def _point(ship, elev, az, r=150.0):
    import App
    ce = math.cos(math.radians(elev))
    body = (r * ce * math.sin(math.radians(az)), r * ce * math.cos(math.radians(az)),
            r * math.sin(math.radians(elev)))
    w = ship.GetWorldLocation()
    R = ship.GetWorldRotation()
    c = [R.GetCol(i) for i in range(3)]
    p = App.TGPoint3()
    p.SetXYZ(w.x + c[0].x * body[0] + c[1].x * body[1] + c[2].x * body[2],
             w.y + c[0].y * body[0] + c[1].y * body[1] + c[2].y * body[2],
             w.z + c[0].z * body[0] + c[1].z * body[1] + c[2].z * body[2])
    return p


# (attacker, target, which ship, weapon, method, [(azimuth, elevation, original's answer)])
ARC_CASES = [
    ("Akira", "Nebula", "atk", "Ventral Phaser 1", "CanHit", [(240, -50, 1), (240, -10, 0), (90, -50, 0)]),
    ("Akira", "Nebula", "atk", "Ventral Phaser 2", "CanHit", [(0, -45, 1), (0, 10, 0)]),
    ("Galor", "Ambassador", "tgt", "Ventral Phaser 1", "CanHit", [(270, -30, 1), (270, -5, 1), (270, 10, 0), (90, -30, 0)]),
    ("KessokLight", "CardHybrid", "tgt", "Ventral Beam 1", "CanHit", [(185, -60, 1), (185, -10, 0), (5, -60, 0)]),
    ("KessokHeavy", "Marauder", "atk", "Dorsal Beam 1", "CanHit", [(180, 50, 1), (180, 10, 0), (0, 60, 1)]),
    ("KessokHeavy", "Marauder", "tgt", "Ventral Phaser", "CanHit", [(180, -50, 1), (0, -50, 1), (0, 30, 0)]),
    ("Akira", "Nebula", "atk", "Forward Torp 1", "IsInArc", [(25, 25, 1), (0, 30, 0), (30, 0, 0), (25, 0, 1)]),
    ("Akira", "Nebula", "atk", "Forward Torp 1", "CanHit", [(25, 25, 1), (0, 30, 0)]),
    ("Vorcha", "Keldon", "atk", "Port Cannon", "IsInArc", [(0, 0, 1), (90, 0, 0)]),
]


@pytest.mark.parametrize("atk,tgt,which,name,meth,cells", ARC_CASES,
                         ids=["%s-%s-%s" % (c[0], c[3], c[4]) for c in ARC_CASES])
def test_weapon_fires_where_the_original_does(oracle, atk, tgt, which, name, meth, cells):
    s = oracle(attacker=atk, target=tgt, range_gu=57.0)
    ship = getattr(s, which)
    sub = _all_subs(ship)[name]
    for az, el, want in cells:
        assert getattr(sub, meth)(_point(ship, el, az)) == want, (az, el)


def test_can_hit_has_no_range_limit(oracle):
    """The Akira's banks author MaxDamageDistance; the original answers the
    same arc map at 150 GU, and at 3000 GU, as close in."""
    s = oracle(attacker="Akira", target="Nebula", range_gu=57.0)
    bank = _all_subs(s.atk)["Ventral Phaser 1"]
    assert bank.GetMaxDamageDistance() < 150.0
    assert bank.CanHit(_point(s.atk, -50, 240, 3000.0)) == 1


# The Galaxy's ventral and dorsal banks: (name, the original's GetPosition).
GALAXY_BANKS = [
    ("Ventral Phaser 1", (-1.33, 1.3, 0.16)), ("Ventral Phaser 2", (-0.665, 2.17469, 0.16)),
    ("Ventral Phaser 3", (0.665, 2.17469, 0.16)), ("Ventral Phaser 4", (1.33, 1.3, 0.16)),
    ("Dorsal Phaser 1", (-1.69, 1.27, 0.5)), ("Dorsal Phaser 2", (-0.845, 2.43913, 0.5)),
    ("Dorsal Phaser 3", (0.845, 2.43913, 0.5)), ("Dorsal Phaser 4", (1.69, 1.27, 0.5)),
]


def test_phaser_banks_sit_at_the_middle_of_their_arcs(oracle):
    s = oracle(attacker="Galaxy", target="Sovereign", range_gu=57.0)
    subs = _all_subs(s.atk)
    for name, want in GALAXY_BANKS:
        p = subs[name].GetPositionTG()
        assert math.dist((p.x, p.y, p.z), want) < 1e-4, name
        hard = subs[name].GetMountPositionTG()
        assert (round(hard.x, 4), round(hard.y, 4)) == ((0.0, 1.3) if "Ventral" in name else (0.0, 1.27))


def test_a_lock_on_a_bank_aims_at_its_position(oracle):
    """A subsystem lock reads GetPositionTG: two banks sharing a hardpoint are
    two aim points."""
    s = oracle(attacker="Sovereign", target="Galaxy", range_gu=57.0)
    subs = _all_subs(s.tgt)
    a = subs["Ventral Phaser 1"].GetWorldLocation()
    b = subs["Ventral Phaser 4"].GetWorldLocation()
    assert math.dist((a.x, a.y, a.z), (b.x, b.y, b.z)) == pytest.approx(2.66, abs=1e-3)


# (attacker, target, which, weapon, the original's direction in the model frame)
ROUGH_CASES = [
    ("Galaxy", "Sovereign", "atk", "Dorsal Phaser 2", (-0.4394, 0.7611, 0.4772)),
    ("Galaxy", "Sovereign", "tgt", "Ventral Phaser 1", (-0.8141, 0.0, -0.5807)),
    ("Galaxy", "Sovereign", "atk", "Forward Tractor 2", (-0.1913, 0.3314, -0.9239)),
    ("Galaxy", "Sovereign", "atk", "Aft Torpedo 1", (0.0, -1.0, 0.0)),
    ("Warbird", "BirdOfPrey", "tgt", "Star Cannon", (-0.2113, 0.9532, -0.2164)),
    ("KessokLight", "CardHybrid", "tgt", "Aft Tractor", (0.1485, -0.554, 0.8192)),
]


@pytest.mark.parametrize("atk,tgt,which,name,want", ROUGH_CASES, ids=[c[0] + "-" + c[3] for c in ROUGH_CASES])
def test_rough_direction_matches_the_original(oracle, atk, tgt, which, name, want):
    s = oracle(attacker=atk, target=tgt, range_gu=57.0)
    ship = getattr(s, which)
    w = _all_subs(ship)[name].CalculateRoughDirection()
    R = ship.GetWorldRotation()
    got = [w.x * R.GetCol(i).x + w.y * R.GetCol(i).y + w.z * R.GetCol(i).z for i in range(3)]
    cos = sum(g * x for g, x in zip(got, want)) / (math.sqrt(sum(g * g for g in got)) or 1.0)
    assert math.degrees(math.acos(max(-1.0, min(1.0, cos)))) < 1.0, got
