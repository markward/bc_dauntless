"""Pure-math tests for the disc projection. No SDK objects — feed in
TGPoint3 + TGMatrix3 directly so the test is fast + deterministic."""
import math
import pytest

from engine.appc.math import TGPoint3, TGMatrix3
from engine.ui.radar_projection import project_contact, Contact


def _identity():
    m = TGMatrix3()
    return m


def _yaw(theta):
    """Yaw matrix — rotates forward (Y) toward right (X) by +theta rad
    looking down (+Z). Columns are model right / forward / up."""
    m = TGMatrix3()
    c, s = math.cos(theta), math.sin(theta)
    # right = (cos, -sin, 0); forward = (sin, cos, 0); up = (0, 0, 1)
    m._m = [
        [ c,  s,  0.0],
        [-s,  c,  0.0],
        [0.0, 0.0, 1.0],
    ]
    return m


def test_contact_at_player_forward_within_range():
    """Contact 4000 m ahead of a player facing +Y → (x≈0, y≈+0.5)."""
    c = project_contact(
        player_pos=TGPoint3(0.0, 0.0, 0.0),
        player_rot=_identity(),
        target_pos=TGPoint3(0.0, 4000.0, 0.0),
        target_rot=_identity(),
        range_m=8000.0,
    )
    assert c is not None
    assert abs(c.x) < 1e-6
    assert c.y == pytest.approx(0.5, abs=1e-6)
    assert abs(c.alt) < 1e-6
    assert abs(c.heading) < 1e-6


def test_contact_to_player_right_within_range():
    c = project_contact(
        player_pos=TGPoint3(0.0, 0.0, 0.0),
        player_rot=_identity(),
        target_pos=TGPoint3(2000.0, 0.0, 0.0),
        target_rot=_identity(),
        range_m=8000.0,
    )
    assert c.x == pytest.approx(0.25, abs=1e-6)
    assert abs(c.y) < 1e-6


def test_contact_above_player_uses_alt():
    c = project_contact(
        player_pos=TGPoint3(0.0, 0.0, 0.0),
        player_rot=_identity(),
        target_pos=TGPoint3(0.0, 0.0, 4000.0),
        target_rot=_identity(),
        range_m=8000.0,
    )
    # In-plane projection is the origin; altitude carries the offset.
    assert abs(c.x) < 1e-6
    assert abs(c.y) < 1e-6
    assert c.alt == pytest.approx(0.5, abs=1e-6)


def test_off_disc_contact_returns_none():
    """Contact 10 km ahead with range = 8 km → outside disc → None."""
    c = project_contact(
        player_pos=TGPoint3(0.0, 0.0, 0.0),
        player_rot=_identity(),
        target_pos=TGPoint3(0.0, 10000.0, 0.0),
        target_rot=_identity(),
        range_m=8000.0,
    )
    assert c is None


def test_disc_coords_are_player_relative():
    """Player rotated 90° (yaw +π/2 — forward now along +X). A contact
    along world +X is "ahead" of the player, so y should be positive,
    x near zero."""
    c = project_contact(
        player_pos=TGPoint3(0.0, 0.0, 0.0),
        player_rot=_yaw(math.pi / 2.0),
        target_pos=TGPoint3(4000.0, 0.0, 0.0),
        target_rot=_identity(),
        range_m=8000.0,
    )
    assert abs(c.x) < 1e-6
    assert c.y == pytest.approx(0.5, abs=1e-6)


def test_heading_is_target_forward_relative_to_player_forward():
    """Player faces +Y; target faces -Y (i.e. directly toward the player).
    Relative heading should be π (180°)."""
    c = project_contact(
        player_pos=TGPoint3(0.0, 0.0, 0.0),
        player_rot=_identity(),
        target_pos=TGPoint3(0.0, 2000.0, 0.0),
        target_rot=_yaw(math.pi),
        range_m=8000.0,
    )
    assert abs(abs(c.heading) - math.pi) < 1e-6
