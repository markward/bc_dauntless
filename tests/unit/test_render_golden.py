"""tests/helpers/render_golden.py: record only under UPDATE_RENDER_GOLDEN=1,
check per frame and name the first frame that differs."""
import json
import sys

import pytest

from tests.helpers import render_golden


def _frames():
    return [render_golden.frame(phasers=[b"\x01" * 80, b"\x02" * 80],
                                tractors=[b"\x03" * 80]),
            render_golden.frame(torps=[b"torp"], lights=[b"l1", b"l2"]),
            render_golden.frame()]


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


def test_check_skips_without_a_golden_for_this_platform(golden_dir):
    with pytest.raises(pytest.skip.Exception, match="no render golden"):
        render_golden.check("missing", _frames())
