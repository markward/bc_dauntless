"""The per-tick ProximityCheck pass runs from a cached pair table.

A 64-ship fight carries 272 live (check, watched ship) pairs. Evaluating each
in Python cost ~1 ms a tick, and 94% of ticks fire nothing. The pass now keeps
the pairs packed between ticks, asks the transform store once which pairs
could fire, and re-runs only those through ProximityCheck._evaluate_one.

What it must preserve is the old pass, event for event: every set, every
registered check in order, every watched entry in order -- including what a
handler that runs mid-pass (AddEvent dispatches synchronously) changes for the
pairs after it. `_reference_pass` below IS that old pass.
"""
import random

import pytest

import App
from engine.appc import planet
from engine.appc.ai import ProximityCheck, ProximityCheck_Create, ProximityEvent
from engine.appc.math import TGPoint3
from engine.appc.objects import ObjectClass
from engine.appc.sets import SetClass_Create
from engine.appc.ships import ShipClass
from engine.appc.transform_store import get_store


class _OwnLocation(ObjectClass):
    """Answers GetWorldLocation itself, so the store cannot test it."""

    def __init__(self, xyz):
        super().__init__()
        self._own = list(xyz)

    def GetWorldLocation(self):
        return TGPoint3(*self._own)

    def nudge(self, d):
        self._own = [c + e for c, e in zip(self._own, d)]


def _reference_pass():
    for pSet in App.g_kSetManager._sets.values():
        pm = pSet.GetProximityManager() if hasattr(pSet, "GetProximityManager") else None
        if pm is None:
            continue
        for check, anchor in getattr(pm, "_proximity_checks", ()):
            check.Evaluate(anchor)


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(App.g_kSetManager, "_sets", {})
    log = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent",
                        lambda evt: _proximity(evt) and log.append(evt))
    return log


def _proximity(evt):
    """Only the proximity events: building a scene posts others."""
    return isinstance(evt, ProximityEvent)


def _move(obj, d):
    if isinstance(obj, _OwnLocation):
        obj.nudge(d)
    else:
        p = obj.GetWorldLocation()
        obj.SetTranslateXYZ(p.x + d[0], p.y + d[1], p.z + d[2])


class _Scene:
    """A seeded scene, rebuilt identically for each pass under test."""

    def __init__(self, seed):
        rng = self.rng = random.Random(seed)
        self.sets = []
        self.objs = []
        self.checks = []
        for si in range(2):
            pSet = SetClass_Create()
            App.g_kSetManager.AddSet(pSet, "S%d" % si)
            self.sets.append(pSet)
            for k in range(7):
                xyz = tuple(rng.uniform(-60, 60) for _ in range(3))
                if k == 6:
                    o = _OwnLocation(xyz)
                else:
                    o = ShipClass()
                    o.SetTranslateXYZ(*xyz)
                pSet.AddObjectToSet(o, "S%d.%d" % (si, k))
                self.objs.append(o)
        for _ in range(9):
            self.new_check()
        # One check whose anchor comes with its manager entry.
        c = ProximityCheck_Create(500)
        c.tag = "explicit"
        c.SetRadius(40.0)
        c.AddObjectToCheckList(self.objs[1], ProximityCheck.TT_INSIDE)
        self.sets[0].GetProximityManager().AddProximityCheck(c, self.objs[0])
        self.checks.append(c)

    def new_check(self):
        rng = self.rng
        pSet = rng.choice(self.sets)
        c = ProximityCheck_Create(400 + len(self.checks))
        c.tag = "c%d" % len(self.checks)
        c.SetRadius(rng.uniform(10.0, 60.0))
        if rng.random() < 0.2:
            c.SetTranslateXYZ(*(rng.uniform(-60, 60) for _ in range(3)))
            pSet.GetProximityManager().AddObject(c)
        else:
            anchor = rng.choice([o for o in self.objs
                                 if o.GetContainingSet() is pSet])
            pSet.GetProximityManager().AddObject(c)
            anchor.AttachObject(c)
        for _ in range(rng.randint(1, 4)):
            tt = rng.choice((0, 0, 1, 1, 5))
            c.AddObjectToCheckList(rng.choice(self.objs), tt)
        self.checks.append(c)
        return c

    def handle(self, evt):
        """A ConditionInRange-style re-arm, plus a random mid-pass change."""
        rng = self.rng
        check, obj = evt.GetProximityCheck(), evt.GetObject()
        tt = check.GetTriggerType(obj)
        line = (check.tag, obj.GetName(), tt)
        if tt in (0, 1):
            check.SetTriggerType(obj, 1 - tt)
        roll = rng.random()
        if roll < 0.15:
            _move(rng.choice(self.objs), [rng.uniform(-30, 30) for _ in range(3)])
        elif roll < 0.25:
            rng.choice(self.checks).AddObjectToCheckList(
                rng.choice(self.objs), rng.choice((0, 1)))
        elif roll < 0.32:
            c = rng.choice(self.checks)
            if c._check_objects:
                c.RemoveObjectFromCheckList(rng.choice(c._check_objects)[0])
        elif roll < 0.36:
            self.new_check()
        elif roll < 0.42:
            rng.choice(self.checks).SetRadius(rng.uniform(10.0, 60.0))
        elif roll < 0.45:
            rng.choice(self.checks).SetTriggerType(
                rng.choice(self.objs), rng.choice((0, 1)))
        elif roll < 0.47:
            rng.choice(self.objs).SetDeleteMe(1)
        return line

    def tick_moves(self):
        for o in self.objs:
            # Drift toward the origin so the scene stays crowded.
            p = (o.GetWorldLocation() if not isinstance(o, _OwnLocation)
                 else TGPoint3(*o._own))
            _move(o, [self.rng.uniform(-12, 12) - 0.1 * c
                      for c in (p.x, p.y, p.z)])


