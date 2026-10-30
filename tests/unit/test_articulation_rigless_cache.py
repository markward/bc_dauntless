"""A ship with no rig is looked up once, then skipped until the snapshots change.

`_BY_LEAF` changes only in `snapshot_for_leaf` and `reset`, so a generation
counter bumped in exactly those two places makes the cached "no rig" exact.
"""
import App
import pytest

from engine.appc import articulated_part, articulation

LEAF = "riglesscachetest"


class _Ship:
    def __init__(self):
        self._articulation_leaf = LEAF

    def GetAlertLevel(self):
        return 0


@pytest.fixture(autouse=True)
def _clean():
    articulated_part.reset()
    yield
    articulated_part.reset()


@pytest.fixture
def lookups(monkeypatch):
    seen = []
    real = articulated_part.parts_for_leaf

    def spy(leaf):
        seen.append(leaf)
        return real(leaf)

    monkeypatch.setattr(articulated_part, "parts_for_leaf", spy)
    return seen


def test_an_unrigged_ship_looks_up_its_rig_once(lookups):
    ship = _Ship()
    articulation.tick_ship(ship, 0.1)
    articulation.tick_ship(ship, 0.1)
    assert len(lookups) == 1


def test_a_new_snapshot_for_any_leaf_is_seen(lookups):
    ship = _Ship()
    articulation.tick_ship(ship, 0.1)
    p = articulated_part.ArticulatedPartProperty_Create("left wing")
    p.SetStateAngle("cruise", 10.0)
    App.g_kModelPropertyManager.RegisterLocalTemplate(p)
    articulated_part.snapshot_for_leaf(LEAF)
    articulation.tick_ship(ship, 0.1)
    assert len(lookups) == 2
    assert hasattr(ship, "_articulation_poses")


def test_reset_is_seen():
    before = articulated_part.generation()
    articulated_part.reset()
    assert articulated_part.generation() != before
