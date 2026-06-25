"""WarpVFX — per-frame warp animator (Stage 2: ST warp dust streak).

Owns the 4-phase warp clock and the streak/flash/turn envelopes. Ticked each
frame by the host loop; started/stopped by the WarpSequence. Pure math,
headless-safe. The speed sensation comes from the DUST pass (driven by
streak_intensity + travel_dir); the camera/ship turn is applied by the host
using turn_fraction.

Spec: docs/superpowers/specs/2026-06-22-warp-vfx-dust-streak-design.md
"""


def _smooth(t):
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3.0 - 2.0 * t)


# Ship-speed envelope timing (separate from the visual streak/flash envelopes).
# The last _T_ENTER_BOOST seconds of align ramp the ship from its cruise speed
# up to in-system warp speed (the "blast off" just before the burst flash); the
# _T_EXIT_DECEL seconds AFTER the transit ends ramp it back down to 0 (the glide-
# in as the destination system appears). The manager stays active through the
# decel tail so the host keeps driving the speed override after arrival.
_T_ENTER_BOOST = 1.0
_T_EXIT_DECEL = 2.0


class WarpVFX:
    def __init__(self):
        self._active = False
        self._heading = (0.0, 1.0, 0.0)
        self._vantage = None
        self._dst_vantage = None
        self._t_align = 0.0
        self._t_transit = 0.0
        self._t0 = 0.0
        self._e = 0.0
        self._turn = 0.0
        self._streak = 0.0
        self._flash = 0.0
        self._phase = "align"

    def start(self, heading, t_align, t_transit, now, vantage=None,
              dst_vantage=None):
        self._heading = tuple(heading)
        # Galaxy-map position the procedural sky is projected from at warp start
        # (the source system's vantage). None when the source isn't
        # galaxy-mapped (sky stays blacked out then).
        self._vantage = tuple(vantage) if vantage is not None else None
        # Destination system's vantage. When known, the projection vantage
        # travels src -> dst across the transit and ARRIVES on dst, so the
        # destination's own nebula looms ahead and envelops on exit (continuous
        # with the in-system sky). When None, fall back to the legacy fixed-rate
        # parallax along the heading.
        self._dst_vantage = tuple(dst_vantage) if dst_vantage is not None else None
        self._t_align = max(0.01, float(t_align))
        self._t_transit = max(0.01, float(t_transit))
        self._t0 = float(now)
        self._e = 0.0
        self._active = True
        self._turn = 0.0
        self._streak = 0.0
        self._flash = 0.0
        self._phase = "align"

    def _elapsed(self, now):
        return now - self._t0

    def tick(self, now):
        if not self._active:
            return
        e = self._elapsed(now)
        self._e = e
        total = self._t_align + self._t_transit
        if e < self._t_align:
            # ALIGN: turn ramps 0->1, no streak, engine-spool (no flash yet).
            self._turn = _smooth(e / self._t_align)
            self._streak = 0.0
            self._flash = 0.0
            self._phase = "align"
        elif e < total:
            self._turn = 1.0
            tp = (e - self._t_align) / self._t_transit   # transit progress 0..1
            # streak: fast ramp at burst, hold, shrink at exit.
            self._streak = min(_smooth(tp / 0.12), _smooth((1.0 - tp) / 0.15))
            # flash: burst boom (decays over first 10% of transit) + exit boom.
            burst = max(0.0, 1.0 - tp / 0.10)
            exit_ = max(0.0, (tp - 0.90) / 0.10)
            self._flash = min(1.0, burst + exit_)
            self._phase = "transit"
        else:
            # EXIT DECEL TAIL: the transit/streak is over and the destination
            # system is shown; the ship glides from in-system warp speed to 0.
            # No streak, no flash, no forced turn (the arrival placement owns the
            # ship's orientation now).
            self._turn = 1.0
            self._streak = 0.0
            self._flash = 0.0
            self._phase = "exit"
        if e >= total + _T_EXIT_DECEL:
            self._active = False
            self._turn = 1.0
            self._streak = 0.0
            self._flash = 0.0

    def ship_speed(self, nominal, warp_speed):
        """Desired forward speed (GU/s) for the current warp phase.

        `nominal` = cruise speed while aligning; `warp_speed` = in-system warp.
          align cruise -> (last _T_ENTER_BOOST s) ramp up to warp_speed
          transit      -> 0 (camera ~still so the slow dust drift reads cleanly;
                          the transit is blacked out, so this is invisible)
          exit         -> ramp warp_speed -> 0 over _T_EXIT_DECEL s (glide-in)
        """
        e = self._e
        t_align = self._t_align
        total = t_align + self._t_transit
        if e < t_align:
            boost_start = t_align - _T_ENTER_BOOST
            if e < boost_start:
                return nominal
            f = _smooth((e - boost_start) / _T_ENTER_BOOST)
            return nominal + (warp_speed - nominal) * f
        if e < total:
            return 0.0
        f = _smooth((e - total) / _T_EXIT_DECEL)
        return warp_speed * (1.0 - f)

    def sky_vantage(self, rate):
        """Galaxy-map vantage to project the procedural sky from THIS frame, or
        None if the source wasn't mapped. Advances forward along the warp heading
        at `rate` galaxy-units/sec across the transit (held at the start during
        align and at the end during the exit decel), so the projected clusters
        and nebulae stream past — the "flying through the galaxy" parallax."""
        if self._vantage is None:
            # No source vantage: sit statically at the destination if mapped,
            # else blacked out.
            return self._dst_vantage
        te = self._e - self._t_align
        if te < 0.0:
            te = 0.0
        elif te > self._t_transit:
            te = self._t_transit
        v = self._vantage
        if self._dst_vantage is not None:
            # Travel src -> dst, arriving on dst exactly at transit end so the
            # destination nebula looms ahead and envelops on arrival rather than
            # streaming past. `rate` is unused on this path.
            d, f = self._dst_vantage, te / self._t_transit
            return (v[0] + (d[0] - v[0]) * f,
                    v[1] + (d[1] - v[1]) * f,
                    v[2] + (d[2] - v[2]) * f)
        # Legacy: destination unmapped — fixed-rate parallax along the heading.
        h = self._heading
        return (v[0] + h[0] * rate * te,
                v[1] + h[1] * rate * te,
                v[2] + h[2] * rate * te)

    def stop(self):
        self._active = False
        self._turn = 0.0
        self._streak = 0.0
        self._flash = 0.0

    def is_active(self):        return self._active
    def phase(self):            return self._phase
    def turn_fraction(self):    return self._turn
    def streak_intensity(self): return self._streak
    def flash_intensity(self):  return self._flash
    def travel_dir(self):       return self._heading


_singleton = WarpVFX()


def get():
    return _singleton
