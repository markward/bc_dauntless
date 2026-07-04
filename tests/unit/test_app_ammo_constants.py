"""AT_* ammo-type constants on the App shim.

The constants are plain 0-based ints matching the real Appc.AT_* enum.  The
SDK only ever passes them as the first arg of TorpedoSystem.SetAmmoType,
which selects an ammo slot in the same domain as GetAmmoTypeNumber() /
range(GetNumAmmoTypes()) — E2M0.py:720 selects the Sovereign's slot-1
Quantum via App.AT_TWO.
"""
import App


def test_at_constants_are_zero_based_ints():
    assert App.AT_ONE == 0
    assert App.AT_TWO == 1
    assert App.AT_THREE == 2
    assert App.AT_FOUR == 3
    assert App.AT_FIVE == 4


def test_at_constants_are_plain_ints():
    for const in (App.AT_ONE, App.AT_TWO, App.AT_THREE, App.AT_FOUR,
                  App.AT_FIVE):
        assert type(const) is int
