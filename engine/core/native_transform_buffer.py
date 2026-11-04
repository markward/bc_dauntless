"""The host's render interpolation buffer: a thin adapter over the native one
(native motion phase 3c).

The snapshots, the lerp, the player's live mode and its handover blend all
live in C++ (`dauntless::InterpBuffer` behind the host's `interp_*`
bindings), keyed by render instance id and fed by one frame-end capture from
the live transform store. This keeps only the Python-side set of tracked
iids, so `has()` and `prune()` cost no boundary crossing, and gives `sample()`
the same `(TGPoint3, TGMatrix3) | None` shape as
`engine.core.transform_buffer.TransformBuffer.sample`, which stays as the
pure-Python twin oracle. `advance_ticks` drives `roll()` and
`reseat_from_live()`.
"""

from engine import host_io
from engine.appc.math import TGMatrix3, TGPoint3


class NativeTransformBuffer:
    def __init__(self):
        self._tracked = set()

    def has(self, iid) -> bool:
        return iid in self._tracked

    def roll(self) -> None:
        """Start a tick batch: prev = cur for every tracked instance."""
        host_io.interp_roll()

    def reseat_from_live(self) -> None:
        """prev = the live store pose (a multi-tick frame, before its last
        tick)."""
        host_io.interp_reseat()

    def capture(self) -> None:
        """The frame-end publish: cur = the live store pose."""
        host_io.interp_capture()

    def track(self, iid, compose: bool) -> None:
        """Track `iid` (captured at once); `compose` also draws it in
        interp_compose."""
        self._tracked.add(iid)
        host_io.interp_track(iid, True, bool(compose))

    def untrack(self, iid) -> None:
        self._tracked.discard(iid)
        host_io.interp_track(iid, False, False)

    def snap(self, iid, *_ignored) -> None:
        """prev = cur = the live store pose: a discontinuity for one
        instance. Extra (loc, rot) arguments are the Python twin's and are
        ignored: the native side reads the store."""
        host_io.interp_snap(iid)

    def reset_all(self) -> None:
        """Drop every snapshot, last drawn pose and the handover; tracking
        stays and the next capture re-seeds."""
        host_io.interp_reset_all()

    def prune(self, live_iids) -> None:
        """Untrack every iid not in `live_iids`."""
        live = set(live_iids)
        for iid in [k for k in self._tracked if k not in live]:
            self.untrack(iid)

    def sample(self, iid, alpha):
        """The DRAWN pose (live or lerp, then the handover blend), set-local
        and unscaled, or None for an untracked iid or nothing to draw."""
        if iid not in self._tracked:
            return None
        got = host_io.interp_sample(iid, alpha)
        if got is None:
            return None
        pos, rot9 = got
        rot = TGMatrix3()
        rot.set_from_tuple(rot9)
        return TGPoint3(pos[0], pos[1], pos[2]), rot
