"""Minimal TGA decoder for the game's ship-icon assets.

Stock BC ship icons under data/Icons/Ships/ are uncompressed 32-bit BGRA
Targa Type 2 images (128x128), and for a long time that was the only case
this decoder needed. Community packs are not so uniform — every one of the
Steamrunner pack's four icons is Type 10 (RLE) — so both true-colour
flavours are handled now, at 24 or 32 bpp. Colour-mapped TGAs are still
unsupported; no BC or corpus asset uses them.

Returns (width, height, rgba_bytes) — rgba_bytes is RGBA (not BGRA),
suitable for direct PNG encoding.
"""
from __future__ import annotations

import struct


_UNCOMPRESSED_TRUE_COLOUR = 2
_RLE_TRUE_COLOUR = 10


def _decode_rle(blob: bytes, offset: int, expected: int,
                bytes_per_pixel: int) -> bytes:
    """Expand Targa Type 10 run-length data into raw BGR(A) pixels.

    Each packet is a header byte plus payload, with
    ``count = (header & 0x7F) + 1``. The top bit selects the kind: SET means
    a run (one pixel, repeated `count` times), CLEAR means a literal block of
    `count` pixels.

    Runs are allowed to span scanlines. The 1.0 spec said they should not,
    but real encoders emit them that way, so decoding as one flat pixel
    stream is what actually reads these files.
    """
    out = bytearray(expected)
    pos = offset
    written = 0
    while written < expected:
        if pos >= len(blob):
            raise ValueError("TGA RLE data truncated")
        header = blob[pos]
        pos += 1
        count = (header & 0x7F) + 1
        # Clamp so a malformed packet claiming more pixels than the image
        # holds fills the remainder and stops, rather than running off the
        # end of the buffer.
        span = min(count * bytes_per_pixel, expected - written)
        if header & 0x80:
            pixel = blob[pos:pos + bytes_per_pixel]
            if len(pixel) < bytes_per_pixel:
                raise ValueError("TGA RLE run packet truncated")
            pos += bytes_per_pixel
            out[written:written + span] = (
                pixel * (span // bytes_per_pixel))
        else:
            chunk = blob[pos:pos + count * bytes_per_pixel]
            if len(chunk) < span:
                raise ValueError("TGA RLE literal packet truncated")
            out[written:written + span] = chunk[:span]
            pos += count * bytes_per_pixel
        written += span
    return bytes(out)


def decode_tga(blob: bytes) -> tuple[int, int, bytes]:
    if len(blob) < 18:
        raise ValueError("TGA header truncated")
    (id_length, cmap_type, image_type,
     _cmap_first, _cmap_len, _cmap_size,
     _x_origin, _y_origin,
     width, height,
     bpp, descriptor) = struct.unpack("<BBBHHBHHHHBB", blob[:18])

    if image_type not in (_UNCOMPRESSED_TRUE_COLOUR, _RLE_TRUE_COLOUR):
        raise ValueError(f"unsupported TGA image type {image_type}; "
                         "only true-colour uncompressed (2) and RLE (10) "
                         "are implemented")
    if bpp not in (24, 32):
        raise ValueError(f"unsupported bpp {bpp}")
    if cmap_type != 0:
        raise ValueError("colour-mapped TGAs not supported")

    pixel_start = 18 + id_length
    bytes_per_pixel = bpp // 8
    expected = width * height * bytes_per_pixel
    if image_type == _RLE_TRUE_COLOUR:
        pixels = _decode_rle(blob, pixel_start, expected, bytes_per_pixel)
    else:
        pixels = blob[pixel_start:pixel_start + expected]
        if len(pixels) < expected:
            raise ValueError("TGA pixel data truncated")

    # Convert BGR(A) → RGBA
    rgba = bytearray(width * height * 4)
    for i in range(width * height):
        src = i * bytes_per_pixel
        dst = i * 4
        rgba[dst]     = pixels[src + 2]  # R
        rgba[dst + 1] = pixels[src + 1]  # G
        rgba[dst + 2] = pixels[src]      # B
        rgba[dst + 3] = pixels[src + 3] if bytes_per_pixel == 4 else 255

    # Bit 5 of descriptor: 1 = origin at top-left, 0 = origin at bottom-left.
    top_left = bool(descriptor & 0x20)
    if not top_left:
        row = width * 4
        flipped = bytearray(len(rgba))
        for y in range(height):
            src_off = (height - 1 - y) * row
            flipped[y * row:(y + 1) * row] = rgba[src_off:src_off + row]
        rgba = flipped

    return width, height, bytes(rgba)
