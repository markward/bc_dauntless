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
        assert (mods.replacements_root() / sound).is_file(), sound


def test_generated_tgl_reads_back_every_line():
    got = tgl_reader._parse(g.build(), source="test")
    for key, text, sound in g.entries():
        assert got.strings[key] == text
        assert got.sounds[key] == sound


def test_every_wav_is_a_format_the_native_decoder_accepts():
    """native/src/audio/src/wav.cc takes PCM only (format 1, not
    WAVE_FORMAT_EXTENSIBLE), 1-2 channels, 8 or 16 bit."""
    import struct
    for key, _text, sound in g.entries():
        if not sound.lower().endswith(".wav"):
            continue
        data = (mods.replacements_root() / sound).read_bytes()
        assert data[:4] == b"RIFF" and data[8:12] == b"WAVE", key
        off = 12
        while data[off:off + 4] != b"fmt ":
            off += 8 + struct.unpack_from("<I", data, off + 4)[0]
        code, channels, _rate, _bps, _align, bits = struct.unpack_from(
            "<HHIIHH", data, off + 8)
        assert (code, channels in (1, 2), bits in (8, 16)) == (1, True, True), key


def test_every_shipped_voice_file_is_a_listed_dauntless_line():
    """.gitignore un-ignores replacements/sfx WAVs for our own lines; this
    keeps that exception from admitting anything else (BC audio is
    copyrighted and must never be committed)."""
    root = mods.replacements_root()
    listed = {sound for _k, _t, sound in g.entries()}
    shipped = {p.relative_to(root).as_posix()
               for p in (root / "sfx").rglob("*") if p.is_file()}
    assert shipped <= listed
