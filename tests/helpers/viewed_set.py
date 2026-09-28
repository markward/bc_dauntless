"""A viewed set for render-feed tests.

Every world-space render feed now carries only items in the VIEWED frame
(system-frames Plan 2 Task 5): an item in no set, or with nothing viewed, is
not in the scene. A test that is about a feed's shape rather than its frame
scoping puts its objects here -- a plain set made the explicit rendered set --
so the same-set invariant hands it exactly the raw positions it always saw.
"""
import pytest

VIEWED = "Viewed"


def viewed_set():
    """The plain set bound as the explicit rendered set (created on demand)."""
    import App
    from engine.appc.sets import SetClass_Create
    pSet = App.g_kSetManager._sets.get(VIEWED)
    if pSet is None:
        pSet = SetClass_Create()
        App.g_kSetManager.AddSet(pSet, VIEWED)
    App.g_kSetManager.MakeRenderedSet(VIEWED)
    return pSet


def place_in_viewed_set(obj):
    """Add `obj` to the viewed set under a unique name; returns `obj`."""
    viewed_set().AddObjectToSet(obj, "obj_%d" % id(obj))
    return obj


def release_viewed_set():
    import App
    App.g_kSetManager.ClearRenderedSet()
    App.g_kSetManager._sets.pop(VIEWED, None)


@pytest.fixture
def viewed():
    """Fixture form: a bound viewed set, released afterwards."""
    pSet = viewed_set()
    yield pSet
    release_viewed_set()
