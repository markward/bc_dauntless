"""actions.scripted_line_pending: is a playing sequence still going to speak?

Mission dialogue is overwhelmingly TGSequences of speak CharacterActions with
gaps between lines; crew_hazard_prompts must not start a line in one of
those gaps (the next scripted line cuts it off)."""
import App

from engine.appc import actions
from engine.appc.actions import TGAction, TGSequence_Create


class _Hold(TGAction):
    """Plays until completed by hand -- a camera move or a long animation."""

    def Play(self):
        self._playing = True


def _line(key="Line"):
    return App.CharacterAction_Create(
        None, App.CharacterAction.AT_SAY_LINE, key, "Captain", 1, None)


def test_nothing_playing_means_no_scripted_line():
    assert actions.scripted_line_pending() is False


def test_a_line_still_to_come_after_a_gap_is_pending():
    hold = _Hold()
    seq = TGSequence_Create()
    seq.AppendAction(hold)
    seq.AppendAction(_line())
    seq.Play()
    assert actions.scripted_line_pending() is True
    seq.Abort()


def test_a_sequence_without_lines_is_not_dialogue():
    hold = _Hold()
    seq = TGSequence_Create()
    seq.AppendAction(hold)
    seq.Play()
    assert actions.scripted_line_pending() is False
    seq.Abort()


def test_a_line_already_spoken_no_longer_counts():
    hold = _Hold()
    spoken = _line()
    seq = TGSequence_Create()
    seq.AppendAction(spoken)
    seq.AppendAction(hold)
    seq.Play()
    if spoken.IsPlaying():
        spoken.Completed()
    assert hold.IsPlaying()
    assert actions.scripted_line_pending() is False
    seq.Abort()


def test_a_line_inside_a_nested_sequence_counts():
    hold = _Hold()
    inner = TGSequence_Create()
    inner.AppendAction(_line())
    outer = TGSequence_Create()
    outer.AppendAction(hold)
    outer.AppendAction(inner)
    outer.Play()
    assert actions.scripted_line_pending() is True
    outer.Abort()


def test_an_aborted_sequence_is_not_dialogue():
    hold = _Hold()
    seq = TGSequence_Create()
    seq.AppendAction(hold)
    seq.AppendAction(_line())
    seq.Play()
    seq.Abort()
    assert actions.scripted_line_pending() is False


def test_a_sequence_that_was_never_played_is_not_dialogue():
    seq = TGSequence_Create()
    seq.AppendAction(_Hold())
    seq.AppendAction(_line())
    assert actions.scripted_line_pending() is False


def test_a_finished_sequence_is_not_dialogue():
    hold = _Hold()
    seq = TGSequence_Create()
    seq.AppendAction(hold)
    seq.Play()
    hold.Completed()
    assert not seq.IsPlaying()
    assert actions.scripted_line_pending() is False


def test_mission_swap_forgets_a_sequence_left_playing():
    """A prior mission's sequence that never finished must not hold the
    prompts off for the rest of the session."""
    seq = TGSequence_Create()
    seq.AppendAction(_Hold())
    seq.AppendAction(_line())
    seq.Play()
    actions.reset_launched_sequences()
    assert actions.scripted_line_pending() is False


def test_mission_swap_keeps_sequences_it_is_told_to_keep():
    kept, dropped = TGSequence_Create(), TGSequence_Create()
    for seq in (kept, dropped):
        seq.AppendAction(_Hold())
        seq.AppendAction(_line())
        seq.Play()
    actions.reset_launched_sequences(keep={id(kept)})
    assert actions.scripted_line_pending() is True
    kept.Abort()
    assert actions.scripted_line_pending() is False
