"""The source guards' view of host_loop.run() (tests/helpers/host_frame_source):
run()'s source with the frame's sim section back in place of its
_run_frame_sim call (native motion phase 4, Task 1)."""
import inspect

from engine import host_loop
from tests.helpers import host_frame_source


def test_run_source_parses_as_one_function():
    assert host_frame_source.run_tree().name == "run"


def test_run_source_has_the_section_in_place():
    src = host_frame_source.run_source()
    assert (src.index('frame_profiler.mark("sim")')
            < src.index("for _tick_i in range(_sim_ticks_this_frame)")
            < src.index('frame_profiler.mark("render_prep")'))
    assert "_run_frame_sim(" not in src


def test_each_marker_appears_once():
    run_src = inspect.getsource(host_loop.run)
    sim_src = inspect.getsource(host_loop._run_frame_sim)
    for marker in (host_frame_source.CALL, host_frame_source.CALL_END):
        assert run_src.count(marker) == 1, marker
    for marker in (host_frame_source.BEGIN, host_frame_source.END):
        assert sim_src.count(marker) == 1, marker
