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
