"""Tests for the warp-core breach shockwave registry (engine/appc/shockwaves.py)."""
import pytest

from engine.appc import shockwaves
from engine.appc.math import TGPoint3


@pytest.fixture(autouse=True)
def _clean():
    shockwaves.reset()
    yield
    shockwaves.reset()


def test_spawn_then_render_data_has_one_entry_at_age_zero():
    shockwaves.spawn(TGPoint3(1.0, 2.0, 3.0), 4.0, 0.7)
    data = shockwaves.render_data()
    assert len(data) == 1
    assert data[0]["world_center"] == (1.0, 2.0, 3.0)
    assert data[0]["max_radius"] == 4.0
    assert data[0]["age"] == 0.0
    assert data[0]["lifetime"] == 0.7


def test_spawn_accepts_a_tuple_center():
    shockwaves.spawn((5.0, 6.0, 7.0), 4.0, 0.7)
    assert shockwaves.render_data()[0]["world_center"] == (5.0, 6.0, 7.0)


def test_advance_increments_age():
    shockwaves.spawn(TGPoint3(0, 0, 0), 4.0, 0.7)
    shockwaves.advance(0.1)
    assert shockwaves.render_data()[0]["age"] == pytest.approx(0.1)


def test_descriptor_dropped_when_age_reaches_lifetime():
    shockwaves.spawn(TGPoint3(0, 0, 0), 4.0, 0.7)
    shockwaves.advance(0.7)            # age >= lifetime -> pruned
    assert shockwaves.render_data() == []


def test_descriptor_survives_just_under_lifetime():
    shockwaves.spawn(TGPoint3(0, 0, 0), 4.0, 0.7)
    shockwaves.advance(0.69)
    assert len(shockwaves.render_data()) == 1


def test_reset_clears_registry():
    shockwaves.spawn(TGPoint3(0, 0, 0), 4.0, 0.7)
    shockwaves.reset()
    assert shockwaves.render_data() == []
