"""ET_AI_DONE announces a ship AI's end (cleared, replaced, or completed).

BC fires this when a ship's AI is destroyed/replaced or finishes; listeners
key on GetInt() == the ended AI's GetID() with the ship as destination
(Conditions/ConditionPlayerOrbitting.OrbitDone — the "leaving orbit" helm
line trigger — and Bridge/HelmCharacterHandlers.AIDone).
"""
import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ai_driver import tick_all_ai
from engine.appc.ships import ShipClass


class _Capture:
    def __init__(self):
        self.events = []

    def OnDone(self, event):
        self.events.append(event)


def _capture_ai_done():
    cap = _Capture()
    wrapper = App.TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(cap)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_AI_DONE, wrapper, "OnDone")
    return cap


def _teardown():
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    App.g_kSetManager._sets.clear()


def test_clear_ai_fires_ai_done_with_id_and_ship_destination():
    try:
        cap = _capture_ai_done()
        ship = ShipClass()
        ai = PlainAI_Create(ship, "Orders")
        ship.SetAI(ai)
        assert cap.events == []          # installing over None: nothing ended

        ship.ClearAI()
        assert len(cap.events) == 1
        evt = cap.events[0]
        assert evt.GetInt() == ai.GetID()
        assert evt.GetDestination() is ship
    finally:
        _teardown()


def test_set_ai_over_existing_fires_ai_done_for_old_tree():
    try:
        cap = _capture_ai_done()
        ship = ShipClass()
        old = PlainAI_Create(ship, "Orbit")
        ship.SetAI(old)
        new = PlainAI_Create(ship, "Stay")
        ship.SetAI(new)                  # All Stop replacing Orbit
        assert [e.GetInt() for e in cap.events] == [old.GetID()]
    finally:
        _teardown()


def test_root_tree_completion_fires_ai_done_once():
    try:
        cap = _capture_ai_done()
        pSet = App.SetClass_Create(); pSet.SetName("S")
        App.g_kSetManager._sets["S"] = pSet
        ship = ShipClass()
        pSet.AddObjectToSet(ship, "Ship")
        ai = PlainAI_Create(ship, "OneShot")
        inst = ai.GetScriptInstance()    # data-bag fallback
        inst.Update = lambda: ArtificialIntelligence.US_DONE
        ship.SetAI(ai)

        tick_all_ai(0.0)
        tick_all_ai(1.0)                 # DONE latched — must not re-fire
        assert [e.GetInt() for e in cap.events] == [ai.GetID()]
    finally:
        _teardown()


def test_dummy_ai_without_get_id_is_skipped():
    try:
        cap = _capture_ai_done()
        ship = ShipClass()
        ship.SetAI(object())             # bare test double, no GetID
        ship.ClearAI()
        assert cap.events == []
    finally:
        _teardown()
