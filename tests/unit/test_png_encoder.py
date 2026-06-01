import struct
import zlib


def test_emits_valid_png_signature():
    from engine.ui.png_encoder import encode_png_rgba
    rgba = bytes([255, 0, 0, 255])
    blob = encode_png_rgba(1, 1, rgba)
    assert blob.startswith(b"\x89PNG\r\n\x1a\n")


def test_emits_ihdr_with_correct_dimensions():
    from engine.ui.png_encoder import encode_png_rgba
    rgba = bytes([0, 0, 0, 255] * 4)  # 2x2
    blob = encode_png_rgba(2, 2, rgba)
    assert blob[12:16] == b"IHDR"
    width, height = struct.unpack(">II", blob[16:24])
    assert (width, height) == (2, 2)


def test_round_trips_through_pillow_when_available():
    try:
        from PIL import Image
        import io
    except ImportError:
        return
    from engine.ui.png_encoder import encode_png_rgba
    rgba = bytes([200, 100, 50, 255,  10, 20, 30, 255]) * 2
    blob = encode_png_rgba(2, 2, rgba)
    img = Image.open(io.BytesIO(blob))
    assert img.size == (2, 2)
    assert img.mode == "RGBA"
