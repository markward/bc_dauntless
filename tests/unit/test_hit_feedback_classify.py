"""Severity classifier — pure function, table-driven.

Severity rule (spec §3.1):
- CRITICAL iff sub_transition is not None AND subsystem is not hull.
- SHIELD iff absorbed_shields > 0 AND nothing else absorbed anything.
- HULL otherwise.
"""
import pytest

from engine.appc.hit_feedback import Severity, classify


class _Sub:
    """Marker class for subsystem identity in the classifier."""
    pass


HULL = _Sub()
SENSORS = _Sub()
ENGINES = _Sub()
WEAPONS = _Sub()


@pytest.mark.parametrize(
    "absorbed_shields,absorbed_sub,absorbed_hull,sub_transition,subsystem,expected",
    [
        # (1) Shield-only absorb.
        (50.0, 0.0, 0.0, None, HULL, Severity.SHIELD),
        # (2) Shield + sub spillover.
        (30.0, 20.0, 0.0, None, SENSORS, Severity.HULL),
        # (3) Shield depleted, hull bleed.
        (30.0, 0.0, 20.0, None, HULL, Severity.HULL),
        # (4) Direct hull hit, no shields.
        (0.0, 0.0, 50.0, None, HULL, Severity.HULL),
        # (5) Sub flipped damaged.
        (0.0, 50.0, 0.0, "damaged", ENGINES, Severity.CRITICAL),
        # (6) Sub flipped disabled.
        (0.0, 100.0, 0.0, "disabled", WEAPONS, Severity.CRITICAL),
        # (7) Sub flipped destroyed.
        (0.0, 80.0, 0.0, "destroyed", SENSORS, Severity.CRITICAL),
        # (8) Hull "transition" is ignored — hull is excluded from CRITICAL.
        (0.0, 0.0, 999.0, "damaged", HULL, Severity.HULL),
        # (9) Subsystem == None edge case (no picked sub) → HULL.
        (0.0, 0.0, 50.0, None, None, Severity.HULL),
        # (10) Shield absorbed everything but subsystem is non-hull — still SHIELD.
        #      (Subsystem identity doesn't matter when nothing leaked past shields.)
        (100.0, 0.0, 0.0, None, SENSORS, Severity.SHIELD),
    ],
)
def test_classify_severity_table(absorbed_shields, absorbed_sub,
                                  absorbed_hull, sub_transition,
                                  subsystem, expected):
    assert classify(
        absorbed_shields=absorbed_shields,
        absorbed_subsystem=absorbed_sub,
        absorbed_hull=absorbed_hull,
        sub_transition=sub_transition,
        subsystem=subsystem,
        hull=HULL,
    ) == expected


def test_severity_enum_values():
    """Stable int values — used as a wire-side integer between Python and C++."""
    assert int(Severity.SHIELD) == 0
    assert int(Severity.HULL) == 1
    assert int(Severity.CRITICAL) == 2
