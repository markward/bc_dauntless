"""End-to-end: PlainAI/EvadeTorps now SEES an incoming torpedo.

This is the behaviour the ticket is about. Before the AIScriptAssist fix,
AIScriptAssist_GetIncomingTorpIDsInSet returned () unconditionally, so
EvadeTorps.UpdateTorpInfo short-circuited at `if not lIncomingTorpIDs` and
dTorpInfo stayed empty -- the ship never learned a torp was inbound and
never steered. With the fix the poll returns the real torp id, the AI
resolves it via Torpedo_GetObjectByID, and records its approach vector.

Not a full live pass: this drives the SDK AI body headlessly. In-game
verification is a Quick Battle -- fire torpedoes at an NPC and watch it
break off.
"""
import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem
from engine.appc import projectiles


def _reset():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    projectiles._active.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset()
    yield
    _reset()


def _build_ship():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass()
    ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    ship._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ship._impulse_engine_subsystem.SetMaxSpeed(120.0)
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    pSet.AddObjectToSet(ship, "Ours")
    return ship


def test_evade_torps_records_incoming_torpedo():
    ship = _build_ship()
    # A torpedo 100 GU dead ahead on +Y, closing at 50 GU/s.
    torp = projectiles.Torpedo()
    torp._position = TGPoint3(0, 100, 0)
    torp._velocity = TGPoint3(0, -50, 0)
    projectiles.register(torp)

    plain = PlainAI_Create(ship, "TestAI")
    plain.SetScriptModule("EvadeTorps")
    inst = plain.GetScriptInstance()

    # First Update runs UpdateTorpInfo (iUpdateNum starts at UPDATE_TORP_INFO).
    inst.Update()

    assert torp.GetObjID() in inst.dTorpInfo, (
        "EvadeTorps did not record the incoming torpedo -- the AIScriptAssist "
        "poll is dead again"
    )
