"""Host-loop wiring of the Bridge Editor preview (spec §12.2)."""
import pytest

from engine import host_loop


class Editor:
    def __init__(self, alert, dt):
        self._a, self._dt = alert, dt

    def preview_alert(self):
        return self._a

    def preview_dt(self, player_dt, frame_dt):
        return player_dt if self._a is None else self._dt


def test_the_editor_overrides_the_alert_only_while_open():
    assert host_loop._bridge_effective_alert(2, Editor(None, 0.0)) == 2
    assert host_loop._bridge_effective_alert(2, Editor(1, 0.0)) == 1
    assert host_loop._bridge_effective_alert(2, host_loop._NULL_PICKER) == 2


def test_the_clock_dt_comes_from_the_editor_when_it_has_one():
    assert host_loop._bridge_clock_dt(Editor(1, 0.016), 0.0, 0.016) == 0.016
    assert host_loop._bridge_clock_dt(Editor(None, 0.0), 0.02, 0.016) == 0.02
    assert host_loop._bridge_clock_dt(host_loop._NULL_PICKER, 0.02, 0.016) == 0.02


def test_the_texture_clock_is_game_time_while_the_editor_is_closed():
    offset = [0.0]
    assert host_loop._bridge_texture_time(offset, 12.5, Editor(None, 0.0), 0.0) == 12.5
    assert offset == [0.0]


def test_the_texture_clock_runs_on_the_preview_clock_while_the_editor_is_open():
    # The sim (game time) is frozen while the editor is open; panels and
    # flipbooks still play, on the preview clock (0 when it is paused).
    offset = [0.0]
    editor = Editor(1, 0.016)
    assert host_loop._bridge_texture_time(offset, 12.5, editor, 0.016) == pytest.approx(12.516)
    assert host_loop._bridge_texture_time(offset, 12.5, editor, 0.016) == pytest.approx(12.532)
    assert host_loop._bridge_texture_time(offset, 12.5, editor, 0.0) == pytest.approx(12.532)


def test_the_texture_clock_never_steps_back_when_the_editor_closes():
    offset = [0.0]
    host_loop._bridge_texture_time(offset, 12.5, Editor(1, 0.5), 0.5)
    assert host_loop._bridge_texture_time(offset, 12.6, Editor(None, 0.0), 0.0) == pytest.approx(13.1)
