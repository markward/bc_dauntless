"""g_kUtopiaModule torpedo-economy round-trip, plus the starbase reload itself.

Covers the four UtopiaModule methods MissionLib.SetMaxTorpsForPlayer /
SetTotalTorpsAtStarbase write and Actions.ShipScriptActions.DockWithStarbase
reads. SDK sentinel -1 means "unset / unlimited".

The reload half pins TorpedoSystem.LoadAmmoType's RETURN value, which
ShipScriptActions.ReloadShip:394-395 depends on:

    iLoadAtStarbase = iLoadAtStarbase - iTorpsToLoad     # stock not handed over
    iLoadLeftover   = pTorpSys.LoadAmmoType(iType, iTorpsToLoad)
    SetCurrentStarbaseTorpedoLoad(iType, iLoadLeftover + iLoadAtStarbase)

i.e. LoadAmmoType returns how many of the requested rounds could NOT be loaded,
and the starbase keeps (untaken + didn't-fit). The invariant that identifies the
contract: torpedoes are CONSERVED across ship + starbase.
"""
import App


def _reset_utopia():
    App.g_kUtopiaModule._max_torpedo_load.clear()
    App.g_kUtopiaModule._starbase_torpedo_load.clear()


def test_max_torpedo_load_round_trip():
    _reset_utopia()
    App.g_kUtopiaModule.SetMaxTorpedoLoad(0, 300)
    App.g_kUtopiaModule.SetMaxTorpedoLoad(1, 60)
    assert App.g_kUtopiaModule.GetMaxTorpedoLoad(0) == 300
    assert App.g_kUtopiaModule.GetMaxTorpedoLoad(1) == 60


def test_starbase_torpedo_load_round_trip():
    _reset_utopia()
    App.g_kUtopiaModule.SetCurrentStarbaseTorpedoLoad(0, -1)
    App.g_kUtopiaModule.SetCurrentStarbaseTorpedoLoad(2, 12)
    assert App.g_kUtopiaModule.GetCurrentStarbaseTorpedoLoad(0) == -1
    assert App.g_kUtopiaModule.GetCurrentStarbaseTorpedoLoad(2) == 12


def test_unseen_type_returns_sdk_sentinel():
    _reset_utopia()
    assert App.g_kUtopiaModule.GetMaxTorpedoLoad(7) == -1
    assert App.g_kUtopiaModule.GetCurrentStarbaseTorpedoLoad(7) == -1


def _ship_with_ammo(*, max_torps, available):
    """A player ship carrying one finite torpedo type, registered for the
    ObjID lookup ReloadShip does via TGObject_GetTGObjectPtr."""
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import TorpedoSystem
    from engine.appc.weapon_subsystems import TorpedoAmmoType

    ship = ShipClass()
    system = TorpedoSystem("Torpedo System")
    ammo = TorpedoAmmoType("Photon", max_torpedoes=max_torps)
    ammo.SetAvailable(available)
    system.AddAmmoType(ammo)
    ship.SetTorpedoSystem(system)
    App.Game_SetCurrentPlayer(ship)
    return ship, system, ammo


def test_load_ammo_type_returns_zero_when_it_all_fits():
    """Everything requested was absorbed, so nothing is left for the starbase."""
    _, system, ammo = _ship_with_ammo(max_torps=50, available=10)
    assert system.LoadAmmoType(0, 15) == 0
    assert ammo.GetAvailable() == 25


def test_load_ammo_type_returns_the_overflow():
    """Only the free space is absorbed; the rest is reported back as leftover."""
    _, system, ammo = _ship_with_ammo(max_torps=20, available=18)
    # Room for 2 of the 9 requested.
    assert system.LoadAmmoType(0, 9) == 7
    assert ammo.GetAvailable() == 20


def test_load_ammo_type_absent_slot_loads_nothing_and_keeps_it_all():
    """No such slot ⇒ nothing could be loaded, so every round is leftover.
    Returning 0 here would silently DELETE the starbase's stock."""
    _, system, _ = _ship_with_ammo(max_torps=20, available=0)
    assert system.LoadAmmoType(7, 12) == 12


def test_starbase_reload_conserves_torpedoes():
    """The reported crash: Actions.ShipScriptActions.ReloadShip raised
    'TypeError: unsupported operand type(s) for +: NoneType and int' at line 395
    during the starbase dock sequence, because LoadAmmoType returned None.

    Runs the REAL SDK action. Ship has 5 of a max-20 type; the starbase holds
    100. ReloadShip may hand over at most iMaxTorps=20, of which 15 fit, so the
    starbase should end up with (100-20) + 5 = 85 and the ship full at 20 —
    105 torpedoes before, 105 after."""
    import Actions.ShipScriptActions
    _reset_utopia()
    ship, system, ammo = _ship_with_ammo(max_torps=20, available=5)
    App.g_kUtopiaModule.SetCurrentStarbaseTorpedoLoad(0, 100)
    total_before = ammo.GetAvailable() + App.g_kUtopiaModule.GetCurrentStarbaseTorpedoLoad(0)

    Actions.ShipScriptActions.ReloadShip(None, ship.GetObjID())

    assert ammo.GetAvailable() == 20, "ship was not reloaded to capacity"
    assert App.g_kUtopiaModule.GetCurrentStarbaseTorpedoLoad(0) == 85
    total_after = ammo.GetAvailable() + App.g_kUtopiaModule.GetCurrentStarbaseTorpedoLoad(0)
    assert total_after == total_before, (
        f"torpedoes were created or destroyed: {total_before} -> {total_after}")


def test_methods_not_stubs():
    # Regression: harness saw _NamedStub calls because these fell through
    # _UtopiaModule.__getattr__. Confirm they're real bound methods now.
    import App as _App
    assert not isinstance(_App.g_kUtopiaModule.SetMaxTorpedoLoad, _App._NamedStub)
    assert not isinstance(_App.g_kUtopiaModule.GetMaxTorpedoLoad, _App._NamedStub)
    assert not isinstance(
        _App.g_kUtopiaModule.SetCurrentStarbaseTorpedoLoad, _App._NamedStub
    )
    assert not isinstance(
        _App.g_kUtopiaModule.GetCurrentStarbaseTorpedoLoad, _App._NamedStub
    )
