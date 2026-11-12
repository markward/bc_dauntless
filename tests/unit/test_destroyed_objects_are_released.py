"""What BC deletes stops being held by the engine.

The strong id registry (engine/core/ids.py) turned every discarded TGObject
into a permanent one. These pin each release that the Quick Battle leak
needed; tests/integration/test_quickbattle_end_frees_battle.py checks the
whole of it.
"""
import gc
import weakref

import App
from engine.appc.events import (
    TGEvent_Create, TGEventManager, TGPythonInstanceWrapper,
)
from engine.core import ids


def test_a_weak_entry_leaves_the_registry_with_its_object():
    evt = TGEvent_Create()
    obj_id = evt.GetObjID()
    assert ids.get_object_by_id(obj_id) is evt
    del evt
    gc.collect()
    assert obj_id not in ids._weak_registry
    assert obj_id not in ids._registry


def test_an_event_is_released_once_dispatched_but_survives_its_holder():
    mgr = TGEventManager()
    evt = TGEvent_Create()
    evt.SetEventType(42)
    ref = weakref.ref(evt)
    held = [evt]                        # a timer or a button keeps it
    mgr.AddEvent(evt)
    del evt
    assert ids.get_object_by_id(held[0].GetObjID()) is None
    assert ref() is held[0]             # still postable by its holder
    held.clear()
    gc.collect()
    assert ref() is None


def test_an_unposted_event_is_freed_with_its_last_reference():
    ref = weakref.ref(TGEvent_Create())
    gc.collect()
    assert ref() is None


def test_a_wrapper_is_not_kept_by_the_registry():
    ref = weakref.ref(TGPythonInstanceWrapper())
    gc.collect()
    assert ref() is None


def test_a_func_handler_filter_is_held_weakly():
    from engine.appc.events import TGEventHandlerObject

    class Target:
        pass

    mgr = TGEventManager()
    t = Target()
    ref = weakref.ref(t)
    mgr.AddBroadcastPythonFuncHandler(42, TGEventHandlerObject(), "x.y", t)
    del t
    gc.collect()
    assert ref() is None
    evt = TGEvent_Create()
    evt.SetEventType(42)
    mgr.AddEvent(evt)                   # the dead entry goes at dispatch
    assert mgr._broadcast_handlers[42] == []


def test_a_condition_does_not_keep_its_handler_alive():
    from engine.appc.ai import TGCondition

    class Handler:
        def ConditionChanged(self, cond):
            pass

    cond = TGCondition()
    h = Handler()
    ref = weakref.ref(h)
    cond.AddHandler(h)
    assert cond._live_handlers() == [h]
    del h
    gc.collect()
    assert ref() is None
    assert cond._live_handlers() == []


def test_a_deleted_ships_ai_is_torn_down_at_once():
    """BC deletes the AI tree with the ship: from that instant its
    conditions handle nothing (an AI timer to a dead condition's wrapper
    would otherwise depend on when the GC runs). The instance is released,
    its wrapper stops dispatching and its broadcast handlers go."""
    from engine.appc import ai_teardown
    from engine.appc.ai import ConditionalAI_Create, ConditionScript

    calls = []

    class Cond:
        def __init__(self):
            self.pEventHandler = TGPythonInstanceWrapper()
            self.pEventHandler.SetPyWrapper(self)
            App.g_kEventManager.AddBroadcastPythonMethodHandler(
                42, self.pEventHandler, "Hit")
            self.pEventHandler.AddPythonMethodHandlerForInstance(43, "Hit")

        def Hit(self, evt):
            calls.append(evt.GetEventType())

    class Ship:
        pass

    cs = ConditionScript()
    inst = Cond()
    cs._instance = inst
    wrapper = inst.pEventHandler
    iref = weakref.ref(inst)
    del inst
    node = ConditionalAI_Create(None, "x")
    node.AddCondition(cs)
    ship = Ship()
    ship._ai = node
    try:
        ai_teardown.tear_down(ship)
        assert ship._ai is None
        assert cs._instance is None
        assert iref() is None                  # freed now, not at GC time
        for et in (42, 43):
            evt = TGEvent_Create()
            evt.SetEventType(et)
            evt.SetDestination(wrapper)
            App.g_kEventManager.AddEvent(evt)
        assert calls == []
        assert not any(h[0] is wrapper
                       for h in App.g_kEventManager._method_handlers.get(42, ()))
    finally:
        App.g_kEventManager._method_handlers.pop(42, None)


def test_a_deleted_menu_child_is_freed_but_found_while_held():
    from engine.appc.characters import STMenu
    menu = STMenu("m")
    child = STMenu("c")
    menu.AddChild(child)
    cid = child.GetObjID()
    ref = weakref.ref(child)
    menu.DeleteChild(child)
    assert ids.get_object_by_id(cid) is child      # still held here
    del child
    gc.collect()
    assert ref() is None
    assert ids.get_object_by_id(cid) is None


def test_kill_children_frees_the_whole_subtree():
    from engine.appc.characters import STMenu
    menu = STMenu("m")
    sub = STMenu("sub")
    leaf = STMenu("leaf")
    sub.AddChild(leaf)
    menu.AddChild(sub)
    refs = [weakref.ref(sub), weakref.ref(leaf)]
    del sub, leaf
    menu.KillChildren()
    gc.collect()
    assert [r() for r in refs] == [None, None]


def test_remove_and_delete_takes_the_check_out_of_its_manager():
    """SDK ConditionInRange scraps its old sphere on every retarget; the
    entry used to stay in _proximity_checks for the rest of the mission."""
    from engine.appc.ai import ProximityCheck
    from engine.appc.planet import ProximityManager

    class _Set:
        pass

    pset = _Set()
    pm = ProximityManager(pset)
    pset._proximity_manager = pm
    check = ProximityCheck(0)
    pm.AddObject(check)
    assert any(c is check for c, _a in pm._proximity_checks)
    check.RemoveAndDelete()
    assert not any(c is check for c, _a in pm._proximity_checks)
    assert ids.get_object_by_id(check.GetObjID()) is None
