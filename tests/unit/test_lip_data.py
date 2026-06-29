"""BC .LIP lip-animation file parser.

Format validated empirically across all 593 game .LIP files: a flat array of
12-byte (int32 code, float32 start_s, float32 duration_s) records, no header,
contiguous (start[n] + duration[n] == start[n+1]). code 0 == closed/silence.
"""
import struct
from pathlib import Path

import pytest

from engine.appc.lip_data import LipSegment, parse_lip, lip_path_for

_REC = struct.Struct("<iff")


def _write_lip(path, records):
    path.write_bytes(b"".join(_REC.pack(c, s, d) for c, s, d in records))


def test_parse_lip_decodes_records(tmp_path):
    f = tmp_path / "x.LIP"
    _write_lip(f, [(1, 0.0, 0.1), (50, 0.1, 0.3)])
    segs = parse_lip(f)
    assert all(isinstance(s, LipSegment) for s in segs)
    assert [(s.code, round(s.start, 4), round(s.duration, 4)) for s in segs] == [
        (1, 0.0, 0.1),
        (50, 0.1, 0.3),
    ]


def test_segment_end(tmp_path):
    f = tmp_path / "x.LIP"
    _write_lip(f, [(7, 0.5, 0.25)])
    assert parse_lip(f)[0].end == pytest.approx(0.75)


def test_parse_empty_file_is_empty_list(tmp_path):
    f = tmp_path / "empty.LIP"
    f.write_bytes(b"")
    assert parse_lip(f) == []


def test_parse_lip_rejects_non_multiple_of_12(tmp_path):
    f = tmp_path / "bad.LIP"
    f.write_bytes(b"\x01\x02\x03")
    with pytest.raises(ValueError):
        parse_lip(f)


def test_lip_path_for_finds_sibling(tmp_path):
    wav = tmp_path / "gl001.mp3"
    wav.write_bytes(b"x")
    lip = tmp_path / "gl001.LIP"
    lip.write_bytes(b"")
    assert lip_path_for(str(wav)) == str(lip)


def test_lip_path_for_absent_returns_none(tmp_path):
    wav = tmp_path / "gl001.mp3"
    wav.write_bytes(b"x")
    assert lip_path_for(str(wav)) is None


def test_lip_path_for_empty_input_returns_none():
    assert lip_path_for(None) is None
    assert lip_path_for("") is None


# --- Real BC asset cross-check (skips when game/ assets are not present) ------
_PICARD = (
    Path(__file__).resolve().parents[2]
    / "game" / "sfx" / "Bridge" / "Crew" / "Picard" / "PicardYes3.LIP"
)


@pytest.mark.skipif(not _PICARD.is_file(), reason="game/ assets not present")
def test_parse_real_picard_yes3():
    segs = parse_lip(_PICARD)
    assert len(segs) == 8
    assert segs[0].code == 1
    assert segs[0].start == pytest.approx(0.0)
    assert segs[-1].code == 0  # trailing silence -> closed mouth
    # Contiguous partition: each segment ends exactly where the next starts.
    for a, b in zip(segs, segs[1:]):
        assert a.end == pytest.approx(b.start, abs=1e-3)
