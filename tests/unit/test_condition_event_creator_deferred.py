"""ConditionEventCreator's event goes out at the tick boundary, after the code
that changed the condition, so its handlers read the status that code left."""
import App
from engine.appc import ai
from engine.core.loop import GameLoop


def test_a_passing_status_is_never_seen(monkeypatch):
    monkeypatch.setattr(ai, "_pending_condition_events", [])
    cond = App.TGCondition()
    creator = App.ConditionEventCreator()
    evt = App.TGEvent_Create()
    evt.SetEventType(App.Mission_GetNextEventType())
    creator.SetEvent(evt)
    creator.AddCondition(cond)
    seen = []
    real_add = App.g_kEventManager.AddEvent

    def add(e):
        if e is evt:
            seen.append(cond.GetStatus())
        else:
            real_add(e)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", add)
    cond.SetStatus(1)
    cond.SetStatus(0)
    cond.SetStatus(1)
    assert seen == []
    GameLoop().tick()
    assert seen == [1, 1, 1]


def test_the_effect_boundary_posts_them_too(monkeypatch):
    """A condition a damage delivery flips (a watcher crossing at the effect
    queue's boundary) has its event posted at that same boundary."""
    from engine.appc import effect_queue
    monkeypatch.setattr(ai, "_pending_condition_events", [])
    cond = App.TGCondition()
    creator = App.ConditionEventCreator()
    evt = App.TGEvent_Create()
    evt.SetEventType(App.Mission_GetNextEventType())
    creator.SetEvent(evt)
    creator.AddCondition(cond)
    seen = []
    real_add = App.g_kEventManager.AddEvent

    def add(e):
        if e is evt:
            seen.append(cond.GetStatus())
        else:
            real_add(e)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", add)
    cond.SetStatus(1)
    effect_queue.boundary()
    assert seen == [1]
