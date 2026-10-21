"""An ammo-type switch must drop the REAL SDK ConditionTorpsReady to 0.

Seen live (QuickBattle, three Akiras, 2026-10-20): FedAttack's FireScript
switches photon -> quantum ~0.2 s into a fight (Preprocessors.ChooseTorpType).
The switch unloads every tube -- BC-measured, the Sovereign's first quantum
salvo needs ~45 s (stbc-oracle `torpedo_sovereign_quantum_57`) -- but our
UnloadTorpedo posted no event, so the condition stayed latched 1 and the AI
flew forward and tail-first rear torpedo runs with six empty tubes for a
full 40 s reload. BC's unload posts ET_TORPEDO_FIRED (dest = the tube);
see tests/unit/test_torpedo_unload_event.py.

Goes through the real registration path, AddBroadcastPythonMethodHandler
with the tube as destination filter, like the reload-event sibling.
"""
import importlib
import sys

import pytest

import App
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create


@pytest.fixture
def akira_in_set():
    """A real hardpoint Akira: six tubes, MaxReady 1, ReloadDelay 40, and two
    ammo types (Photon slot 0, Quantum slot 1) -- the switch the AI makes."""
    App.g_kTimerManager._time = 0.0
    ship = ShipClass_Create("Akira")
    ship.SetName("Akira-1")
    App.g_kModelPropertyManager.ClearLocalTemplates()
    mod_name = "ships.Hardpoints.akira"
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    sys.modules[mod_name].LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()
    ship.GetTorpedoSystem().TurnOn()

    test_set = SetClass()
    App.g_kSetManager.AddSet(test_set, "test_set")
    test_set.AddObjectToSet(ship, "Akira-1")

    yield ship

    App.g_kSetManager.DeleteSet("test_set")
    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]
    App.g_kTimerManager._time = 0.0


@pytest.mark.parametrize("direction", [None, "back", "forward"])
def test_ammo_switch_drops_condition_torps_ready(akira_in_set, direction):
    ship = akira_in_set
    torps = ship.GetTorpedoSystem()
    assert torps.GetNumAmmoTypes() == 2
    assert all(torps.GetWeapon(i).GetNumReady() == 1
               for i in range(torps.GetNumWeapons())), "every tube starts loaded"

    # The same three conditions FedAttack builds: any tube, rear tubes only
    # (RearTorpsReadyRearShieldOk), forward tubes only.
    args = [ship.GetName()]
    if direction == "back":
        args.append(App.TGPoint3_GetModelBackward())
    elif direction == "forward":
        args.append(App.TGPoint3_GetModelForward())
    cond = App.ConditionScript_Create(
        "Conditions.ConditionTorpsReady", "ConditionTorpsReady", *args)
    cond.SetActive()
    assert cond.GetStatus() == 1

    App.g_kTimerManager._time = 0.23
    torps.SetAmmoType(1)                 # photon -> quantum, as ChooseTorpType does

    assert all(torps.GetWeapon(i).GetNumReady() == 0
               for i in range(torps.GetNumWeapons())), "the switch unloads every tube"
    assert cond.GetStatus() == 0, (
        "ConditionTorpsReady stayed latched ready after the ammo switch emptied "
        "every tube -- UnloadTorpedo must post ET_TORPEDO_FIRED like BC's "
        "TorpedoTube_UnloadTorpedo (0x0057D9A0)")