@pytest.mark.parametrize("seed", range(12))
def test_fires_exactly_what_the_old_pass_fired(world, monkeypatch, seed):
    logs = []
    for run_pass in (_reference_pass, planet.evaluate_proximity_checks):
        App.g_kSetManager._sets.clear()
        scene = _Scene(seed)
        lines = []
        monkeypatch.setattr(App.g_kEventManager, "AddEvent",
                            lambda evt: _proximity(evt)
                            and lines.append(scene.handle(evt)))
        for t in range(80):
            scene.tick_moves()
            lines.append(("tick", t))
            run_pass()
        logs.append(lines)
    fired = [line for line in logs[0] if line[0] != "tick"]
    assert len(fired) > 40          # the scene really does fire
    assert logs[1] == logs[0]


def _pair_scene():
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "Pairs")
    ships = []
    for k, x in enumerate((0.0, 100.0, 200.0, 300.0)):
        s = ShipClass()
        s.SetTranslateXYZ(x, 0.0, 0.0)
        pSet.AddObjectToSet(s, "ship%d" % k)
        ships.append(s)
    pm = pSet.GetProximityManager()

    def check(anchor, watched, radius, tt=ProximityCheck.TT_INSIDE):
        c = ProximityCheck_Create(600)
        c.SetRadius(radius)
        pm.AddObject(c)
        anchor.AttachObject(c)
        c.AddObjectToCheckList(watched, tt)
        return c
    return pSet, ships, check


def test_a_quiet_tick_makes_one_store_call_and_reads_no_location(world, monkeypatch):
    _pSet, ships, check = _pair_scene()
    for k in range(3):
        check(ships[k], ships[k + 1], 10.0)
    planet.evaluate_proximity_checks()
    cls = type(get_store())
    reads, reports = [], []
    real_get, real_report = cls.get_position, cls.proximity_report
    monkeypatch.setattr(cls, "get_position",
                        lambda self, *h: reads.append(h) or real_get(self, *h))
    monkeypatch.setattr(cls, "proximity_report",
                        lambda self, *a: reports.append(a) or real_report(self, *a))
    planet.evaluate_proximity_checks()
    planet.evaluate_proximity_checks()
    assert world == []
    assert reads == []
    assert len(reports) == 2


