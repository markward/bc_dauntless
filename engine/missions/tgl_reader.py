"""Binary TGL parser.

BC's localization databases are stored as .tgl files. Layout
(reverse-engineered from sdk/Build/Data/TGL/Tutorial/Tutorial.tgl,
sdk/Build/Data/TGL/Tutorial/Episode/Episode.tgl, and
game/data/TGL/Maelstrom/Maelstrom.tgl + game/data/TGL/Bridge Crew General.TGL):

    header (20 bytes):
        uint32  magic            (0x00001701 in every sample examined)
        uint32  unknown          (always 1)
        uint32  unknown          (always 0)
        uint32  count            (number of entries)
        uint32  unknown          (always 0)

    toc (count * 12 bytes), one triple per entry:
        uint32  value_start_wchars   start of entry i's value in the values
                                     blob, measured in UTF-16 code units
        uint32  filename_start_bytes start of entry i's filename in the
                                     filenames blob, in bytes
        uint32  key_end_bytes        end of entry i's key in the keys blob,
                                     in bytes (== start of key i+1)
        Each entry i's slice is therefore [TOC[i], TOC[i+1]) for value and
        filename (with TOC[count] taken from the size prefix below), and
        [TOC[i-1].f2, TOC[i].f2) for keys (with TOC[-1].f2 == 0).

    keys blob (TOC[count-1].f2 bytes):
        concatenated NUL-terminated ASCII keys, in TOC order.

    uint32  value_size_wchars
    values blob (value_size_wchars * 2 bytes):
        concatenated NUL-terminated UTF-16-LE strings, in TOC order.

    uint32  filename_size_bytes
    filenames blob:
        concatenated NUL-terminated ASCII media filenames, in TOC order.
        Speakers are NOT stored as a separate field — when a TGL has
        speakered dialogue the filename path encodes the speaker
        (e.g. "sfx/Bridge/Crew/XO/...") and the exporter optionally
        prepends "Speaker: " into the value string at export time.

Entries with empty filename strings ("") are not surfaced in TGLFile.sounds.

A truly empty TGL (the tutorial's placeholder Episode.tgl, which has
count=1 and a trailing "Unused" filler) decodes to a TGLFile with no
strings and no sounds.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path


class TGLParseError(ValueError):
    pass


@dataclass
class TGLFile:
    strings: dict[str, str] = field(default_factory=dict)
    sounds:  dict[str, str] = field(default_factory=dict)
    source:  str = ""


_HEADER_FMT = "<5I"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)   # 20
_TOC_ENTRY_SIZE = 12


def read_tgl(path: Path | str) -> TGLFile:
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise TGLParseError(f"cannot read {path}: {exc}") from exc
    return _parse(data, source=str(path))


def _parse(data: bytes, *, source: str) -> TGLFile:
    if len(data) < _HEADER_SIZE:
        raise TGLParseError(
            f"header truncated ({len(data)} < {_HEADER_SIZE})")

    count = struct.unpack_from("<I", data, 12)[0]
    out = TGLFile(source=source)
    if count == 0:
        return out

    toc_off = _HEADER_SIZE
    toc_end = toc_off + count * _TOC_ENTRY_SIZE
    if toc_end > len(data):
        raise TGLParseError(
            f"TOC truncated (need {toc_end} bytes, have {len(data)})")

    # Total key-section size lives in the third field of the last TOC entry.
    last_triple_off = toc_off + (count - 1) * _TOC_ENTRY_SIZE
    try:
        _f0, _f1, keys_total = struct.unpack_from(
            "<3I", data, last_triple_off)
    except struct.error as exc:
        raise TGLParseError("TOC last entry truncated") from exc

    keys_off = toc_end
    keys_end = keys_off + keys_total
    if keys_end + 4 > len(data):
        raise TGLParseError("keys section truncated")

    value_size_chars = struct.unpack_from("<I", data, keys_end)[0]
    values_off = keys_end + 4
    values_end = values_off + value_size_chars * 2
    if values_end + 4 > len(data):
        raise TGLParseError("values section truncated")

    filename_size_bytes = struct.unpack_from("<I", data, values_end)[0]
    files_off = values_end + 4
    files_end = files_off + filename_size_bytes
    if files_end > len(data):
        raise TGLParseError("filenames section truncated")

    keys = _split_ascii(data[keys_off:keys_end])
    values = _split_utf16(data[values_off:values_end])
    files = _split_ascii(data[files_off:files_end])

    # In Maelstrom-style files, all three sections have ``count`` entries.
    # In the placeholder Episode.tgl, only the filenames section has data
    # ("Unused\0") and keys/values are empty; treat the file as containing
    # no usable strings.
    if not keys or not values:
        return out

    n = min(len(keys), len(values), len(files))
    for i in range(n):
        out.strings[keys[i]] = values[i]
        if files[i]:
            out.sounds[keys[i]] = files[i]
    return out


def build_tgl_bytes(strings: dict, sounds: dict | None = None) -> bytes:
    """Inverse of _parse, for tests that need a real TGL on disk. Lives in
    this file so the two layouts cannot drift apart."""
    sounds = sounds or {}
    keys = list(strings)
    key_blob = b"".join(k.encode("ascii") + b"\x00" for k in keys)
    val_blob = b"".join(strings[k].encode("utf-16-le") + b"\x00\x00" for k in keys)
    file_blob = b"".join(sounds.get(k, "").encode("ascii") + b"\x00" for k in keys)
    header = struct.pack(_HEADER_FMT, 0, 0, 0, len(keys), 0)
    toc = b"".join(struct.pack("<3I", 0, 0, len(key_blob)) for _ in keys)
    return (header + toc + key_blob
            + struct.pack("<I", len(val_blob) // 2) + val_blob
            + struct.pack("<I", len(file_blob)) + file_blob)


def _split_ascii(blob: bytes) -> list[str]:
    if not blob:
        return []
    # Drop the trailing empty string from a NUL terminator at the end.
    parts = blob.split(b"\x00")
    if parts and parts[-1] == b"":
        parts = parts[:-1]
    return [p.decode("ascii", errors="replace") for p in parts]


def _split_utf16(blob: bytes) -> list[str]:
    if not blob:
        return []
    # Each entry ends in a 2-byte NUL (0x00 0x00). Walk pairs.
    out: list[str] = []
    cur = bytearray()
    i = 0
    while i + 1 < len(blob):
        pair = blob[i:i + 2]
        if pair == b"\x00\x00":
            out.append(cur.decode("utf-16-le", errors="replace"))
            cur = bytearray()
        else:
            cur += pair
        i += 2
    if cur:
        out.append(cur.decode("utf-16-le", errors="replace"))
    return out
