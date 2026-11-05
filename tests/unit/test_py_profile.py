"""engine.core.py_profile: an opt-in cProfile window over whole frames.

DAUNTLESS_PROFILE_PY=<path> turns it on; DAUNTLESS_PROFILE_PY_FRAMES=start:count
picks the window (default 600:600). The stats land in <path> as pstats.
"""
import pstats

from engine.core import py_profile


def _work():
    return sum(i * i for i in range(200))


def test_off_without_the_env(monkeypatch, tmp_path):
    monkeypatch.delenv("DAUNTLESS_PROFILE_PY", raising=False)
    w = py_profile.Window.from_env()
    assert w is None


def test_window_profiles_only_its_frames_and_dumps(monkeypatch, tmp_path):
    out = tmp_path / "py.pstats"
    monkeypatch.setenv("DAUNTLESS_PROFILE_PY", str(out))
    monkeypatch.setenv("DAUNTLESS_PROFILE_PY_FRAMES", "2:3")
    w = py_profile.Window.from_env()
    assert (w.start, w.count) == (2, 3)
    states = []
    for _ in range(8):
        w.frame_tick()
        states.append(w.active)
        _work()
    # frames 0,1 off; 2,3,4 on; dumped at the start of frame 5; off after.
    assert states == [False, False, True, True, True, False, False, False]
    assert out.exists()
    st = pstats.Stats(str(out))
    names = {fn for (_, _, fn) in st.stats}
    assert "_work" in names


def test_default_window(monkeypatch, tmp_path):
    monkeypatch.setenv("DAUNTLESS_PROFILE_PY", str(tmp_path / "p"))
    monkeypatch.delenv("DAUNTLESS_PROFILE_PY_FRAMES", raising=False)
    w = py_profile.Window.from_env()
    assert (w.start, w.count) == (600, 600)
