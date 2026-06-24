"""Nebula ship wake — the trail tracker.

Records the player's recent world positions (sampled by distance moved) into a
fading, bounded ring buffer while the player is in a nebula. Emits trail points
{pos, strength} (strength age-faded 1→0) that the volumetric raymarch uses to
churn + energize the cloud behind the ship. Pure logic, no GL. Driven entirely
by where the ship went — no RNG.
"""

SPACING = 6.0       # GU the ship must move before a new trail point is laid
N = 24              # max trail points (matches u_wake[24]); bounds length + cost
LIFETIME = 12.0     # seconds a point lives; at impulse this sets the trail length
FRONT_RISE = 0.5    # seconds the newest point fades IN over (kills the leading-
                    # edge "pop"/strobe as each point is laid at full strength)


class _Point:
    __slots__ = ("pos", "born")

    def __init__(self, pos, born):
        self.pos = pos
        self.born = born


def _dist2(a, b):
    dx, dy, dz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return dx * dx + dy * dy + dz * dz


class NebulaWakeTracker:
    def __init__(self):
        self._points = []      # oldest first
        self._last = None      # last recorded position
        self._out = []

    def reset(self):
        self._points = []
        self._last = None
        self._out = []

    def update(self, in_nebula, pos, game_time):
        if not in_nebula or pos is None:
            if self._points or self._out:
                self._points = []
                self._out = []
            self._last = None
            return

        # Record a new point only when the ship has moved >= SPACING.
        if self._last is None or _dist2(pos, self._last) >= SPACING * SPACING:
            self._points.append(_Point((pos[0], pos[1], pos[2]), game_time))
            self._last = (pos[0], pos[1], pos[2])
            if len(self._points) > N:
                self._points = self._points[-N:]

        # Expire + build the output with age-faded strength.
        alive = []
        out = []
        for p in self._points:
            age = game_time - p.born
            if age < 0.0 or age >= LIFETIME:
                continue
            alive.append(p)
            fade = 1.0 - age / LIFETIME            # 1 → 0 over the lifetime
            rise = age / FRONT_RISE if age < FRONT_RISE else 1.0  # 0 → 1 ease-in
            s = fade * rise
            out.append({"pos": p.pos, "strength": s})
        self._points = alive
        self._out = out

    def trail_points(self):
        return self._out
