"""Bug D regression: ``_strip_emit_position`` models a phaser strip
as an arc on a sphere, not a straight line.

Galaxy DorsalPhaser1 is mounted at body Position = (0, 1.27, 0.5),
faces body -X (port), pivots around body +Z (up), with Length = 1.69.
The rim of the strip is a curve on the sphere of radius Length around
Position. Beams emerge from the point on that arc closest (in yaw)
to the target.

Prior behaviour treated the strip as a 1D line along Right, so emit
points landed inside the saucer body when Right pointed away from the
hull rim.

See ``docs/instrumented_experiments/hardpoint_handling_research.md``
section "Bug D" for the full investigation.
"""
import math

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.properties import PhaserProperty
from engine.appc.subsystems import PhaserBank


class _StubShip:
    """Minimal ship stand-in: identity rotation, origin position."""
    def __init__(self):
        self._loc = TGPoint3(0.0, 0.0, 0.0)
        self._rot = TGMatrix3()  # identity by default
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetParentSubsystem(self): return None
    def GetParentShip(self): return self


def _galaxy_dorsal1_bank():
    """Build a Galaxy-DorsalPhaser1-like PhaserBank for arc tests."""
    bank = PhaserBank("DorsalPhaser1")
    # Hardpoint values from sdk/.../ships/Hardpoints/galaxy.py:384-415.
    prop = PhaserProperty("DorsalPhaser1")
    prop.SetPosition(0.0, 1.27, 0.5)
    prop.SetOrientation(TGPoint3(-1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    prop.SetLength(1.69)
    prop.SetWidth(1.35)
    prop.SetArcWidthAngles(-0.872665, 0.872665)  # ±50°
    prop.SetArcHeightAngles(-0.052360, 1.047198)
    bank.SetProperty(prop)
    # Attach to a stub ship at origin (identity rotation).
    bank._parent_ship = _StubShip()
    return bank


def test_emit_point_lies_on_sphere_of_radius_length():
    bank = _galaxy_dorsal1_bank()
    # Target far in body -X direction (port broadside) -- expect emit
    # at Position + Length × (-X), i.e. on the strip's centre arc.
    target = TGPoint3(-100.0, 1.27, 0.5)
    emit = bank._strip_emit_position(target)
    cx, cy, cz = 0.0, 1.27, 0.5  # bank world Position (identity rot)
    radius = math.sqrt((emit.x - cx) ** 2
                     + (emit.y - cy) ** 2
                     + (emit.z - cz) ** 2)
    assert radius == math.isclose(radius, 1.69, abs_tol=1e-6) or abs(radius - 1.69) < 1e-6


def test_emit_point_points_toward_target_when_in_arc():
    bank = _galaxy_dorsal1_bank()
    # Target directly to port -- yaw = 0 (centred on Forward).
    target = TGPoint3(-100.0, 1.27, 0.5)
    emit = bank._strip_emit_position(target)
    # Direction Position -> emit must equal world_forward = (-1, 0, 0).
    dx = emit.x - 0.0
    dy = emit.y - 1.27
    dz = emit.z - 0.5
    norm = math.sqrt(dx*dx + dy*dy + dz*dz)
    assert abs(dx / norm - (-1.0)) < 1e-6
    assert abs(dy / norm) < 1e-6
    assert abs(dz / norm) < 1e-6


def test_emit_yaw_clamps_to_arc_width():
    bank = _galaxy_dorsal1_bank()
    # Target dead ahead of the ship is far outside DorsalPhaser1's ±50°
    # arc (centred on -X). For Forward=(-1,0,0), Up=(0,0,1) the derived
    # Right = up × forward = (0,-1,0), so a +Y target sits in the -Right
    # half-plane -> yaw clamps to -50° (the left edge of the arc).
    target = TGPoint3(0.0, 100.0, 0.5)
    emit = bank._strip_emit_position(target)
    dx = emit.x - 0.0
    dy = emit.y - 1.27
    dz = emit.z - 0.5
    # Rodrigues with axis=+Z, angle=-50° on Forward=(-1,0,0) yields
    # (-cos50°, +sin50°, 0): the forward axis pivots toward +Y.
    expected_x = -math.cos(0.872665)
    expected_y =  math.sin(0.872665)
    norm = math.sqrt(dx*dx + dy*dy + dz*dz)
    assert abs(dx / norm - expected_x) < 1e-5
    assert abs(dy / norm - expected_y) < 1e-5
    assert abs(dz / norm) < 1e-5


def test_emit_point_for_length_zero_emitter_collapses_to_position():
    bank = PhaserBank("PointEmitter")
    prop = PhaserProperty("PointEmitter")
    prop.SetPosition(0.0, 1.0, 0.0)
    prop.SetOrientation(TGPoint3(0.0, 1.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    prop.SetLength(0.0)
    bank.SetProperty(prop)
    bank._parent_ship = _StubShip()
    target = TGPoint3(5.0, 5.0, 5.0)
    emit = bank._strip_emit_position(target)
    assert (round(emit.x, 6), round(emit.y, 6), round(emit.z, 6)) == (0.0, 1.0, 0.0)


def test_set_property_mirrors_up_axis_onto_subsystem():
    bank = PhaserBank("DorsalPhaser1")
    prop = PhaserProperty("DorsalPhaser1")
    prop.SetOrientation(TGPoint3(-1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    bank.SetProperty(prop)
    assert (bank._up.x, bank._up.y, bank._up.z) == (0.0, 0.0, 1.0)


def test_set_property_mirrors_width_onto_subsystem():
    bank = PhaserBank("DorsalPhaser1")
    prop = PhaserProperty("DorsalPhaser1")
    prop.SetWidth(1.35)
    bank.SetProperty(prop)
    assert bank.GetWidth() == 1.35
