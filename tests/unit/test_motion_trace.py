"""engine.core.motion_trace: off unless DAUNTLESS_MOTION_TRACE names a file;
when on, one CSV row per recorded frame under a header."""
import csv

from engine.core import motion_trace


def _reset():
    motion_trace._path = None
    motion_trace._rows = []
    motion_trace._frame = 0


def test_off_without_the_env_var(monkeypatch):
    _reset()
    monkeypatch.delenv(motion_trace.TRACE_ENV, raising=False)
    assert motion_trace.configure_from_env() is False
    assert not motion_trace.enabled()
    motion_trace.record(t_start=0.0, frame_dt=0.0, ticks=0, alpha=0.0,
                        interp=False, ai=False, cutscene=False, handover=False,
                        live=None, drawn=None, eye=None, target=None)
    assert motion_trace._rows == []


def test_rows_land_under_the_header(monkeypatch, tmp_path):
    _reset()
    out = tmp_path / "trace.csv"
    monkeypatch.setenv(motion_trace.TRACE_ENV, str(out))
    assert motion_trace.configure_from_env()
    for i in range(3):
        motion_trace.record(
            t_start=float(i), frame_dt=1.0 / 144, ticks=i % 2, alpha=0.25,
            interp=True, ai=True, cutscene=False, handover=False,
            live=(1.0, 2.0, 3.0), drawn=(1.0, 2.0, float(i)),
            eye=(0.0, 0.0, 0.0), target=None)
    motion_trace.flush()
    _reset()
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 3
    assert rows[2]["drawn_z"] == "2.000000"
    assert rows[1]["ticks"] == "1" and rows[0]["interp"] == "1"
    assert rows[0]["tgt_x"] == ""
