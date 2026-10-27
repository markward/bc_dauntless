"""The committed Dauntless dialogue TGL is generated from
tools/dialogue/dauntless_crew.json -- never hand-edited."""
from engine import mods
from engine.missions import tgl_reader
from tools import gen_dauntless_tgl as g


def test_committed_tgl_matches_generator_output():
    assert g.tgl_path().read_bytes() == g.build()


def test_every_line_has_text_and_its_sound_file_is_shipped():
    for key, text, sound in g.entries():
        assert text.strip(), key
        if not sound:
            continue    # subtitle-only line: no voice file to ship
        assert (mods.replacements_root() / sound).is_file(), sound


def test_generated_tgl_reads_back_every_line():
    got = tgl_reader._parse(g.build(), source="test")
    for key, text, sound in g.entries():
        assert got.strings[key] == text
        assert got.sounds.get(key, "") == sound


def _listed_wavs() -> set:
    """Every WAV the game is told to play from replacements: our own crew
    lines, plus replacement voices in native/assets/dialogue/patches.json."""
    import json
    from engine.appc import dialogue_patches
    listed = {sound for _k, _t, sound in g.entries() if sound.lower().endswith(".wav")}
    raw = json.loads(dialogue_patches.patches_path().read_text(encoding="utf-8"))
    for entry in raw.values():
        for rep in entry.get("replace", {}).values():
            sound = rep.get("sound", "")
            if sound.lower().endswith(".wav"):
                listed.add(sound)
    return listed


def test_every_wav_is_a_format_the_native_decoder_accepts():
    """native/src/audio/src/wav.cc takes PCM only (format 1, not
    WAVE_FORMAT_EXTENSIBLE), 1-2 channels, 8 or 16 bit."""
    import struct
    for sound in sorted(_listed_wavs()):
        data = (mods.replacements_root() / sound).read_bytes()
        assert data[:4] == b"RIFF" and data[8:12] == b"WAVE", sound
        off = 12
        while data[off:off + 4] != b"fmt ":
            off += 8 + struct.unpack_from("<I", data, off + 4)[0]
        code, channels, _rate, _bps, _align, bits = struct.unpack_from(
            "<HHIIHH", data, off + 8)
        assert (code, channels in (1, 2), bits in (8, 16)) == (1, True, True), sound


def test_every_shipped_voice_file_is_a_listed_line():
    """.gitignore un-ignores replacements/sfx WAVs for our own lines; this
    keeps that exception from admitting anything else (BC audio is
    copyrighted and must never be committed)."""
    root = mods.replacements_root()
    shipped = {p.relative_to(root).as_posix()
               for p in (root / "sfx").rglob("*") if p.is_file()}
    assert shipped <= _listed_wavs()


_SUBTITLE_ONLY = {
    "SaffiQBProtectedLost1": "The ship we were assigned to protect has been "
                             "destroyed. Ending simulation.",
    "SaffiQBTimeUp1": "We have run out of time. Ending simulation.",
}


def test_subtitle_only_lines_are_allowed():
    by_key = {k: (t, s) for k, t, s in g.entries()}
    got = tgl_reader._parse(g.build(), source="test")
    for key, text in _SUBTITLE_ONLY.items():
        assert by_key[key] == (text, "")
        assert got.strings[key] == text
        assert key not in got.sounds
