"""LipSyncRuntime: game-relative wav resolution, the random-phoneme fallback for
lines that ship no .LIP (BC's documented behavior, sdk/lipsync.html), and the
speech->sink cue path. The pure controller is covered in
test_lip_sync_controller; this exercises the BC-specific glue.
"""
import random

from engine.lip_sync_runtime import (
    LipSyncRuntime, _random_phoneme_segments, _abs_sfx, _GAME_DIR,
)

_CODES = [32, 37, 50, 66, 113]   # representative speaking codes


def test_random_phoneme_segments_contiguous_cover_and_in_set():
    rng = random.Random(1234)
    segs = _random_phoneme_segments(1.5, rng, _CODES)
    assert len(segs) >= 2
    assert all(s.code in _CODES for s in segs)             # drawn from the set
    for a, b in zip(segs, segs[1:]):                       # contiguous
        assert abs(a.end - b.start) < 1e-6
    assert abs(segs[-1].end - 1.5) < 0.01                  # covers the duration
    assert len({s.code for s in segs}) > 1                 # random, not constant


def test_random_phoneme_segments_empty_for_zero_duration_or_no_codes():
    assert _random_phoneme_segments(0.0, random.Random(0), _CODES) == []
    assert _random_phoneme_segments(1.0, random.Random(0), []) == []


def test_abs_sfx_resolves_game_relative():
    # A bare relative path that isn't a CWD file resolves under game/.
    out = _abs_sfx("sfx/Bridge/Crew/XO/gf009.mp3")
    assert out == str(_GAME_DIR / "sfx/Bridge/Crew/XO/gf009.mp3")


class _FakeRenderer:
    def __init__(self):
        self.calls = []

    def set_officer_face(self, iid, slot_a, slot_b, mix):
        self.calls.append((iid, slot_a, slot_b, mix))


class _Char:
    def __init__(self, name, iid):
        self._character_name = name
        self._render_instance = iid


def test_no_lip_line_drives_flap_through_sink():
    r = _FakeRenderer()
    rt = LipSyncRuntime(r, lambda: [_Char("Saffi", 7)])
    try:
        # A wav with no .LIP sibling -> generic flap for the duration.
        rt._on_speech("Saffi", "sfx/Bridge/Crew/XO/__definitely_missing__.mp3",
                      duration=1.0, now=100.0)
        rt.update(100.10)   # ~first open phase
        assert any(c[0] == 7 for c in r.calls), "flap did not drive the face sink"
        # The opening flap reaches a non-neutral (open) viseme at some point.
        rt.update(100.20)
        assert any(c[1] != "neutral" for c in r.calls)
    finally:
        rt.close()


def test_line_with_no_wav_is_ignored():
    r = _FakeRenderer()
    rt = LipSyncRuntime(r, lambda: [_Char("Saffi", 7)])
    try:
        rt._on_speech("Saffi", None, duration=1.0, now=0.0)
        rt.update(0.1)
        assert r.calls == []   # nothing to animate without a voice line
    finally:
        rt.close()
