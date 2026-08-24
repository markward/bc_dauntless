"""Panel throttling: poll on a cadence, but never lag interaction.

The target list rebuilds the full subsystem tree of every contact just to
decide whether anything changed — 26.0 ms of a 26.7 ms UI phase at 33
contacts. Polling it at 2 Hz is the fix, but a throttle that also delays
clicks or a view switch is worse than the cost it removes, so those paths
are what these tests pin.
"""
from typing import Optional

import pytest

from engine.ui.panel import Panel
from engine.ui.panel_registry import PanelRegistry


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class _CountingPanel(Panel):
    def __init__(self, name: str, interval: float = 0.0):
        super().__init__()
        self._name = name
        self._interval = interval
        self.polls = 0
        self.handled = True

    @property
    def name(self) -> str:
        return self._name

    @property
    def poll_interval_s(self) -> float:
        return self._interval

    def render_payload(self) -> Optional[str]:
        self.polls += 1
        return "js:%d" % self.polls

    def dispatch_event(self, action: str) -> bool:
        return self.handled


@pytest.fixture
def clock():
    return _Clock()


def _registry(clock, *panels):
    reg = PanelRegistry(clock=clock)
    for p in panels:
        reg.register(p)
    return reg


def test_default_panel_is_polled_every_frame(clock):
    p = _CountingPanel("plain")
    reg = _registry(clock, p)
    for _ in range(10):
        reg.render_all()
        clock.advance(1 / 60.0)
    assert p.polls == 10


def test_throttled_panel_polls_on_its_interval(clock):
    p = _CountingPanel("slow", interval=0.5)
    reg = _registry(clock, p)
    # 3 seconds at 60 fps.
    for _ in range(180):
        reg.render_all()
        clock.advance(1 / 60.0)
    # One immediate first render (starts due) + one per 0.5 s thereafter.
    assert 6 <= p.polls <= 8, p.polls


def test_first_render_is_immediate_not_delayed_by_the_interval(clock):
    """A throttled panel must emit once before its first interval elapses,
    or the HUD is blank for half a second at mission start."""
    p = _CountingPanel("slow", interval=0.5)
    reg = _registry(clock, p)
    reg.render_all()
    assert p.polls == 1


def test_a_handled_event_renders_on_the_next_frame(clock):
    """Clicking a row must not wait for the next poll."""
    p = _CountingPanel("slow", interval=0.5)
    reg = _registry(clock, p)
    reg.render_all()                 # consumes the initial due flag
    clock.advance(1 / 60.0)
    reg.render_all()                 # throttled: no poll
    assert p.polls == 1

    assert reg.dispatch("slow/row-clicked") is True
    clock.advance(1 / 60.0)
    reg.render_all()
    assert p.polls == 2, "a click waited for the poll interval"


def test_an_unhandled_event_does_not_force_a_render(clock):
    p = _CountingPanel("slow", interval=0.5)
    p.handled = False
    reg = _registry(clock, p)
    reg.render_all()
    reg.dispatch("slow/ignored")
    clock.advance(1 / 60.0)
    reg.render_all()
    assert p.polls == 1


def test_a_visibility_flip_renders_on_the_next_frame(clock):
    """Switching tactical -> bridge must hide the HUD now, not in 0.5 s."""
    p = _CountingPanel("slow", interval=0.5)
    reg = _registry(clock, p)
    reg.render_all()
    clock.advance(1 / 60.0)

    p.visible = False
    reg.render_all()
    assert p.polls == 2, "a visibility change waited for the poll interval"


def test_reassigning_the_same_visibility_does_not_force_a_render(clock):
    """The host loop assigns `visible` every frame. If an unchanged assignment
    marked the panel due, the throttle would never take effect at all."""
    p = _CountingPanel("slow", interval=0.5)
    reg = _registry(clock, p)
    reg.render_all()
    for _ in range(20):
        p.visible = True             # same value, every frame
        reg.render_all()
        clock.advance(1 / 60.0)
    assert p.polls == 1, p.polls


def test_invalidate_all_forces_a_render_without_relying_on_super(clock):
    """Most Panel subclasses override invalidate() without calling super().
    The registry sets the flag itself so that stays safe."""
    class _NoSuper(_CountingPanel):
        def invalidate(self) -> None:
            pass                      # deliberately does NOT call super()

    p = _NoSuper("slow", interval=0.5)
    reg = _registry(clock, p)
    reg.render_all()
    clock.advance(1 / 60.0)

    reg.invalidate_all()
    reg.render_all()
    assert p.polls == 2


def test_throttling_one_panel_does_not_throttle_its_neighbours(clock):
    fast = _CountingPanel("fast")
    slow = _CountingPanel("slow", interval=0.5)
    reg = _registry(clock, fast, slow)
    for _ in range(60):
        reg.render_all()
        clock.advance(1 / 60.0)
    assert fast.polls == 60
    assert slow.polls <= 3, slow.polls


def test_the_target_list_is_the_panel_that_is_throttled():
    """Pins the intent: this exists for one measured panel, not as a blanket
    policy. If another panel takes an interval, that should be deliberate."""
    from engine.ui.target_list_view import TARGET_LIST_POLL_S
    assert TARGET_LIST_POLL_S == 0.5
