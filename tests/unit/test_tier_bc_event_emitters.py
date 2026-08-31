"""Engine emitters for the Tier B/C gaps in docs/engine/event-emitter-gaps.md.

Companion to test_tier_a_event_emitters.py. Tier A was "the post is the only
missing piece"; these needed a piece of state or an accessor built first, or
-- for ET_SET_TARGET -- needed the SDK read that says do not emit at all.

Events are captured by spying on App.g_kEventManager.AddEvent rather than by
registering SDK handlers: the contract is "the engine posts exactly this
event, exactly this often", and the negative cases (no post per tick while
held, no post on a no-op, no post at all for ET_SET_TARGET) are the whole
risk. AddEvent dispatches synchronously, so there is no drain step.
"""
import App
import pytest


@pytest.fixture
def posted(monkeypatch):
    """Every event the engine posts during the test, in order."""
    events = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", events.append)
    return events


def _of_type(posted, event_type):
    return [e for e in posted if e.GetEventType() == event_type]


# ── ET_SET_TARGET — deliberately NOT emitted ─────────────────────────────────
# Gap #2. Every SDK registration of ET_SET_TARGET (ScienceMenuHandlers.py:134,
# HelmMenuHandlers.py:281) is paired with an ET_TARGET_WAS_CHANGED
# registration on the same object to the same handler function. Nothing
# listens to ET_SET_TARGET alone; seven sites listen to ET_TARGET_WAS_CHANGED
# alone. So emitting it would add no reachable behaviour and would run
# TargetChanged twice per change on the Science and Helm menus.

def test_set_target_posts_only_target_was_changed(posted):
    """If you are here because you added an ET_SET_TARGET emitter: read the
    comment above. The SDK says the two events funnel to one handler, so a
    second post is a double-dispatch, not new behaviour."""
    from engine.appc.ships import ShipClass

    ship, target = ShipClass(), ShipClass()
    target.SetName("Target")
    ship.SetTarget(target)

    assert len(_of_type(posted, App.ET_TARGET_WAS_CHANGED)) == 1
    assert _of_type(posted, App.ET_SET_TARGET) == []


def test_the_two_target_events_are_distinct_constants():
    """The assertion above is only meaningful while the constants differ; if
    they ever collapsed to the same int it would pass vacuously."""
    assert App.ET_SET_TARGET != App.ET_TARGET_WAS_CHANGED
