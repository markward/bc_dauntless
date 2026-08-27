"""Due-time tree walking: a ship's AI tree is skipped while nothing is due.

Measured at 100 ships: 100 trees walked per tick, 87% executing nothing. A tree
now records the earliest _next_update_time it saw while being walked and is not
walked again until then, capped at AI_MAX_SLEEP_TICKS.

What these tests protect is the SCHEDULING CONTRACT, not the speed:

  - a node that is due must still run on the tick it is due
  - a tree containing an every-tick node must never sleep
  - the cap must actually cap, because a due time is only trustworthy for the
    nodes the walk reached (an inactive branch's conditions are silent by
    design), and the cap is what bounds that blindness
  - the escape hatch must restore exact per-tick walking

A blanket every-N-ticks stride was tried first and rejected: it was faster but
delayed nodes that WERE due, which measurably changed combat. The last test
here is the shape of that regression.
"""
import pytest

from engine.appc import ai_driver
from engine.appc.ai_driver import tick_all_ai, US_ACTIVE


class _Ship:
    def __init__(self, name, ai):
        self._name = name
        self._ai = ai

    def GetName(self):
        return self._name

    def GetAI(self):
        return self._ai

    def IsDying(self):
        return False

    def IsDead(self):
        return False


class _Node:
    """AI node with an explicit cadence, counting the ticks it is WALKED."""
    _status = US_ACTIVE
    _has_focus = False

    def __init__(self, interval):
        self._interval = interval
        self._next_update_time = 0.0
        self._contained_ai = None
        self.walks = 0
        self.runs = 0

    def GetShip(self):
        return self._ship

    def IsInterruptable(self):
        return True

    def SetActive(self, *a):
        pass

    def SetInactive(self, *a):
        pass


def _handler(ai, game_time):
    """Stands in for _tick_plain: reports its due time, runs only when due."""
    ai.walks += 1
    ai_driver._note_due(ai._next_update_time)
    if game_time < ai._next_update_time:
        return US_ACTIVE
    ai.runs += 1
    ai._next_update_time = game_time + ai._interval
    ai_driver._note_due(ai._next_update_time)
    return US_ACTIVE


@pytest.fixture
def scene(monkeypatch):
    """One ship, one node, driven through the real tick_all_ai."""
    made = {}

    def build(interval, max_sleep=4):
        node = _Node(interval)
        ship = _Ship("S", node)
        node._ship = ship
        monkeypatch.setattr(ai_driver, "AI_MAX_SLEEP_TICKS", max_sleep)
        ai_driver._DISPATCH_BY_TYPE[_Node] = _handler
        monkeypatch.setattr(ai_driver, "iter_ships", lambda: [ship],
                            raising=False)
        import engine.appc.ship_iter as ship_iter
        monkeypatch.setattr(ship_iter, "iter_ships", lambda: [ship])
        made["node"] = node
        made["ship"] = ship
        return node, ship

    yield build
    ai_driver._DISPATCH_BY_TYPE.pop(_Node, None)


def _run(ticks, dt=1.0 / 60.0, start=0.0):
    t = start
    for _ in range(ticks):
        t += dt
        tick_all_ai(game_time=t)
    return t


def test_an_every_tick_node_is_never_slept_through(scene):
    """interval 0.0 means due every tick. Such a tree must be walked every
    tick -- this is the PlainAI steering case the blanket stride broke."""
    node, _ = scene(interval=0.0)
    _run(30)
    assert node.walks == 30, "an every-tick node was slept through"
    assert node.runs == 30


def test_a_long_cadence_node_sleeps_but_only_to_the_cap(scene):
    """A 10-second cadence would allow a 600-tick sleep; the cap holds it to 4
    so an unnoticed condition change cannot go unseen for ten seconds."""
    node, _ = scene(interval=10.0, max_sleep=4)
    _run(60)
    # 60 ticks, walked at most every 4th -> ~15 walks, and certainly not 60.
    assert node.walks <= 16, "the cap did not cap: %d walks" % node.walks
    assert node.walks >= 12, "slept far past the cap: %d walks" % node.walks
    assert node.runs == 1, "a 10 s cadence node ran %d times in 1 s" % node.runs


def test_a_due_node_still_runs_on_the_tick_it_is_due(scene):
    """The contract that matters: sleeping must not DELAY anything.

    A 0.1 s cadence is 6 ticks, longer than the 4-tick cap, so the tree sleeps
    between runs -- and must still fire on schedule."""
    node, _ = scene(interval=0.1, max_sleep=4)
    _run(60)                      # one simulated second
    assert node.runs == 10, (
        "a 0.1 s cadence node ran %d times in 1 s -- sleeping delayed it"
        % node.runs)


def test_max_sleep_zero_restores_exact_per_tick_walking(scene):
    """The documented escape hatch. If this stops working, the 'set 0 to
    restore' comment is a claim nobody checked."""
    node, _ = scene(interval=10.0, max_sleep=0)
    _run(30)
    assert node.walks == 30


def test_a_ship_seen_for_the_first_time_is_walked_immediately(scene):
    """No stale due time may keep a freshly-spawned ship inert -- a mission
    dropping a wave mid-fight would show it as a visible hitch."""
    node, _ = scene(interval=10.0, max_sleep=4)
    _run(1)
    assert node.walks == 1
    assert node.runs == 1


def test_sleeping_actually_skips_walks(scene):
    """Guard on the saving itself. Every test above passes if sleeping never
    engages -- the correctness properties are all satisfied by walking always.
    This one fails if the optimisation quietly stops optimising."""
    node, _ = scene(interval=10.0, max_sleep=4)
    _run(40)
    assert node.walks < 40, "nothing slept; the scheduler is a no-op"
