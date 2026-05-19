"""Tests for the TGL parser smoke-test harness."""
from pathlib import Path

import pytest

from tools.tgl_harness import discover_tgl_files


def test_discover_walks_temp_dir_case_insensitively(tmp_path, monkeypatch):
    """discover_tgl_files picks up .tgl and .TGL, ignores other suffixes."""
    root = tmp_path / "fake_tgl_root"
    root.mkdir()
    (root / "alpha.tgl").write_bytes(b"")
    (root / "BETA.TGL").write_bytes(b"")
    (root / "nested").mkdir()
    (root / "nested" / "gamma.Tgl").write_bytes(b"")
    (root / "ignore.txt").write_bytes(b"")
    (root / "ignore.tglx").write_bytes(b"")

    import tools.tgl_harness as harness
    monkeypatch.setattr(harness, "ROOTS", [root])

    found = discover_tgl_files()

    assert [p.name for p in found] == sorted(["alpha.tgl", "BETA.TGL", "gamma.Tgl"])


def test_discover_skips_missing_root(tmp_path, monkeypatch):
    """A non-existent root is silently skipped (game/ may not be installed)."""
    missing = tmp_path / "does_not_exist"
    present = tmp_path / "present"
    present.mkdir()
    (present / "x.tgl").write_bytes(b"")

    import tools.tgl_harness as harness
    monkeypatch.setattr(harness, "ROOTS", [missing, present])

    found = discover_tgl_files()
    assert [p.name for p in found] == ["x.tgl"]


from engine.missions.tgl_reader import TGLParseError
from tools.tgl_harness import classify

PROJECT_ROOT = Path(__file__).parent.parent.parent
SDK_TGL_ROOT = PROJECT_ROOT / "sdk" / "Build" / "Data" / "TGL"


def test_classify_pass_returns_counts():
    """A real, non-empty TGL classifies as pass with (strings, sounds) counts."""
    sample = SDK_TGL_ROOT / "Tutorial" / "Tutorial.tgl"
    if not sample.is_file():
        pytest.skip(f"{sample} not present")

    status, reason = classify(sample)

    assert status == "pass"
    kind, payload = reason
    assert kind == "counts"
    strings_count, sounds_count = payload
    assert strings_count > 0 or sounds_count > 0


def test_classify_empty_synthetic(tmp_path):
    """A valid count=0 TGL decodes to zero strings and zero sounds → fail/empty.

    No real TGL in the project actually decodes to empty (the original
    engine asserts on empty TGLs, so the game never ships one), but the
    parser handles count=0 cleanly and the harness must surface it as a
    defensive guard against parser regressions.
    """
    import struct
    bad = tmp_path / "empty.tgl"
    # 20-byte header: magic, 1, 0, count=0, 0
    bad.write_bytes(struct.pack("<5I", 0x00001701, 1, 0, 0, 0))

    status, reason = classify(bad)

    assert status == "fail"
    kind, payload = reason
    assert kind == "empty"
    assert payload is None


def test_classify_parse_error_on_truncated_file(tmp_path):
    """A four-byte file trips TGLParseError and surfaces as a parse failure."""
    bad = tmp_path / "bad.tgl"
    bad.write_bytes(b"\x01\x17\x00\x00")

    status, reason = classify(bad)

    assert status == "fail"
    kind, payload = reason
    assert kind == "parse"
    assert isinstance(payload, TGLParseError)


from tools.tgl_harness import error_key


def test_error_key_for_parse_exception():
    """Parse failures key on '<ExcType>: <first-line-of-message[:80]>'."""
    exc = TGLParseError("keys section truncated")
    key = error_key("fail", ("parse", exc))
    assert key == "TGLParseError: keys section truncated"


def test_error_key_truncates_long_messages():
    """Messages longer than 80 chars are truncated."""
    long_msg = "x" * 200
    exc = TGLParseError(long_msg)
    key = error_key("fail", ("parse", exc))
    assert key == "TGLParseError: " + "x" * 80


def test_error_key_takes_first_line_only():
    """Multi-line exception messages get truncated to the first line."""
    exc = TGLParseError("first line\nsecond line\nthird line")
    key = error_key("fail", ("parse", exc))
    assert key == "TGLParseError: first line"


def test_error_key_for_empty_failure():
    """Empty TGLs share a single literal grouping key."""
    key = error_key("fail", ("empty", None))
    assert key == "empty TGL (0 strings, 0 sounds)"


from tools.tgl_harness import format_line


def test_format_line_pass_single_line():
    """Pass renders as one line with (strings=N sounds=M) suffix."""
    path = PROJECT_ROOT / "game" / "data" / "TGL" / "Foo.tgl"
    out = format_line(path, "pass", ("counts", (42, 17)))
    assert out == "  PASS  game/data/TGL/Foo.tgl  (strings=42 sounds=17)"


def test_format_line_empty_single_line():
    """Empty failure renders as one line with 'empty: ...' suffix."""
    path = PROJECT_ROOT / "sdk" / "Build" / "Data" / "TGL" / "Tutorial" / "Episode" / "Episode.tgl"
    out = format_line(path, "fail", ("empty", None))
    assert out == (
        "  FAIL  sdk/Build/Data/TGL/Tutorial/Episode/Episode.tgl"
        "  empty: 0 strings, 0 sounds"
    )


def test_format_line_parse_two_lines():
    """Parse failure renders as two lines: path, then indented exception."""
    path = PROJECT_ROOT / "game" / "data" / "TGL" / "Bad.tgl"
    exc = TGLParseError("keys section truncated")
    out = format_line(path, "fail", ("parse", exc))
    assert out == (
        "  FAIL  game/data/TGL/Bad.tgl\n"
        "         TGLParseError: keys section truncated"
    )


def test_format_line_handles_path_outside_project_root(tmp_path):
    """Paths outside PROJECT_ROOT fall back to the absolute path."""
    path = tmp_path / "x.tgl"
    out = format_line(path, "pass", ("counts", (1, 1)))
    assert str(path) in out
    assert out.startswith("  PASS  ")
