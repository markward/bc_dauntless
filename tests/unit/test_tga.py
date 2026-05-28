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
