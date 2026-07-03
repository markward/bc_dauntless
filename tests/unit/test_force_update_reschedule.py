"""ForceUpdate reschedules a cadence-gated AI to re-run on the next tick.

Exercises the gate directly on a PlainAI (the simplest node type that honours
_next_update_time in ai_driver._tick_plain). A node with a long GetNextUpdateTime
runs once, then sits idle until its cadence elapses — unless ForceUpdate() resets
its next-update time, which makes the very next driver tick re-run it.
"""
from engine.appc.ai import PlainAI
from engine.appc.ai_driver import tick_ai


class _CountingScript:
    """Minimal PlainAI script instance: counts Update() calls and reports a
    long update cadence so the driver gates subsequent ticks."""
    def __init__(self, interval):
        self.calls = 0
        self._interval = interval

    def Update(self):
        self.calls += 1
        return PlainAI.US_ACTIVE

    def GetNextUpdateTime(self):
        return self._interval


def _plain_with_script(interval=100.0):
    ai = PlainAI(None, "Gated")
    script = _CountingScript(interval)
    ai._script_instance = script
    return ai, script


def test_gate_suppresses_rerun_within_cadence():
    ai, script = _plain_with_script(interval=100.0)

    # First tick always runs (starts overdue at _next_update_time == 0.0).
    tick_ai(ai, game_time=0.0)
    assert script.calls == 1
    assert ai._next_update_time == 100.0

    # A tick well within the 100s cadence is gated — Update does NOT re-run.
    tick_ai(ai, game_time=1.0)
    assert script.calls == 1
    assert ai._next_update_time == 100.0


def test_force_update_reruns_on_next_tick():
    ai, script = _plain_with_script(interval=100.0)

    tick_ai(ai, game_time=0.0)
    assert script.calls == 1

    # Mid-cadence tick is gated (control).
    tick_ai(ai, game_time=1.0)
    assert script.calls == 1

    # ForceUpdate resets the schedule; it is a reschedule, not a synchronous
    # re-tick, so the count is unchanged until the next driver tick.
    ai.ForceUpdate()
    assert ai._next_update_time == 0.0
    assert script.calls == 1

    # The next tick — still within the original 100s window — now re-runs.
    tick_ai(ai, game_time=1.0)
    assert script.calls == 2
    # And it reschedules again from the current game_time.
    assert ai._next_update_time == 101.0
