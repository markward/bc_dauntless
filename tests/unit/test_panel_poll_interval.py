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
    policy. If another panel takes an interval, that should be deliberate.

    Asserts the INSTANCE property, which is what PanelRegistry.render_all
    actually reads. Asserting only the module constant let the property be
    rewritten to return a literal (or 0.0) with the test still green.
    """
    from engine.ui.target_list_view import TargetListView, TARGET_LIST_POLL_S
    assert TARGET_LIST_POLL_S == 0.5
    assert TargetListView().poll_interval_s == 0.5


# ── Hidden panels are not polled ────────────────────────────────────────────
#
# The throttle caps the target list at 2 Hz; this removes the poll entirely
# while the panel is off screen (bridge view, cutscene, Ship Property Viewer),
# which is the larger win. It is safe by construction: the `visible` setter
# marks the panel due on a FLIP, so the hide itself still emits one payload
# (the JS needs to be told to hide) and the un-hide renders on the next frame.


def test_a_hidden_panel_is_not_polled(clock):
    p = _CountingPanel("plain")               # interval 0: normally every frame
    reg = _registry(clock, p)
    reg.render_all()
    assert p.polls == 1

    p.visible = False
    reg.render_all()
    assert p.polls == 2, "the hide itself must emit — JS has to be told"

    for _ in range(30):
        clock.advance(1 / 60.0)
        reg.render_all()
    assert p.polls == 2, "a hidden panel was still polled"


def test_a_hidden_throttled_panel_is_not_polled(clock):
    p = _CountingPanel("slow", interval=0.5)
    reg = _registry(clock, p)
    reg.render_all()
    p.visible = False
    reg.render_all()
    baseline = p.polls
    for _ in range(180):                      # 3 s — six intervals
        clock.advance(1 / 60.0)
        reg.render_all()
    assert p.polls == baseline, "a hidden panel kept paying its 2 Hz poll"


def test_a_panel_renders_immediately_when_it_becomes_visible_again(clock):
    p = _CountingPanel("slow", interval=0.5)
    reg = _registry(clock, p)
    reg.render_all()
    p.visible = False
    reg.render_all()
    for _ in range(180):
        clock.advance(1 / 60.0)
        reg.render_all()
    hidden_polls = p.polls

    p.visible = True
    reg.render_all()
    assert p.polls == hidden_polls + 1, (
        "un-hiding waited for the poll interval instead of the next frame")


def test_mark_due_is_public_surface_and_forces_the_next_poll(clock):
    """The host loop invalidates the target list on a target change. That has
    to be a supported call, not a poke at Panel._render_due."""
    p = _CountingPanel("slow", interval=0.5)
    reg = _registry(clock, p)
    reg.render_all()
    clock.advance(1 / 60.0)
    reg.render_all()
    assert p.polls == 1

    p.mark_due()
    clock.advance(1 / 60.0)
    reg.render_all()
    assert p.polls == 2


# ── The real panel, through the real registry ──────────────────────────────


def _target_list_fixture():
    """Minimal live game + target menu so a real TargetListView can render."""
    import App
    from engine.appc.ships import ShipClass
    from engine.core.game import Game, Episode, Mission, _set_current_game

    App._reset_target_menu_singleton()
    App.STTargetMenu_CreateW("Targets")
    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    player = ShipClass()
    player.SetName("Player")
    game.SetPlayer(player)
    _set_current_game(game)
    return game, player


def test_the_real_target_list_view_is_throttled_through_the_registry(clock):
    """Every other target-list test calls render_payload() directly, so the
    throttle was only ever exercised against a synthetic panel. Drive the real
    class through the real registry."""
    from engine.core.game import _set_current_game
    from engine.ui.target_list_view import TargetListView

    _target_list_fixture()
    try:
        view = TargetListView()
        polls = []
        inner = view.render_payload

        def _counting():
            polls.append(1)
            return inner()

        view.render_payload = _counting        # instance attr; class untouched

        reg = PanelRegistry(clock=clock)
        reg.register(view)

        first = reg.render_all()
        assert first and first[0].startswith("setTargetList(")
        for _ in range(180):                   # 3 s at 60 fps
            clock.advance(1 / 60.0)
            reg.render_all()
        assert 6 <= len(polls) <= 8, len(polls)

        # ...and it stops entirely when the panel goes off screen.
        view.visible = False
        reg.render_all()
        hidden = len(polls)
        for _ in range(180):
            clock.advance(1 / 60.0)
            reg.render_all()
        assert len(polls) == hidden
    finally:
        _set_current_game(None)


# --- a visibility flip must be observed, however it was made ---------------
# The hidden-panel skip is safe only if the flip TO hidden is noticed. That
# used to rely on every panel routing through the Panel.visible SETTER — a
# rule nothing enforced, and which six panels broke by assigning _visible
# directly in close(). The result: ESC killed a panel's GL half and left its
# CEF chrome on screen, because the payload carrying visible:false was never
# polled for. Confirmed live on the star map and the QuickBattle setup panel.

def test_a_direct_visibility_flip_still_gets_one_last_poll():
    """The registry observes visibility itself rather than trusting panels to
    announce it, so bypassing the setter cannot strand chrome on screen."""
    clock = _Clock()
    registry = PanelRegistry(clock=clock)
    panel = _CountingPanel("p")
    registry.register(panel)
    registry.render_all()                    # drain the initial due
    before = panel.polls

    panel._visible = False                   # what close() does in six panels

    registry.render_all()
    assert panel.polls == before + 1, (
        "a panel going hidden must be polled once more so CEF is told")


def test_a_hidden_panel_is_not_polled_again_after_that():
    """The counterweight: the extra poll is ONE frame, not a standing cost.
    Without this, the fix would quietly undo the optimisation it protects."""
    clock = _Clock()
    registry = PanelRegistry(clock=clock)
    panel = _CountingPanel("p")
    registry.register(panel)
    registry.render_all()
    panel._visible = False
    registry.render_all()                    # the one last poll
    settled = panel.polls

    for _ in range(5):
        clock.advance(1.0)
        registry.render_all()
    assert panel.polls == settled


def test_becoming_visible_again_resumes_polling():
    clock = _Clock()
    registry = PanelRegistry(clock=clock)
    panel = _CountingPanel("p")
    registry.register(panel)
    registry.render_all()
    panel._visible = False
    registry.render_all()
    settled = panel.polls

    panel._visible = True
    registry.render_all()
    assert panel.polls == settled + 1
