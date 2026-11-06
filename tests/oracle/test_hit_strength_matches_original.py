"""How much a weapon hit carries, and how big its splash is, matches the
original game (stbc-oracle measurements; mechanics reference §1.5, §1.6,
§12).

* A torpedo's splash is its PAYLOAD's DamageRadiusFactor, never the launching
  tube's: every photon hit carried 0.13 (258 hits), never the Galaxy's and
  Sovereign's tubes' 0.20.
* A torpedo the shields partly stop reaches the hull with its splash shrunk by
  the same fraction (63 of 63 hits; tests/unit/test_projectile_leak_radius.py
  pins the shrink itself).
* A shot that crosses no shield bubble while the shields are up hits nothing:
  the hull is inside the bubble (101 of 288 expired torpedoes passed inside a
  shielded Galaxy's GetRadius without hitting it).
* Phaser damage scales with the firing bank's condition: 133.4 -> 120.7 ->
  106.5 per second at 100 / 90 / 80%.
"""
import math

import pytest

from tests.oracle.conftest import FRONT

HIGH = 2


def _front_rate(scene, seconds=3.0):
    before = scene.face(FRONT)
    scene.run(seconds)
    return (before - scene.face(FRONT)) / seconds


def test_a_torpedo_carries_its_payloads_splash_not_the_tubes(oracle):
    from engine.appc import combat, projectiles
    s = oracle(attacker="Galaxy", target="Sovereign", range_gu=100.0)
    tube = s.emitters("torpedo")[0]
    assert tube.GetDamageRadiusFactor() == pytest.approx(0.20)
    projectiles._active.clear()
    s.fire("torpedo")
    s.run(1.0)
    live = [t for t in projectiles._active if t._source_ship is s.atk]
    assert live, "the Galaxy launched a torpedo"
    for t in live:
        assert combat.weapon_splash_radius(t, None) == pytest.approx(0.13)


def test_the_payload_wins_over_the_hardpoint():
    from engine.appc import combat

    class _R:
        def __init__(self, v):
            self.v = v

        def GetDamageRadiusFactor(self):
            return self.v
    assert combat.weapon_splash_radius(_R(0.20), _R(0.13)) == pytest.approx(0.13)
    assert combat.weapon_splash_radius(_R(0.15), None) == pytest.approx(0.15)
    assert combat.weapon_splash_radius(_R(0.15), _R(0.0)) == pytest.approx(0.15)


def _pulse_quanta(scene, seconds=4.0):
    """Every damage pulse that landed on the front face (a drop of more than one
    point in a tick), with the target's shield regeneration off so each drop is
    exactly one pulse."""
    sh = scene.tgt.GetShields()
    for f in range(6):
        sh.SetShieldChargePerSecond(f, 0.0)
    out, last = [], scene.face(FRONT)
    for _t, _s in scene.sample_until(seconds):
        now = scene.face(FRONT)
        if last - now > 1.0:
            out.append(last - now)
        last = now
    return out


@pytest.mark.parametrize("condition", [0.9, 0.8])
def test_phaser_damage_scales_with_the_banks_condition(oracle, condition):
    """133.4 -> 120.7 -> 106.5 per second at 100 / 90 / 80%: 0.905 and 0.798 of
    full, the bank's condition. Each pulse of a worn bank is that fraction of a
    full bank's (a Kessok Heavy's forward beams at 57 GU, a parked Galaxy)."""
    assert 120.7 / 133.4 == pytest.approx(0.9, abs=0.01)
    assert 106.5 / 133.4 == pytest.approx(0.8, abs=0.01)
    full = oracle(attacker="KessokHeavy", target="Galaxy", range_gu=57)
    full.fire("phaser", intensity=HIGH)
    q_full = _pulse_quanta(full)
    worn = oracle(attacker="KessokHeavy", target="Galaxy", range_gu=57)
    worn.atk.GetRepairSubsystem().SetCondition(0.0)   # no repairs: the banks stay worn
    for bank in worn.emitters("phaser"):
        bank.SetCondition(bank.GetMaxCondition() * condition)
    worn.fire("phaser", intensity=HIGH)
    q_worn = _pulse_quanta(worn)
    assert q_full and q_worn
    assert max(q_worn) / max(q_full) == pytest.approx(condition, rel=1e-6)


# -- the shield bubble ------------------------------------------------------------------------

def _boxed(oracle):
    """A Galaxy with the hull box the live game caches at realize time (headless has none)."""
    from engine.host_loop import BC_MODEL_SCALE
    s = oracle(attacker="Sovereign", target="Galaxy", range_gu=3000.0)
    half = tuple(v * BC_MODEL_SCALE for v in (232.064, 322.166, 70.4982))
    s.tgt._shield_hull_box = ((0.0, 0.0, 0.0), half)
    from engine.appc import native_combat
    native_combat.push_field(s.tgt, "_shield_hull_box") if hasattr(native_combat, "push_field") else None
    return s, half


def _world(ship, x, y, z):
    import App
    from engine.appc.math import TGPoint3
    p = TGPoint3(x, y, z)
    p.MultMatrixLeft(ship.GetWorldRotation())
    loc = ship.GetWorldLocation()
    return App.TGPoint3(p.x + loc.x, p.y + loc.y, p.z + loc.z) if False else TGPoint3(
        p.x + loc.x, p.y + loc.y, p.z + loc.z)


def test_a_point_inside_getradius_can_be_outside_the_bubble(oracle):
    """Above the Galaxy's saucer: inside its 4.37 GU GetRadius sphere, outside the
    shield ellipsoid (sqrt(3) x the 0.70 GU half height) and the hull box."""
    from engine.appc import combat
    s, half = _boxed(oracle)
    above = _world(s.tgt, 0.0, 0.0, half[2] * math.sqrt(3.0) + 0.3)
    assert (above.x - s.tgt.GetWorldLocation().x) ** 2 + (above.y - s.tgt.GetWorldLocation().y) ** 2 \
        + (above.z - s.tgt.GetWorldLocation().z) ** 2 < s.tgt.GetRadius() ** 2
    assert not combat.point_in_shield_bubble(s.tgt, above)
    inside = _world(s.tgt, 0.0, 0.0, half[2] * 1.2)
    assert combat.point_in_shield_bubble(s.tgt, inside)


def test_a_shot_skimming_over_the_hull_inside_getradius_misses(oracle):
    """A segment that passes above the hull box -- well inside GetRadius -- hits
    nothing; one through the box hits."""
    from engine.appc import combat
    s, half = _boxed(oracle)
    z = half[2] + 0.4
    a = _world(s.tgt, 0.0, 2.0, z)
    b = _world(s.tgt, 0.0, -2.0, z)
    assert not combat.hull_segment_hit(s.tgt, a, b, s.tgt.GetRadius())
    a = _world(s.tgt, 0.0, 2.0, 0.0)
    b = _world(s.tgt, 0.0, -2.0, 0.0)
    assert combat.hull_segment_hit(s.tgt, a, b, s.tgt.GetRadius())
