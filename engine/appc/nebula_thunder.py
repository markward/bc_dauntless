"""Nebula lightning — the thunder flash driver.

A seeded state machine: while the player is inside a nebula, it spawns
occasional distant flashes (transient directional lights biased toward the
view) with a brighten→dim envelope, and schedules a delayed thunder rumble per
flash. Pure logic — emits plain Flash objects + due-audio names; the host loop
turns flashes into directionals (cloud + hull lighting) and god-ray descriptors
and plays the audio. No GL, no audio calls here. Deterministic given the seed.
"""
import math
import random

INTERVAL = 12.0          # mean seconds between flashes
INTERVAL_JITTER = 6.0    # +/- jitter on the interval
RISE = 0.3               # envelope rise time (s)
HOLD = 0.15              # hold at peak (s)
DECAY = 2.0              # decay time (s)
PEAK_MIN = 0.7
PEAK_MAX = 1.3
CONE_DEG = 45.0          # direction spread (deg) around camera-forward
AUDIO_DELAY_MIN = 0.5
AUDIO_DELAY_MAX = 2.0
THUNDER_SOUND = "AtmosphereRumble"
BASE_COLOR = (0.85, 0.9, 1.0)   # cold-white lightning


class Flash:
    __slots__ = ("dir", "color", "peak", "born", "life", "intensity")

    def __init__(self, dir_, color, peak, born):
        self.dir = dir_           # unit (x,y,z) world
        self.color = color
        self.peak = peak
        self.born = born          # game_time at spawn
        self.life = RISE + HOLD + DECAY
        self.intensity = 0.0      # set each tick by the driver


class NebulaThunderDriver:
    def __init__(self, seed=1337):
        self._seed = seed
        self._rng = random.Random(seed)
        self._flashes = []
        self._audio = []          # list of (due_time, sound_name)
        self._next_at = None      # game_time of the next spawn (lazy)

    def reset(self):
        self._flashes = []
        self._audio = []
        self._next_at = None
        self._rng = random.Random(self._seed)

    # ── envelope ──────────────────────────────────────────────────────────
    def _envelope(self, flash, age):
        if age < 0.0 or age >= flash.life:
            return 0.0
        if age < RISE:
            # rise with a small secondary flicker so it reads as lightning
            base = max(1e-6, age / RISE)
            flick = 0.85 + 0.15 * math.sin(age * 60.0)
            return flash.peak * base * flick
        if age < RISE + HOLD:
            return flash.peak
        decay_age = age - RISE - HOLD
        return flash.peak * max(0.0, 1.0 - decay_age / DECAY)

    # ── spawning ──────────────────────────────────────────────────────────
    def _rand_dir_in_cone(self, forward):
        # Normalize forward; fall back to +Y.
        fx, fy, fz = forward
        flen = math.sqrt(fx*fx + fy*fy + fz*fz)
        if flen < 1e-6:
            fx, fy, fz, flen = 0.0, 1.0, 0.0, 1.0
        fx, fy, fz = fx/flen, fy/flen, fz/flen
        # Sample a direction within CONE_DEG of forward (uniform on the cap).
        cos_max = math.cos(math.radians(CONE_DEG))
        ct = 1.0 - self._rng.random() * (1.0 - cos_max)
        st = math.sqrt(max(0.0, 1.0 - ct*ct))
        phi = self._rng.random() * 2.0 * math.pi
        # Build a basis around forward.
        up = (0.0, 0.0, 1.0) if abs(fz) < 0.9 else (1.0, 0.0, 0.0)
        rx = fy*up[2] - fz*up[1]; ry = fz*up[0] - fx*up[2]; rz = fx*up[1] - fy*up[0]
        rl = math.sqrt(rx*rx + ry*ry + rz*rz) or 1.0
        rx, ry, rz = rx/rl, ry/rl, rz/rl
        ux = ry*fz - rz*fy; uy = rz*fx - rx*fz; uz = rx*fy - ry*fx
        dx = ct*fx + st*(math.cos(phi)*rx + math.sin(phi)*ux)
        dy = ct*fy + st*(math.cos(phi)*ry + math.sin(phi)*uy)
        dz = ct*fz + st*(math.cos(phi)*rz + math.sin(phi)*uz)
        return (dx, dy, dz)

    def _spawn_flash(self, game_time, camera_forward):
        peak = self._rng.uniform(PEAK_MIN, PEAK_MAX)
        d = self._rand_dir_in_cone(camera_forward)
        f = Flash(d, BASE_COLOR, peak, game_time)
        self._flashes.append(f)
        delay = self._rng.uniform(AUDIO_DELAY_MIN, AUDIO_DELAY_MAX)
        self._audio.append((game_time + delay, THUNDER_SOUND))
        return f

    # ── tick ──────────────────────────────────────────────────────────────
    def update(self, in_nebula, dt, game_time, camera_forward=(0.0, 1.0, 0.0)):
        if not in_nebula:
            # Leave the nebula → storm stops; drop transient state.
            if self._flashes:
                self._flashes = []
            self._next_at = None
            return
        if self._next_at is None:
            self._next_at = game_time + self._rng.uniform(
                INTERVAL - INTERVAL_JITTER, INTERVAL + INTERVAL_JITTER)
        if game_time >= self._next_at:
            self._spawn_flash(game_time, camera_forward)
            self._next_at = game_time + self._rng.uniform(
                INTERVAL - INTERVAL_JITTER, INTERVAL + INTERVAL_JITTER)
        # Update envelopes; expire dead flashes.
        alive = []
        for f in self._flashes:
            f.intensity = self._envelope(f, game_time - f.born)
            if f.intensity > 0.0:
                alive.append(f)
        self._flashes = alive

    def active_flashes(self):
        return list(self._flashes)

    def pop_due_audio(self, game_time):
        due = [name for (t, name) in self._audio if t <= game_time]
        self._audio = [(t, name) for (t, name) in self._audio if t > game_time]
        return due
