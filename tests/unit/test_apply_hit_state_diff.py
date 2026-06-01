"""_subsystem_state_flags + _diff_state.

Worst-new-flag priority: destroyed > disabled > damaged > None.
A flag transitioning False→True counts; True→True does not.
"""
import pytest

from engine.appc.combat import _subsystem_state_flags, _diff_state


class _Sub:
    """Configurable subsystem stub."""
    def __init__(self, damaged=False, disabled=False, destroyed=False):
        self._d = damaged
        self._x = disabled
        self._z = destroyed
    def IsDamaged(self):   return self._d
    def IsDisabled(self):  return self._x
    def IsDestroyed(self): return self._z


def test_flags_reads_all_three_methods():
    sub = _Sub(damaged=True, disabled=False, destroyed=True)
    assert _subsystem_state_flags(sub) == (True, False, True)


def test_flags_missing_methods_default_false():
    class Bare: pass
    assert _subsystem_state_flags(Bare()) == (False, False, False)


@pytest.mark.parametrize(
    "before,after,expected",
    [
        # No change.
        ((False, False, False), (False, False, False), None),
        ((True,  False, False), (True,  False, False), None),
        # Healthy → damaged.
        ((False, False, False), (True,  False, False), "damaged"),
        # Damaged → disabled (damaged stays True).
        ((True,  False, False), (True,  True,  False), "disabled"),
        # Disabled → destroyed.
        ((True,  True,  False), (True,  True,  True),  "destroyed"),
        # Multiple flags flipping at once — pick the worst NEW one.
        ((False, False, False), (True,  True,  False), "disabled"),
        ((False, False, False), (True,  True,  True),  "destroyed"),
        # Pre-existing damaged, jump straight to destroyed in one tick.
        ((True,  False, False), (True,  True,  True),  "destroyed"),
        # Already destroyed, no further transition possible.
        ((True,  True,  True),  (True,  True,  True),  None),
    ],
)
def test_diff_state_priority(before, after, expected):
    assert _diff_state(before, after) == expected
