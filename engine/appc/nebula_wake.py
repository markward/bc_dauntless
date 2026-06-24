"""Nebula ship wake — multi-emitter trail tracker.

One ring buffer PER emitter (impulse-engine pod), keyed by a caller-supplied
stable key. Each point records the pod's world position, birth time, and size.
Strength fades IN over FRONT_RISE (no pop) then OUT to 0 over LIFETIME. A pod
absent from a tick's input (went offline) keeps its existing points — they fade
out — but grows no new ones, and is dropped once empty. Pure logic, no GL,
deterministic from the emitter inputs (no RNG). The renderer draws each point
as an additive billboard sized by point["size"] × a renderer dial.
"""

SPACING = 1.0       # GU a pod must move before a new trail point is laid;
                    # fine spacing = many small puffs, small/fast per-birth steps
N = 120             # max trail points PER EMITTER; bounds trail length + draw cost
LIFETIME = 12.0     # seconds a point lives; at impulse this sets the trail length
FRONT_RISE = 0.5    # seconds the newest point fades IN over (kills the pop/strobe)


class _Point:
    __slots__ = ("pos", "born", "size")

    def __init__(self, pos, born, size):
        self.pos = pos
        self.born = born
        self.size = size


class _Emitter:
    __slots__ = ("points", "last")

    def __init__(self):
        self.points = []      # oldest first
        self.last = None      # last recorded position for this emitter


def _dist2(a, b):
    dx, dy, dz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return dx * dx + dy * dy + dz * dz


class NebulaWakeTracker:
    def __init__(self):
        self._emitters = {}    # key -> _Emitter
        self._out = []

    def reset(self):
        self._emitters = {}
        self._out = []

    def update(self, in_nebula, emitters, game_time):
        """emitters: list of {"key", "pos":(x,y,z), "size":float} — ACTIVE pods
        only (the caller filters offline ones)."""
        if not in_nebula:
            if self._emitters or self._out:
                self._emitters = {}
                self._out = []
            return

        # Record by distance for each active emitter.
        active_keys = set()
        for em in emitters:
            key = em["key"]
            pos = em["pos"]
            size = em["size"]
            active_keys.add(key)
            st = self._emitters.get(key)
            if st is None:
                st = _Emitter()
                self._emitters[key] = st
            if st.last is None or _dist2(pos, st.last) >= SPACING * SPACING:
                st.points.append(_Point((pos[0], pos[1], pos[2]), game_time, size))
                st.last = (pos[0], pos[1], pos[2])
                if len(st.points) > N:
                    st.points = st.points[-N:]

        # Expire + build the flattened output. Inactive emitters (not fed this
        # tick) keep fading; drop them once empty.
        out = []
        dead = []
        for key, st in self._emitters.items():
            alive = []
            for p in st.points:
                age = game_time - p.born
                if age < 0.0 or age >= LIFETIME:
                    continue
                alive.append(p)
                fade = 1.0 - age / LIFETIME             # 1 -> 0 over the lifetime
                rise = age / FRONT_RISE if age < FRONT_RISE else 1.0  # 0 -> 1 ease-in
                out.append({"pos": p.pos, "strength": fade * rise, "size": p.size})
            st.points = alive
            if not alive and key not in active_keys:
                dead.append(key)
        for key in dead:
            del self._emitters[key]

        self._out = out

    def trail_points(self):
        return self._out
