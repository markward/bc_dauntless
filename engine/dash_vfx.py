"""dash_vfx — the player's Set Course / heading DASH's screen flash, dust
smear intensity and nacelle-glow clock (in-system-warp spec §4, Task 6).

Deliberately much simpler than `engine.warp_vfx.WarpVFX`, which drives the
cross-system tunnel's align/transit/exit phases: a dash never blacks out the
scene or streaks the tunnel's own `u_warp_streak` drift/prism mode (the real
system, drawn as normal, is the whole point). This module owns only the two
things a dash still needs a clock for:

* the 0..1 dash intensity that raises the dust pass's smear cap
  (`dust_pass.h:kDashSmearScale`) and drives the warp-nacelle glow envelope;
* the engage/drop-out screen-flash pulse, which is combined with the
  tunnel's own flash (`max`, never zeroing the other -- host_loop.py) since
  the two effects are mutually exclusive in play but share one renderer
  channel.

Driven from the two no-op hooks `engine.appc.dash._on_engage_fx` /
`_on_drop_out_fx` (ruling R3) and ticked once per frame from host_loop.py on
the same game clock the dash itself runs on
(``App.g_kUtopiaModule.GetGameTime()``).
"""
from __future__ import annotations

# Screen-flash pulse length after either engage() or drop_out() (spec §4:
# "the tunnel's existing screen flash on engage and drop-out").
_FLASH_DURATION_S = 0.4

# dash_intensity ramp length, both up (engage) and down (drop-out). Short
# enough to feel immediate, long enough that the dust smear doesn't pop.
_RAMP_DURATION_S = 0.5


class DashVFX:
    """One dash's flash/intensity clock. Not itself the dash state machine
    (`engine.appc.dash._Dash` owns that) -- just the VFX envelopes derived
    from when it engaged and dropped out."""

    def __init__(self):
        self._now = 0.0
        self._t_engage = None    # game time of the last engage(), or None
        self._t_drop = None      # game time of the last drop_out(), or None

    def engage(self, now: float) -> None:
        """Start the dash clock: the engage flash fires now, dash_intensity
        starts ramping 0 -> 1. Clears any previous drop-out, so a fresh dash
        never inherits the tail of the last one."""
        self._t_engage = float(now)
        self._t_drop = None
        self._now = float(now)

    def drop_out(self, now: float) -> None:
        """End the dash: the drop-out flash fires now, dash_intensity starts
        ramping back down to 0."""
        self._t_drop = float(now)
        self._now = float(now)

    def tick(self, now: float) -> None:
        """Advance the clock. Safe to call every frame regardless of whether
        a dash is in progress -- with no engage() yet, every query stays 0."""
        self._now = float(now)

    def dash_intensity(self) -> float:
        """0 -> 1 over `_RAMP_DURATION_S` after engage(); holds at 1 while
        dashing; 1 -> 0 over `_RAMP_DURATION_S` after drop_out()."""
        if self._t_engage is None:
            return 0.0
        if self._t_drop is not None:
            e = self._now - self._t_drop
            if e >= _RAMP_DURATION_S:
                return 0.0
            return max(0.0, 1.0 - e / _RAMP_DURATION_S)
        e = self._now - self._t_engage
        if e >= _RAMP_DURATION_S:
            return 1.0
        return max(0.0, e / _RAMP_DURATION_S)

    def flash_intensity(self) -> float:
        """1 -> 0 over `_FLASH_DURATION_S` after engage() and again after
        drop_out(); whichever fired more recently wins (they never overlap
        in practice -- a dash is always longer than the flash)."""
        best = 0.0
        for t in (self._t_engage, self._t_drop):
            if t is None:
                continue
            e = self._now - t
            if 0.0 <= e < _FLASH_DURATION_S:
                v = 1.0 - e / _FLASH_DURATION_S
                if v > best:
                    best = v
        return best

    def engine_glow(self):
        """(drive, burst): drive tracks `dash_intensity` (1 while dashing,
        spooling up/down with the same ramps); burst is always 0 -- a dash
        has no one-shot jump burst, unlike the tunnel's."""
        return (self.dash_intensity(), 0.0)


_singleton = DashVFX()


def get() -> DashVFX:
    return _singleton
