"""The in-flight torpedo table behind "which torpedoes are coming at me?".

App.AIScriptAssist_GetIncomingTorpIDsInSet (BC's Appc 0x00473830 -- engine
code in BC too) is asked by every NPC's EvadeTorps every 0.15 s, and the answer
walks every torpedo in flight. A 64-ship fight keeps ~1,500 up (BC's 60 s
default lifetime), and the Python walk over projectiles._active -- frame
lookups, offsets and vector allocations per torpedo -- was over half of all AI
time (perf register, 2026-10-29 cProfile of combat_stress at 64 ships).

So the walk is a table: one row per torpedo (id, transform handle, velocity,
source id, set group), kept in step by engine/appc/projectiles.py, scanned in
one call. Positions are NOT in the row -- it holds the transform handle and
reads the store live, so motion needs no sync. The answer is the walk's, id
for id and in order; tests/unit/test_torpedo_scan_conformance.py runs the
two against each other.

Two backends, one contract, exactly as engine/appc/transform_store.py: the
native table (C++, native/src/transforms/src/torpedo_scan.cc) whenever the
native transform store is live -- rows hold ITS handles -- and a pure-Python
one headless.

`group` is id(set) of the torpedo's set (0 = in no set). `incoming` takes
(group, dx, dy, dz) for each group the observer can see: the offset that
frames.offset_between gives from the observer's set to that group's set. A
row whose group is not listed is in another frame, never incoming.
"""
import math

from engine.appc.transform_store import StaleHandleError, get_store


class PythonTorpedoScan:
    """Dict-of-rows backend. Insertion-ordered, like the native table."""

    __slots__ = ("_store", "_rows")

    def __init__(self, store):
        self._store = store
        self._rows: dict = {}

    def add(self, tid, xi, xg, vx, vy, vz, has_source, source, group) -> None:
        row = self._rows.get(tid)
        new = [xi, xg, float(vx), float(vy), float(vz),
               bool(has_source), int(source), int(group)]
        if row is None:
            self._rows[tid] = new
        else:
            row[:] = new

    def remove(self, tid) -> bool:
        return self._rows.pop(tid, None) is not None

    def set_velocity(self, tid, vx, vy, vz) -> None:
        row = self._rows.get(tid)
        if row is not None:
            row[2:5] = [float(vx), float(vy), float(vz)]

    def set_source(self, tid, has_source, source) -> None:
        row = self._rows.get(tid)
        if row is not None:
            row[5:7] = [bool(has_source), int(source)]

    def set_group(self, tid, group) -> None:
        row = self._rows.get(tid)
        if row is not None:
            row[7] = int(group)

    def clear(self) -> None:
        self._rows.clear()

    def size(self) -> int:
        return len(self._rows)

    def incoming(self, obs, obs_vel, threshold, match_source, firing_id,
                 offsets) -> list:
        """projectiles._closing_time + _matches_source per row, in the same
        arithmetic order as the native kernel."""
        out = []
        if not offsets:
            return out
        offs = {g: (x, y, z) for g, x, y, z in offsets}
        ox, oy, oz = obs
        ovx, ovy, ovz = obs_vel
        get_position = self._store.get_position
        for tid, (xi, xg, vx, vy, vz, has_src, src, group) in self._rows.items():
            if match_source and (not has_src or src != firing_id):
                continue
            off = offs.get(group)
            if off is None:
                continue
            try:
                px, py, pz = get_position(xi, xg)
            except StaleHandleError:
                continue
            dx = (px + off[0]) - ox
            dy = (py + off[1]) - oy
            dz = (pz + off[2]) - oz
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            if dist < 1e-6:
                t = 0.0
            else:
                rx = vx - ovx
                ry = vy - ovy
                rz = vz - ovz
                inv = 1.0 / dist
                closing = -(rx * (dx * inv) + ry * (dy * inv) + rz * (dz * inv))
                if closing <= 1e-6:
                    continue
                t = dist / closing
            if t <= threshold:
                out.append(tid)
        return out


class NativeTorpedoScan:
    """C++ backend: the process-wide dauntless::torpedo_scan()."""

    __slots__ = ("_h",)

    def __init__(self, host_module):
        self._h = host_module

    def add(self, tid, xi, xg, vx, vy, vz, has_source, source, group) -> None:
        self._h.torpedo_scan_add(tid, xi, xg, float(vx), float(vy), float(vz),
                                 bool(has_source), int(source), int(group))

    def remove(self, tid) -> bool:
        return self._h.torpedo_scan_remove(tid)

    def set_velocity(self, tid, vx, vy, vz) -> None:
        self._h.torpedo_scan_set_velocity(tid, float(vx), float(vy), float(vz))

    def set_source(self, tid, has_source, source) -> None:
        self._h.torpedo_scan_set_source(tid, bool(has_source), int(source))

    def set_group(self, tid, group) -> None:
        self._h.torpedo_scan_set_group(tid, int(group))

    def clear(self) -> None:
        self._h.torpedo_scan_clear()

    def size(self) -> int:
        return self._h.torpedo_scan_size()

    def incoming(self, obs, obs_vel, threshold, match_source, firing_id,
                 offsets) -> list:
        return self._h.torpedo_scan_incoming(
            obs, obs_vel, float(threshold), bool(match_source),
            int(firing_id), offsets)


_SCAN = None
_SCAN_STORE = None


def get_scan():
    """The table for the live transform store. Resolved at USE, and again
    whenever the store singleton is replaced (tests reset it), so rows never
    hold handles into a store nobody reads."""
    global _SCAN, _SCAN_STORE
    store = get_store()
    if _SCAN is None or _SCAN_STORE is not store:
        from engine.appc.transform_store import NativeTransformStore
        if isinstance(store, NativeTransformStore):
            _SCAN = NativeTorpedoScan(store._h)
        else:
            _SCAN = PythonTorpedoScan(store)
        _SCAN.clear()
        _SCAN_STORE = store
        from engine.appc import projectiles
        projectiles._scan_reset()
    return _SCAN
