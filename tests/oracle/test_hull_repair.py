"""Hull damage is repaired and listed like any subsystem.

The original repairs the hull in combat (stbc-oracle duels: hull HP rises in
+5.5 steps in 84 of 88 hull series, median 5.54 HP/s with a full queue) and
Brex announces hull repairs (Bridge/EngineerMenuHandlers.py ge111). A hit's
damage reaches the repair bay at the tick boundary, so the queue is read one
step after the hit.
"""
import pytest


def _hit_hull(s, amount=900.0):
    import App
    from engine.appc import combat
    p = App.TGPoint3()
    p.SetXYZ(-2.0, -0.75, 0.0)               # a Galaxy hull point with no subsystem in reach
    combat.apply_hit(s.atk, amount, p, s.tgt, splash_radius=0.15, bypass_shields=True)


def test_hull_damage_is_queued_listed_and_repaired(oracle):
    s = oracle(attacker="Galaxy", target="Sovereign", range_gu=3000.0)
    hull, bay = s.atk.GetHull(), s.atk.GetRepairSubsystem()
    _hit_hull(s)
    s.run(0.1)
    assert hull in bay._queue
    from engine.ui.eng_repair_pane import repair_pane_snapshot
    snap = repair_pane_snapshot(s.atk, lambda wid, sub: None)
    assert [r["label"] for r in snap["repair"]] == [hull.GetName()]
    c0 = hull.GetCondition()
    s.run(10.0)
    # Alone in the queue: MaxRepairPoints 50 / complexity 3 = 16.67 HP/s.
    assert (hull.GetCondition() - c0) / 10.0 == pytest.approx(50.0 / 3.0, rel=0.02)
