"""The wall-clock guard the mission harnesses run every mission inside.

It replaces signal.alarm()/SIGALRM on EVERY platform, not just Windows, so a
defect here lands on the machines we develop on. The mechanism it uses --
PyThreadState_SetAsyncExc -- arms an exception on a thread rather than raising
one, and an armed exception that outlives its block detonates in whatever
unrelated code runs next. These tests pin the boundary: the exception must
land inside the block, or not at all.
"""
import threading
import time

import pytest

import tools.timeout_guard as timeout_guard


def test_block_that_outlives_the_deadline_raises_inside_itself():
    with pytest.raises(TimeoutError) as excinfo:
        with timeout_guard.raise_after(0.05, "boom"):
            time.sleep(2.0)
    assert "boom" in str(excinfo.value)


def test_block_that_finishes_in_time_is_untouched():
    with timeout_guard.raise_after(5.0, "boom"):
        result = 1 + 1
    assert result == 2
    # A cancelled timer must leave nothing armed: burn bytecode (the only point
    # at which an async exception can be delivered) and require silence.
    for _ in range(200000):
        pass


class _ManualTimer:
    """threading.Timer that fires only when the test says so.

    The race is decided by whether the timer's callback runs before or after
    the guarded block exits, and a real Timer decides that by wall clock --
    the one thing a test must not depend on. This takes the clock out.
    """

    fired_callback = None

    def __init__(self, interval, function):
        _ManualTimer.fired_callback = function
        self.daemon = False

    def start(self):
        pass

    def cancel(self):
        pass


def test_a_timer_firing_after_the_block_exits_arms_nothing(monkeypatch):
    """The race the guard exists to survive.

    Arming is two steps -- record that it fired, then call into the
    interpreter -- and so is the exit path: check that record, then disarm.
    Interleaved the wrong way, the exit disarms and THEN the arming lands,
    leaving a HarnessTimeout pending on a thread that has already left the
    guarded region, where it detonates in whatever ran next. Here the callback
    is held until the block has fully exited, the worst case for that ordering.
    """
    monkeypatch.setattr(timeout_guard.threading, "Timer", _ManualTimer)
    _ManualTimer.fired_callback = None

    with timeout_guard.raise_after(0.05, "boom"):
        pass
    assert _ManualTimer.fired_callback is not None, "guard never armed a timer"

    # The timer thread wakes up late, after the block is gone. It must decline
    # to arm rather than leave an exception pending on this thread.
    late = threading.Thread(target=_ManualTimer.fired_callback)
    late.start()
    late.join(5.0)
    assert not late.is_alive(), "late timer callback deadlocked"

    # Anything the late callback armed detonates here, outside the block.
    for _ in range(2000000):
        pass


def test_a_timer_firing_during_the_block_still_raises_inside_it(monkeypatch):
    """The other half of the same seam: declining to arm late must not become
    declining to arm at all. Fired while the block is live, the exception has
    to land in the block exactly as a real timeout would."""
    monkeypatch.setattr(timeout_guard.threading, "Timer", _ManualTimer)
    _ManualTimer.fired_callback = None

    with pytest.raises(TimeoutError):
        with timeout_guard.raise_after(0.05, "boom"):
            fire = threading.Thread(target=_ManualTimer.fired_callback)
            fire.start()
            fire.join(5.0)
            for _ in range(2000000):   # bytecode boundaries for delivery
                pass
