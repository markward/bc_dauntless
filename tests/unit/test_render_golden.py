"""tests/helpers/render_golden.py: record is inert unless UPDATE_RENDER_GOLDEN
records; "1" refuses (the Python builders the goldens were recorded from are
gone); "native" records native frames, only with RENDER_GOLDEN_RULING (Mark's
ruling, 2026-11-07); the writer counts and digests each frame; check compares
per frame and names the first frame that differs."""
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
    path = render_golden._write("tiny", _frames(), "python")
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
    render_golden._write("tiny", _frames(), "python")
    assert path.read_bytes() == before


def _record_tiny(monkeypatch):
    render_golden._write("tiny", _frames(), "python")


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


def test_the_writer_refuses_frames_from_another_source(golden_dir):
    frames = _frames()
    frames[1] = render_golden.frame(source="native")
    with pytest.raises(pytest.fail.Exception, match="frames from"):
        render_golden._write("tiny", frames, "python")
    with pytest.raises(pytest.fail.Exception, match="frames from"):
        render_golden._write("tiny", _frames(), "native")
    assert not list(golden_dir.iterdir())


def test_update_1_refuses_now_the_builders_are_gone(golden_dir, monkeypatch):
    """The Python builders were deleted once the goldens were recorded
    (phase 6 follow-up 4, Task 3): under UPDATE_RENDER_GOLDEN=1 record
    fails, writing nothing, even for frames tagged "python"."""
    monkeypatch.setenv("UPDATE_RENDER_GOLDEN", "1")
    monkeypatch.setenv("RENDER_GOLDEN_RULING", "plan: some ruling")
    with pytest.raises(pytest.fail.Exception,
                       match="Python builders are gone.*ruling"):
        render_golden.record("tiny", _frames())
    assert not list(golden_dir.iterdir())


RULING = "docs/superpowers/plans/example.md: Mark 2026-11-07"


def test_update_native_records_the_native_frames_with_the_ruling(
        golden_dir, monkeypatch):
    """Mark's ruling (2026-11-07): UPDATE_RENDER_GOLDEN=native re-records
    from the native feeds, naming the recorded ruling in the header."""
    monkeypatch.setenv("UPDATE_RENDER_GOLDEN", "native")
    monkeypatch.setenv("RENDER_GOLDEN_RULING", RULING)
    native = _frames("native")
    with pytest.raises(pytest.skip.Exception, match="native feeds"):
        render_golden.record("tiny", native)
    data = json.loads((golden_dir / ("tiny.%s.json" % sys.platform))
                      .read_text())
    assert data["source"] == "native feeds"
    assert data["ruling"] == RULING
    monkeypatch.delenv("UPDATE_RENDER_GOLDEN")
    render_golden.check("tiny", native)


def test_update_native_needs_a_recorded_ruling(golden_dir, monkeypatch):
    monkeypatch.setenv("UPDATE_RENDER_GOLDEN", "native")
    for ruling in (None, "", "   "):
        if ruling is None:
            monkeypatch.delenv("RENDER_GOLDEN_RULING", raising=False)
        else:
            monkeypatch.setenv("RENDER_GOLDEN_RULING", ruling)
        with pytest.raises(pytest.fail.Exception,
                           match="RENDER_GOLDEN_RULING.*never re-record"):
            render_golden.record("tiny", _frames("native"))
    assert not list(golden_dir.iterdir())


def test_update_native_refuses_frames_not_from_the_native_feeds(
        golden_dir, monkeypatch):
    monkeypatch.setenv("UPDATE_RENDER_GOLDEN", "native")
    monkeypatch.setenv("RENDER_GOLDEN_RULING", RULING)
    with pytest.raises(pytest.fail.Exception, match="frames from"):
        render_golden.record("tiny", _frames("python"))
    assert not list(golden_dir.iterdir())


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", "NATIVE",
                                   "Native", "python", "1"])
def test_only_native_ever_writes_the_fixture_dir(monkeypatch, tmp_path,
                                                 value):
    """No RENDER_GOLDEN_DIR: record targets the committed fixture dir (here
    a stand-in). Every UPDATE_RENDER_GOLDEN value but "native" writes
    nothing there: inert, or "1", which fails."""
    monkeypatch.setattr(render_golden, "FIXTURES", tmp_path)
    monkeypatch.delenv("RENDER_GOLDEN_DIR", raising=False)
    monkeypatch.setenv("RENDER_GOLDEN_RULING", RULING)
    if value is None:
        monkeypatch.delenv("UPDATE_RENDER_GOLDEN", raising=False)
    else:
        monkeypatch.setenv("UPDATE_RENDER_GOLDEN", value)
    for source in ("python", "native"):
        if value == "1":
            with pytest.raises(pytest.fail.Exception, match="are gone"):
                render_golden.record("tiny", _frames(source))
        else:
            render_golden.record("tiny", _frames(source))
    assert not list(tmp_path.iterdir())
    monkeypatch.setenv("UPDATE_RENDER_GOLDEN", "native")
    with pytest.raises(pytest.skip.Exception):
        render_golden.record("tiny", _frames("native"))
    assert [p.name for p in tmp_path.iterdir()] == [
        "tiny.%s.json" % sys.platform]
