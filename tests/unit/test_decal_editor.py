import math

import pytest

from engine.ui.decal_editor import (
    Placement,
    centre,
    chirality_ok,
    from_json_entry,
    move_uv,
    place_at_hit,
    reposition,
    roll,
    roll_angle,
    scale,
    set_width,
    to_json_entry,
    valid_name,
    width,
)


def _mag(v):
    return math.sqrt(sum(c * c for c in v))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _norm(v):
    m = _mag(v)
    return tuple(c / m for c in v)


def _approx_vec(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# place_at_hit
# ---------------------------------------------------------------------------

FWD = (0.0, 1.0, 0.0)
UP = (0.0, 0.0, 1.0)
RIGHT = (1.0, 0.0, 0.0)


@pytest.mark.parametrize("normal", [
    (0.0, 0.0, 1.0),   # +z
    (0.0, 0.0, -1.0),  # -z
    (1.0, 0.0, 0.0),   # +x (forward is parallel here -> exercises fallback
                       # too, but kept separate below; this is a case where
                       # forward IS perpendicular to +x, so no fallback)
    (0.3, 0.1, 0.94868329805),  # tilted, arbitrary
])
def test_place_at_hit_basic_properties(normal):
    hit = (10.0, 20.0, 30.0)
    aspect = 2.0
    p = place_at_hit("top", hit, normal, FWD, UP, ship_radius=100.0,
                      mask_aspect=aspect)

    assert _approx_vec(centre(p), hit)
    assert chirality_ok(p)

    n = _norm(normal)
    assert abs(_dot(p.u_axis, n)) < 1e-6
    assert abs(_dot(p.v_axis, n)) < 1e-6

    assert abs(_mag(p.u_axis) / _mag(p.v_axis) - aspect) < 1e-6

    # Lettering top points toward the projected ship forward.
    proj_fwd = _norm((FWD[0] - n[0] * _dot(FWD, n),
                       FWD[1] - n[1] * _dot(FWD, n),
                       FWD[2] - n[2] * _dot(FWD, n)))
    neg_v_hat = _norm(tuple(-c for c in p.v_axis))
    assert _dot(neg_v_hat, proj_fwd) > 0.99


def test_place_at_hit_sizes():
    hit = (0.0, 0.0, 0.0)
    p = place_at_hit("top", hit, (0.0, 0.0, 1.0), FWD, UP,
                      ship_radius=100.0, mask_aspect=2.0)
    assert abs(_mag(p.u_axis) - 25.0) < 1e-6          # 0.25 * radius
    assert abs(_mag(p.v_axis) - 12.5) < 1e-6           # width / aspect
    assert abs(p.depth - 1.25) < 1e-6                  # 0.05 * width


def test_place_at_hit_forward_parallel_to_normal_falls_back_to_up():
    # Normal along +forward: forward's projection onto the plane ⟂ n is
    # ~zero, so the up reference must fall back to ship_up.
    hit = (5.0, 5.0, 5.0)
    p = place_at_hit("nose", hit, FWD, FWD, UP, ship_radius=40.0,
                      mask_aspect=1.5)
    assert chirality_ok(p)
    n = _norm(FWD)
    proj_up = _norm((UP[0] - n[0] * _dot(UP, n),
                      UP[1] - n[1] * _dot(UP, n),
                      UP[2] - n[2] * _dot(UP, n)))
    neg_v_hat = _norm(tuple(-c for c in p.v_axis))
    assert _dot(neg_v_hat, proj_up) > 0.99


def test_place_at_hit_zero_radius_raises():
    with pytest.raises(ValueError):
        place_at_hit("x", (0, 0, 0), (0, 0, 1), FWD, UP, ship_radius=0.0,
                      mask_aspect=2.0)


def test_place_at_hit_zero_normal_raises():
    with pytest.raises(ValueError):
        place_at_hit("x", (0, 0, 0), (0.0, 0.0, 0.0), FWD, UP,
                      ship_radius=100.0, mask_aspect=2.0)


# ---------------------------------------------------------------------------
# reposition
# ---------------------------------------------------------------------------

def test_reposition_keeps_width_and_aspect():
    p = place_at_hit("top", (0, 0, 0), (0, 0, 1), FWD, UP,
                      ship_radius=100.0, mask_aspect=2.0)
    w0, aspect0 = width(p), width(p) / _mag(p.v_axis)

    p2 = reposition(p, (50.0, 0.0, 0.0), (1.0, 0.0, 0.0), FWD, UP)
    assert abs(width(p2) - w0) < 1e-6
    assert abs(width(p2) / _mag(p2.v_axis) - aspect0) < 1e-6
    assert abs(p2.depth - p.depth) < 1e-6
    assert _approx_vec(centre(p2), (50.0, 0.0, 0.0))
    assert chirality_ok(p2)


def test_reposition_preserves_roll_angle():
    p = place_at_hit("top", (0, 0, 0), (0, 0, 1), FWD, UP,
                      ship_radius=100.0, mask_aspect=2.0)
    p = roll(p, math.radians(40.0))
    r0 = roll_angle(p, FWD)

    p2 = reposition(p, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0), FWD, UP)
    r1 = roll_angle(p2, FWD)
    assert abs(r1 - r0) < 1e-6


