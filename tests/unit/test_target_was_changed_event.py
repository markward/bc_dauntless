"""ET_TARGET_WAS_CHANGED — the constant must exist and ShipClass.SetTarget
must fire it on an actual change of the resolved target.

Real BC fires this from ShipClass::SetTarget (Appc-side). Consumers register
with AddPythonFuncHandlerForInstance ON THE SHIP whose target changed
(Camera.py:719 on the player, Bridge/HelmMenuHandlers.py:280 and
Bridge/ScienceMenuHandlers.py:133 on pShip) -- so the event's destination is
the ship, and this engine's synchronous TGEventHandlerObject.ProcessEvent
dispatch (destination-first, see engine/appc/events.py:466) is what those
consumers ride.

AI/Preprocessors.py's UseShipTarget instead uses a BROADCAST method handler
filtered by target=pShip (AddBroadcastPythonMethodHandler), which is the
other dispatch path TGEventManager.AddEvent drives -- see the end-to-end
test below.

NOTE: App.g_kEventManager.AddEvent dispatches synchronously (destination
first, then broadcast handlers -- engine/appc/events.py:466); there is no
DispatchAll()/drain step to call.
"""
import App
from engine.appc.ai import PreprocessingAI_Create, PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


def _kitted_ship(name):
    s = ShipClass()
    s._hull = HullSubsystem("H")
    s._hull.SetMaxCondition(1000.0)
    s.SetName(name)
    return s


import pytest


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_constant_is_a_real_distinct_int_not_a_named_stub():
    # The _NamedStub failure mode: App.__getattr__ hands back a FRESH stub
    # per access, hashed by id(), so two accesses would never be equal or
    # hash-equal. A real module-level int does not have that problem.
    a = App.ET_TARGET_WAS_CHANGED
    b = App.ET_TARGET_WAS_CHANGED
    assert isinstance(a, int)
    assert a == b
    assert hash(a) == hash(b)


def test_set_target_to_new_object_fires_exactly_one_event_destination_is_ship():
    ship = _kitted_ship("Ours")
    target = _kitted_ship("Target")

    received = []
    ship.AddPythonFuncHandlerForInstance(
        App.ET_TARGET_WAS_CHANGED, __name__ + "._record")
    globals()["_record_sink"] = received

    ship.SetTarget(target)

    assert len(received) == 1
    evt = received[0]
    assert evt.GetDestination() is ship


def _record(pShip, pEvent):
    globals()["_record_sink"].append(pEvent)


def test_setting_the_same_target_again_fires_nothing():
    ship = _kitted_ship("Ours")
    target = _kitted_ship("Target")
    ship.SetTarget(target)

    received = []
    ship.AddPythonFuncHandlerForInstance(
        App.ET_TARGET_WAS_CHANGED, __name__ + "._record2")
    globals()["_record2_sink"] = received

    ship.SetTarget(target)  # same object again

    assert received == []


def _record2(pShip, pEvent):
    globals()["_record2_sink"].append(pEvent)


def test_clearing_a_real_target_to_none_fires():
    ship = _kitted_ship("Ours")
    target = _kitted_ship("Target")
    ship.SetTarget(target)

    received = []
    ship.AddPythonFuncHandlerForInstance(
        App.ET_TARGET_WAS_CHANGED, __name__ + "._record3")
    globals()["_record3_sink"] = received

    ship.SetTarget(None)

    assert len(received) == 1
    assert ship.GetTarget() is None


def _record3(pShip, pEvent):
    globals()["_record3_sink"].append(pEvent)


def test_resolution_by_name_fires_only_when_the_resolved_object_differs():
    """SelectTarget.Update calls pOurShip.SetTarget(self.sCurrentTarget) with
    a STRING every tick, even when the underlying target hasn't changed.
    Firing must be gated on the resolved OBJECT changing, not the string."""
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = _kitted_ship("Ours")
    target = _kitted_ship("Target")
    pSet.AddObjectToSet(ship, "Ours")
    pSet.AddObjectToSet(target, "Target")

    received = []
    ship.AddPythonFuncHandlerForInstance(
        App.ET_TARGET_WAS_CHANGED, __name__ + "._record4")
    globals()["_record4_sink"] = received

    ship.SetTarget("Target")
    assert len(received) == 1
    assert ship.GetTarget() is target

    # Same name again -> same resolved object -> no new event.
    ship.SetTarget("Target")
    assert len(received) == 1


def _record4(pShip, pEvent):
    globals()["_record4_sink"].append(pEvent)


def test_use_ship_target_preprocessor_reacts_end_to_end():
    """Drive the REAL AI/Preprocessors.py UseShipTarget through
    PreprocessingAI.SetPreprocessingMethod (Task 9's CodeAISet call), then
    change the ship's target and assert it reacts per its own source
    (AI/Preprocessors.py:2322-2400):

    * CodeAISet registers a broadcast method handler for
      ET_TARGET_WAS_CHANGED filtered to this ship.
    * TargetChanged updates self.sTargetName to the new target's name.
    * It walks GetAllAIsInTree()[1:] and calls
      CallExternalFunction("SetTarget", sTargetName) on every leaf AI --
      here a PlainAI child that registered a SetTarget hook.
    """
    from AI.Preprocessors import UseShipTarget

    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = _kitted_ship("Ours")
    target = _kitted_ship("Target")
    pSet.AddObjectToSet(ours, "Ours")
    pSet.AddObjectToSet(target, "Target")

    inst = UseShipTarget()
    pp = PreprocessingAI_Create(ours, "UseShipTargetPP")
    pp.SetPreprocessingMethod(inst, "Update")  # runs CodeAISet()

    # A leaf AI underneath, registered for the SetTarget external function
    # -- mirrors test_select_target_dispatch's dispatch-to-leaf pattern.
    leaf = PlainAI_Create(ours, "Leaf")
    received = []

    class _Inst:
        def SetObj(self, name):
            received.append(name)

    leaf._script_instance = _Inst()
    leaf.RegisterExternalFunction("SetTarget", {"FunctionName": "SetObj"})
    pp.SetContainedAI(leaf)

    assert inst.sTargetName is None  # no target yet at bind time

    ours.SetTarget(target)

    assert inst.sTargetName == "Target"
    assert received == ["Target"]
