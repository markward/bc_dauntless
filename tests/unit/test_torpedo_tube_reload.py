"""TorpedoTube.UpdateReload — advances _num_ready when reload elapses.
Caps at _max_ready.  Time source is time.monotonic().
"""
import time

from engine.appc.subsystems import TorpedoTube, TorpedoSystem


def _tube(num_ready=0, max_ready=1, reload_delay=40.0):
    tube = TorpedoTube("Forward Torpedo 1")
    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    parent.AddChildSubsystem(tube)
    tube._max_ready = max_ready
    tube._num_ready = num_ready
    tube._reload_delay = reload_delay
    return tube


def test_update_reload_caps_at_max_ready():
    tube = _tube(num_ready=1, max_ready=1)
    tube.UpdateReload(dt=100.0)
    assert tube.GetNumReady() == 1


def test_update_reload_no_change_before_delay():
    tube = _tube(num_ready=0, max_ready=1, reload_delay=40.0)
    # Simulate firing now, then ask for an update at dt=0.1 (should not advance).
    tube._last_fire_time = time.monotonic()
    tube.UpdateReload(dt=0.1)
    assert tube.GetNumReady() == 0


def test_update_reload_advances_after_delay():
    tube = _tube(num_ready=0, max_ready=1, reload_delay=0.001)  # tiny delay for test
    tube._last_fire_time = time.monotonic() - 1.0  # >> reload_delay ago
    tube.UpdateReload(dt=0.0)
    assert tube.GetNumReady() == 1


def test_update_reload_resets_timer_after_each_increment():
    """A tube with multiple ready slots reloads them one at a time, each
    waiting reload_delay from the previous reload."""
    tube = _tube(num_ready=0, max_ready=2, reload_delay=0.001)
    # First reload triggers.
    tube._last_fire_time = time.monotonic() - 1.0
    tube.UpdateReload(dt=0.0)
    assert tube.GetNumReady() == 1
    first_reload_time = tube.GetLastFireTime()
    # Immediate second call — last_fire_time was just updated, not enough
    # has elapsed for the next slot.
    tube.UpdateReload(dt=0.0)
    assert tube.GetNumReady() == 1
    # Manually rewind last_fire_time to simulate another reload_delay passing.
    tube._last_fire_time = first_reload_time - 1.0
    tube.UpdateReload(dt=0.0)
    assert tube.GetNumReady() == 2
