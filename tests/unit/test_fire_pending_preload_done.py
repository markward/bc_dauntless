"""Per-tick firing of QuickBattle's stored preload-done event.

QuickBattle.StartSimulationAction creates a TGEvent(ET_PRELOAD_DONE,
destination=mission) and calls Game.SetPreLoadDoneEvent(evt), trusting the
engine to fire it once asset preloading finishes. In dauntless asset loading is
synchronous, so the host main loop fires the stored event on the next tick (and
StartSimulation2 — the handler — then spawns the player ship, which the same
tick's reconciliation pass realizes). These tests pin the fire-once contract of
the `_fire_pending_preload_done` helper that the loop calls.
"""
import App
from engine.core.game import Game, _set_current_game


class _RecordingDestination(App.TGEventHandlerObject):
    """A TGEventHandlerObject (the type AddEvent routes to) that records each
    ProcessEvent so tests can assert the stored event was actually posted."""

    def __init__(self):
        super().__init__()
        self.processed = []

    def ProcessEvent(self, event):
        self.processed.append(event)


def _make_preload_event(dest):
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_PRELOAD_DONE)
    evt.SetDestination(dest)
    return evt


def test_fires_pending_event_and_clears_it():
    """A Game with a pending _preload_done_event posts that event through the
    event manager (destination.ProcessEvent runs) and clears the slot."""
    from engine import host_loop as hl
    dest = _RecordingDestination()
    evt = _make_preload_event(dest)
    game = Game()
    game.SetPreLoadDoneEvent(evt)
    _set_current_game(game)

    hl._fire_pending_preload_done()

    assert dest.processed == [evt]
    assert game._preload_done_event is None

    _set_current_game(None)


def test_fires_once_only():
    """Calling the helper again after the slot is cleared does not re-post."""
    from engine import host_loop as hl
    dest = _RecordingDestination()
    evt = _make_preload_event(dest)
    game = Game()
    game.SetPreLoadDoneEvent(evt)
    _set_current_game(game)

    hl._fire_pending_preload_done()
    hl._fire_pending_preload_done()

    assert dest.processed == [evt]  # not [evt, evt]
    assert game._preload_done_event is None

    _set_current_game(None)


def test_no_game_is_noop():
    """No current game => helper is a silent no-op (no exception)."""
    from engine import host_loop as hl
    _set_current_game(None)
    hl._fire_pending_preload_done()  # must not raise


def test_no_pending_event_is_noop():
    """A game with no pending event => helper is a silent no-op."""
    from engine import host_loop as hl
    game = Game()
    _set_current_game(game)

    hl._fire_pending_preload_done()  # must not raise

    assert game._preload_done_event is None
    _set_current_game(None)
