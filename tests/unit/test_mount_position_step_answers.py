"""subsystem_world_position answers a mount once per combat stretch.

In a 64-ship fight a weapon mount's world position was rebuilt ~100 times a
tick, each time re-reading the ship's pose and walking the articulation
lookup: a firing phaser bank asks for it ~4 times a tick (strip emit point,
arc test, aim, beam), the held-weapon pump again. Inside an
engine.core.step_memo block (the combat step) each mount is computed once;
step_memo.forget() -- every hit, deaths, subsystem damage, tractors moving
ships -- drops the answers. Every call still returns its own TGPoint3.
"""
import pytest

from engine.appc import articulation
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import ShipSubsystem, subsystem_world_position
from engine.core import step_memo


@pytest.fixture
def mount(monkeypatch):
    ship = ShipClass_Create("Galaxy")
    ship.SetTranslateXYZ(10.0, -4.0, 2.5)
    rot = TGMatrix3()
    rot.MakeZRotation(0.7)
    ship.SetMatrixRotation(rot)
    sub = ShipSubsystem("Phaser Bank")
    sub._position = TGPoint3(1.25, 3.0, -0.5)
    sub.SetParentShip(ship)
    computed = []
    real = articulation.part_transform_point

    def counting(*a, **k):
        computed.append(1)
        return real(*a, **k)
    monkeypatch.setattr(articulation, "part_transform_point", counting)
    return ship, sub, computed


def _xyz(p):
    return (p.x, p.y, p.z)


def test_outside_a_step_every_call_computes(mount):
    ship, sub, computed = mount
    subsystem_world_position(sub)
    subsystem_world_position(sub)
    assert len(computed) == 2


def test_inside_a_step_a_mount_is_computed_once(mount):
    ship, sub, computed = mount
    outside = _xyz(subsystem_world_position(sub))
    with step_memo.combat_step():
        first = subsystem_world_position(sub)
        second = subsystem_world_position(sub)
        assert len(computed) == 2               # 1 outside + 1 inside
        assert _xyz(first) == _xyz(second) == outside


def test_each_call_gets_its_own_point(mount):
    ship, sub, computed = mount
    with step_memo.combat_step():
        first = subsystem_world_position(sub)
        want = _xyz(first)
        first.x += 100.0
        assert first is not subsystem_world_position(sub)
        assert _xyz(subsystem_world_position(sub)) == want


def test_forget_recomputes_a_moved_ship(mount):
    ship, sub, computed = mount
    with step_memo.combat_step():
        before = _xyz(subsystem_world_position(sub))
        ship.SetTranslateXYZ(50.0, 0.0, 0.0)
        step_memo.forget()
        after = _xyz(subsystem_world_position(sub))
    assert after != before
    assert after == _xyz(subsystem_world_position(sub))


def test_the_block_closing_drops_the_answers(mount):
    ship, sub, computed = mount
    with step_memo.combat_step():
        subsystem_world_position(sub)
    ship.SetTranslateXYZ(-30.0, 0.0, 0.0)
    with step_memo.combat_step():
        inside = _xyz(subsystem_world_position(sub))
    assert inside == _xyz(subsystem_world_position(sub))
