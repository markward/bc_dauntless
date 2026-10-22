"""Spec 2026-10-22 warp-in §6.7: which Incoming line the tactical officer says."""
import pytest

from engine.quickbattle import late_arrivals as la


@pytest.mark.parametrize("n,already,key", [
    (0, False, None), (0, True, None),
    (1, True, "Incoming6"), (4, True, "Incoming6"),
    (1, False, "Incoming1"), (2, False, "Incoming2"),
    (3, False, "Incoming3"), (4, False, "Incoming4"),
    (5, False, "Incoming5"), (9, False, "Incoming5"),
])
def test_enemy_callout_key(n, already, key):
    assert la.enemy_callout_key(n, already) == key


def test_other_key():
    assert la.OTHER_CALLOUT_KEY == "gs025"
