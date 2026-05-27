"""End-to-end: Galaxy hardpoint's FiringChainString gets parsed onto
the TorpedoSystemProperty and is visible at the TorpedoSystem after
loadspacehelper.CreateShip.

galaxy.py:1006-1008 sets
``Torpedoes.SetFiringChainString("0;Single;123;Dual;53;Quad")`` —
before this slice the call landed on a TGObject ``_Stub`` and was
silently dropped. Now the chain shows up on the live system so
StartFiring can dispatch the burst pattern.
"""
import App
import pytest


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_galaxy_torpedo_system_exposes_three_firing_chains():
    import loadspacehelper
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = loadspacehelper.CreateShip("Galaxy", pSet, "Galaxy", None, 0, 0)
    ts = ship.GetTorpedoSystem()
    assert ts is not None
    prop = ts.GetProperty()
    assert prop is not None
    chains = prop.GetFiringChains()
    assert chains == [
        ("Single", [0]),
        ("Dual",   [1, 2, 3]),
        ("Quad",   [5, 3]),
    ], (
        f"Galaxy's FiringChainString from galaxy.py:1006-1008 didn't "
        f"land on the property; got {chains!r}"
    )


def test_galor_torpedo_system_has_no_chains():
    """Galor's hardpoint sets the chain string to "" — the parser
    yields an empty list, so TorpedoSystem falls back to round-robin."""
    import loadspacehelper
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = loadspacehelper.CreateShip("Galor", pSet, "Galor", None, 0, 0)
    ts = ship.GetTorpedoSystem()
    assert ts is not None
    prop = ts.GetProperty()
    assert prop is not None
    assert prop.GetFiringChains() == []
