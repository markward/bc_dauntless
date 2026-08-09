"""BC .LIP lip-animation file parser.

Format validated empirically across all 593 game .LIP files: a flat array of
12-byte (int32 code, float32 start_s, float32 duration_s) records, no header,
contiguous (start[n] + duration[n] == start[n+1]). code 0 == closed/silence.
"""
import struct
from pathlib import Path

import pytest

from engine.appc.lip_data import (
    LipSegment, parse_lip, lip_path_for, scale_segments,
)

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


# --- scale_segments: normalise a .LIP timeline onto the real audio clock ------
# BC's .LIP timings run at 2x the mp3 clock for ~79% of the shipped corpus
# (median speech-end/mp3 == 1.999 across 4799 pairs; Episode 8 is the lone 1:1
# folder), so a verbatim timeline animates the mouth for twice the line.


def test_scale_segments_fits_timeline_to_audio_duration(tmp_path):
    f = tmp_path / "x.LIP"
    _write_lip(f, [(1, 0.0, 2.0), (50, 2.0, 4.0), (0, 6.0, 2.0)])   # 8s timeline
    out = scale_segments(parse_lip(f), 4.0)                          # 4s of audio
    assert [s.code for s in out] == [1, 50, 0]                       # codes intact
    assert out[-1].end == pytest.approx(4.0)                         # fits the clip
    assert [(round(s.start, 4), round(s.duration, 4)) for s in out] == [
        (0.0, 1.0), (1.0, 2.0), (3.0, 1.0),
    ]


def test_scale_segments_stays_contiguous(tmp_path):
    f = tmp_path / "x.LIP"
    _write_lip(f, [(1, 0.0, 0.3), (50, 0.3, 0.7), (0, 1.0, 0.4)])
    out = scale_segments(parse_lip(f), 0.6)
    for a, b in zip(out, out[1:]):
        assert a.end == pytest.approx(b.start, abs=1e-6)


def test_scale_segments_no_op_without_a_known_audio_duration(tmp_path):
    f = tmp_path / "x.LIP"
    _write_lip(f, [(1, 0.0, 2.0), (0, 2.0, 1.0)])
    segs = parse_lip(f)
    # 0.0 means "the decoder could not tell us" -- play the file as authored
    # rather than stretching it onto a guess.
    assert scale_segments(segs, 0.0) == segs
    assert scale_segments(segs, -1.0) == segs


def test_scale_segments_empty_and_zero_length_timelines(tmp_path):
    f = tmp_path / "z.LIP"
    _write_lip(f, [(0, 0.0, 0.0)])
    assert scale_segments([], 3.0) == []
    assert scale_segments(parse_lip(f), 3.0) == parse_lip(f)   # no total to scale


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[2] / "game" / "sfx" / "Maelstrom"
         / "Episode 1" / "Mission 1" / "E1M1Entrance1.LIP").is_file(),
    reason="game/ assets not present",
)
def test_scale_segments_normalises_real_2x_e1m1_line():
    """E1M1Entrance1 (Picard's walk-on line): 14.07s of .LIP over 6.79s of mp3."""
    lip = (Path(__file__).resolve().parents[2] / "game" / "sfx" / "Maelstrom"
           / "Episode 1" / "Mission 1" / "E1M1Entrance1.LIP")
    segs = parse_lip(lip)
    assert segs[-1].end == pytest.approx(14.07, abs=0.05)   # authored 2x timebase
    out = scale_segments(segs, 6.79)
    assert out[-1].end == pytest.approx(6.79, abs=1e-3)
    assert len(out) == len(segs)


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
