from PIL import Image
from tools.bake_backdrop_appearance import compute_appearance


def _solid(rgb, size=64):
    return Image.new("RGBA", (size, size), rgb + (255,))


def test_compute_appearance_solid_colour():
    ap = compute_appearance(_solid((120, 40, 200)))
    # mean is the solid colour (within rounding of the 48x48 downsample)
    assert abs(ap["meanColor"][0] - 120) <= 3
    assert abs(ap["meanColor"][1] - 40) <= 3
    assert abs(ap["meanColor"][2] - 200) <= 3
    # fully lit -> coverage ~1.0
    assert ap["coverage"] >= 0.95
    assert len(ap["palette"]) == 5
    assert all(len(c) == 3 for c in ap["palette"])


def test_compute_appearance_mostly_black_low_coverage():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 255))
    for x in range(0, 6):
        for y in range(0, 6):
            img.putpixel((x, y), (255, 255, 255, 255))
    ap = compute_appearance(img)
    assert ap["coverage"] < 0.2  # ~36/4096 lit
