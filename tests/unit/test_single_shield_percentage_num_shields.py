"""GetSingleShieldPercentage(NUM_SHIELDS) must not raise.

E3M2's CoreDamage (Maelstrom/Episode3/E3M2/E3M2.py:1389) calls
pShields.GetSingleShieldPercentage(App.ShieldClass.NUM_SHIELDS) on every
ET_ENVIRONMENT_DAMAGE while shields are up. Index 6 is one past the last face;
it raised IndexError and killed the host loop the moment the player raised
shields in the Vesuvi cloud (live crash 2026-09-28).

What BC returns there is unmeasured; the SDK author's intent is "overall
shields below 5%", so NUM_SHIELDS reads as the whole-generator percentage.
"""
import pytest

from engine.appc.subsystems import ShieldSubsystem


def _gen(cur, face_max=1000.0):
    ss = ShieldSubsystem("Shield Generator")
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, face_max)
        ss.SetCurShields(f, cur[f])
    ss.TurnOn()
    return ss


def test_num_shields_index_reads_the_whole_generator():
    ss = _gen([1000.0, 0.0, 500.0, 500.0, 1000.0, 0.0])
    assert ss.GetSingleShieldPercentage(ShieldSubsystem.NUM_SHIELDS) == pytest.approx(
        ss.GetShieldPercentage())
    assert ss.GetSingleShieldPercentage(ShieldSubsystem.NUM_SHIELDS) == pytest.approx(0.5)


def test_num_shields_index_is_zero_while_the_generator_is_off():
    ss = _gen([1000.0] * 6)
    ss.TurnOff()
    assert ss.GetSingleShieldPercentage(ShieldSubsystem.NUM_SHIELDS) == 0.0


def test_real_faces_are_unchanged():
    ss = _gen([1000.0, 250.0, 0.0, 0.0, 0.0, 0.0])
    assert ss.GetSingleShieldPercentage(0) == pytest.approx(1.0)
    assert ss.GetSingleShieldPercentage(1) == pytest.approx(0.25)
