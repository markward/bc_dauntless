"""WarpVFX — per-frame warp-transit animator (Stage 2 warp VFX).

Owns the timed flythrough state: interpolates the procedural-sky vantage
origin->destination and drives the star-streak + warp-flash envelopes. Ticked
each frame by the host loop; started/stopped by the WarpSequence. Headless-safe
(pure math; no renderer dependency).

Spec: docs/superpowers/specs/2026-06-22-warp-vfx-flythrough-design.md
"""


def _lerp3(a, b, t):
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def _smooth(t):  # smoothstep ease
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3.0 - 2.0 * t)


class WarpVFX:
    def __init__(self):
        self._active = False
        self._src = (0.0, 0.0, 0.0)
        self._dst = (0.0, 0.0, 0.0)
        self._dur = 0.0
        self._t0 = 0.0
        self._travel = (0.0, 1.0, 0.0)
        self._vantage = (0.0, 0.0, 0.0)
        self._streak = 0.0
        self._flash = 0.0

    def start(self, src_vantage, dst_vantage, duration, travel_dir, now):
        self._src = tuple(src_vantage)
        self._dst = tuple(dst_vantage)
        self._dur = max(0.01, float(duration))
        self._t0 = float(now)
        self._travel = tuple(travel_dir)
        self._vantage = self._src
        self._active = True
        self._streak = 0.0
        self._flash = 1.0   # entry flash peak

    def progress(self, now):
        return min(1.0, max(0.0, (now - self._t0) / self._dur))

    def tick(self, now):
        if not self._active:
            return
        p = self.progress(now)
        self._vantage = _lerp3(self._src, self._dst, _smooth(p))
        # streak: ramp in over the first 20%, hold, ramp out over the last 15%.
        ramp_in = _smooth(p / 0.2)
        ramp_out = _smooth((1.0 - p) / 0.15)
        self._streak = min(ramp_in, ramp_out)
        # flash: entry pulse (decays over first 15%) + exit pulse (rises in last 8%).
        entry = max(0.0, 1.0 - p / 0.15)
        exit_ = max(0.0, (p - 0.92) / 0.08)
        self._flash = min(1.0, entry + exit_)
        if p >= 1.0:
            self._active = False
            self._streak = 0.0
            self._flash = 0.0

    def stop(self):
        self._active = False
        self._streak = 0.0
        self._flash = 0.0

    def is_active(self):        return self._active
    def vantage(self):          return self._vantage
    def streak_intensity(self): return self._streak
    def flash_intensity(self):  return self._flash
    def travel_dir(self):       return self._travel


_singleton = WarpVFX()


def get():
    return _singleton
