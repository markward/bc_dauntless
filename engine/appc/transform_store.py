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

    # ── Internal ──────────────────────────────────────────────────────────────

    def _check(self, index: int, generation: int) -> None:
        gens = self._generations
        if index < 0 or index >= len(gens) or gens[index] != generation:
            raise StaleHandleError(
                "transform handle (%r, %r) is stale" % (index, generation))


class NativeTransformStore:
    """C++ backend. Thin translation of RuntimeError to StaleHandleError so
    both backends raise the same exception type."""

    __slots__ = ("_h",)

    def __init__(self, host_module):
        self._h = host_module

    def alloc(self) -> tuple[int, int]:
        return self._h.transform_alloc()

    def free(self, index: int, generation: int) -> None:
        try:
            self._h.transform_free(index, generation)
        except RuntimeError as exc:
            raise StaleHandleError(str(exc)) from exc

    def live_count(self) -> int:
        return self._h.transform_live_count()

    def capacity(self) -> int:
        return self._h.transform_capacity()

    def get_position(self, index: int, generation: int) -> tuple:
        try:
            return tuple(self._h.transform_get_position(index, generation))
        except RuntimeError as exc:
            raise StaleHandleError(str(exc)) from exc

    def set_position(self, index: int, generation: int,
                     x: float, y: float, z: float) -> None:
        try:
            self._h.transform_set_position(index, generation,
                                           float(x), float(y), float(z))
        except RuntimeError as exc:
            raise StaleHandleError(str(exc)) from exc

    def get_rotation(self, index: int, generation: int) -> tuple:
        try:
            return tuple(self._h.transform_get_rotation(index, generation))
        except RuntimeError as exc:
            raise StaleHandleError(str(exc)) from exc

    def set_rotation(self, index: int, generation: int, t9) -> None:
        try:
            self._h.transform_set_rotation(index, generation,
                                           [float(v) for v in t9])
        except RuntimeError as exc:
            raise StaleHandleError(str(exc)) from exc

    def get_rotation_col(self, index: int, generation: int, col: int) -> tuple:
        if col < 0 or col > 2:
            raise IndexError(col)
        try:
            return tuple(
                self._h.transform_get_rotation_col(index, generation, col))
        except RuntimeError as exc:
            raise StaleHandleError(str(exc)) from exc


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
