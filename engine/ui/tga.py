"""Minimal TGA decoder for the game's ship-icon assets.

The BC ship icons under game/data/Icons/Ships/ are uncompressed 32-bit
BGRA Targa Type 2 images (128x128). This decoder targets that case
plus uncompressed 24-bit BGR; RLE (Type 10) is not used by these
assets and is unsupported.

Returns (width, height, rgba_bytes) — rgba_bytes is RGBA (not BGRA),
suitable for direct PNG encoding.
"""
from __future__ import annotations

import struct


def decode_tga(blob: bytes) -> tuple[int, int, bytes]:
    if len(blob) < 18:
        raise ValueError("TGA header truncated")
    (id_length, cmap_type, image_type,
     _cmap_first, _cmap_len, _cmap_size,
     _x_origin, _y_origin,
     width, height,
     bpp, descriptor) = struct.unpack("<BBBHHBHHHHBB", blob[:18])

    if image_type != 2:
        raise ValueError(f"unsupported TGA image type {image_type}; "
                         "only uncompressed true-colour (2) is implemented")
    if bpp not in (24, 32):
        raise ValueError(f"unsupported bpp {bpp}")
    if cmap_type != 0:
        raise ValueError("colour-mapped TGAs not supported")

    pixel_start = 18 + id_length
    bytes_per_pixel = bpp // 8
    expected = width * height * bytes_per_pixel
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
