"""CPU budget for sub-project 3's beyond-range branch (spec: Performance).

Measures can_detect for out-of-range KNOWN contacts (the new branch, worst
case: set compare + power read + IsObjectKnown + jam scan over 3 nebulae)
against in-range contacts (the old path) with time.process_time, as
test_sensor_occlusion_bench.py does -- wall clock is too noisy on a shared
machine. Budget: the new branch costs at most 3x the in-range call."""
import time

from engine.appc import contact_index
from engine.appc import sensor_detection as sd
from tests.unit.test_sensor_reach import _observer_in_set, _ship_at


class _FarNeb:
    def IsObjectInNebula(self, obj):
        return 0


def _per_call(obs, ships, reps):
    t0 = time.process_time()
    for _ in range(reps):
        for s in ships:
            sd.can_detect(obs, s)
    return (time.process_time() - t0) / (reps * len(ships))


def test_beyond_range_branch_stays_within_budget(monkeypatch):
    monkeypatch.setattr(contact_index, "nebulae_in",
                        lambda pSet: (_FarNeb(), _FarNeb(), _FarNeb()))
    s, obs, sensors = _observer_in_set(2000.0)
    near = [_ship_at(s, "n%d" % i, 100.0 + i) for i in range(40)]
    far = [_ship_at(s, "f%d" % i, 5000.0 + i) for i in range(40)]
    for ship in far:
        sensors.AddKnownObject(ship)
    assert all(sd.can_detect(obs, x) for x in far)
    _per_call(obs, near + far, 20)                    # warm caches
    in_range = min(_per_call(obs, near, 200) for _ in range(3))
    beyond = min(_per_call(obs, far, 200) for _ in range(3))
    assert beyond <= 3.0 * in_range, (beyond, in_range)
