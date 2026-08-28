"""_dispatch_ai's single-slot out-of-action cache.

_out_of_action was re-asked on every node visit -- 772 visits/tick at 100
ships, ~7.7 per ship -- for an answer that is per SHIP per tick. It is now
cached in a single slot keyed on ship identity and reset at each root tick.

The saving is real and directly measured (0.632 -> 0.203 us/visit, ~5 ms per
frame), but the thing worth testing is the scoping: a ship that dies between
root ticks must be seen on the next one, and two ships in the same tick must
not share an answer.
"""
import pytest

from engine.appc import ai_driver
from engine.appc.ai_driver import tick_ai, US_DONE, US_ACTIVE


class _Ship:
    def __init__(self, dying=False):
        self._dying = dying

    def IsDying(self):
        return self._dying

    def IsDead(self):
        return False


class _Node:
    """Minimal AI node: reports which ship it belongs to and counts ticks."""
    _status = US_ACTIVE
    _has_focus = False

    def __init__(self, ship):
        self._ship = ship
        self.ticks = 0
        self._contained_ai = None
        self._next_update_time = 0.0

    def GetShip(self):
        return self._ship

    def IsInterruptable(self):
        return True

    # Root reconciliation calls these on every node it reached; a bare double
    # without them fails in _reconcile_active, not in the gate under test.
    def SetActive(self, *a):
        self._active = True

    def SetInactive(self, *a):
        self._active = False

    def GetContainedAI(self):
        return self._contained_ai


def _install_handler(monkeypatch):
    """Route _Node through a handler that just counts, so the test observes
    exactly whether the gate let the node run."""
    def handler(ai, game_time):
        ai.ticks += 1
        return US_ACTIVE

    ai_driver._DISPATCH_BY_TYPE[_Node] = handler
    yield
    ai_driver._DISPATCH_BY_TYPE.pop(_Node, None)


@pytest.fixture(autouse=True)
def _handler():
    yield from _install_handler(None)


def test_a_live_ship_ticks_and_a_dying_one_does_not():
    live = _Node(_Ship(dying=False))
    dead = _Node(_Ship(dying=True))
    assert tick_ai(live, 0.0) == US_ACTIVE
    assert live.ticks == 1
    assert tick_ai(dead, 0.0) == US_DONE
    assert dead.ticks == 0


def test_two_ships_in_the_same_tick_do_not_share_the_slot():
    """The slot holds one ship. Ship B must not inherit ship A's answer just
    because A was asked first -- which is what a slot reset only at frame
    boundaries would do."""
    ship_a = _Ship(dying=False)
    ship_b = _Ship(dying=True)
    a, b = _Node(ship_a), _Node(ship_b)

    for _ in range(5):
        assert tick_ai(a, 0.0) == US_ACTIVE
        assert tick_ai(b, 0.0) == US_DONE
    assert a.ticks == 5
    assert b.ticks == 0


def test_a_ship_that_dies_between_root_ticks_is_seen_on_the_next_one():
    """The reason the slot is reset per ROOT tick rather than held longer."""
    ship = _Ship(dying=False)
    node = _Node(ship)

    assert tick_ai(node, 0.0) == US_ACTIVE
    assert node.ticks == 1

    ship._dying = True
    assert tick_ai(node, 0.0) == US_DONE, (
        "the slot outlived its root tick and served a stale 'alive'")
    assert node.ticks == 1


def test_a_ship_that_revives_between_root_ticks_is_also_seen():
    """Symmetric case -- a cached True must not latch either. Reviving is not
    a real game transition, but a cache that cannot go both ways is a cache
    with a hidden direction, and that is worth knowing now rather than later.
    """
    ship = _Ship(dying=True)
    node = _Node(ship)

    assert tick_ai(node, 0.0) == US_DONE
    ship._dying = False
    assert tick_ai(node, 0.0) == US_ACTIVE
    assert node.ticks == 1


def test_the_slot_is_actually_being_used():
    """Guard against the saving quietly disappearing: within one root tick the
    ship must be asked ONCE however many nodes are visited.

    Without this, a later refactor that re-asks per node would keep every test
    above passing while restoring the full cost."""
    calls = []
    ship = _Ship(dying=False)

    class _CountingShip(_Ship):
        def IsDying(self):
            calls.append(1)
            return False

    node = _Node(_CountingShip(dying=False))
    child = _Node(node._ship)
    node._contained_ai = child

    def handler(ai, game_time):
        ai.ticks += 1
        if ai._contained_ai is not None:
            tick_ai(ai._contained_ai, game_time)
        return US_ACTIVE

    ai_driver._DISPATCH_BY_TYPE[_Node] = handler
    try:
        ai_driver._ooa_cache[0] = None
        tick_ai(node, 0.0)
    finally:
        ai_driver._DISPATCH_BY_TYPE.pop(_Node, None)

    assert node.ticks == 1 and child.ticks == 1, "the child never ran"
    assert len(calls) == 1, (
        "IsDying was asked %d times for one ship in one root tick; the slot "
        "is not being consulted" % len(calls))
