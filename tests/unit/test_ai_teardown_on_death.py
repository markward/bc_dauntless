# tests/unit/test_ai_teardown_on_death.py
"""A dead ship's AI tree must get LostFocus and be detached (spec #15).
Nothing outside ships.py touched the AI slot, so a destroyed ship's Warp
leaf never ran LostFocus (which re-enables collisions) and its tree stayed
installed on a hulk."""
import pytest

import App
from engine.appc import ship_death
from engine.appc.ai import PlainAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


class _Leaf:
    def __init__(self): self.lost = 0
    def Update(self): return 0
    def GotFocus(self): pass
    def LostFocus(self): self.lost += 1


def test_marking_a_ship_dead_dispatches_lost_focus_and_detaches_the_tree():
    App.g_kSetManager._sets.clear(); ship_death.reset()
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass(); ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ship, "Doomed")
    leaf = _Leaf()
    plain = PlainAI_Create(ship, "Leaf"); plain._script_instance = leaf
    ship.SetAI(plain)
    tick_ai(plain, 0.0)                      # gains focus
    done_events = []
    w = App.TGPythonInstanceWrapper()
    class _Rec:
        def Done(self, evt): done_events.append(evt)
    w.SetPyWrapper(_Rec())
    App.g_kEventManager.AddBroadcastPythonMethodHandler(App.ET_AI_DONE, w, "Done", ship)

    ship_death._mark_dead(ship)

    assert leaf.lost == 1, "LostFocus never reached the leaf"
    assert ship.GetAI() is None
    assert done_events == [], "ET_AI_DONE must not be announced for a ship that died"