def test_reposition_survives_forward_fallback_placement():
    # A bow decal: place_at_hit's normal equals ship_forward, so its
    # up-reference came from ship_up's fallback, not forward's projection.
    # Repositioning it onto an ordinary normal must not raise.
    p = place_at_hit("nose", (5.0, 5.0, 5.0), FWD, FWD, UP,
                      ship_radius=40.0, mask_aspect=1.5)
    p2 = reposition(p, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), FWD, UP)
    assert chirality_ok(p2)
    assert _approx_vec(centre(p2), (0.0, 0.0, 0.0))


def test_reposition_roll_preserved_from_fallback_onto_ordinary_normal():
    p = place_at_hit("nose", (5.0, 5.0, 5.0), FWD, FWD, UP,
                      ship_radius=40.0, mask_aspect=1.5)
    p = roll(p, math.radians(20.0))
    r0 = roll_angle(p, FWD, UP)

    p2 = reposition(p, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), FWD, UP)
    r1 = roll_angle(p2, FWD, UP)
    assert abs(r1 - r0) < 1e-6


def test_reposition_roll_preserved_from_ordinary_onto_fallback_normal():
    # The reverse: an ordinary decal repositioned onto a bow hit, where the
    # new normal equals ship_forward and triggers place_at_hit's fallback.
    p = place_at_hit("top", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), FWD, UP,
                      ship_radius=100.0, mask_aspect=2.0)
    p = roll(p, math.radians(-30.0))
    r0 = roll_angle(p, FWD, UP)

    p2 = reposition(p, (5.0, 5.0, 5.0), FWD, FWD, UP)
    assert chirality_ok(p2)
    r1 = roll_angle(p2, FWD, UP)
    assert abs(r1 - r0) < 1e-6


# ---------------------------------------------------------------------------
# move_uv / roll / scale round-trips
# ---------------------------------------------------------------------------

def _sample_placement():
    return place_at_hit("top", (10.0, -5.0, 3.0), (0.2, 0.3, 0.9327379),
                         FWD, UP, ship_radius=80.0, mask_aspect=1.6)


def test_move_uv_round_trip():
    p = _sample_placement()
    p2 = move_uv(p, 3.0, -2.0)
    p3 = move_uv(p2, -3.0, 2.0)
    assert _approx_vec(p3.origin, p.origin)
    assert _approx_vec(p3.u_axis, p.u_axis)
    assert _approx_vec(p3.v_axis, p.v_axis)


def test_move_uv_displaces_centre_along_uv():
    p = _sample_placement()
    u_hat = _norm(p.u_axis)
    v_hat = _norm(p.v_axis)
    p2 = move_uv(p, 5.0, 0.0)
    expected = tuple(c0 + 5.0 * u for c0, u in zip(centre(p), u_hat))
    assert _approx_vec(centre(p2), expected)


def test_roll_full_turn_round_trip():
    p = _sample_placement()
    p2 = roll(p, 2.0 * math.pi)
    assert _approx_vec(p2.origin, p.origin, tol=1e-4)
    assert _approx_vec(p2.u_axis, p.u_axis, tol=1e-4)
    assert _approx_vec(p2.v_axis, p.v_axis, tol=1e-4)


def test_roll_90_degrees_changes_roll_angle_by_90():
    p = _sample_placement()
    r0 = roll_angle(p, FWD)
    p2 = roll(p, math.radians(90.0))
    r1 = roll_angle(p2, FWD)
    delta = (r1 - r0 + math.pi) % (2.0 * math.pi) - math.pi
    assert abs(delta - math.radians(90.0)) < 1e-6


def test_roll_keeps_centre_and_chirality():
    p = _sample_placement()
    p2 = roll(p, math.radians(37.0))
    assert _approx_vec(centre(p2), centre(p))
    assert chirality_ok(p2)


def test_scale_round_trip():
    p = _sample_placement()
    p2 = scale(p, 2.0)
    p3 = scale(p2, 0.5)
    assert _approx_vec(p3.origin, p.origin)
    assert _approx_vec(p3.u_axis, p.u_axis)
    assert _approx_vec(p3.v_axis, p.v_axis)
    assert abs(p3.depth - p.depth) < 1e-6


