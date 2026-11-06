"""tests/helpers/render_golden.py: record is inert without
UPDATE_RENDER_GOLDEN=1 and refuses with it (the Python builders the goldens
were recorded from are gone); the writer counts and digests each frame; check
compares per frame and names the first frame that differs."""
import json
import sys

import pytest

from tests.helpers import render_golden


def _frames(source="python"):
    return [render_golden.frame(phasers=[b"\x01" * 80, b"\x02" * 80],
                                tractors=[b"\x03" * 80], source=source),
            render_golden.frame(torps=[b"torp"], lights=[b"l1", b"l2"],
                                source=source),
            render_golden.frame(source=source)]


@pytest.fixture
def golden_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("RENDER_GOLDEN_DIR", str(tmp_path))
    monkeypatch.delenv("UPDATE_RENDER_GOLDEN", raising=False)
    return tmp_path


def test_record_is_inert_without_the_env(golden_dir):
    assert not render_golden.recording()
    render_golden.record("tiny", _frames())
    assert not list(golden_dir.iterdir())


def test_the_writer_writes_per_frame_counts_and_digests(golden_dir):
    path = render_golden._write("tiny", _frames(), "test frames")
    assert path == golden_dir / ("tiny.%s.json" % sys.platform)
    data = json.loads(path.read_text())
    assert data["scene"] == "tiny" and data["platform"] == sys.platform
    recs = data["frames"]
    assert [{k: r[k] for k in ("frame", "phasers", "tractors", "torps",
                               "lights")} for r in recs] == [
        {"frame": 0, "phasers": 2, "tractors": 1, "torps": 0, "lights": 0},
        {"frame": 1, "phasers": 0, "tractors": 0, "torps": 1, "lights": 2},
        {"frame": 2, "phasers": 0, "tractors": 0, "torps": 0, "lights": 0}]
    assert all(len(r["sha"]) == 64 for r in recs)
    assert len({r["sha"] for r in recs}) == 3
    # The same frames write the same bytes.
    before = path.read_bytes()
    render_golden._write("tiny", _frames(), "test frames")
    assert path.read_bytes() == before


def _record_tiny(monkeypatch):
    render_golden._write("tiny", _frames(), "test frames")


def test_check_passes_the_recorded_frames(golden_dir, monkeypatch):
    _record_tiny(monkeypatch)
    render_golden.check("tiny", _frames())


def test_check_names_the_first_frame_that_differs(golden_dir, monkeypatch):
    _record_tiny(monkeypatch)
    bad = _frames()
    bad[1]["lights"][1] = b"l3"
    bad[2]["torps"].append(b"x")
    with pytest.raises(AssertionError) as e:
        render_golden.check("tiny", bad)
    msg = str(e.value)
    assert "frame 1 differs" in msg, msg
    assert "[1, 2]" in msg, msg


def test_a_moved_item_is_a_difference(golden_dir, monkeypatch):
    """Bytes moved between feeds, or split differently, change the digest."""
    _record_tiny(monkeypatch)
    bad = _frames()
    bad[0]["tractors"].insert(0, bad[0]["phasers"].pop())
    with pytest.raises(AssertionError, match="frame 0 differs"):
        render_golden.check("tiny", bad)
    split = _frames()
    split[1]["lights"] = [b"l", b"1l2"]
    with pytest.raises(AssertionError, match="frame 1 differs"):
        render_golden.check("tiny", split)


def test_check_fails_on_a_frame_count(golden_dir, monkeypatch):
    _record_tiny(monkeypatch)
    with pytest.raises(AssertionError, match="3 frames"):
        render_golden.check("tiny", _frames()[:2])


def test_a_missing_golden_fails_on_a_required_platform(golden_dir,
                                                        monkeypatch):
    monkeypatch.setattr(render_golden.sys, "platform", "darwin")
    assert "darwin" in render_golden.REQUIRED_PLATFORMS
    with pytest.raises(AssertionError,
                       match=r"missing\.darwin\.json is missing"):
        render_golden.check("missing", _frames())
    with pytest.raises(AssertionError, match="is missing"):
        render_golden.differing_frames("missing", _frames())


def test_a_missing_golden_skips_on_another_platform(golden_dir, monkeypatch):
    monkeypatch.setattr(render_golden.sys, "platform", "plan9")
    assert "plan9" not in render_golden.REQUIRED_PLATFORMS
    with pytest.raises(pytest.skip.Exception, match="no render golden"):
        render_golden.check("missing", _frames())


def test_differing_frames_lists_every_frame_that_differs(golden_dir,
                                                         monkeypatch):
    _record_tiny(monkeypatch)
    assert render_golden.differing_frames("tiny", _frames()) == []
    bad = _frames()
    bad[0]["phasers"][0] = b"\x09" * 80
    bad[2]["lights"].append(b"x")
    assert render_golden.differing_frames("tiny", bad) == [0, 2]
    with pytest.raises(AssertionError, match="3 frames"):
        render_golden.differing_frames("tiny", _frames()[:2])


def test_the_writer_refuses_native_frames(golden_dir):
    frames = _frames()
    frames[1] = render_golden.frame(source="native")
    with pytest.raises(pytest.fail.Exception, match="never written from the "
                       "native feeds"):
        render_golden._write("tiny", frames, "test frames")
    assert not list(golden_dir.iterdir())


def test_record_always_refuses_now_the_builders_are_gone(golden_dir,
                                                         monkeypatch):
    """The Python builders were deleted once the goldens were recorded
    (phase 6 follow-up 4, Task 3), and a golden is never recorded from the
    native feeds: under UPDATE_RENDER_GOLDEN=1 record fails, writing
    nothing, even for frames tagged "python"."""
    monkeypatch.setenv("UPDATE_RENDER_GOLDEN", "1")
    with pytest.raises(pytest.fail.Exception,
                       match="Python builders are gone.*Mark"):
        render_golden.record("tiny", _frames())
    assert not list(golden_dir.iterdir())


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", "1"])
def test_record_never_writes_the_fixture_dir(monkeypatch, tmp_path, value):
    """No RENDER_GOLDEN_DIR: record targets the committed fixture dir (here
    a stand-in) and writes nothing there, whatever UPDATE_RENDER_GOLDEN is:
    inert unless it is "1", and then it fails."""
    monkeypatch.setattr(render_golden, "FIXTURES", tmp_path)
    monkeypatch.delenv("RENDER_GOLDEN_DIR", raising=False)
    if value is None:
        monkeypatch.delenv("UPDATE_RENDER_GOLDEN", raising=False)
    else:
        monkeypatch.setenv("UPDATE_RENDER_GOLDEN", value)
    if value == "1":
        with pytest.raises(pytest.fail.Exception, match="are gone"):
            render_golden.record("tiny", _frames())
    else:
        render_golden.record("tiny", _frames())
    assert not list(tmp_path.iterdir())
