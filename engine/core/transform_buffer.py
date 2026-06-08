"""Per-instance previous/current transform snapshots for render interpolation.

Holds the last two sim-state transforms for each render instance id and
returns `lerp(prev, cur, alpha)` for the current render frame. Pure: no
renderer, no App, no global state. See the per-frame contract in the
implementation plan and the design spec.
"""

from engine.core.interpolate import lerp_transform


class TransformBuffer:
    def __init__(self):
        self._prev = {}  # iid -> (loc, rot)
        self._cur = {}   # iid -> (loc, rot)

    def has(self, iid) -> bool:
        return iid in self._cur

    def roll(self) -> None:
        """Promote current snapshots to previous (start of a tick batch)."""
        self._prev = dict(self._cur)

    def set_current(self, iid, loc, rot) -> None:
        """Record the post-tick live transform. Seeds prev = cur for a
        previously unseen iid so the first rendered frame does not smear."""
        self._cur[iid] = (loc, rot)
        if iid not in self._prev:
            self._prev[iid] = (loc, rot)

    def reset_all(self) -> None:
        """Forget all snapshots (mission swap / scene discontinuity)."""
        self._prev.clear()
        self._cur.clear()

    def prune(self, live_iids) -> None:
        """Drop iids not present in live_iids (despawned instances)."""
        live = set(live_iids)
        for iid in [k for k in self._cur if k not in live]:
            self._cur.pop(iid, None)
            self._prev.pop(iid, None)

    def sample(self, iid, alpha):
        """Return interpolated (loc, rot) for iid, or None if unknown."""
        cur = self._cur.get(iid)
        if cur is None:
            return None
        prev = self._prev.get(iid, cur)
        return lerp_transform(prev[0], prev[1], cur[0], cur[1], alpha)
