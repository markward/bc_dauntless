"""impulse_fractions fuses two pod walks without fusing their semantics.

The online and output fractions use genuinely different predicates — online
counts pods that are not _is_offline (disabled OR destroyed OR parent out of
action), output weights by condition and treats only IsDisabled as forfeiting
the whole share. Fusing the iteration is safe; fusing the rules would not be.
These pin that the fused result equals calling both separately.
"""
import pytest

from engine.appc.subsystems import (impulse_fractions, impulse_online_fraction,
                                    impulse_output_fraction)


class _Pod:
    def __init__(self, disabled=False, destroyed=False, condition=1.0):
        self._disabled = disabled
        self._destroyed = destroyed
        self._condition = condition

    def IsDisabled(self):            return self._disabled
    def IsDestroyed(self):           return self._destroyed
    def GetConditionPercentage(self): return self._condition


class _Ship:
    """Minimal ship for _is_offline's _out_of_action check."""
    def __init__(self, dying=False, dead=False):
        self._dying, self._dead = dying, dead

    def IsDying(self):  return self._dying
    def IsDead(self):   return self._dead


class _IES:
    """Impulse engine set.

    MUST define GetParentShip. impulse_fractions gates its fused fast path on
    `implements(ies, "GetParentShip")`, and every real IES defines it
    (subsystems.py) -- so on a live ship the fast path is what runs. A double
    without it sends all cases down the fallback instead, and the branch that
    actually ships is never executed: deleting the IsDestroyed() test from it
    left the entire 5788-test suite green.

    _IESNoShip below keeps the fallback branch covered too, so the coverage
    is widened rather than merely moved.
    """
    def __init__(self, pods=(), on=True, disabled=False, destroyed=False,
                 power=1.0, ship=None):
        self._pods = list(pods)
        self._on = on
        self._disabled = disabled
        self._destroyed = destroyed
        self._power = power
        self._ship = ship if ship is not None else _Ship()

    def IsDisabled(self):                 return self._disabled
    def IsDestroyed(self):                return self._destroyed
    def IsOn(self):                       return self._on
    def GetNumChildSubsystems(self):      return len(self._pods)
    def GetChildSubsystem(self, i):       return self._pods[i]
    def GetPowerPercentageWanted(self):   return self._power
    def GetParentShip(self):              return self._ship


class _IESNoShip(_IES):
    """An IES that does NOT implement GetParentShip, so impulse_fractions
    takes the _is_offline fallback. Keeps that branch exercised now that the
    default double drives the fast path."""
    GetParentShip = None                  # implements() -> False

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)


def _both(ies):
    return impulse_online_fraction(ies), impulse_output_fraction(ies)


CASES = {
    "none":               None,
    "no pods":            _IES(),
    "all healthy":        _IES([_Pod(), _Pod(), _Pod()]),
    "one disabled":       _IES([_Pod(), _Pod(disabled=True), _Pod()]),
    "one destroyed":      _IES([_Pod(), _Pod(destroyed=True), _Pod()]),
    "partial damage":     _IES([_Pod(condition=0.5), _Pod(condition=0.25)]),
    "all disabled":       _IES([_Pod(disabled=True), _Pod(disabled=True)]),
    "master off":         _IES([_Pod(), _Pod()], on=False),
    "master disabled":    _IES([_Pod(), _Pod()], disabled=True),
    "master destroyed":   _IES([_Pod(), _Pod()], destroyed=True),
    "overdriven slider":  _IES([_Pod(), _Pod()], power=1.25),
    "starved slider":     _IES([_Pod(), _Pod()], power=0.0),
    "disabled+damaged":   _IES([_Pod(disabled=True), _Pod(condition=0.5)]),
}


@pytest.mark.parametrize("label", sorted(CASES))
def test_fused_matches_calling_both(label):
    ies = CASES[label]
    assert impulse_fractions(ies) == _both(ies), label


def test_the_two_predicates_really_do_differ():
    """A destroyed-but-not-disabled pod counts against ONLINE but not against
    OUTPUT. If this ever stops holding, fusing the walks would be fusing the
    rules and the parametrised equality above would be vacuous."""
    ies = _IES([_Pod(), _Pod(destroyed=True)])
    online, output = impulse_fractions(ies)
    assert online == pytest.approx(0.5)
    assert output == pytest.approx(1.0)


def test_a_switched_off_master_still_reports_online_pods():
    """Output is zero when the master is off, but the pods are still there —
    the short-circuit in the separate output call must not leak into online."""
    ies = _IES([_Pod(), _Pod()], on=False)
    online, output = impulse_fractions(ies)
    assert online == pytest.approx(1.0)
    assert output == 0.0
