"""Authoritative storage for every object's position and rotation.

One contract, two backends. The native backend (C++ contiguous array) is used
when _dauntless_host is present; the pure-Python backend is used headless.
They are never live at the same time, so this is one contract with two
implementations, not two sources of truth —
tests/unit/test_transform_store_conformance.py runs the identical suite
against both, which is what stops them drifting.

Handles are (index, generation). The generation counter exists so a stale
handle from a freed object fails loudly instead of silently reading whatever
object recycled its index.

Rotations are row-major nine-float tuples throughout, matching TGMatrix3's
storage and its mIJ = row I, column J naming. Column-vector convention: column
1 is forward (CLAUDE.md ↦ "Rotation matrix convention").
"""

from array import array

_IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)

# Twelve floats per slot: three position, nine rotation (row-major).
_STRIDE = 12


class StaleHandleError(RuntimeError):
    """A handle whose generation no longer matches its slot."""


class PythonTransformStore:
    """Flat-list backend. Used when the native extension is absent."""

    __slots__ = ("_data", "_generations", "_free", "_live")

    def __init__(self):
        self._data: list[float] = []
        self._generations: list[int] = []
        self._free: list[int] = []
        self._live: int = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def alloc(self) -> tuple[int, int]:
        if self._free:
            index = self._free.pop()
            self._generations[index] += 1
        else:
            index = len(self._generations)
            self._generations.append(1)
            self._data.extend((0.0,) * _STRIDE)
        base = index * _STRIDE
        self._data[base:base + 3] = [0.0, 0.0, 0.0]
        self._data[base + 3:base + _STRIDE] = list(_IDENTITY)
        self._live += 1
        return index, self._generations[index]

    def free(self, index: int, generation: int) -> None:
        self._check(index, generation)
        # Bump on free as well as on reuse, so a handle to a freed-but-not-yet
        # reused slot is stale immediately rather than only after realloc.
        self._generations[index] += 1
        self._free.append(index)
        self._live -= 1

    def live_count(self) -> int:
        return self._live

    def capacity(self) -> int:
        return len(self._generations)

    # ── Access ────────────────────────────────────────────────────────────────

    def get_position(self, index: int, generation: int) -> tuple:
        self._check(index, generation)
        base = index * _STRIDE
        d = self._data
        return (d[base], d[base + 1], d[base + 2])

    def set_position(self, index: int, generation: int,
                     x: float, y: float, z: float) -> None:
        self._check(index, generation)
        base = index * _STRIDE
        d = self._data
        d[base] = float(x)
        d[base + 1] = float(y)
        d[base + 2] = float(z)

    def get_rotation(self, index: int, generation: int) -> tuple:
        self._check(index, generation)
        base = index * _STRIDE + 3
        return tuple(self._data[base:base + 9])

    def set_rotation(self, index: int, generation: int, t9) -> None:
        self._check(index, generation)
        base = index * _STRIDE + 3
        self._data[base:base + 9] = [float(v) for v in t9]

    def get_rotation_col(self, index: int, generation: int, col: int) -> tuple:
        self._check(index, generation)
        if col < 0 or col > 2:
            raise IndexError(col)
        base = index * _STRIDE + 3
        d = self._data
        return (d[base + col], d[base + 3 + col], d[base + 6 + col])

    def get_positions(self, handles) -> list:
        out = []
        d = self._data
        gens = self._generations
        n = len(gens)
        for index, generation in handles:
            if index < 0 or index >= n or gens[index] != generation:
                raise StaleHandleError(
                    "transform handle (%r, %r) is stale" % (index, generation))
            base = index * _STRIDE
            out.append((d[base], d[base + 1], d[base + 2]))
        return out

    def within_radius(self, handles, x: float, y: float, z: float,
                      r2: float) -> bytes:
        """One flag per handle: 1 when its position lies within or on the
        sphere, by the compare ProximityManager.GetNearObjects used to make
        itself (`dx*dx + dy*dy + dz*dz <= r2`)."""
        d = self._data
        gens = self._generations
        n = len(gens)
        out = bytearray(len(handles))
        for k, (index, generation) in enumerate(handles):
            if index < 0 or index >= n or gens[index] != generation:
                raise StaleHandleError(
                    "transform handle (%r, %r) is stale" % (index, generation))
            base = index * _STRIDE
            dx = d[base] - x
            dy = d[base + 1] - y
            dz = d[base + 2] - z
            out[k] = dx * dx + dy * dy + dz * dz <= r2
        return bytes(out)

    def proximity_report(self, anchors, objects, r2, want, start: int) -> list:
        """Indices from `start` of the proximity pairs Python must look at.

        Pair k is anchor handle (anchors[2k], anchors[2k+1]), object handle
        (objects[2k], objects[2k+1]), radius squared r2[k] and want[k]: 0
        reports when the object is inside (`dx*dx + dy*dy + dz*dz <= r2`), 1
        when it is outside, 2 always, 3 never. A stale handle on a want 0, 1
        or 3 pair is reported, not raised. Backs engine.appc.proximity_table.
        """
        d = self._data
        gens = self._generations
        n = len(gens)
        out = []
        for k in range(start, len(want)):
            w = want[k]
            if w == 2:
                out.append(k)
                continue
            ai, ag = anchors[2 * k], anchors[2 * k + 1]
            oi, og = objects[2 * k], objects[2 * k + 1]
            if (ai >= n or gens[ai] != ag or oi >= n or gens[oi] != og):
                out.append(k)
                continue
            if w == 3:
                continue
            a, o = ai * _STRIDE, oi * _STRIDE
            dx = d[o] - d[a]
            dy = d[o + 1] - d[a + 1]
            dz = d[o + 2] - d[a + 2]
            if (dx * dx + dy * dy + dz * dz <= r2[k]) == (w == 0):
                out.append(k)
        return out

    def sweep_candidates(self, starts, seg_lens, skips, centres, bounds) -> list:
        """The (torpedo, ship) pairs close enough for projectiles.update_all's
        narrow hit tests, flat [t, s, ...] ordered by torpedo then ship.

        Torpedo t's tick segment starts at starts[3t:3t+3] and is
        seg_lens[t] long; ship s is a sphere of radius bounds[s] at
        centres[3s:3s+3]. A pair is dropped only when `dx*dx + dy*dy + dz*dz
        > reach*reach` (d = centre - start, reach = bound + seg_len) -- so a
        NaN stays a candidate. skips[t] is the ship index t never meets (its
        shooter), or -1. Pure arithmetic; touches no slot.
        """
        out = []
        for t in range(len(seg_lens)):
            px, py, pz = starts[3 * t], starts[3 * t + 1], starts[3 * t + 2]
            n = seg_lens[t]
            skip = skips[t]
            for s in range(len(bounds)):
                if s == skip:
                    continue
                dx = centres[3 * s] - px
                dy = centres[3 * s + 1] - py
                dz = centres[3 * s + 2] - pz
                reach = bounds[s] + n
                if (dx * dx + dy * dy + dz * dz) > reach * reach:
                    continue
                out.append(t)
                out.append(s)
        return out

    # ── Internal ──────────────────────────────────────────────────────────────

    def _check(self, index: int, generation: int) -> None:
        gens = self._generations
        if index < 0 or index >= len(gens) or gens[index] != generation:
            raise StaleHandleError(
                "transform handle (%r, %r) is stale" % (index, generation))


