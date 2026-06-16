"""Regression: the firing-arc gate and the strip emit point must be correct
under a LEFT-HANDED (det = -1) ship rotation — which is what ``AlignToVectors``
produces (see objects.py:135 and CLAUDE.md's X-axis-flip note).

The gate derived ``world_up = world_dir × world_right`` and the strip emit
derived ``world_right = world_up × world_forward`` via cross products. A cross
product of vectors carried through a det = -1 matrix flips sign
(``(R·a)×(R·b) = -R·(a×b)``), so on a real maneuvering ship:

  * the gate's pitch inverted — ventral banks fired at targets ABOVE the ship
    and dorsal banks went silent (the live-combat symptom);
  * the emit's yaw mirrored — the beam emerged from the wrong side of the strip
    and raked through the firing ship's own hull.

The fix: rotate the *stored* body up/right directly instead of re-deriving them
with a cross product (which is exactly what the Ship Property Viewer already
does, and why its arcs looked correct). Debug session: 2026-06-16.
"""
import pytest

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.properties import PhaserProperty
from engine.appc.subsystems import PhaserBank, subsystem_world_position
from engine.appc.weapon_subsystems import _emitter_in_arc, _resolve_bank_aim_world


class _Ship:
    def __init__(self, R):
        self._loc = TGPoint3(0.0, 0.0, 0.0)
        self._R = R
    def GetWorldLocation(self):
        return self._loc
    def GetWorldRotation(self):
        return self._R
    def GetParentSubsystem(self):
        return None
    def GetParentShip(self):
        return self


class _Target:
    def __init__(self, x, y, z):
        self._loc = TGPoint3(x, y, z)
    def GetWorldLocation(self):
        return self._loc


def _left_handed():
    """A det = -1 rotation: flip body +X -> world -X. Body up (+Z) and forward
    (+Y) map to world +Z / +Y unchanged, so 'above' is unambiguous."""
    R = TGMatrix3()
    R.SetCol(0, TGPoint3(-1.0, 0.0, 0.0))
    return R


def _bank(name, forward, arc_height, ship):
    b = PhaserBank(name)
    p = PhaserProperty(name)
    p.SetPosition(0.0, 1.27, 0.5)
    p.SetOrientation(TGPoint3(*forward), TGPoint3(0.0, 0.0, 1.0))
    p.SetLength(1.69)
    p.SetWidth(0.0)
    # Wide yaw so pitch is the discriminator; realistic galaxy pitch ranges.
    p.SetArcWidthAngles(-1.396263, 1.396263)
    p.SetArcHeightAngles(*arc_height)
    b.SetProperty(p)
    b._parent_ship = ship
    return b


_ROTATIONS = [(TGMatrix3(), "identity-det+1"), (_left_handed(), "left-handed-det-1")]


@pytest.mark.parametrize("R,label", _ROTATIONS)
def test_pitch_gate_correct_under_either_handedness(R, label):
    """Dorsal (up arc) engages above-targets, ventral (down arc) engages
    below-targets — independent of the ship rotation's handedness."""
    ship = _Ship(R)
    dorsal = _bank("Dorsal", (0.0, 1.0, 0.0), (-0.05236, 1.047198), ship)   # up
    ventral = _bank("Ventral", (0.0, 1.0, 0.0), (-1.047198, 0.05236), ship)  # down
    above = _Target(0.0, 1000.0, 300.0)   # ahead + above
    below = _Target(0.0, 1000.0, -300.0)  # ahead + below

    assert _emitter_in_arc(dorsal, ship, _resolve_bank_aim_world(dorsal, above)) is True
    assert _emitter_in_arc(ventral, ship, _resolve_bank_aim_world(ventral, above)) is False
    assert _emitter_in_arc(dorsal, ship, _resolve_bank_aim_world(dorsal, below)) is False
    assert _emitter_in_arc(ventral, ship, _resolve_bank_aim_world(ventral, below)) is True


@pytest.mark.parametrize("R,label", _ROTATIONS)
def test_strip_emit_faces_target_under_either_handedness(R, label):
    """The emit point lies on the half of the strip facing the target (so the
    beam leaves toward the target, not back through the hull) — independent of
    the rotation's handedness."""
    ship = _Ship(R)
    bank = _bank("Fore", (0.0, 1.0, 0.0), (-0.5, 0.5), ship)
    target = _Target(500.0, 1000.0, 0.0)  # ahead and to one side
    center = subsystem_world_position(bank, ship)
    emit = bank._strip_emit_position(target.GetWorldLocation())
    ed = (emit.x - center.x, emit.y - center.y, emit.z - center.z)
    td = (target._loc.x - center.x, target._loc.y - center.y, target._loc.z - center.z)
    facing = ed[0] * td[0] + ed[1] * td[1] + ed[2] * td[2]
    assert facing > 0.0, f"{label}: emit points away from target (mirrored side)"
