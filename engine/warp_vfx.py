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


class WarpVFX:
    def __init__(self):
        self._active = False
        self._heading = (0.0, 1.0, 0.0)
        self._t_align = 0.0
        self._t_transit = 0.0
        self._t0 = 0.0
        self._turn = 0.0
        self._streak = 0.0
        self._flash = 0.0
        self._phase = "align"

    def start(self, heading, t_align, t_transit, now):
        self._heading = tuple(heading)
        self._t_align = max(0.01, float(t_align))
        self._t_transit = max(0.01, float(t_transit))
        self._t0 = float(now)
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
        total = self._t_align + self._t_transit
        if e < self._t_align:
            # ALIGN: turn ramps 0->1, no streak, engine-spool (no flash yet).
            self._turn = _smooth(e / self._t_align)
            self._streak = 0.0
            self._flash = 0.0
            self._phase = "align"
        else:
            self._turn = 1.0
            tp = (e - self._t_align) / self._t_transit   # transit progress 0..1
            # streak: fast ramp at burst, hold, shrink at exit.
            self._streak = min(_smooth(tp / 0.12), _smooth((1.0 - tp) / 0.15))
            # flash: burst boom (decays over first 10% of transit) + exit boom.
            burst = max(0.0, 1.0 - tp / 0.10)
            exit_ = max(0.0, (tp - 0.90) / 0.10)
            self._flash = min(1.0, burst + exit_)
            self._phase = "transit"
        if e >= total:
            self._active = False
            self._turn = 1.0
            self._streak = 0.0
            self._flash = 0.0

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
