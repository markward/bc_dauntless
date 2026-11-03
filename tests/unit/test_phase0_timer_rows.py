"""Phase 0 timer rows: `prox.near`, `prox.line`, `ai.avoid`.

Native motion + proximity design §5.0 (runbook §5): the baseline needs the
proximity queries and the AvoidObstacles step timed on their own, nested under
whichever scope calls them, so phase 1's saving can be read off rows rather
than inferred from cProfile shares.
"""
import inspect

import pytest

import App
from engine.appc import ai_optimized
from engine.appc.math import TGPoint3
from engine.appc.planet import ProximityManager
from engine.appc.ships import ShipClass
from engine.core import frame_profiler as fp


@pytest.fixture(autouse=True)
def _profiler_on():
    fp.set_enabled(True, native=False)
    fp.reset()
    yield
    fp.set_enabled(False, native=False)
    fp.reset()


def _ship_at(x):
    s = ShipClass()
    s.SetTranslateXYZ(x, 0.0, 0.0)
    return s


def test_near_query_is_timed_as_prox_near_under_its_caller():
    pm = ProximityManager()
    near = _ship_at(10.0)
    pm.AddObject(near)
    fp.begin_frame()
    with fp.scope("ai.avoid"):
        result = pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0)
    fp.end_frame()
    assert near in result
    assert "prox.near" in fp.phases()
    assert fp.parents()["prox.near"] == "ai.avoid"


def test_line_query_is_timed_as_prox_line():
    pm = ProximityManager()
    on_leg = _ship_at(50.0)
    pm.AddObject(on_leg)
    fp.begin_frame()
    result = pm.GetLineIntersectObjects(TGPoint3(0, 0, 0), TGPoint3(100, 0, 0), 1.0)
    fp.end_frame()
    assert on_leg in result
    assert "prox.line" in fp.phases()


class _FakeAvoid:
    def Update(self, dEndTime):
        return App.PreprocessingAI.PS_DONE

    def GetNextUpdateTime(self):
        return 0.25


def test_avoidance_update_is_timed_as_ai_avoid_and_keeps_its_signature():
    cls = ai_optimized._phased_avoidance_class(_FakeAvoid)
    # ai_driver._tick_preprocessing probes the arity to pass dEndTime through.
    assert list(inspect.signature(cls.Update).parameters) == ["self", "dEndTime"]
    inst = cls.__new__(cls)
    fp.begin_frame()
    out = inst.Update(1.0)
    fp.end_frame()
    assert out == App.PreprocessingAI.PS_NORMAL      # still non-lethal
    assert "ai.avoid" in fp.phases()
