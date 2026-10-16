"""engine.core.frame_profiler spike capture -- one-off long frames to a file.

The averaged report cannot see a single slow frame: a 5 s arrival hitch is
blended at alpha 0.15 and decays before the next 120-frame report prints. The
spike log records the RAW numbers of every frame over a threshold instead.
"""
import time

import pytest

from engine.core import frame_profiler as fp


@pytest.fixture(autouse=True)
def _isolated_profiler(monkeypatch):
    from engine import host_io
    monkeypatch.setattr(host_io, "profiler_last_frame_raw",
                        lambda: {"cpu_ms": 0.0, "scopes": []})
    fp.set_enabled(False, native=False)
    fp.reset()
    fp.configure_spike_log(None)
    yield
    fp.set_enabled(False, native=False)
    fp.reset()
    fp.configure_spike_log(None)


def _busy(seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass


def _frame(phase_s: float, scope_s: float = 0.0) -> None:
    fp.begin_frame()
    fp.mark("sim")
    if scope_s:
        with fp.scope("scene.celestial"):
            _busy(scope_s)
    _busy(phase_s)
    fp.end_frame()


def test_configure_enables_the_profiler(tmp_path):
    fp.configure_spike_log(tmp_path / "spikes.log", threshold_ms=5.0,
                           native=False)
    assert fp.is_enabled()
    assert fp.spike_log_path() == tmp_path / "spikes.log"


def test_a_fast_frame_writes_nothing(tmp_path):
    log = tmp_path / "spikes.log"
    fp.configure_spike_log(log, threshold_ms=50.0, native=False)
    _frame(0.001)
    assert fp.maybe_log_spike() is False
    assert not log.exists() or "spike #" not in log.read_text()


def test_a_slow_frame_is_written_with_its_raw_breakdown(tmp_path):
    log = tmp_path / "spikes.log"
    fp.configure_spike_log(log, threshold_ms=10.0, native=False)
    # Many fast frames first: the EMA would dilute the slow one, the raw
    # record must not.
    for _ in range(20):
        _frame(0.0005)
    _frame(0.005, scope_s=0.020)
    assert fp.maybe_log_spike() is True
    text = log.read_text()
    assert "spike #1" in text
    lines = {ln.split()[0]: ln for ln in text.splitlines()
             if ln.strip() and ln.split()[0] in ("sim", "scene.celestial")}
    # Raw: the scope is >= its 20 ms, not an average blended toward 0.5 ms.
    assert float(lines["scene.celestial"].split()[1]) >= 20.0
    assert float(lines["sim"].split()[1]) >= 25.0


def test_the_child_is_indented_under_its_parent(tmp_path):
    log = tmp_path / "spikes.log"
    fp.configure_spike_log(log, threshold_ms=5.0, native=False)
    _frame(0.0, scope_s=0.010)
    fp.maybe_log_spike()
    rows = [ln for ln in log.read_text().splitlines()
            if "scene.celestial" in ln]
    assert rows and rows[0].startswith("      scene.celestial")


def test_spikes_are_numbered_and_appended(tmp_path):
    log = tmp_path / "spikes.log"
    fp.configure_spike_log(log, threshold_ms=5.0, native=False)
    _frame(0.010)
    fp.maybe_log_spike()
    _frame(0.010)
    fp.maybe_log_spike()
    text = log.read_text()
    assert "spike #1" in text and "spike #2" in text


def test_context_is_recorded(tmp_path):
    log = tmp_path / "spikes.log"
    fp.configure_spike_log(log, threshold_ms=5.0, native=False)
    _frame(0.010)
    fp.maybe_log_spike(context="view=Vesuvi6 warp=arriving")
    assert "view=Vesuvi6 warp=arriving" in log.read_text()


def test_native_raw_scopes_are_written(tmp_path, monkeypatch):
    from engine import host_io
    monkeypatch.setattr(host_io, "profiler_last_frame_raw", lambda: {
        "cpu_ms": 812.0,
        "scopes": [
            {"name": "frame", "cpu_ms": 812.0, "calls": 1, "depth": 0},
            {"name": "rock.near.stream", "cpu_ms": 790.5, "calls": 1,
             "depth": 1},
        ]})
    log = tmp_path / "spikes.log"
    fp.configure_spike_log(log, threshold_ms=5.0, native=False)
    _frame(0.010)
    fp.maybe_log_spike()
    text = log.read_text()
    assert "rock.near.stream" in text and "790.5" in text


def test_disabled_capture_never_writes(tmp_path):
    fp.set_enabled(True, native=False)
    _frame(0.010)
    assert fp.maybe_log_spike() is False


def test_spike_mode_suppresses_the_periodic_stderr_report(tmp_path):
    fp.configure_spike_log(tmp_path / "spikes.log", threshold_ms=5.0,
                           native=False)
    assert not any(fp.should_report() for _ in range(fp.REPORT_EVERY * 2))


def test_a_missing_parent_directory_is_created(tmp_path):
    log = tmp_path / "logs" / "spikes.log"
    fp.configure_spike_log(log, threshold_ms=5.0, native=False)
    _frame(0.010)
    assert fp.maybe_log_spike() is True
    assert "spike #1" in log.read_text()


def test_an_unwritable_path_never_raises(tmp_path):
    # A directory cannot be opened for append.
    (tmp_path / "is_a_dir").mkdir()
    fp.configure_spike_log(tmp_path / "is_a_dir", threshold_ms=5.0,
                           native=False)
    _frame(0.010)
    assert fp.maybe_log_spike() is False


def test_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DAUNTLESS_PROFILE_SPIKES", str(tmp_path / "s.log"))
    monkeypatch.setenv("DAUNTLESS_PROFILE_SPIKE_MS", "40")
    assert fp.configure_spike_log_from_env(native=False) is True
    assert fp.spike_log_path() == tmp_path / "s.log"
    assert fp.spike_threshold_ms() == 40.0


def test_from_env_unset_does_nothing(monkeypatch):
    monkeypatch.delenv("DAUNTLESS_PROFILE_SPIKES", raising=False)
    assert fp.configure_spike_log_from_env(native=False) is False
    assert not fp.is_enabled()


def test_context_callable_runs_only_for_a_spike(tmp_path):
    calls = []

    def ctx():
        calls.append(1)
        return "view=Starbase12"

    fp.configure_spike_log(tmp_path / "s.log", threshold_ms=50.0,
                           native=False)
    _frame(0.001)
    fp.maybe_log_spike(context=ctx)
    assert calls == []
    _frame(0.060)
    fp.maybe_log_spike(context=ctx)
    assert calls == [1]
    assert "view=Starbase12" in (tmp_path / "s.log").read_text()


def test_warp_arrival_actions_are_scoped():
    """Each arrival action is its own profiler scope, so a spike owned by one
    of them is attributable instead of vanishing into the sim phase."""
    from engine.appc import warp

    # Degenerate inputs take each action's early-out path: the scope must
    # wrap the whole body, early-outs included.
    actions = {
        "warp.depart": warp._WarpDepartAction(None, None, hard_cut=True),
        "warp.place_player": warp._PlacePlayerAction(None, None, None),
        "warp.arrive_finalize": warp._ArriveFinalizeAction(None),
        "warp.exited_warp": warp._ArrivalExitedWarpAction(None),
        "warp.clear_targets": warp._ArrivalClearTargetsAction(None),
    }
    fp.set_enabled(True, native=False)
    fp.begin_frame()
    fp.mark("sim")
    for action in actions.values():
        action._do_play()
    fp.end_frame()
    assert set(actions) <= set(fp.parents())


def test_game_loop_timer_ticks_are_scoped():
    from engine.core.loop import GameLoop

    fp.set_enabled(True, native=False)
    fp.begin_frame()
    fp.mark("sim")
    GameLoop().tick()
    fp.end_frame()
    assert {"gl.timers.game", "gl.timers.real"} <= set(fp.parents())
