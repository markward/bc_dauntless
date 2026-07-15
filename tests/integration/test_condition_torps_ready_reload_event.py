"""End-to-end proof that ET_TORPEDO_RELOAD reaches the REAL SDK
Conditions.ConditionTorpsReady, through the REAL production registration
path -- not a test double.

test_torpedo_reload_event.py registers its listener with
AddBroadcastPythonFuncHandler, which does NOT destination-filter. The real
SDK caller, Conditions/ConditionTorpsReady.py:140, registers with
AddBroadcastPythonMethodHandler(..., target=pTube) -- which DOES
destination-filter (engine/appc/events.py _dispatch). Nothing exercised
that path end-to-end before this test.

This guards C-1: engine/appc/objects.py ObjectClass_GetObject used to
return None unconditionally whenever pSet is None
(``if pSet is None or not hasattr(pSet, "GetObject"): return None``).
ConditionTorpsReady.SetupInitialState calls
``App.ObjectClass_GetObject(None, sObjectName)`` (ConditionTorpsReady.py:57)
-- so it ALWAYS got None, even though the ship was already registered in a
set (AI/Compound/FedAttack.py:242 constructs this condition for a ship
that's already in the world). With iObjectID staying App.NULL_ID,
SetupEventHandlers took the "object doesn't exist yet" branch and
registered only an ET_ENTERED_SET listener -- AddHandlersToTube was NEVER
called, so no tube's ET_TORPEDO_RELOAD/ET_TORPEDO_FIRED ever reached the
condition. Its sibling, ShipClass_GetObject (engine/appc/ships.py), already
had the correct fallback to SetClass_GetNull() -- ObjectClass_GetObject was
the odd one out.

RED (pre-fix): the condition's status stays 0 forever, no matter how many
tubes reload -- because the reload broadcast never reaches a handler that
was never registered.
GREEN (post-fix): the condition's status flips to 1 once a tube reloads.
"""
import importlib
import sys

import pytest

import App
from engine import host_loop
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create


@pytest.fixture
def galaxy_in_set():
    """A real hardpoint Galaxy (6 torpedo tubes, MaxReady=1,
    ImmediateDelay=0.25, ReloadDelay=40.0 -- sdk/Build/scripts/ships/
    Hardpoints/galaxy.py), registered in a real SetClass under a name, the
    way loadspacehelper.CreateShip does before a mission's AI ever
    constructs a ConditionTorpsReady for it.
    """
    App.g_kTimerManager._time = 0.0

    ship = ShipClass_Create("Galaxy")
    ship.SetName("Dauntless")
    App.g_kModelPropertyManager.ClearLocalTemplates()
    mod_name = "ships.Hardpoints.galaxy"
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    mod = sys.modules[mod_name]
    mod.LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()
    ship.GetTorpedoSystem().TurnOn()

    test_set = SetClass()
    App.g_kSetManager.AddSet(test_set, "test_set")
    test_set.AddObjectToSet(ship, "Dauntless")

    yield ship

    App.g_kSetManager.DeleteSet("test_set")
    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]
    App.g_kTimerManager._time = 0.0


def test_condition_torps_ready_flips_true_on_real_reload_broadcast(galaxy_in_set):
    ship = galaxy_in_set
    torps = ship.GetTorpedoSystem()
    assert torps.GetNumWeapons() == 6, "Galaxy should have 6 torpedo tubes"

    # Drain every tube so the ship has ZERO rounds ready anywhere -- the
    # condition's initial-state scan (SetStateFromTorpCount, run only if
    # C-1's fallback lets SetupInitialState find the ship) must read False.
    # Task 7's ship-wide 0.5s fire stagger means only one tube can launch per
    # instant, so each drain shot advances the clock past the gate first.
    App.g_kTimerManager._time = 100.0
    for i in range(torps.GetNumWeapons()):
        torps.GetWeapon(i).Fire()
        App.g_kTimerManager._time += 0.6
    assert all(
        torps.GetWeapon(i).GetNumReady() == 0 for i in range(torps.GetNumWeapons())
    ), "setup bug: every tube must be drained before the condition is built"

    # Construct the REAL SDK condition, the way AI/Compound/FedAttack.py:242
    # does: App.ConditionScript_Create("Conditions.ConditionTorpsReady", ...).
    cond = App.ConditionScript_Create(
        "Conditions.ConditionTorpsReady", "ConditionTorpsReady", ship.GetName()
    )
    cond.SetActive()

    assert cond.GetStatus() == 0, (
        "no torpedoes ready anywhere -- the condition must start false"
    )

    # Advance the GAME clock (not wall time) past ReloadDelay and pump the
    # real per-frame weapon-reload driver -- host_loop._advance_weapons,
    # exactly what the render loop calls every frame.
    App.g_kTimerManager._time = 100.0 + 40.0
    host_loop._advance_weapons([ship], 1.0 / 60.0)

    assert any(
        torps.GetWeapon(i).GetNumReady() == 1 for i in range(torps.GetNumWeapons())
    ), "a tube must actually have reloaded for this assertion to mean anything"

    assert cond.GetStatus() == 1, (
        "ConditionTorpsReady never observed ET_TORPEDO_RELOAD through the "
        "real AddBroadcastPythonMethodHandler(..., target=pTube) path -- "
        "see C-1 (engine/appc/objects.py ObjectClass_GetObject pSet=None "
        "fallback to SetClass_GetNull())."
    )
