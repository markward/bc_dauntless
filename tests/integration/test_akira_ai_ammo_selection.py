"""AI torpedo-type selection on a multi-ammo-type hull (the Akira crash).

Akira declares TWO ammo types (Photon slot 0 + Quantum slot 1,
sdk/.../Hardpoints/akira.py:157-161), so the AI's ChooseTorpType
(AI/Preprocessors.py:533) doesn't early-return like it does for
single-type hulls (Galaxy) — it calls ``SetAmmoType(iChosenAmmo)`` with an
int slot index.  Our shim used to treat that as a STORE, clobbering the
slot-0 TorpedoAmmoType object with the int, so the next
``pTorp.GetCurrentAmmoType().GetLaunchSpeed()`` (Preprocessors.py:768,
GetWeaponInfo) crashed with ``AttributeError: 'int' object has no
attribute 'GetLaunchSpeed'`` and killed the host loop.
"""
import pytest

import App
from engine.appc.ai import PreprocessingAI_Create
from engine.appc.weapon_subsystems import TorpedoAmmoType


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _spawn_akira():
    import loadspacehelper
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = loadspacehelper.CreateShip("Akira", pSet, "Akira", None, 0, 0)
    ts = ship.GetTorpedoSystem()
    assert ts is not None
    assert ts.GetNumAmmoTypes() == 2  # Photon + Quantum
    return ts


def _fire_script():
    from AI.Preprocessors import FireScript
    fs = FireScript("Target")
    fs.pCodeAI = PreprocessingAI_Create(None, "FirePP")
    return fs


def _target_loc():
    loc = App.TGPoint3()
    loc.SetXYZ(0.0, 100.0, 0.0)
    return loc


def test_choose_torp_type_single_available_switch_keeps_ammo_objects():
    """The Preprocessors.py:548 branch: exactly one type has ammo left and it
    isn't the selected one, so the SDK switches with SetAmmoType(int)."""
    ts = _spawn_akira()
    ts.SetCurrentAmmoSlot(1)                                  # Quantum selected
    ts.LoadAmmoType(1, -ts.GetNumAvailableTorpsToType(1))     # ...and drained
    _fire_script().ChooseTorpType(ts, _target_loc(), 0.0)

    assert ts.GetAmmoTypeNumber() == 0                        # switched to Photon
    ammo = ts.GetCurrentAmmoType()
    assert isinstance(ammo, TorpedoAmmoType)
    assert ammo.GetLaunchSpeed() == pytest.approx(19.0)       # PhotonTorpedo.py:59
    assert isinstance(ts.GetAmmoType(1), TorpedoAmmoType)     # slot 1 not clobbered


def test_choose_torp_type_rating_loop_keeps_ammo_objects():
    """The full 2-types-available rating path (Preprocessors.py:556-640).
    Whatever slot wins, the slot table must still hold TorpedoAmmoType
    objects and GetCurrentAmmoType().GetLaunchSpeed() must work — this is
    exactly what GetWeaponInfo does on the next AI tick."""
    ts = _spawn_akira()
    _fire_script().ChooseTorpType(ts, _target_loc(), 5.0)

    for slot in range(ts.GetNumAmmoTypes()):
        assert isinstance(ts.GetAmmoType(slot), TorpedoAmmoType)
    speed = ts.GetCurrentAmmoType().GetLaunchSpeed()
    assert isinstance(speed, float) and speed > 0.0
