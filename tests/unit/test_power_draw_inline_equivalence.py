"""PowerSubsystem._draw: the inlined form against the original three-method one.

_draw used to call _draw_main / _draw_backup; the hot path now inlines their
arithmetic (~19,000 saved calls a frame at 100 ships). An inline is only worth
having if it is EXACTLY the thing it replaced, so this keeps the original as a
reference implementation and diffs the two across the whole input cross-product
-- return value AND all five pieces of mutated state.

It earns its place: the first version of the inline spelled the mode test as
`!= PSM_BACKUP_FIRST and != PSM_BACKUP_ONLY`, which silently re-routed the
fourth mode, PSM_DIRECT_MAIN, from backup-only to main-first. All 276 existing
power tests passed with that defect live. This one fails.
"""
import itertools
from engine.appc.subsystems import (PowerSubsystem, PSM_MAIN_FIRST,
                                    PSM_BACKUP_FIRST, PSM_BACKUP_ONLY,
                                    PSM_DIRECT_MAIN)


def _orig_draw(p, amount, mode):
    if amount <= 0.0:
        return 0.0
    got = 0.0
    if mode == PSM_MAIN_FIRST:
        got += p._draw_main(amount)
        got += p._draw_backup(amount - got)
    elif mode == PSM_BACKUP_FIRST:
        got += p._draw_backup(amount)
        got += p._draw_main(amount - got)
    else:
        got += p._draw_backup(amount)
    p._power_dispensed += got
    return got


def _mk(mc, mb, bc, bb):
    p = PowerSubsystem("P")
    p._main_conduit_current = mc
    p._main_battery_power = mb
    p._backup_conduit_current = bc
    p._backup_battery_power = bb
    p._power_dispensed = 0.0
    return p


def test_inlined_draw_matches_the_original_for_every_mode():
    vals = [0.0, 1.0, 5.0, 12.5]
    modes = [PSM_MAIN_FIRST, PSM_BACKUP_FIRST, PSM_BACKUP_ONLY, PSM_DIRECT_MAIN]
    n = 0
    for mc, mb, bc, bb, amt, mode in itertools.product(
            vals, vals, vals, vals, [-1.0, 0.0, 0.5, 3.0, 20.0], modes):
        a = _mk(mc, mb, bc, bb)
        b = _mk(mc, mb, bc, bb)
        ga = a._draw(amt, mode)
        gb = _orig_draw(b, amt, mode)
        state_a = (a._main_conduit_current, a._main_battery_power,
                   a._backup_conduit_current, a._backup_battery_power,
                   a._power_dispensed)
        state_b = (b._main_conduit_current, b._main_battery_power,
                   b._backup_conduit_current, b._backup_battery_power,
                   b._power_dispensed)
        assert ga == gb, (mc, mb, bc, bb, amt, mode, ga, gb)
        assert state_a == state_b, (mc, mb, bc, bb, amt, mode, state_a, state_b)
        n += 1
    print("compared", n, "cases")
    assert n == 5120, n


# ── _pump_consumers: the _power_wanted inline vs a real getter override ──────
#
# _pump_consumers sums `consumer._power_wanted` rather than calling
# GetPowerWanted(), on the reasoning that the getter is a bare
# `return self._power_wanted` that _update_power wrote a line earlier. That is
# true of PoweredSubsystem -- and NOT of PowerSubsystem, whose GetPowerWanted
# returns _power_wanted_total, a different field entirely. PowerSubsystem
# derives from ShipSubsystem, not PoweredSubsystem, so ships.AddPoweredConsumer
# can never register one and the inline is safe TODAY. The hazard is that it
# turns "a consumer that overrides the getter" from a working case into a
# silently wrong total, with nothing in the code saying so.

from engine.appc.subsystems import PoweredSubsystem, PowerSubsystem


class _OverridingConsumer(PoweredSubsystem):
    """A consumer whose published demand is NOT its own _power_wanted -- the
    shape PowerSubsystem already has."""

    def __init__(self, name=""):
        super().__init__(name)
        self._declared = 0.0

    def GetPowerWanted(self):
        return self._declared

    def _update_power(self, dt, source):
        self._power_wanted = 999.0      # the raw field: deliberately wrong
        self._declared = 7.0            # what the getter publishes


class _Ship:
    def __init__(self, consumers):
        self._powered_consumers = list(consumers)


def test_pump_consumers_honours_a_getter_override():
    p = PowerSubsystem("P")
    c = _OverridingConsumer("C")
    p.GetParentShip = lambda: _Ship([c])

    p._pump_consumers(1.0 / 60.0)

    assert p.GetPowerWanted() == 7.0


def test_pump_consumers_still_uses_the_fast_field_for_plain_consumers():
    """The guard must not cost the common case its inline: a stock
    PoweredSubsystem does not define GetPowerWanted, so the field is read
    directly and the total still matches."""
    p = PowerSubsystem("P")
    a = PoweredSubsystem("A")
    b = PoweredSubsystem("B")
    a.SetNormalPowerPerSecond(100.0); a.TurnOn()
    b.SetNormalPowerPerSecond(50.0);  b.TurnOn()
    p.GetParentShip = lambda: _Ship([a, b])

    p._pump_consumers(1.0 / 60.0)

    assert p.GetPowerWanted() == a._power_wanted + b._power_wanted
    assert p.GetPowerWanted() > 0.0
