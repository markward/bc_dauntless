"""Live DOF tuning under --developer.

The point of these keys is that a visual constant gets calibrated in ONE
session: nudge in flight, read the value off stderr, and it becomes the
default in engine/cameras/dof.py. Without them each candidate value costs a
rebuild and a relaunch.
"""
import engine.dev_mode as dev_mode
import engine.dev_keybindings as dev_keybindings
from engine.cameras.dof import FocusSolver, STRENGTH_MAX, STRENGTH_MIN


class _FakeKeys:
    """Hands back a distinct int for any KEY_* name asked of it."""

    def __init__(self):
        self._codes = {}

    def __getattr__(self, name):
        return self._codes.setdefault(name, len(self._codes) + 1)


class _FakeHost:
    def __init__(self):
        self.keys = _FakeKeys()


def test_comma_and_period_are_registered(monkeypatch):
    seen = {}

    def _capture(key, handler, description):
        seen[key] = (handler, description)

    monkeypatch.setattr(dev_mode, "register_dev_keybinding", _capture)
    fake = _FakeHost()
    # register_for_frame tolerates a None session/player -- every handler that
    # needs them checks first.
    dev_keybindings.register_for_frame(fake, None, None)

    assert fake.keys.KEY_COMMA in seen
    assert fake.keys.KEY_PERIOD in seen
    assert "DOF" in seen[fake.keys.KEY_PERIOD][1]


def test_the_handlers_survive_no_host_loop_solver(monkeypatch):
    """The handler resolves host_loop._focus_solver lazily. If the loop has
    not started, pressing the key must be a no-op rather than an exception
    that kills the input dispatch."""
    seen = {}

    def _capture(key, handler, description):
        seen[key] = (handler, description)

    monkeypatch.setattr(dev_mode, "register_dev_keybinding", _capture)
    fake = _FakeHost()
    dev_keybindings.register_for_frame(fake, None, None)

    import engine.host_loop as host_loop
    monkeypatch.setattr(host_loop, "_focus_solver", None, raising=False)
    seen[fake.keys.KEY_PERIOD][0]()   # must not raise


def test_nudging_up_then_down_returns_to_the_start():
    s = FocusSolver()
    start = s.near_strength
    s.nudge_strength(0.1)
    s.nudge_strength(-0.1)
    assert abs(s.near_strength - start) < 1e-9


def test_nudge_saturates_rather_than_running_away():
    s = FocusSolver()
    for _ in range(200):
        s.nudge_strength(0.1)
    assert s.near_strength == STRENGTH_MAX
    for _ in range(200):
        s.nudge_strength(-0.1)
    assert s.near_strength == STRENGTH_MIN
