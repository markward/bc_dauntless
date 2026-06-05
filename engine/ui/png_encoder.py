"""Minimal PNG encoder using only the standard library.

Encodes RGBA pixel data into a valid PNG byte stream. No interlacing,
no palette, no compression-level tuning — just enough for the ship-icon
cache. Each scanline gets a filter byte of 0 (None) followed by the
raw RGBA bytes; the concatenated stream is deflated as one IDAT chunk.
"""
from __future__ import annotations

import struct
import zlib

_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    return length + chunk_type + data + crc


def encode_png_rgba(width: int, height: int, rgba: bytes) -> bytes:
    if len(rgba) != width * height * 4:
        raise ValueError("rgba length does not match width*height*4")
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    row = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * row:(y + 1) * row])
    idat = zlib.compress(bytes(raw), 6)
    return (_SIGNATURE
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", idat)
            + _chunk(b"IEND", b""))


def encode_png_rgb(width: int, height: int, rgb: bytes) -> bytes:
    """Encode RGB pixels (24-bit, no alpha) as a truecolour PNG. Same
    minimal pipeline as ``encode_png_rgba``; only the IHDR colour-type
    byte changes (2 = truecolour, vs 6 = truecolour + alpha)."""
    if len(rgb) != width * height * 3:
        raise ValueError("rgb length does not match width*height*3")
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgb[y * row:(y + 1) * row])
    idat = zlib.compress(bytes(raw), 6)
    return (_SIGNATURE
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", idat)
            + _chunk(b"IEND", b""))
