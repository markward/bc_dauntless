"""Firing-arc gate + strip-emit correctness under the RIGHT-HANDED ship
convention (post 2026-06-18 un-mirror).

AlignToVectors now builds ``right = forward × up`` (det = +1) and the renderer
draws the rotation with no reflection, so the raw rotation IS the frame the
player sees. The arc gate's ``world_right`` is therefore ``forward × up`` =
``R·GetCol(0)`` = true starboard, and the strip emit shares that frame so the
beam leaves on the side the gate admits.

These guard the geometry against regressing to the old left-handed derivation
(which lit the opposite-side bank and raked the beam through the firing ship's
own hull). See docs/superpowers/plans/2026-06-18-render-handedness-unmirror.md.
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


def _banked(angle_z, angle_x=0.0):
    """A right-handed (det = +1) proper rotation — the real player/NPC case
    after the un-mirror. Yaw about Z then pitch about X."""
    Rz = TGMatrix3(); Rz.MakeRotation(angle_z, TGPoint3(0.0, 0.0, 1.0))
    Rx = TGMatrix3(); Rx.MakeRotation(angle_x, TGPoint3(1.0, 0.0, 0.0))
    return Rz.MultMatrix(Rx)


# Right-handed rotations only — det < 0 ships no longer exist (AlignToVectors
# builds det = +1, _world_matrix_from does not reflect).
_ROTATIONS = [
    (TGMatrix3(), "identity"),
    (_banked(0.6), "yaw-0.6"),
    (_banked(-1.1, 0.4), "yaw-1.1-pitch-0.4"),
]


def _bank(name, forward, arc_height, ship, arc_width=(-1.396263, 1.396263)):
    b = PhaserBank(name)
    p = PhaserProperty(name)
    p.SetPosition(0.0, 1.27, 0.5)
    p.SetOrientation(TGPoint3(*forward), TGPoint3(0.0, 0.0, 1.0))
    p.SetLength(1.69)
    p.SetWidth(0.0)
    p.SetArcWidthAngles(*arc_width)
    p.SetArcHeightAngles(*arc_height)
    b.SetProperty(p)
    b._parent_ship = ship
    return b


def _world(R, vx, vy, vz):
    v = TGPoint3(vx, vy, vz)
    v.MultMatrixLeft(R)
    return v


@pytest.mark.parametrize("R,label", _ROTATIONS)
def test_pitch_gate_correct(R, label):
    """Dorsal (up arc) engages above-targets, ventral (down arc) engages
    below-targets — 'above/below' along the ship's own up axis."""
    ship = _Ship(R)
    dorsal = _bank("Dorsal", (0.0, 1.0, 0.0), (-0.05236, 1.047198), ship)
    ventral = _bank("Ventral", (0.0, 1.0, 0.0), (-1.047198, 0.05236), ship)
    fwd = _world(R, 0.0, 1000.0, 0.0)
    up = _world(R, 0.0, 0.0, 300.0)
    above = _Target(fwd.x + up.x, fwd.y + up.y, fwd.z + up.z)
    below = _Target(fwd.x - up.x, fwd.y - up.y, fwd.z - up.z)

    assert _emitter_in_arc(dorsal, ship, _resolve_bank_aim_world(dorsal, above)) is True
    assert _emitter_in_arc(ventral, ship, _resolve_bank_aim_world(ventral, above)) is False
    assert _emitter_in_arc(dorsal, ship, _resolve_bank_aim_world(dorsal, below)) is False
    assert _emitter_in_arc(ventral, ship, _resolve_bank_aim_world(ventral, below)) is True


@pytest.mark.parametrize("R,label", _ROTATIONS)
def test_starboard_target_engages_starboard_banks(R, label):
    """A target on the ship's STARBOARD side (true right = R·GetCol(0) = R·+X)
    engages the starboard-favouring forward bank (Galaxy VentralPhaser3, yaw
    −20..+80) and the +X-firing side bank (VentralPhaser4), and NOT their port
    mirrors (VP2/VP1) which would fire through the hull."""
    ship = _Ship(R)
    vp3 = _bank("VP3", (0.0, 1.0, 0.0), (-1.047198, 1.047198), ship,
                arc_width=(-0.349066, 1.396263))   # starboard-favouring fwd
    vp2 = _bank("VP2", (0.0, 1.0, 0.0), (-1.047198, 1.047198), ship,
                arc_width=(-1.396263, 0.349066))   # port-favouring fwd
    vp4 = _bank("VP4", (1.0, 0.0, 0.0), (-1.047198, 1.047198), ship,
                arc_width=(-0.872665, 0.872665))   # +X = starboard side
    vp1 = _bank("VP1", (-1.0, 0.0, 0.0), (-1.047198, 1.047198), ship,
                arc_width=(-0.872665, 0.872665))   # -X = port side

    stbd = _world(R, 1.0, 0.0, 0.0)   # true starboard
    fwd = _world(R, 0.0, 1.0, 0.0)
    tgt = _Target(900.0 * stbd.x + 500.0 * fwd.x,
                  900.0 * stbd.y + 500.0 * fwd.y,
                  900.0 * stbd.z + 500.0 * fwd.z)

    assert _emitter_in_arc(vp3, ship, _resolve_bank_aim_world(vp3, tgt)) is True, f"{label}: VP3"
    assert _emitter_in_arc(vp4, ship, _resolve_bank_aim_world(vp4, tgt)) is True, f"{label}: VP4"
    assert _emitter_in_arc(vp2, ship, _resolve_bank_aim_world(vp2, tgt)) is False, f"{label}: VP2"
    assert _emitter_in_arc(vp1, ship, _resolve_bank_aim_world(vp1, tgt)) is False, f"{label}: VP1"


@pytest.mark.parametrize("R,label", _ROTATIONS)
def test_strip_emit_faces_target(R, label):
    """The emit point lies on the half of the strip facing the target, so the
    beam leaves toward the target rather than back through the hull."""
    ship = _Ship(R)
    bank = _bank("Fore", (0.0, 1.0, 0.0), (-0.5, 0.5), ship)
    stbd = _world(R, 1.0, 0.0, 0.0)
    fwd = _world(R, 0.0, 1.0, 0.0)
    target = _Target(500.0 * stbd.x + 1000.0 * fwd.x,
                     500.0 * stbd.y + 1000.0 * fwd.y,
                     500.0 * stbd.z + 1000.0 * fwd.z)
    center = subsystem_world_position(bank, ship)
    emit = bank._strip_emit_position(target.GetWorldLocation())
    ed = (emit.x - center.x, emit.y - center.y, emit.z - center.z)
    td = (target._loc.x - center.x, target._loc.y - center.y, target._loc.z - center.z)
    facing = ed[0] * td[0] + ed[1] * td[1] + ed[2] * td[2]
    assert facing > 0.0, f"{label}: emit points away from target"
