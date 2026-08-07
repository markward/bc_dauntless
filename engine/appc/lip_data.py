"""Parser for BC ``.LIP`` lip-animation files.

Format (reverse-engineered and validated across all 593 game ``.LIP`` files):
a flat array of 12-byte records, **no header**::

    (int32 code, float32 start_seconds, float32 duration_seconds)

Records are a contiguous partition of the voice line — ``start[n] + duration[n]
== start[n+1]`` — and the last segment is consistently ``code 0`` (trailing
silence). ``code`` is a phoneme id; 35 distinct values appear across the corpus,
with ``code 0`` meaning closed/silence. The ``code -> viseme`` mapping is *data*
(``lip_phonemes.json``, see :mod:`engine.appc.phoneme_map`); this module only
decodes timing.

Each ``.LIP`` sits beside its voice file with the same basename
(``gl001.mp3`` <-> ``gl001.LIP``); :func:`lip_path_for` resolves that pairing.

This module is intentionally pure-Python and engine-agnostic — it is the cue
*source* for lip-sync regardless of how the mouth is ultimately rendered.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

_REC = struct.Struct("<iff")  # int32 code, float32 start, float32 duration


@dataclass(frozen=True)
class LipSegment:
    """One ``.LIP`` segment: a phoneme ``code`` held for ``duration`` seconds
    starting at ``start`` (both seconds, wall-clock relative to line start)."""

    code: int
    start: float
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


def parse_lip(path) -> list[LipSegment]:
    """Decode a ``.LIP`` file into its ordered list of :class:`LipSegment`.

    Raises ``ValueError`` if the file length is not a whole number of 12-byte
    records (a corrupt/foreign file). An empty file yields ``[]``.
    """
    data = Path(path).read_bytes()
    if len(data) % _REC.size != 0:
        raise ValueError(
            f"{path}: length {len(data)} is not a multiple of {_REC.size} "
            "-- not a valid .LIP file"
        )
    return [
        LipSegment(*_REC.unpack_from(data, off))
        for off in range(0, len(data), _REC.size)
    ]


def scale_segments(segments, audio_duration: float):
    """Return ``segments`` normalised so the timeline spans ``audio_duration``.

    BC's authored ``.LIP`` timings are **not** reliably on the voice clip's own
    clock: measured across all 4799 shipped ``.LIP``/``.mp3`` pairs, the median
    ratio of LIP speech-end to real mp3 length is **1.999**, and 79% of pairs sit
    within 5% of 2.0 (``Bridge/Crew`` and Episodes 1-7 are all 1.999; Episode 8
    is the lone 1:1 folder). LISET was evidently fed half-rate source audio for
    most of the corpus. Played verbatim, a line's mouth animation therefore runs
    at half speed for twice the line -- the officer keeps flapping through the
    *next* speaker's reply (E1M1's intro: Picard's ``E1M1Entrance1`` is 6.79 s of
    audio against a 14.07 s timeline).

    Normalising each timeline onto the clip's real decoded length fixes both the
    2x majority and the 1:1 files with one rule, and is what BC's own engine must
    do to stay in sync (``FUN_00706c60``, "%d phonemes generated to sequence",
    builds a per-phoneme TGSequence at speak time).

    ``audio_duration <= 0`` means the decoder could not tell us (no backend, load
    failure) -- the segments are returned unchanged rather than stretched onto a
    word-count estimate. A timeline with no length is likewise returned as-is.
    """
    segs = list(segments)
    if not segs or audio_duration is None or audio_duration <= 0.0:
        return segs
    total = segs[-1].end
    if total <= 0.0:
        return segs
    k = float(audio_duration) / total
    return [LipSegment(s.code, s.start * k, s.duration * k) for s in segs]


def lip_path_for(wav) -> str | None:
    """Return the sibling ``.LIP`` path for a voice file, or ``None`` if absent.

    BC pairs each voice clip with a same-basename ``.LIP`` (real files use the
    upper-case ``.LIP`` extension). Returns ``None`` for a falsy input or when
    no sibling exists, so callers can no-op cleanly.
    """
    if not wav:
        return None
    p = Path(wav)
    for ext in (".LIP", ".lip"):
        cand = p.with_suffix(ext)
        if cand.is_file():
            return str(cand)
    return None