class NativeTransformStore:
    """C++ backend. Thin translation to StaleHandleError so both backends
    raise the same exception type. A stale (index, generation) can surface
    from pybind11 as either a RuntimeError (the C++ store's own bounds/
    generation check) or a TypeError (a negative index fails the uint32_t
    argument conversion before the C++ check ever runs) — both are caught so
    every caller sees StaleHandleError regardless of which layer rejected it.
    """

    __slots__ = ("_h",)

    def __init__(self, host_module):
        self._h = host_module

    def alloc(self) -> tuple[int, int]:
        return self._h.transform_alloc()

    def free(self, index: int, generation: int) -> None:
        try:
            self._h.transform_free(index, generation)
        except (RuntimeError, TypeError) as exc:
            raise StaleHandleError(str(exc)) from exc

    def live_count(self) -> int:
        return self._h.transform_live_count()

    def capacity(self) -> int:
        return self._h.transform_capacity()

    def get_position(self, index: int, generation: int) -> tuple:
        try:
            return tuple(self._h.transform_get_position(index, generation))
        except (RuntimeError, TypeError) as exc:
            raise StaleHandleError(str(exc)) from exc

    def set_position(self, index: int, generation: int,
                     x: float, y: float, z: float) -> None:
        try:
            self._h.transform_set_position(index, generation,
                                           float(x), float(y), float(z))
        except (RuntimeError, TypeError) as exc:
            raise StaleHandleError(str(exc)) from exc

    def get_rotation(self, index: int, generation: int) -> tuple:
        try:
            return tuple(self._h.transform_get_rotation(index, generation))
        except (RuntimeError, TypeError) as exc:
            raise StaleHandleError(str(exc)) from exc

    def set_rotation(self, index: int, generation: int, t9) -> None:
        try:
            self._h.transform_set_rotation(index, generation,
                                           [float(v) for v in t9])
        except (RuntimeError, TypeError) as exc:
            raise StaleHandleError(str(exc)) from exc

    def get_rotation_col(self, index: int, generation: int, col: int) -> tuple:
        if col < 0 or col > 2:
            raise IndexError(col)
        try:
            return tuple(
                self._h.transform_get_rotation_col(index, generation, col))
        except (RuntimeError, TypeError) as exc:
            raise StaleHandleError(str(exc)) from exc

    def get_positions(self, handles) -> list:
        try:
            return [tuple(p) for p in
                    self._h.transform_get_positions(list(handles))]
        except (RuntimeError, TypeError) as exc:
            raise StaleHandleError(str(exc)) from exc

    def within_radius(self, handles, x: float, y: float, z: float,
                      r2: float) -> bytes:
        """See PythonTransformStore.within_radius. The handles cross as one
        packed uint32 buffer and the flags come back as bytes."""
        flat = array("I")
        for index, generation in handles:
            flat.append(index)
            flat.append(generation)
        try:
            return self._h.transform_within_radius(
                flat, float(x), float(y), float(z), float(r2))
        except (RuntimeError, TypeError) as exc:
            raise StaleHandleError(str(exc)) from exc

    def proximity_report(self, anchors, objects, r2, want, start: int) -> list:
        """See PythonTransformStore.proximity_report. The four buffers cross
        as they are (array("I"), array("I"), array("d"), bytearray)."""
        return self._h.transform_proximity_report(anchors, objects, r2, want,
                                                  start)

    def sweep_candidates(self, starts, seg_lens, skips, centres, bounds) -> list:
        """See PythonTransformStore.sweep_candidates. Buffers cross as they
        are (array("d") x4 and array("i"))."""
        return self._h.transform_sweep_candidates(starts, seg_lens, skips,
                                                  centres, bounds)


_STORE = None


def get_store():
    """The process-wide transform store. Backend selected once, on first use.

    Resolved at USE, never at import: a module-level constant would freeze the
    choice before the host has had a chance to load the extension.
    """
    global _STORE
    if _STORE is None:
        try:
            import _dauntless_host as _h
        except ImportError:
            _h = None
        if _h is not None and hasattr(_h, "transform_alloc"):
            _STORE = NativeTransformStore(_h)
        else:
            _STORE = PythonTransformStore()
    return _STORE


def _reset_store_for_tests() -> None:
    """Drop the singleton so a test can start from an empty store."""
    global _STORE
    _STORE = None
