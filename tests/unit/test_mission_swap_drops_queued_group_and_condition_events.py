"""A mission swap drops the group changes and condition events queued for the
next tick boundary (ObjectGroup._changed, ai._pending_condition_events).

Both queues are module/class state that outlives a mission: an edit or a
condition flip in the old mission's last tick would otherwise be posted into
the new mission at its first boundary, and the queue would keep the old
mission's groups and events alive. reset_mission_state is the one list the
swap and the per-test reset share, so the queues are cleared there."""
import App
from engine import host_loop
from engine.appc import ai
from engine.appc.objects import ObjectGroup


def _queue_a_group_change():
    group = App.ObjectGroup()
    group.SetEventFlag(ObjectGroup.GROUP_CHANGED)
    group.AddName("Swap Test Ship")
    assert any(g is group for g in ObjectGroup._changed)
    return group


def _queue_a_condition_event():
    creator = App.ConditionEventCreator()
    evt = App.TGEvent_Create()
    evt.SetEventType(App.Mission_GetNextEventType())
    creator.SetEvent(evt)
    cond = App.TGCondition()
    creator.AddCondition(cond)
    cond.SetStatus(1)
    assert any(e is evt for e in ai._pending_condition_events)
    return evt


def test_reset_mission_state_drops_a_queued_group_change():
    _queue_a_group_change()
    host_loop.reset_mission_state(None)
    assert ObjectGroup._changed == []


def test_reset_mission_state_drops_a_queued_condition_event():
    _queue_a_condition_event()
    host_loop.reset_mission_state(None)
    assert ai._pending_condition_events == []


def test_nothing_queued_before_the_swap_is_posted_after_it(monkeypatch):
    group = _queue_a_group_change()
    evt = _queue_a_condition_event()
    host_loop.reset_mission_state(None)
    posted = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", posted.append)
    ObjectGroup.deliver_changes()
    ai.deliver_condition_events()
    assert not any(e is evt for e in posted)
    assert not any(e.GetDestination() is group for e in posted)
