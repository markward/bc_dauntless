"""Hull electrical discharges — the crackle driver.

A seeded state machine: while the player is inside a nebula, it spawns brief
electric crackles at random hull points (subsystem mounts + a small offset) at
a rate that scales with the nebula's damage rate (plus rare idle strikes), and
reports a whole-hull emissive boost for the frame. Pure logic — emits plain
descriptors + a float; the host loop feeds the crackle pass and the emissive
binding. No GL. Deterministic given the seed.
"""
import random

IDLE_RATE = 0.4          # discharges/sec at zero damage (rare)
DAMAGE_GAIN = 0.05       # extra discharges/sec per (hull dmg/sec)
BURST_MAX = 3            # max spawns in a single heavy tick
LIFE_MIN = 0.06          # discharge life (s) — "a frame or two"
LIFE_MAX = 0.15
SIZE_MIN = 0.12          # billboard half-size (GU)
SIZE_MAX = 0.30
FLICKER = 0.6            # emissive boost per unit of active intensity
EMISSIVE_MAX = 2.0       # clamp on the whole-hull boost
ANCHOR_OFFSET = 0.15     # random world offset (GU) from the subsystem mount
COLOR = (0.6, 0.8, 1.0)  # electric blue-white


class _Discharge:
    __slots__ = ("pos", "born", "life", "size", "color", "age")

    def __init__(self, pos, born, life, size, color):
        self.pos = pos
        self.born = born
        self.life = life
        self.size = size
        self.color = color
        self.age = 0.0


class HullDischargeDriver:
    def __init__(self, seed=2027):
        self._seed = seed
        self._rng = random.Random(seed)
        self._discharges = []

    def reset(self):
        self._rng = random.Random(self._seed)
        self._discharges = []

    def update(self, in_nebula, damage_rate, dt, hull_points, game_time):
        if not in_nebula or not hull_points:
            if self._discharges:
                self._discharges = []
            return

        rate = IDLE_RATE + DAMAGE_GAIN * max(0.0, damage_rate)
        # Per-tick spawn(s): Bernoulli with a diminishing chance for extras so a
        # heavy (damaging) tick can produce a small burst.
        chance = rate * dt
        n = 0
        while n < BURST_MAX and self._rng.random() < chance:
            n += 1
            chance *= 0.5
        for _ in range(n):
            px, py, pz = self._rng.choice(hull_points)
            o = ANCHOR_OFFSET
            pos = (px + self._rng.uniform(-o, o),
                   py + self._rng.uniform(-o, o),
                   pz + self._rng.uniform(-o, o))
            life = self._rng.uniform(LIFE_MIN, LIFE_MAX)
            size = self._rng.uniform(SIZE_MIN, SIZE_MAX)
            self._discharges.append(_Discharge(pos, game_time, life, size, COLOR))

        alive = []
        for d in self._discharges:
            d.age = game_time - d.born
            if 0.0 <= d.age < d.life:
                alive.append(d)
        self._discharges = alive

    def active_discharges(self):
        return [{"world_pos": d.pos, "age": d.age, "life": d.life,
                 "size": d.size, "color": d.color} for d in self._discharges]

    def emissive_boost(self):
        if not self._discharges:
            return 1.0
        s = 0.0
        for d in self._discharges:
            t = 1.0 - (d.age / d.life if d.life > 0.0 else 1.0)
            if t > 0.0:
                s += t
        boost = 1.0 + FLICKER * s
        return EMISSIVE_MAX if boost > EMISSIVE_MAX else boost