def test_a_handler_moving_a_later_ship_inside_fires_it_in_the_same_pass(world, monkeypatch):
    _pSet, ships, check = _pair_scene()
    first = check(ships[0], ships[1], 150.0)          # fires
    second = check(ships[2], ships[3], 10.0)          # quiet until moved
    planet.evaluate_proximity_checks()                # builds the table
    fired = []

    def add_event(evt):
        if not _proximity(evt):
            return
        fired.append(evt.GetProximityCheck())
        if evt.GetProximityCheck() is first:
            ships[3].SetTranslateXYZ(205.0, 0.0, 0.0)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", add_event)
    ships[3].SetTranslateXYZ(300.0, 0.0, 0.0)
    planet.evaluate_proximity_checks()
    assert fired == [first, second]


def test_a_handler_rearming_a_later_pair_takes_effect_in_the_same_pass(world, monkeypatch):
    _pSet, ships, check = _pair_scene()
    first = check(ships[0], ships[1], 150.0)
    second = check(ships[2], ships[3], 10.0, ProximityCheck.TT_INSIDE)
    planet.evaluate_proximity_checks()
    fired = []

    def add_event(evt):
        if not _proximity(evt):
            return
        fired.append(evt.GetProximityCheck())
        if evt.GetProximityCheck() is first:
            second.SetTriggerType(ships[3], ProximityCheck.TT_OUTSIDE)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", add_event)
    planet.evaluate_proximity_checks()
    assert fired == [first, second]


def test_a_check_a_handler_registers_is_evaluated_in_the_same_pass(world, monkeypatch):
    _pSet, ships, check = _pair_scene()
    first = check(ships[0], ships[1], 150.0)
    planet.evaluate_proximity_checks()
    fired, made = [], []

    def add_event(evt):
        if not _proximity(evt):
            return
        fired.append(evt.GetProximityCheck())
        if not made:
            made.append(check(ships[2], ships[3], 150.0))
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", add_event)
    planet.evaluate_proximity_checks()
    assert fired == [first, made[0]]


@pytest.mark.parametrize("change", [
    "add", "remove", "radius", "anchor", "trigger", "delete_set", "new_check"])
def test_changes_between_ticks_are_seen_on_the_next(world, monkeypatch, change):
    pSet, ships, check = _pair_scene()
    c = check(ships[0], ships[1], 50.0)               # 100 apart: quiet
    planet.evaluate_proximity_checks()
    assert world == []
    if change == "add":
        c.AddObjectToCheckList(ships[0], ProximityCheck.TT_INSIDE)
        expect = [ships[0]]
    elif change == "remove":
        c.SetTriggerType(ships[1], ProximityCheck.TT_OUTSIDE)
        planet.evaluate_proximity_checks()
        assert [e.GetObject() for e in world] == [ships[1]]
        del world[:]
        c.RemoveObjectFromCheckList(ships[1])
        expect = []
    elif change == "radius":
        c.SetRadius(150.0)
        expect = [ships[1]]
    elif change == "anchor":
        ships[2].SetTranslateXYZ(110.0, 0.0, 0.0)
        ships[2].AttachObject(c)
        expect = [ships[1]]
    elif change == "trigger":
        c.SetTriggerType(ships[1], ProximityCheck.TT_OUTSIDE)
        expect = [ships[1]]
    elif change == "delete_set":
        c.SetRadius(150.0)
        App.g_kSetManager.DeleteSet("Pairs")
        expect = []
    elif change == "new_check":
        check(ships[1], ships[2], 150.0)
        expect = [ships[2]]
    planet.evaluate_proximity_checks()
    assert [e.GetObject() for e in world] == expect


def test_a_ship_listed_twice_fires_twice_by_its_first_entry(world):
    """_evaluate_one looks up an object's FIRST entry, so the old pass ran
    both entries as TT_INSIDE and fired twice."""
    _pSet, ships, check = _pair_scene()
    c = check(ships[0], ships[1], 150.0, ProximityCheck.TT_INSIDE)
    c.AddObjectToCheckList(ships[1], ProximityCheck.TT_OUTSIDE)
    planet.evaluate_proximity_checks()
    assert [e.GetObject() for e in world] == [ships[1], ships[1]]
