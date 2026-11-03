"""A mission swap drops the damage effects held for the tick boundary
(native damage, task review M2): a ZERO_CROSS a script's write left queued
names the old mission's ship and must never act in the next mission. Both
swaps reset the queue -- the dev mission picker's
(HostController._drain_pending_swap) and a campaign mission change
(mission_change.change)."""
import App

from engine.appc import effect_queue, ship_death, subsystem_cascade
from engine.appc.subsystems import HullSubsystem
from engine.core import mission_change
from tests.helpers.mission_change_fixtures import (
    _forget_world, _install, _world)


def teardown_function(_):
    effect_queue.reset()
    subsystem_cascade.reset()
    ship_death.reset()
    _forget_world()


def _doomed_ship():
    """A ship whose critical hull a script zeroed: its ZERO_CROSS held."""
    ship = App.ShipClass_Create()
    ship.SetName("Doomed")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(1000.0)
    hull.SetCritical(1)
    ship.SetHull(hull)
    hull.SetCondition(0.0)
    assert not ship.IsDying()
    return ship


def _dev_swap():
    from engine.host_loop import HostController, MissionSession

    class _StubLoader:
        def load(self, name):
            return MissionSession(mission_name=name)

    class _FakeRenderer:
        def destroy_instance(self, iid):
            pass

    h = HostController()
    h.renderer = _FakeRenderer()
    h.loader = _StubLoader()
    h.session = MissionSession(mission_name="prev")
    h.swap_mission("Next.Mission")
    h._drain_pending_swap()


def test_the_dev_mission_swap_drops_held_damage():
    ship = _doomed_ship()
    _dev_swap()
    effect_queue.boundary()
    assert not ship.IsDying()
    assert subsystem_cascade._active == []


def test_a_mission_change_drops_held_damage():
    _world()
    _install("_t.Old", Terminate=lambda m: None)
    _install("_t.New", Initialize=lambda m: None)
    ship = _doomed_ship()
    assert mission_change.change(mission="_t.New") is True
    effect_queue.boundary()
    assert not ship.IsDying()
    assert subsystem_cascade._active == []
