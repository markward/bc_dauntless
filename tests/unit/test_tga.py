"""TGA decoder. Only covers the cases the BC game icons use:
uncompressed 24/32-bit BGR/BGRA (Targa Type 2)."""
import struct


def _make_tga(width: int, height: int, pixels_bgra: bytes) -> bytes:
    """Build a minimal uncompressed 32-bit BGRA TGA. Origin top-left."""
    header = struct.pack(
        "<BBBHHBHHHHBB",
        0,          # id length
        0,          # color map type (none)
        2,          # image type (uncompressed true-color)
        0, 0, 0,    # color map spec
        0, 0,       # x origin, y origin
        width, height,
        32,         # bits per pixel
        0x20,       # image descriptor (0x20 = origin top-left, 8 alpha bits)
    )
    return header + pixels_bgra


def test_decodes_uncompressed_bgra():
    from engine.ui.tga import decode_tga
    pixels = bytes([0, 0, 255, 255,   # red (B=0, G=0, R=255, A=255)
                    255, 0, 0, 255])  # blue (B=255, G=0, R=0, A=255)
    blob = _make_tga(2, 1, pixels)
    width, height, rgba = decode_tga(blob)
    assert width == 2 and height == 1
    assert rgba == bytes([255, 0, 0, 255,  0, 0, 255, 255])


def test_decodes_uncompressed_bgr():
    from engine.ui.tga import decode_tga
    header = struct.pack("<BBBHHBHHHHBB", 0,0,2, 0,0,0, 0,0, 1,1, 24, 0x20)
    pixels = bytes([0, 255, 0])  # green
    width, height, rgba = decode_tga(header + pixels)
    assert (width, height) == (1, 1)
    assert rgba == bytes([0, 255, 0, 255])


# ── RLE (Targa Type 10) ────────────────────────────────────────────────────
# Stock BC ship icons are all Type 2, which is why this decoder started out
# refusing anything else. Community packs are not: all four of the Steamrunner
# pack's icons are Type 10, and refusing them raised straight through
# ship_icons into the panel render and killed the run.
#
# Packet format: one header byte, then count = (header & 0x7F) + 1. With the
# top bit SET the packet is a run — one pixel, repeated count times. Clear, and
# it is a literal packet of count pixels.

def _rle_header(width, height, bpp=32, descriptor=0x20):
    return struct.pack("<BBBHHBHHHHBB",
                       0, 0, 10, 0, 0, 0, 0, 0,
                       width, height, bpp, descriptor)


def test_decodes_rle_run_packet():
    from engine.ui.tga import decode_tga
    # One run of 3 identical red pixels (0x80 | 2 => count 3).
    blob = _rle_header(3, 1) + bytes([0x82]) + bytes([0, 0, 255, 255])
    width, height, rgba = decode_tga(blob)
    assert (width, height) == (3, 1)
    assert rgba == bytes([255, 0, 0, 255]) * 3


def test_decodes_rle_literal_packet():
    from engine.ui.tga import decode_tga
    # A literal packet of 2 pixels (header 1 => count 2): red then blue.
    blob = (_rle_header(2, 1) + bytes([0x01])
            + bytes([0, 0, 255, 255,  255, 0, 0, 255]))
    width, height, rgba = decode_tga(blob)
    assert rgba == bytes([255, 0, 0, 255,  0, 0, 255, 255])


def test_decodes_rle_mixed_packets():
    from engine.ui.tga import decode_tga
    blob = (_rle_header(4, 1)
            + bytes([0x81]) + bytes([0, 0, 255, 255])          # 2x red
            + bytes([0x01]) + bytes([255, 0, 0, 255,           # blue
                                     0, 255, 0, 255]))         # green
    _w, _h, rgba = decode_tga(blob)
    assert rgba == bytes([255, 0, 0, 255,
                          255, 0, 0, 255,
                          0, 0, 255, 255,
                          0, 255, 0, 255])


def test_rle_24_bit_gets_opaque_alpha():
    from engine.ui.tga import decode_tga
    blob = _rle_header(2, 1, bpp=24) + bytes([0x81]) + bytes([0, 255, 0])
    _w, _h, rgba = decode_tga(blob)
    assert rgba == bytes([0, 255, 0, 255]) * 2


def test_rle_respects_bottom_left_origin():
    from engine.ui.tga import decode_tga
    # descriptor 0 => bottom-left origin, so rows come back flipped.
    blob = (_rle_header(1, 2, descriptor=0x00)
            + bytes([0x00]) + bytes([0, 0, 255, 255])    # row 0: red
            + bytes([0x00]) + bytes([255, 0, 0, 255]))   # row 1: blue
    _w, _h, rgba = decode_tga(blob)
    assert rgba == bytes([0, 0, 255, 255,  255, 0, 0, 255])


def test_truncated_rle_raises_rather_than_returning_short_data():
    import pytest
    from engine.ui.tga import decode_tga
    # Claims 4 pixels, supplies one 2-pixel run and then stops.
    blob = _rle_header(4, 1) + bytes([0x81]) + bytes([0, 0, 255, 255])
    with pytest.raises(ValueError):
        decode_tga(blob)


def test_a_packet_overrunning_the_image_is_clamped():
    """A malformed run claiming more pixels than remain must not write past
    the buffer -- it fills what is left and stops."""
    from engine.ui.tga import decode_tga
    blob = _rle_header(2, 1) + bytes([0x8F]) + bytes([0, 0, 255, 255])
    _w, _h, rgba = decode_tga(blob)
    assert rgba == bytes([255, 0, 0, 255]) * 2


def test_still_rejects_a_genuinely_unsupported_type():
    import pytest
    from engine.ui.tga import decode_tga
    # Type 1 = uncompressed COLOUR-MAPPED, which we do not implement.
    blob = struct.pack("<BBBHHBHHHHBB", 0,0,1, 0,0,0, 0,0, 1,1, 32, 0x20)
    with pytest.raises(ValueError):
        decode_tga(blob)
