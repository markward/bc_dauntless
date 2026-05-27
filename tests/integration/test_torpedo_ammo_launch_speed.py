"""Hardpoint loader must populate TorpedoSystem ammo entries with the
actual launch_speed from the configured projectile script, not the
zero-valued App.AT_ONE stub.

Symptom: FireScript.GetWeaponInfo reads
``pTorp.GetCurrentAmmoType().GetLaunchSpeed()`` and passes that
into PredictTargetLocation, which does ``fTime = fDistance / fSpeed``.
If launch_speed is 0 → ZeroDivisionError mid-AI-tick → the wrapping
PreprocessingAI raises out of the driver, killing the firing chain.
The user reported no enemy weapons fire in M3Gameflow after the
combat AI was wired up — this is one reason.

Reference: galaxy.py:1010 ``SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")``;
PhotonTorpedo.py:59 ``GetLaunchSpeed() = 19.0``. Galor uses
CardassianTorpedo at 15.0.
"""
import pytest

import App


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_galaxy_torp_ammo_has_real_photon_launch_speed():
    import loadspacehelper
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = loadspacehelper.CreateShip("Galaxy", pSet, "Galaxy", None, 0, 0)
    ts = ship.GetTorpedoSystem()
    assert ts is not None
    ammo = ts.GetCurrentAmmoType()
    assert ammo is not None
    assert ammo.GetLaunchSpeed() == pytest.approx(19.0), (
        f"Galaxy slot 0 is PhotonTorpedo (launch_speed=19.0 in "
        f"sdk/.../Tactical/Projectiles/PhotonTorpedo.py); got "
        f"{ammo.GetLaunchSpeed()}"
    )


def test_galor_torp_ammo_has_real_cardassian_launch_speed():
    import loadspacehelper
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = loadspacehelper.CreateShip("Galor", pSet, "Galor", None, 0, 0)
    ts = ship.GetTorpedoSystem()
    assert ts is not None
    ammo = ts.GetCurrentAmmoType()
    assert ammo is not None
    assert ammo.GetLaunchSpeed() == pytest.approx(15.0), (
        f"Galor slot 0 is CardassianTorpedo (launch_speed=15.0 in "
        f"sdk/.../Tactical/Projectiles/CardassianTorpedo.py); got "
        f"{ammo.GetLaunchSpeed()}"
    )