def test_scale_keeps_centre_and_aspect():
    p = _sample_placement()
    aspect0 = width(p) / _mag(p.v_axis)
    p2 = scale(p, 2.0)
    assert _approx_vec(centre(p2), centre(p))
    assert abs(width(p2) - 2.0 * width(p)) < 1e-6
    assert abs(width(p2) / _mag(p2.v_axis) - aspect0) < 1e-6


def test_scale_rejects_non_positive_factor():
    p = _sample_placement()
    with pytest.raises(ValueError):
        scale(p, 0.0)
    with pytest.raises(ValueError):
        scale(p, -1.0)


def test_set_width_keeps_centre_roll_and_normal():
    p = _sample_placement()
    p = roll(p, math.radians(25.0))
    r0 = roll_angle(p, FWD)
    c0 = centre(p)

    p2 = set_width(p, 40.0, mask_aspect=2.5)
    assert abs(width(p2) - 40.0) < 1e-6
    assert abs(_mag(p2.v_axis) - 16.0) < 1e-6  # 40 / 2.5
    assert _approx_vec(centre(p2), c0)
    assert _approx_vec(p2.normal, p.normal)
    r1 = roll_angle(p2, FWD)
    assert abs(r1 - r0) < 1e-6


def test_set_width_rejects_non_positive():
    p = _sample_placement()
    with pytest.raises(ValueError):
        set_width(p, 0.0, mask_aspect=2.0)
    with pytest.raises(ValueError):
        set_width(p, 10.0, mask_aspect=0.0)


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------

def test_json_round_trip_without_shape():
    p = _sample_placement()
    entry = to_json_entry(p)
    assert "shape" not in entry
    p2 = from_json_entry("top", entry)
    assert p2.name == "top"
    assert p2.shape == ""
    assert _approx_vec(p2.origin, p.origin)
    assert _approx_vec(p2.u_axis, p.u_axis)
    assert _approx_vec(p2.v_axis, p.v_axis)
    assert _approx_vec(p2.normal, p.normal)
    assert abs(p2.depth - p.depth) < 1e-9


def test_json_round_trip_with_shape():
    p = Placement(name="top", origin=(1.0, 2.0, 3.0), u_axis=(4.0, 0.0, 0.0),
                  v_axis=(0.0, -2.0, 0.0), normal=(0.0, 0.0, 1.0),
                  depth=0.5, shape="amb saucer:0")
    entry = to_json_entry(p)
    assert entry["shape"] == "amb saucer:0"
    p2 = from_json_entry("top", entry)
    assert p2.shape == "amb saucer:0"
    assert p2.origin == (1.0, 2.0, 3.0)


def test_json_null_shape_reads_as_unrestricted_like_the_game():
    """hull_decals.decals_for treats `"shape": null` as "" (every mesh); the
    SPV preview must read it the same, not as None (which the live override
    would drop)."""
    entry = {"shape": None, "origin": [0.0, 0.0, 0.0],
             "u_axis": [4.0, 0.0, 0.0], "v_axis": [0.0, -2.0, 0.0],
             "normal": [0.0, 0.0, 1.0], "depth": 0.5}
    p = from_json_entry("top", entry)
    assert p.shape == ""
    assert "shape" not in to_json_entry(p)


def test_json_entry_matches_committed_ambassador_key_shape():
    # Sanity-check against the shape of the real committed decals.json
    # entry cited in the brief (native/assets/replacements/data/Models/
    # Ships/Ambassador/Masks/decals.json).
    d = {
        "shape": "amb saucer:0",
        "origin": [58.1320915222168, 146.52700805664062, 51.25088119506836],
        "u_axis": [-119.56663513183594, -0.011889359913766384,
                    -0.0024647493846714497],
        "v_axis": [-0.005896189250051975, 59.74415969848633,
                    -2.1634225845336914],
        "normal": [-2.4198923711082898e-05, 0.03618772700428963,
                    0.9993450045585632],
        "depth": 2.0,
    }
    p = from_json_entry("top", d)
    assert chirality_ok(p)
    assert not math.isnan(_dot(p.u_axis, p.normal))


# ---------------------------------------------------------------------------
# valid_name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["", "a/b", "..", ".", "a b", "a.b", "a\\b"])
def test_valid_name_rejects_bad_names(name):
    assert valid_name(name, []) is not None


def test_valid_name_accepts_good_name():
    assert valid_name("top-2_left", []) is None


def test_valid_name_rejects_duplicates_case_insensitively():
    assert valid_name("Top", ["top"]) is not None
    assert valid_name("top", ["Top"]) is not None


def test_valid_name_allows_non_duplicate():
    assert valid_name("bottom", ["top"]) is None
