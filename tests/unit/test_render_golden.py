"""tests/helpers/render_golden.py: record only under UPDATE_RENDER_GOLDEN=1,
check per frame and name the first frame that differs."""
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


def test_record_writes_per_frame_counts_and_digests_then_skips(
        golden_dir, monkeypatch):
    monkeypatch.setenv("UPDATE_RENDER_GOLDEN", "1")
    assert render_golden.recording()
    with pytest.raises(pytest.skip.Exception, match="recorded"):
        render_golden.record("tiny", _frames())
    path = golden_dir / ("tiny.%s.json" % sys.platform)
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
    with pytest.raises(pytest.skip.Exception):
        render_golden.record("tiny", _frames())
    assert path.read_bytes() == before


def _record_tiny(monkeypatch):
    monkeypatch.setenv("UPDATE_RENDER_GOLDEN", "1")
    with pytest.raises(pytest.skip.Exception):
        render_golden.record("tiny", _frames())
    monkeypatch.delenv("UPDATE_RENDER_GOLDEN")


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


def test_record_refuses_native_frames(golden_dir, monkeypatch):
    monkeypatch.setenv("UPDATE_RENDER_GOLDEN", "1")
    frames = _frames()
    frames[1] = render_golden.frame(source="native")
    with pytest.raises(pytest.fail.Exception, match="Python builders"):
        render_golden.record("tiny", frames)
    assert not list(golden_dir.iterdir())


def test_record_refuses_without_the_python_builders(golden_dir, monkeypatch):
    from engine import host_loop
    monkeypatch.setenv("UPDATE_RENDER_GOLDEN", "1")
    assert render_golden.python_builders_available()
    monkeypatch.delattr(host_loop, "_build_torpedo_render_data")
    assert not render_golden.python_builders_available()
    with pytest.raises(pytest.fail.Exception, match="Python builders"):
        render_golden.record("tiny", _frames())
    assert not list(golden_dir.iterdir())


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes"])
def test_the_fixture_dir_is_written_only_under_an_explicit_1(
        monkeypatch, tmp_path, value):
    """No RENDER_GOLDEN_DIR: record targets the committed fixture dir (here
    a stand-in), and writes there only when UPDATE_RENDER_GOLDEN is "1"."""
    monkeypatch.setattr(render_golden, "FIXTURES", tmp_path)
    monkeypatch.delenv("RENDER_GOLDEN_DIR", raising=False)
    if value is None:
        monkeypatch.delenv("UPDATE_RENDER_GOLDEN", raising=False)
    else:
        monkeypatch.setenv("UPDATE_RENDER_GOLDEN", value)
    render_golden.record("tiny", _frames())
    assert not list(tmp_path.iterdir())
    monkeypatch.setenv("UPDATE_RENDER_GOLDEN", "1")
    with pytest.raises(pytest.skip.Exception):
        render_golden.record("tiny", _frames())
    assert [p.name for p in tmp_path.iterdir()] == [
        "tiny.%s.json" % sys.platform]
