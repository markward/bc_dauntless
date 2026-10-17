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

    def snap(self, iid, loc, rot) -> None:
        """Set BOTH snapshots to (loc, rot): a discontinuity for this one
        instance (the player handed off into another region set's
        coordinates), which must not be interpolated across."""
        self._prev[iid] = (loc, rot)
        self._cur[iid] = (loc, rot)

    def set_previous(self, iid, loc, rot) -> None:
        """Re-seat prev for an iid already tracked (advance_ticks); an
        untracked iid is ignored, so this never starts tracking one."""
        if iid in self._cur:
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


def advance_ticks(buf, n, tick, live_poses) -> None:
    """Run `n` sim ticks (`tick()`), keeping `buf`'s prev snapshots exactly
    ONE tick behind the cur the caller records afterwards.

    `alpha` (accumulator / tick_dt) is a fraction of one tick, so
    lerp(prev, cur, alpha) is only right when prev is the pose before the
    LAST tick. A render frame slower than a tick runs two or more; rolling
    once before the batch left prev that many ticks back, so the drawn ship
    lagged on each multi-tick frame and leapt on the next -- the judder seen
    whenever the frame rate dips under 60 Hz while interpolation draws a ship
    (E1M1's undock at ~20 ms frames).

    `live_poses()` -> iterable of (iid, loc, rot) for the objects the buffer
    may track; called only on multi-tick frames, just before the last tick,
    and only iids already tracked are re-seated. 0 ticks: nothing runs."""
    if n <= 0:
        return
    buf.roll()
    for i in range(n):
        if i == n - 1 and n > 1:
            for iid, loc, rot in live_poses():
                buf.set_previous(iid, loc, rot)
        tick()
