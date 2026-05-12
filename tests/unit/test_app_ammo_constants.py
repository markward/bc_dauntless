"""AT_* ammo-type constants on the App shim.

The constants are TorpedoAmmoType instances (not ints) so SDK call sites
like MissionLib.SetTotalTorpsAtStarbase can compare GetAmmoName() to
known torpedo-type strings.
"""
import App
from engine.appc.subsystems import TorpedoAmmoType


def test_at_one_is_torpedo_ammo_type():
    assert isinstance(App.AT_ONE, TorpedoAmmoType)


def test_at_one_name_is_photon():
    assert App.AT_ONE.GetAmmoName() == "Photon"


def test_at_two_name_is_quantum():
    assert App.AT_TWO.GetAmmoName() == "Quantum"


def test_at_constants_are_distinct():
    names = [c.GetAmmoName() for c in
             (App.AT_ONE, App.AT_TWO, App.AT_THREE, App.AT_FOUR, App.AT_FIVE)]
    assert len(set(names)) == 5, f"AT_* names must be distinct: {names}"


def test_at_one_equals_at_one():
    # Same constant referenced twice is the same object.
    assert App.AT_ONE is App.AT_ONE
    assert App.AT_ONE is not App.AT_TWO
