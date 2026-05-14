"""hit_vfx.spawn / update_ages / snapshot — transient impact sprites."""
import pytest
from engine.appc.math import TGPoint3
from engine.appc.hit_vfx import spawn, update_ages, snapshot, _active


@pytest.fixture(autouse=True)
def clear_registry():
    _active.clear()
    yield
    _active.clear()


def test_spawn_appends_with_age_zero():
    spawn(TGPoint3(1, 2, 3))
    snap = snapshot()
    assert len(snap) == 1
    assert snap[0]["age"] == 0.0
    assert snap[0]["position"].x == 1.0


def test_update_ages_increments_each():
    spawn(TGPoint3(0, 0, 0))
    update_ages(dt=0.1)
    snap = snapshot()
    assert snap[0]["age"] == pytest.approx(0.1)


def test_update_ages_prunes_expired():
    spawn(TGPoint3(0, 0, 0))
    update_ages(dt=0.6)  # > 0.5 lifetime
    assert snapshot() == []


def test_snapshot_returns_copy_not_internal_list():
    spawn(TGPoint3(0, 0, 0))
    snap = snapshot()
    snap.clear()
    assert len(snapshot()) == 1


def test_multiple_spawns_independent():
    spawn(TGPoint3(1, 0, 0))
    update_ages(dt=0.3)
    spawn(TGPoint3(2, 0, 0))
    update_ages(dt=0.3)
    # First aged to 0.6 (pruned); second to 0.3 (survives).
    snap = snapshot()
    assert len(snap) == 1
    assert snap[0]["position"].x == 2.0
    assert snap[0]["age"] == pytest.approx(0.3)
