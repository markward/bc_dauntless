# Native Transform Ownership Implementation Plan (Phases 0–3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move authoritative ownership of every object's position and rotation out of Python and into a contiguous C++ store, and stop marshalling transforms across the language boundary for the renderer.

**Architecture:** A `TransformStore` in C++ holds a contiguous vector of POD `Transform { float pos[3]; float rot[9]; }`, index-addressed with generation-counted slots. Each Python `ObjectClass` holds a slot handle allocated in `__init__` and released by `weakref.finalize`. Accessors read through and return fresh Python objects, so SDK semantics are unchanged; hot paths use bulk APIs that build no Python objects at all.

**Tech Stack:** Python 3.11, C++20, pybind11, CMake, pytest, ctest.

**Spec:** `docs/superpowers/specs/2026-09-05-native-transform-ownership-design.md`

**Scope of THIS plan:** spec phases 0–3 (native ownership). Spec phases 4–5 (the C++ motion port and threading) get a second plan, written after this one lands — its tasks reference the store API created here, and writing it now would mean referencing types that do not yet exist.

## Global Constraints

- **Python 3.11.** No new third-party dependencies; `pillow` is the only runtime one and that must not change.
- **Never spell `game` or `sdk` as a path segment** in `engine/`, `tools/`, `tests/` or `native/src`. Use `paths.game_asset(rel)`, `paths.game_root()`, `paths.sdk_scripts()`, `paths.sdk_data()`. Enforced by `tests/unit/test_path_indirection.py`.
- **Never capture a path at import.** No module-level constant may hold one.
- **Rotation convention: column-vector, right-handed, det = +1.** `GetCol(0)` = starboard, `GetCol(1)` = forward, `GetCol(2)` = up. Never `GetRow(1)` to read forward. `TGMatrix3` stores **row-major** internally; `GetCol(i)` reads `m[0][i], m[1][i], m[2][i]`.
- **`MultMatrix` must stay bit-exact.** `tests/unit/test_matrix_multiply_exact.py` pins it, including the load-bearing leading `0.0 +` that preserves signed-zero behaviour. Storage changes must not change one bit of arithmetic or its accumulation order.
- **Game units are GU.** Never name a variable `*_m` / `*_mps` for a distance or speed; use `*_gu` / `*_gups`. (Note the collision with matrix storage naming — this plan renames matrix internals off `_m` entirely, which removes the ambiguity.)
- **Test gate:** `scripts/check_tests.sh` — builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`. Never call a failure "pre-existing" by eyeball.
- **Baseline for this branch (597c3fb3):** `1 failed, 8100 passed, 6 skipped, 1 xfailed`, zero errors. The single failure is `pytest:tests/unit/test_engineer_emitters.py::test_shield_level_change_announces`, the only entry in the ledger.
- **Shared checkout — never destructive git.** Banned: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Always stage with an explicit pathspec.
- **One build tree**, at `<project-root>/build/`. `cmake -B build -S . && cmake --build build -j`. Never run `cmake` from inside `native/`.
- **Do not launch the game.** Live verification is performed by the project owner. Tasks marked **LIVE CHECKPOINT** stop and hand over.

## Pre-flight: replace the borrowed `.so`

This worktree currently has `build/python/_dauntless_host.cpython-311-darwin.so` as a **symlink** to the main tree's build, created only to establish a pytest baseline. `build/BORROWED_SO_README.txt` marks it.

Task 1 is pure Python and may run against the symlink. **Task 3 onward requires a genuine build in this worktree.** Before starting Task 3:

```bash
rm -rf build
cmake -B build -S .
cmake --build build -j
```

A stale or borrowed `.so` is the documented cause of `AttributeError: module '_dauntless_host' has no attribute X`. If you see that error, rebuild — do not change the Python side.

## File Structure

| File | Responsibility |
|---|---|
| `engine/appc/math.py` | `TGMatrix3` storage flattened to nine slotted floats (Task 1) |
| `engine/appc/transform_store.py` | Store contract, backend selection, pure-Python backend (Task 2); native backend (Task 3) |
| `native/src/transforms/include/dauntless/transform_store.h` | Store declaration (Task 3) |
| `native/src/transforms/src/transform_store.cc` | Store implementation (Task 3) |
| `native/src/transforms/CMakeLists.txt` | `dauntless_transforms` static lib (Task 3) |
| `native/src/host/host_bindings.cc` | pybind11 bindings for the store (Task 3); instance slot binding (Task 6) |
| `engine/appc/objects.py` | `ObjectClass` slot allocation + read-through accessors (Task 4) |
| `engine/host_loop.py` | Private-field sites (Task 4); render payload carries slots not matrices (Task 6) |
| `tests/unit/test_tgmatrix3_storage.py` | Storage shape + round-trip (Task 1) |
| `tests/unit/test_transform_store_conformance.py` | One contract, run against both backends (Tasks 2, 3) |
| `tests/unit/test_object_transform_slots.py` | Slot lifecycle + aliasing pin (Task 4) |
| `native/tests/test_transform_store.cc` | C++ store unit test (Task 3) |

---

### Task 1: Flatten `TGMatrix3` to nine slotted floats

Removes ~5 of the ~6 allocations per matrix instance. `ObjectClass.GetWorldRotation` builds one on every call at 70 call sites, so this lands a measurable win with no native code and de-risks everything downstream.

This task is atomic: changing the storage without updating consumers leaves a red tree, so the class and all its consumers move together.

**Files:**
- Modify: `engine/appc/math.py` (`TGMatrix3`, from line 161)
- Modify: `engine/host_loop.py:4381`, `engine/host_loop.py:4402-4404`
- Modify: `engine/appc/backdrops.py:186-188`
- Modify: `engine/appc/hull_bounds.py:130-137`
- Modify: `engine/appc/objects.py:352`, `engine/appc/objects.py:357`
- Modify: `tests/unit/test_matrix_multiply_exact.py:26,42-44,49,128-130`
- Modify: `tests/unit/test_interpolate.py:10,33,42,76,108`
- Modify: `tests/unit/test_align_to_vectors_handedness.py:16`
- Modify: `tests/host/test_world_matrices.py:164-165`
- Modify: `tests/host/test_alert_keys.py:59`
- Modify: `tests/host/test_player_control.py:84,206`
- Create: `tests/unit/test_tgmatrix3_storage.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `TGMatrix3` with `__slots__ = ("m00","m01","m02","m10","m11","m12","m20","m21","m22")`, all nine attributes `float`, row-major (`mIJ` = row I, column J). The `_m` attribute **no longer exists**. Every existing public method keeps its exact name and signature: `MakeIdentity`, `MakeZero`, `MakeXRotation`, `MakeYRotation`, `MakeZRotation`, `MakeRotation`, `MakeDiagonal`, `GetRow`, `SetRow`, `GetCol`, `SetCol`, `GetEntry`, `SetEntry`, `Set`, `Transpose`, `MultMatrix`, `MultMatrixLeft`. Two new methods are added for bulk use by later tasks: `as_tuple() -> tuple[float, ...]` returning nine floats row-major, and `set_from_tuple(t: Sequence[float]) -> None` accepting nine floats row-major.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tgmatrix3_storage.py`:

```python
"""TGMatrix3 uses flat slotted storage, not a list-of-lists.

The list-of-lists form cost ~6 allocations per instance (object + __dict__ +
outer list + three rows). ObjectClass.GetWorldRotation builds one on every
call at 70 call sites, per object, per frame.
"""
import pytest

from engine.appc.math import TGMatrix3, TGPoint3


def test_has_slots_and_no_dict():
    m = TGMatrix3()
    assert not hasattr(m, "__dict__"), "TGMatrix3 must not carry a __dict__"
    assert TGMatrix3.__slots__ == (
        "m00", "m01", "m02", "m10", "m11", "m12", "m20", "m21", "m22")


def test_underscore_m_is_gone():
    m = TGMatrix3()
    assert not hasattr(m, "_m"), (
        "_m must not survive as a compatibility shim: it would rebuild a "
        "list-of-lists and silently reintroduce the allocation, in the "
        "places we can no longer see")


def test_default_is_identity_by_attribute():
    m = TGMatrix3()
    assert (m.m00, m.m01, m.m02) == (1.0, 0.0, 0.0)
    assert (m.m10, m.m11, m.m12) == (0.0, 1.0, 0.0)
    assert (m.m20, m.m21, m.m22) == (0.0, 0.0, 1.0)


def test_as_tuple_is_row_major():
    m = TGMatrix3()
    m.Set(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
    assert m.as_tuple() == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)


def test_set_from_tuple_round_trips():
    src = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
    m = TGMatrix3()
    m.set_from_tuple(src)
    assert m.as_tuple() == src


def test_get_entry_matches_attributes():
    m = TGMatrix3()
    m.Set(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
    expected = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
    for i in range(3):
        for j in range(3):
            assert m.GetEntry(i, j) == expected[i][j]


def test_get_col_reads_columns_not_rows():
    """Column-vector convention: GetCol(1) is forward. Regression guard for
    the row/column split unified on 2026-06-18."""
    m = TGMatrix3()
    m.Set(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
    col1 = m.GetCol(1)
    assert (col1.x, col1.y, col1.z) == (2.0, 5.0, 8.0)


def test_set_col_writes_columns():
    m = TGMatrix3()
    m.MakeZero()
    m.SetCol(2, TGPoint3(7.0, 8.0, 9.0))
    assert (m.m02, m.m12, m.m22) == (7.0, 8.0, 9.0)


def test_set_row_writes_rows():
    m = TGMatrix3()
    m.MakeZero()
    m.SetRow(1, TGPoint3(4.0, 5.0, 6.0))
    assert (m.m10, m.m11, m.m12) == (4.0, 5.0, 6.0)


def test_transpose_swaps_indices():
    m = TGMatrix3()
    m.Set(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
    t = m.Transpose()
    assert t.as_tuple() == (1.0, 4.0, 7.0, 2.0, 5.0, 8.0, 3.0, 6.0, 9.0)


def test_transpose_does_not_mutate_source():
    m = TGMatrix3()
    m.Set(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
    m.Transpose()
    assert m.as_tuple() == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tgmatrix3_storage.py -q`
Expected: FAIL — `AttributeError: __slots__` / `test_underscore_m_is_gone` fails because `_m` still exists.

- [ ] **Step 3: Rewrite `TGMatrix3` storage in `engine/appc/math.py`**

Replace the class header, `__init__`, and every constructor:

```python
class TGMatrix3:
    """3×3 matrix stored row-major as nine slotted floats. Default is identity.

    Flat slotted storage, not a list-of-lists: the old form cost ~6
    allocations per instance (object + __dict__ + outer list + three rows),
    and ObjectClass.GetWorldRotation constructs one on every call at 70 call
    sites, per object, per frame.

    Naming: mIJ is row I, column J. Column-vector convention (CLAUDE.md ↦
    "Rotation matrix convention"), so GetCol(1) is forward.
    """

    __slots__ = ("m00", "m01", "m02", "m10", "m11", "m12", "m20", "m21", "m22")

    def __init__(self):
        self.m00 = 1.0; self.m01 = 0.0; self.m02 = 0.0
        self.m10 = 0.0; self.m11 = 1.0; self.m12 = 0.0
        self.m20 = 0.0; self.m21 = 0.0; self.m22 = 1.0

    # ── Bulk access (used by the transform store) ─────────────────────────────

    def as_tuple(self) -> tuple:
        """Nine floats, row-major."""
        return (self.m00, self.m01, self.m02,
                self.m10, self.m11, self.m12,
                self.m20, self.m21, self.m22)

    def set_from_tuple(self, t) -> None:
        """Set all nine entries from a row-major sequence of nine floats."""
        (self.m00, self.m01, self.m02,
         self.m10, self.m11, self.m12,
         self.m20, self.m21, self.m22) = (
            float(t[0]), float(t[1]), float(t[2]),
            float(t[3]), float(t[4]), float(t[5]),
            float(t[6]), float(t[7]), float(t[8]))

    # ── Construction ──────────────────────────────────────────────────────────

    def MakeIdentity(self) -> "TGMatrix3":
        self.m00 = 1.0; self.m01 = 0.0; self.m02 = 0.0
        self.m10 = 0.0; self.m11 = 1.0; self.m12 = 0.0
        self.m20 = 0.0; self.m21 = 0.0; self.m22 = 1.0
        return self

    def MakeZero(self) -> "TGMatrix3":
        self.m00 = 0.0; self.m01 = 0.0; self.m02 = 0.0
        self.m10 = 0.0; self.m11 = 0.0; self.m12 = 0.0
        self.m20 = 0.0; self.m21 = 0.0; self.m22 = 0.0
        return self

    def MakeXRotation(self, angle: float) -> "TGMatrix3":
        c, s = _math.cos(angle), _math.sin(angle)
        self.m00 = 1.0; self.m01 = 0.0; self.m02 = 0.0
        self.m10 = 0.0; self.m11 = c;   self.m12 = -s
        self.m20 = 0.0; self.m21 = s;   self.m22 = c
        return self

    def MakeYRotation(self, angle: float) -> "TGMatrix3":
        c, s = _math.cos(angle), _math.sin(angle)
        self.m00 = c;   self.m01 = 0.0; self.m02 = s
        self.m10 = 0.0; self.m11 = 1.0; self.m12 = 0.0
        self.m20 = -s;  self.m21 = 0.0; self.m22 = c
        return self

    def MakeZRotation(self, angle: float) -> "TGMatrix3":
        c, s = _math.cos(angle), _math.sin(angle)
        self.m00 = c;   self.m01 = -s;  self.m02 = 0.0
        self.m10 = s;   self.m11 = c;   self.m12 = 0.0
        self.m20 = 0.0; self.m21 = 0.0; self.m22 = 1.0
        return self

    def MakeRotation(self, angle: float, axis: TGPoint3) -> "TGMatrix3":
        """Rodrigues' rotation formula."""
        c, s = _math.cos(angle), _math.sin(angle)
        t = 1.0 - c
        x, y, z = axis.x, axis.y, axis.z
        self.m00 = t*x*x + c;   self.m01 = t*x*y - s*z; self.m02 = t*x*z + s*y
        self.m10 = t*x*y + s*z; self.m11 = t*y*y + c;   self.m12 = t*y*z - s*x
        self.m20 = t*x*z - s*y; self.m21 = t*y*z + s*x; self.m22 = t*z*z + c
        return self

    def MakeDiagonal(self, d: TGPoint3) -> "TGMatrix3":
        self.m00 = d.x; self.m01 = 0.0; self.m02 = 0.0
        self.m10 = 0.0; self.m11 = d.y; self.m12 = 0.0
        self.m20 = 0.0; self.m21 = 0.0; self.m22 = d.z
        return self
```

- [ ] **Step 4: Rewrite row/column/entry access**

```python
    # ── Row / Column / Entry access ───────────────────────────────────────────

    def GetRow(self, i: int) -> TGPoint3:
        if i == 0:
            return TGPoint3(self.m00, self.m01, self.m02)
        if i == 1:
            return TGPoint3(self.m10, self.m11, self.m12)
        if i == 2:
            return TGPoint3(self.m20, self.m21, self.m22)
        raise IndexError(i)

    def SetRow(self, i: int, v: TGPoint3) -> None:
        if i == 0:
            self.m00, self.m01, self.m02 = v.x, v.y, v.z
        elif i == 1:
            self.m10, self.m11, self.m12 = v.x, v.y, v.z
        elif i == 2:
            self.m20, self.m21, self.m22 = v.x, v.y, v.z
        else:
            raise IndexError(i)

    def GetCol(self, i: int) -> TGPoint3:
        if i == 0:
            return TGPoint3(self.m00, self.m10, self.m20)
        if i == 1:
            return TGPoint3(self.m01, self.m11, self.m21)
        if i == 2:
            return TGPoint3(self.m02, self.m12, self.m22)
        raise IndexError(i)

    def SetCol(self, i: int, v: TGPoint3) -> None:
        if i == 0:
            self.m00, self.m10, self.m20 = v.x, v.y, v.z
        elif i == 1:
            self.m01, self.m11, self.m21 = v.x, v.y, v.z
        elif i == 2:
            self.m02, self.m12, self.m22 = v.x, v.y, v.z
        else:
            raise IndexError(i)

    _ENTRY_NAMES = (("m00", "m01", "m02"),
                    ("m10", "m11", "m12"),
                    ("m20", "m21", "m22"))

    def GetEntry(self, i: int, j: int) -> float:
        return getattr(self, TGMatrix3._ENTRY_NAMES[i][j])

    def SetEntry(self, i: int, j: int, v: float) -> None:
        setattr(self, TGMatrix3._ENTRY_NAMES[i][j], float(v))

    def Set(self, *entries) -> None:
        """Set all 9 entries row-major: Set(m00,m01,m02, m10,m11,m12, m20,m21,m22)."""
        self.set_from_tuple(entries)
```

Note: `_ENTRY_NAMES` is a class attribute, which `__slots__` permits because it is
defined on the class, not assigned per instance.

- [ ] **Step 5: Rewrite `Transpose` and `MultMatrix`, preserving bit-exact arithmetic**

The arithmetic, its operand order, and the leading `0.0 +` are unchanged — only
where the numbers are read from changes. Keep the existing docstrings.

```python
    def Transpose(self) -> "TGMatrix3":
        result = TGMatrix3()
        result.m00 = self.m00; result.m01 = self.m10; result.m02 = self.m20
        result.m10 = self.m01; result.m11 = self.m11; result.m12 = self.m21
        result.m20 = self.m02; result.m21 = self.m12; result.m22 = self.m22
        return result

    def MultMatrix(self, other: "TGMatrix3") -> "TGMatrix3":
        # (keep the existing docstring verbatim — it explains the unrolling,
        #  the hot path, and why the leading `0.0 +` is load-bearing)
        a00, a01, a02 = self.m00, self.m01, self.m02
        a10, a11, a12 = self.m10, self.m11, self.m12
        a20, a21, a22 = self.m20, self.m21, self.m22
        b00, b01, b02 = other.m00, other.m01, other.m02
        b10, b11, b12 = other.m10, other.m11, other.m12
        b20, b21, b22 = other.m20, other.m21, other.m22

        result = TGMatrix3()
        result.m00 = 0.0 + a00 * b00 + a01 * b10 + a02 * b20
        result.m01 = 0.0 + a00 * b01 + a01 * b11 + a02 * b21
        result.m02 = 0.0 + a00 * b02 + a01 * b12 + a02 * b22
        result.m10 = 0.0 + a10 * b00 + a11 * b10 + a12 * b20
        result.m11 = 0.0 + a10 * b01 + a11 * b11 + a12 * b21
        result.m12 = 0.0 + a10 * b02 + a11 * b12 + a12 * b22
        result.m20 = 0.0 + a20 * b00 + a21 * b10 + a22 * b20
        result.m21 = 0.0 + a20 * b01 + a21 * b11 + a22 * b21
        result.m22 = 0.0 + a20 * b02 + a21 * b12 + a22 * b22
        return result
```

- [ ] **Step 6: Sweep the rest of `math.py`**

Run `grep -n "_m\b" engine/appc/math.py`. Every remaining hit inside `TGMatrix3`
(including `MultMatrixLeft` and any helper below `MultMatrix`) must be converted
to attribute access using the same mechanical rule: `self._m[i][j]` → `self.mIJ`.
Do not change any arithmetic.

- [ ] **Step 7: Run the matrix tests**

Run: `uv run pytest tests/unit/test_tgmatrix3_storage.py tests/unit/test_matrix_multiply_exact.py -q`
Expected: `test_tgmatrix3_storage.py` PASSES. `test_matrix_multiply_exact.py` FAILS — it pokes `._m` directly, which is the next step. Do not "fix" it by restoring `_m`.

- [ ] **Step 8: Update `tests/unit/test_matrix_multiply_exact.py`**

This test pins bit-exactness and must keep doing so. Convert only its storage
access, never its assertions:

```python
# line ~26, the reference implementation:
def _reference_mult(lhs, rhs):
    """Naive triple-loop reference, the form MultMatrix replaced."""
    result = TGMatrix3().MakeZero()
    for i in range(3):
        for j in range(3):
            acc = result.GetEntry(i, j)
            for k in range(3):
                acc += lhs.GetEntry(i, k) * rhs.GetEntry(k, j)
            result.SetEntry(i, j, acc)
    return result


# line ~42, the bit comparison:
def _assert_bit_identical(a, b, label):
    for i in range(3):
        for j in range(3):
            assert _bits(a.GetEntry(i, j)) == _bits(b.GetEntry(i, j)), (
                "%s: entry (%d,%d) differs: %r vs %r"
                % (label, i, j, a.GetEntry(i, j), b.GetEntry(i, j)))


# line ~49, the constructor helper:
def _mk(rows):
    m = TGMatrix3()
    m.set_from_tuple([v for row in rows for v in row])
    return m


# lines ~128-130, the aliasing check:
def test_result_does_not_alias_inputs():
    a = TGMatrix3()
    b = TGMatrix3()
    out = a.MultMatrix(b)
    out.m00 = 99.0
    assert a.m00 == 1.0
    assert b.m00 == 1.0
```

The `_reference_mult` accumulation must stay `acc = 0.0` then `+=` three times in
ascending `k`, matching the original — that is what makes the signed-zero case
meaningful.

- [ ] **Step 9: Update the remaining test consumers**

Apply the mechanical rule `X._m[i][j]` → `X.GetEntry(i, j)` (or the `mIJ`
attribute where `i`/`j` are literals) in:

- `tests/unit/test_interpolate.py:10` — `a = m._m` becomes `a = m.as_tuple()`; update its indexing to flat (`a[i*3+j]`).
- `tests/unit/test_interpolate.py:33,42` — `out._m[i][j]` → `out.GetEntry(i, j)`, `prev._m[i][j]` → `prev.GetEntry(i, j)`, `cur._m[i][j]` → `cur.GetEntry(i, j)`.
- `tests/unit/test_interpolate.py:76` — `m._m = [[0.0]*3]*3` → `m.MakeZero()`.
- `tests/unit/test_interpolate.py:108` — `m._m = [[1,0,0],[0,1,0],[0,0,1]]` → `m.MakeIdentity()`.
- `tests/unit/test_align_to_vectors_handedness.py:16` — `m = R._m` → `m = R.as_tuple()`, then flat indexing.
- `tests/host/test_world_matrices.py:164-165` — `rot._m[0][0]` → `rot.m00`, `rot._m[0][1]` → `rot.m01`.
- `tests/host/test_alert_keys.py:59` — `out._m = [row[:] for row in self._rot._m]` → `out.set_from_tuple(self._rot.as_tuple())`.
- `tests/host/test_player_control.py:84` — same replacement as above.
- `tests/host/test_player_control.py:206` — `final._m[r][c]` → `final.GetEntry(r, c)`, `initial._m[r][c]` → `initial.GetEntry(r, c)`.

- [ ] **Step 10: Update the four engine consumers**

`engine/host_loop.py:4381` (`_rot_determinant`):

```python
def _rot_determinant(rot) -> float:
    """3x3 determinant of a row-major BC TGMatrix3."""
    return (rot.m00 * (rot.m11*rot.m22 - rot.m12*rot.m21)
          - rot.m01 * (rot.m10*rot.m22 - rot.m12*rot.m20)
          + rot.m02 * (rot.m10*rot.m21 - rot.m11*rot.m20))
```

`engine/host_loop.py:4402-4404` (`_world_matrix_from`, keep its docstring verbatim):

```python
    return [
        rot.m00*s, rot.m01*s, rot.m02*s, loc.x,
        rot.m10*s, rot.m11*s, rot.m12*s, loc.y,
        rot.m20*s, rot.m21*s, rot.m22*s, loc.z,
        0.0,       0.0,       0.0,       1.0,
    ]
```

`engine/appc/backdrops.py:186-188` (keep the column-major comment verbatim):

```python
        m9 = [
            rot.m00, rot.m10, rot.m20,  # col 0 (right)
            rot.m01, rot.m11, rot.m21,  # col 1 (forward)
            rot.m02, rot.m12, rot.m22,  # col 2 (up)
        ]
```

`engine/appc/hull_bounds.py:130-137` (keep the world→body comment verbatim):

```python
    qx = R.m00 * dx + R.m10 * dy + R.m20 * dz
    qy = R.m01 * dx + R.m11 * dy + R.m21 * dz
    qz = R.m02 * dx + R.m12 * dy + R.m22 * dz
```

Delete the now-unused `m = R._m` line.

`engine/appc/objects.py:352` and `:357` (`GetRotation` and `GetWorldRotation`):

```python
    def GetRotation(self) -> TGMatrix3:
        result = TGMatrix3()
        result.set_from_tuple(self._rotation.as_tuple())
        return result

    def GetWorldRotation(self) -> TGMatrix3:
        result = TGMatrix3()
        result.set_from_tuple(self._rotation.as_tuple())
        return result
```

- [ ] **Step 11: Prove no `_m` reference survives**

Run: `grep -rn "\._m\b" engine/ tools/`
Expected: **zero** hits. (In `tests/`, the only surviving hits must be
`tests/ui/test_crew_menu_station_name.py` and `tests/unit/test_episode_goals.py`,
which use `self._m` for unrelated dict mappings and must not be touched.)

- [ ] **Step 12: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: only the ledgered `test_engineer_emitters.py::test_shield_level_change_announces` failure. Any other failure is a regression from this task.

- [ ] **Step 13: Commit**

```bash
git add engine/appc/math.py engine/appc/objects.py engine/appc/backdrops.py \
        engine/appc/hull_bounds.py engine/host_loop.py \
        tests/unit/test_tgmatrix3_storage.py tests/unit/test_matrix_multiply_exact.py \
        tests/unit/test_interpolate.py tests/unit/test_align_to_vectors_handedness.py \
        tests/host/test_world_matrices.py tests/host/test_alert_keys.py \
        tests/host/test_player_control.py
git commit -m "perf(math): flatten TGMatrix3 to nine slotted floats

Drops ~5 of ~6 allocations per matrix. GetWorldRotation builds one on
every call at 70 call sites, per object, per frame.

MultMatrix arithmetic, operand order and the load-bearing leading 0.0+
are unchanged; test_matrix_multiply_exact still pins bit-exactness.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `TransformStore` contract and pure-Python backend

Establishes the interface and the fallback implementation. Nothing consumes it yet, so behaviour is unchanged by construction. The conformance suite written here is what later stops the two backends drifting.

**Files:**
- Create: `engine/appc/transform_store.py`
- Create: `tests/unit/test_transform_store_conformance.py`

**Interfaces:**
- Consumes: `TGMatrix3.as_tuple()` / `set_from_tuple()` from Task 1.
- Produces:
  - `class StaleHandleError(RuntimeError)`
  - `class PythonTransformStore` implementing the contract below.
  - `def get_store() -> TransformStore` — module-level singleton accessor, selecting the backend once. In this task it always returns `PythonTransformStore`; Task 3 adds selection.
  - Contract (all indices `int`, all generations `int`, rotations row-major nine-float tuples):
    - `alloc() -> tuple[int, int]` returns `(index, generation)`; new slots are identity rotation at the origin.
    - `free(index: int, generation: int) -> None`; freeing a stale handle raises `StaleHandleError`.
    - `get_position(index, generation) -> tuple[float, float, float]`
    - `set_position(index, generation, x: float, y: float, z: float) -> None`
    - `get_rotation(index, generation) -> tuple` (nine floats, row-major)
    - `set_rotation(index, generation, t9) -> None`
    - `get_rotation_col(index, generation, col: int) -> tuple[float, float, float]`; `col` outside 0..2 raises `IndexError`.
    - `live_count() -> int` — number of currently allocated slots.
    - `capacity() -> int` — number of slots ever created, i.e. the high-water mark. Used to prove the free list is actually reused rather than growing forever.
  - Every accessor raises `StaleHandleError` when the generation does not match.
  - Task 5 extends this contract with `get_positions(handles) -> list[tuple[float, float, float]]`.

- [ ] **Step 1: Write the failing conformance test**

Create `tests/unit/test_transform_store_conformance.py`:

```python
"""One contract, run against every TransformStore backend.

Two backends that are never live at the same time are only safe if something
proves they agree. This is that something. Task 3 adds the native backend to
STORE_FACTORIES; until then it runs against the Python one alone.
"""
import gc

import pytest

from engine.appc.transform_store import PythonTransformStore, StaleHandleError

STORE_FACTORIES = [pytest.param(PythonTransformStore, id="python")]

IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


@pytest.fixture(params=STORE_FACTORIES)
def store(request):
    return request.param()


def test_new_slot_is_identity_at_origin(store):
    i, g = store.alloc()
    assert store.get_position(i, g) == (0.0, 0.0, 0.0)
    assert store.get_rotation(i, g) == IDENTITY


def test_position_round_trips(store):
    i, g = store.alloc()
    store.set_position(i, g, 1.5, -2.5, 3.25)
    assert store.get_position(i, g) == (1.5, -2.5, 3.25)


def test_rotation_round_trips(store):
    i, g = store.alloc()
    src = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
    store.set_rotation(i, g, src)
    assert store.get_rotation(i, g) == src


def test_rotation_col_reads_columns(store):
    """Column-vector convention: col 1 is forward."""
    i, g = store.alloc()
    store.set_rotation(i, g, (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0))
    assert store.get_rotation_col(i, g, 0) == (1.0, 4.0, 7.0)
    assert store.get_rotation_col(i, g, 1) == (2.0, 5.0, 8.0)
    assert store.get_rotation_col(i, g, 2) == (3.0, 6.0, 9.0)


def test_slots_are_independent(store):
    a_i, a_g = store.alloc()
    b_i, b_g = store.alloc()
    store.set_position(a_i, a_g, 1.0, 1.0, 1.0)
    store.set_position(b_i, b_g, 2.0, 2.0, 2.0)
    assert store.get_position(a_i, a_g) == (1.0, 1.0, 1.0)
    assert store.get_position(b_i, b_g) == (2.0, 2.0, 2.0)


def test_freed_handle_is_stale(store):
    i, g = store.alloc()
    store.free(i, g)
    with pytest.raises(StaleHandleError):
        store.get_position(i, g)
    with pytest.raises(StaleHandleError):
        store.set_position(i, g, 0.0, 0.0, 0.0)
    with pytest.raises(StaleHandleError):
        store.get_rotation(i, g)


def test_double_free_raises(store):
    i, g = store.alloc()
    store.free(i, g)
    with pytest.raises(StaleHandleError):
        store.free(i, g)


def test_reused_index_gets_a_new_generation(store):
    """The whole point of the generation counter: a stale handle must not
    silently read whatever object recycled its index."""
    i1, g1 = store.alloc()
    store.free(i1, g1)
    i2, g2 = store.alloc()
    assert i2 == i1, "expected the free list to reuse the index"
    assert g2 != g1
    store.set_position(i2, g2, 5.0, 5.0, 5.0)
    with pytest.raises(StaleHandleError):
        store.get_position(i1, g1)


def test_live_count_tracks_alloc_and_free(store):
    assert store.live_count() == 0
    handles = [store.alloc() for _ in range(10)]
    assert store.live_count() == 10
    for i, g in handles[:4]:
        store.free(i, g)
    assert store.live_count() == 6


def test_many_alloc_free_cycles_do_not_leak(store):
    """Torpedoes churn hard; the free list must actually be reused."""
    for _ in range(1000):
        i, g = store.alloc()
        store.free(i, g)
    assert store.live_count() == 0
    assert store.capacity() <= 4, (
        "free list is not being reused; capacity grew to %d" % store.capacity())


def test_growth_preserves_existing_slots(store):
    handles = []
    for n in range(200):
        i, g = store.alloc()
        store.set_position(i, g, float(n), 0.0, 0.0)
        handles.append((i, g, n))
    for i, g, n in handles:
        assert store.get_position(i, g) == (float(n), 0.0, 0.0)
```

Note this test also requires `capacity() -> int` on the contract.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_transform_store_conformance.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.transform_store'`.

- [ ] **Step 3: Implement the Python backend**

Create `engine/appc/transform_store.py`:

```python
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


_STORE = None


def get_store():
    """The process-wide transform store. Backend selected once, on first use.

    Resolved at USE, never at import: a module-level constant would freeze the
    choice before the host has had a chance to load the extension.
    """
    global _STORE
    if _STORE is None:
        _STORE = PythonTransformStore()
    return _STORE


def _reset_store_for_tests() -> None:
    """Drop the singleton so a test can start from an empty store."""
    global _STORE
    _STORE = None
```

- [ ] **Step 4: Run the conformance suite**

Run: `uv run pytest tests/unit/test_transform_store_conformance.py -q`
Expected: PASS, all tests, `python` param only.

- [ ] **Step 5: Reset the singleton between tests**

Add to `tests/conftest.py`'s existing autouse `_reset_leakable_engine_globals`
fixture (find it by `grep -n "_reset_leakable_engine_globals" tests/conftest.py`):

```python
    from engine.appc import transform_store
    transform_store._reset_store_for_tests()
```

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: only the ledgered failure.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/transform_store.py \
        tests/unit/test_transform_store_conformance.py tests/conftest.py
git commit -m "feat(transforms): TransformStore contract + Python backend

Generation-counted slot handles so a stale handle fails loudly instead of
reading whatever object recycled its index. No callers yet.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Native `TransformStore` and pybind11 bindings

**Before starting:** replace the borrowed `.so` (see Pre-flight above). `rm -rf build && cmake -B build -S . && cmake --build build -j`.

**Files:**
- Create: `native/src/transforms/CMakeLists.txt`
- Create: `native/src/transforms/include/dauntless/transform_store.h`
- Create: `native/src/transforms/src/transform_store.cc`
- Create: `native/tests/test_transform_store.cc`
- Modify: `native/CMakeLists.txt` (add `add_subdirectory(src/transforms)` beside the existing `add_subdirectory(src/audio)` at line 139)
- Modify: `native/src/host/host_bindings.cc` (bindings)
- Modify: `native/src/host/CMakeLists.txt` (link `dauntless_transforms`)
- Modify: `engine/appc/transform_store.py` (native backend + selection)
- Modify: `tests/unit/test_transform_store_conformance.py` (add the native param)

**Interfaces:**
- Consumes: the contract from Task 2.
- Produces:
  - C++ `dauntless::TransformStore` with methods `alloc()`, `free()`, `position()`, `set_position()`, `rotation()`, `set_rotation()`, `rotation_col()`, `live_count()`, `capacity()`, and `dauntless::transform_store()` returning the process-wide instance by reference.
  - Python bindings on `_dauntless_host`: `transform_alloc()`, `transform_free(i, g)`, `transform_get_position(i, g)`, `transform_set_position(i, g, x, y, z)`, `transform_get_rotation(i, g)`, `transform_set_rotation(i, g, t9)`, `transform_get_rotation_col(i, g, col)`, `transform_live_count()`, `transform_capacity()`. A stale handle raises Python `RuntimeError`, which the Python backend wrapper re-raises as `StaleHandleError`.
  - `NativeTransformStore` in `engine/appc/transform_store.py`, and `get_store()` returning it when `_dauntless_host` exposes `transform_alloc`.

- [ ] **Step 1: Write the failing C++ test**

Create `native/tests/test_transform_store.cc`:

```cpp
#include <gtest/gtest.h>
#include "dauntless/transform_store.h"

using dauntless::TransformStore;

TEST(TransformStoreTest, NewSlotIsIdentityAtOrigin) {
    TransformStore s;
    auto [i, g] = s.alloc();
    auto p = s.position(i, g);
    EXPECT_FLOAT_EQ(p[0], 0.0f);
    EXPECT_FLOAT_EQ(p[1], 0.0f);
    EXPECT_FLOAT_EQ(p[2], 0.0f);
    auto r = s.rotation(i, g);
    EXPECT_FLOAT_EQ(r[0], 1.0f);
    EXPECT_FLOAT_EQ(r[4], 1.0f);
    EXPECT_FLOAT_EQ(r[8], 1.0f);
}

TEST(TransformStoreTest, ReusedIndexGetsNewGeneration) {
    TransformStore s;
    auto [i1, g1] = s.alloc();
    s.free(i1, g1);
    auto [i2, g2] = s.alloc();
    EXPECT_EQ(i2, i1);
    EXPECT_NE(g2, g1);
    EXPECT_FALSE(s.valid(i1, g1));
    EXPECT_TRUE(s.valid(i2, g2));
}

TEST(TransformStoreTest, GrowthPreservesExistingSlots) {
    TransformStore s;
    std::vector<std::pair<std::uint32_t, std::uint32_t>> handles;
    for (int n = 0; n < 500; ++n) {
        auto h = s.alloc();
        s.set_position(h.first, h.second,
                       static_cast<float>(n), 0.0f, 0.0f);
        handles.push_back(h);
    }
    for (int n = 0; n < 500; ++n) {
        auto p = s.position(handles[n].first, handles[n].second);
        EXPECT_FLOAT_EQ(p[0], static_cast<float>(n));
    }
}

TEST(TransformStoreTest, RotationColReadsColumns) {
    TransformStore s;
    auto [i, g] = s.alloc();
    const std::array<float, 9> m{1, 2, 3, 4, 5, 6, 7, 8, 9};
    s.set_rotation(i, g, m);
    auto c1 = s.rotation_col(i, g, 1);
    EXPECT_FLOAT_EQ(c1[0], 2.0f);
    EXPECT_FLOAT_EQ(c1[1], 5.0f);
    EXPECT_FLOAT_EQ(c1[2], 8.0f);
}

TEST(TransformStoreTest, FreeListIsReused) {
    TransformStore s;
    for (int n = 0; n < 1000; ++n) {
        auto h = s.alloc();
        s.free(h.first, h.second);
    }
    EXPECT_EQ(s.live_count(), 0u);
    EXPECT_LE(s.capacity(), 4u);
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: FAIL — `dauntless/transform_store.h` not found.

- [ ] **Step 3: Write the header**

Create `native/src/transforms/include/dauntless/transform_store.h`:

```cpp
#pragma once

#include <array>
#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

namespace dauntless {

// Thrown when a handle's generation no longer matches its slot.
class StaleHandle : public std::runtime_error {
public:
    StaleHandle(std::uint32_t index, std::uint32_t generation);
};

// Contiguous, index-addressed storage for every object's world transform.
//
// Position and rotation live here rather than on the Python object so that
// the renderer and the motion integrator can read them without crossing the
// language boundary. Rotation is row-major nine floats, matching TGMatrix3's
// mIJ = row I, column J. Column-vector convention: column 1 is forward.
//
// Slots are generation-counted: a handle to a freed slot fails loudly rather
// than silently reading whatever object recycled its index. Indices stay
// valid across growth, which is why callers receive an index and never a
// pointer — the backing vector reallocates.
//
// NOT internally synchronised. The threaded integrator (spec phase 5) works
// on disjoint slots inside a window where the GIL is released and no other
// code runs, so no locking is required or wanted here.
class TransformStore {
public:
    struct Transform {
        float pos[3];
        float rot[9];
    };

    // Returns (index, generation). New slots are identity at the origin.
    std::pair<std::uint32_t, std::uint32_t> alloc();
    void free(std::uint32_t index, std::uint32_t generation);

    bool valid(std::uint32_t index, std::uint32_t generation) const;

    std::array<float, 3> position(std::uint32_t index,
                                  std::uint32_t generation) const;
    void set_position(std::uint32_t index, std::uint32_t generation,
                      float x, float y, float z);

    std::array<float, 9> rotation(std::uint32_t index,
                                  std::uint32_t generation) const;
    void set_rotation(std::uint32_t index, std::uint32_t generation,
                      const std::array<float, 9>& r);

    std::array<float, 3> rotation_col(std::uint32_t index,
                                      std::uint32_t generation,
                                      int col) const;

    std::uint32_t live_count() const { return live_; }
    std::uint32_t capacity() const {
        return static_cast<std::uint32_t>(generations_.size());
    }

    // Unchecked access for the render and integrate paths, which have already
    // validated the handle. Callers must not retain the reference across an
    // alloc().
    const Transform& at(std::uint32_t index) const { return slots_[index]; }
    Transform& at(std::uint32_t index) { return slots_[index]; }

private:
    void check(std::uint32_t index, std::uint32_t generation) const;

    std::vector<Transform> slots_;
    std::vector<std::uint32_t> generations_;
    std::vector<std::uint32_t> free_;
    std::uint32_t live_ = 0;
};

// The process-wide store.
TransformStore& transform_store();

}  // namespace dauntless
```

- [ ] **Step 4: Write the implementation**

Create `native/src/transforms/src/transform_store.cc`:

```cpp
#include "dauntless/transform_store.h"

#include <string>

namespace dauntless {

namespace {
constexpr float kIdentity[9] = {1.0f, 0.0f, 0.0f,
                                0.0f, 1.0f, 0.0f,
                                0.0f, 0.0f, 1.0f};
}  // namespace

StaleHandle::StaleHandle(std::uint32_t index, std::uint32_t generation)
    : std::runtime_error("transform handle (" + std::to_string(index) + ", " +
                         std::to_string(generation) + ") is stale") {}

std::pair<std::uint32_t, std::uint32_t> TransformStore::alloc() {
    std::uint32_t index;
    if (!free_.empty()) {
        index = free_.back();
        free_.pop_back();
        ++generations_[index];
    } else {
        index = static_cast<std::uint32_t>(generations_.size());
        generations_.push_back(1);
        slots_.emplace_back();
    }
    Transform& t = slots_[index];
    t.pos[0] = t.pos[1] = t.pos[2] = 0.0f;
    for (int i = 0; i < 9; ++i) t.rot[i] = kIdentity[i];
    ++live_;
    return {index, generations_[index]};
}

void TransformStore::free(std::uint32_t index, std::uint32_t generation) {
    check(index, generation);
    // Bump on free as well as on reuse, so a handle to a freed-but-not-yet
    // reused slot is stale immediately.
    ++generations_[index];
    free_.push_back(index);
    --live_;
}

bool TransformStore::valid(std::uint32_t index,
                           std::uint32_t generation) const {
    return index < generations_.size() && generations_[index] == generation;
}

void TransformStore::check(std::uint32_t index,
                           std::uint32_t generation) const {
    if (!valid(index, generation)) throw StaleHandle(index, generation);
}

std::array<float, 3> TransformStore::position(
        std::uint32_t index, std::uint32_t generation) const {
    check(index, generation);
    const Transform& t = slots_[index];
    return {t.pos[0], t.pos[1], t.pos[2]};
}

void TransformStore::set_position(std::uint32_t index, std::uint32_t generation,
                                  float x, float y, float z) {
    check(index, generation);
    Transform& t = slots_[index];
    t.pos[0] = x;
    t.pos[1] = y;
    t.pos[2] = z;
}

std::array<float, 9> TransformStore::rotation(
        std::uint32_t index, std::uint32_t generation) const {
    check(index, generation);
    const Transform& t = slots_[index];
    std::array<float, 9> out{};
    for (int i = 0; i < 9; ++i) out[i] = t.rot[i];
    return out;
}

void TransformStore::set_rotation(std::uint32_t index, std::uint32_t generation,
                                  const std::array<float, 9>& r) {
    check(index, generation);
    Transform& t = slots_[index];
    for (int i = 0; i < 9; ++i) t.rot[i] = r[i];
}

std::array<float, 3> TransformStore::rotation_col(
        std::uint32_t index, std::uint32_t generation, int col) const {
    check(index, generation);
    if (col < 0 || col > 2) throw std::out_of_range("rotation column");
    const Transform& t = slots_[index];
    return {t.rot[col], t.rot[3 + col], t.rot[6 + col]};
}

TransformStore& transform_store() {
    static TransformStore store;
    return store;
}

}  // namespace dauntless
```

- [ ] **Step 5: Add the CMake target**

Create `native/src/transforms/CMakeLists.txt`, following the `dauntless_audio`
pattern (headers only for Python — never link the embed libpython into a static
lib pulled into the module):

```cmake
add_library(dauntless_transforms STATIC
    src/transform_store.cc
)
target_include_directories(dauntless_transforms PUBLIC include)
target_compile_features(dauntless_transforms PUBLIC cxx_std_20)
```

Add to `native/CMakeLists.txt` beside the other subdirectories (line ~139):

```cmake
add_subdirectory(src/transforms)
```

Register the C++ test with the project's existing ctest pattern — find how
another native test is registered (`grep -rn "add_test\|gtest_discover_tests" native/`)
and follow it exactly for `native/tests/test_transform_store.cc`, linking
`dauntless_transforms`.

- [ ] **Step 6: Run the C++ test**

Run: `cmake --build build -j && ctest --test-dir build -R TransformStoreTest --output-on-failure`
Expected: PASS, 5 tests.

- [ ] **Step 7: Add the pybind11 bindings**

In `native/src/host/host_bindings.cc`, add `#include "dauntless/transform_store.h"`
at the top with the other includes, and register the bindings alongside the
existing `m.def(...)` calls:

```cpp
    // ── Transform store ──────────────────────────────────────────────────────
    // Authoritative position/rotation for every ObjectClass. See
    // docs/superpowers/specs/2026-09-05-native-transform-ownership-design.md.
    m.def("transform_alloc", []() {
              return dauntless::transform_store().alloc();
          },
          "Allocate a transform slot. Returns (index, generation).");

    m.def("transform_free",
          [](std::uint32_t i, std::uint32_t g) {
              dauntless::transform_store().free(i, g);
          },
          py::arg("index"), py::arg("generation"),
          "Release a transform slot. Raises RuntimeError if the handle is stale.");

    m.def("transform_get_position",
          [](std::uint32_t i, std::uint32_t g) {
              return dauntless::transform_store().position(i, g);
          },
          py::arg("index"), py::arg("generation"));

    m.def("transform_set_position",
          [](std::uint32_t i, std::uint32_t g, float x, float y, float z) {
              dauntless::transform_store().set_position(i, g, x, y, z);
          },
          py::arg("index"), py::arg("generation"),
          py::arg("x"), py::arg("y"), py::arg("z"));

    m.def("transform_get_rotation",
          [](std::uint32_t i, std::uint32_t g) {
              return dauntless::transform_store().rotation(i, g);
          },
          py::arg("index"), py::arg("generation"),
          "Row-major nine floats.");

    m.def("transform_set_rotation",
          [](std::uint32_t i, std::uint32_t g, const std::array<float, 9>& r) {
              dauntless::transform_store().set_rotation(i, g, r);
          },
          py::arg("index"), py::arg("generation"), py::arg("rot9"));

    m.def("transform_get_rotation_col",
          [](std::uint32_t i, std::uint32_t g, int col) {
              return dauntless::transform_store().rotation_col(i, g, col);
          },
          py::arg("index"), py::arg("generation"), py::arg("col"));

    m.def("transform_live_count", []() {
              return dauntless::transform_store().live_count();
          });

    m.def("transform_capacity", []() {
              return dauntless::transform_store().capacity();
          });
```

`std::array` conversions need `#include <pybind11/stl.h>`; check whether the file
already has it (`grep -n "pybind11/stl.h" native/src/host/host_bindings.cc`) and
add it if not.

Link the library in `native/src/host/CMakeLists.txt`: add
`dauntless_transforms` to the same `target_link_libraries` list that already
names `dauntless_audio`.

- [ ] **Step 8: Register the bindings in the host_io manifest**

`engine/host_io.py` validates the live module against a binding manifest.
Add all nine names to the `_REQUIRED_BINDINGS` list (find it by
`grep -n "_REQUIRED_BINDINGS" engine/host_io.py`). A missing one must fail
loudly as a stale build rather than degrade silently.

- [ ] **Step 9: Rebuild and add the native backend**

Run: `cmake --build build -j`

Then add to `engine/appc/transform_store.py`:

```python
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
```

And replace `get_store()`:

```python
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
```

- [ ] **Step 10: Add the native backend to the conformance suite**

In `tests/unit/test_transform_store_conformance.py`, replace `STORE_FACTORIES`:

```python
import pytest

from engine.appc.transform_store import (
    NativeTransformStore, PythonTransformStore, StaleHandleError)

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

_HAS_NATIVE = _h is not None and hasattr(_h, "transform_alloc")

STORE_FACTORIES = [
    pytest.param(PythonTransformStore, id="python"),
    pytest.param(
        lambda: NativeTransformStore(_h), id="native",
        marks=pytest.mark.skipif(
            not _HAS_NATIVE,
            reason="native _dauntless_host transform bindings not built")),
]
```

**Note the native store is a process-wide singleton**, so `live_count()` and
`capacity()` do not start at zero across tests. Adjust the two tests that assert
absolute counts (`test_live_count_tracks_alloc_and_free`,
`test_many_alloc_free_cycles_do_not_leak`) to measure **deltas** from a baseline
captured at the start of the test, e.g.:

```python
def test_live_count_tracks_alloc_and_free(store):
    base = store.live_count()
    handles = [store.alloc() for _ in range(10)]
    assert store.live_count() - base == 10
    for i, g in handles[:4]:
        store.free(i, g)
    assert store.live_count() - base == 6
```

and for the churn test, assert capacity does not grow by more than a small
constant rather than asserting an absolute bound.

- [ ] **Step 11: Run the conformance suite against both backends**

Run: `uv run pytest tests/unit/test_transform_store_conformance.py -v`
Expected: every test PASSES twice, once per backend. **No skips** — a skipped
native param means the build did not produce the bindings; rebuild.

- [ ] **Step 12: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: only the ledgered failure.

- [ ] **Step 13: Commit**

```bash
git add native/src/transforms native/tests/test_transform_store.cc \
        native/CMakeLists.txt native/src/host/host_bindings.cc \
        native/src/host/CMakeLists.txt engine/appc/transform_store.py \
        engine/host_io.py tests/unit/test_transform_store_conformance.py
git commit -m "feat(transforms): native TransformStore + bindings

Contiguous generation-counted slots in C++, bound to Python and running
the same conformance suite as the pure-Python backend.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `ObjectClass` switches to store-backed transforms — **LIVE CHECKPOINT**

The highest-risk task: every object's transform moves, and nothing should look different. This is also where the `SetMatrixRotation` aliasing change lands.

**Files:**
- Modify: `engine/appc/objects.py` (`ObjectClass.__init__` line ~57, translation accessors ~284-305, rotation accessors ~344-400, direction helpers ~497-520)
- Modify: the 29 private-field sites — enumerate with `grep -rn "\._position\b\|\._rotation\b" engine/ | grep -v "^engine/appc/objects.py"`, covering `engine/host_loop.py`, `engine/appc/properties.py`, `engine/appc/weapon_subsystems.py`, `engine/appc/object_emitter.py`, `engine/appc/subsystems.py`, `engine/appc/projectiles.py`
- Create: `tests/unit/test_object_transform_slots.py`

**Interfaces:**
- Consumes: `get_store()`, `StaleHandleError` (Task 2/3); `TGMatrix3.as_tuple()`/`set_from_tuple()` (Task 1).
- Produces: `ObjectClass._xform` — a `tuple[int, int]` handle. `ObjectClass._position` and `ObjectClass._rotation` **no longer exist as attributes**; all access goes through the accessors.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_object_transform_slots.py`:

```python
"""ObjectClass transforms live in the TransformStore, not on the instance."""
import gc

import pytest

from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.objects import ObjectClass
from engine.appc.transform_store import StaleHandleError, get_store


def test_object_has_a_slot_handle():
    o = ObjectClass()
    assert isinstance(o._xform, tuple) and len(o._xform) == 2


def test_private_position_attribute_is_gone():
    o = ObjectClass()
    assert not hasattr(o, "_position")
    assert not hasattr(o, "_rotation")


def test_position_round_trips_through_accessors():
    o = ObjectClass()
    o.SetTranslateXYZ(1.5, -2.5, 3.25)
    p = o.GetTranslate()
    assert (p.x, p.y, p.z) == (1.5, -2.5, 3.25)
    w = o.GetWorldLocation()
    assert (w.x, w.y, w.z) == (1.5, -2.5, 3.25)


def test_getters_return_independent_copies():
    """Established contract: callers may mutate what they get back, and the
    mutation must not write through to the object."""
    o = ObjectClass()
    o.SetTranslateXYZ(1.0, 2.0, 3.0)
    p = o.GetTranslate()
    p.x = 99.0
    assert o.GetTranslate().x == 1.0


def test_rotation_round_trips():
    o = ObjectClass()
    m = TGMatrix3()
    m.MakeZRotation(0.5)
    o.SetMatrixRotation(m)
    assert o.GetWorldRotation().as_tuple() == m.as_tuple()


def test_set_matrix_rotation_copies_and_does_not_alias():
    """BEHAVIOUR CHANGE, pinned deliberately.

    objects.py previously did `self._rotation = matrix`, storing the caller's
    matrix BY REFERENCE, so mutating it afterwards silently re-oriented the
    object. Writing into the store copies instead. This test records that as a
    decision so nobody 'fixes' it back.
    """
    o = ObjectClass()
    m = TGMatrix3()
    m.MakeIdentity()
    o.SetMatrixRotation(m)
    m.m00 = 99.0
    assert o.GetWorldRotation().m00 == 1.0


def test_get_world_rotation_returns_a_copy():
    o = ObjectClass()
    r = o.GetWorldRotation()
    r.m00 = 42.0
    assert o.GetWorldRotation().m00 == 1.0


def test_direction_helpers_read_columns():
    """GetCol(1) is forward — never GetRow(1)."""
    o = ObjectClass()
    m = TGMatrix3()
    m.Set(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
    o.SetMatrixRotation(m)
    fwd = o.GetWorldForwardTG()
    assert (fwd.x, fwd.y, fwd.z) == (2.0, 5.0, 8.0)


def test_slot_is_released_when_object_is_collected():
    store = get_store()
    before = store.live_count()
    o = ObjectClass()
    handle = o._xform
    assert store.live_count() == before + 1
    del o
    gc.collect()
    assert store.live_count() == before
    with pytest.raises(StaleHandleError):
        store.get_position(*handle)


def test_slot_released_even_in_a_reference_cycle():
    """ObjectClass instances sit in cycles (they are event handlers and the
    event manager holds refs back), which is why release uses
    weakref.finalize rather than __del__."""
    store = get_store()
    before = store.live_count()
    o = ObjectClass()
    o._self_cycle = o          # deliberate cycle
    handle = o._xform
    del o
    gc.collect()
    assert store.live_count() == before
    with pytest.raises(StaleHandleError):
        store.get_position(*handle)


def test_many_objects_do_not_leak_slots():
    store = get_store()
    before = store.live_count()
    for _ in range(500):
        ObjectClass()
    gc.collect()
    assert store.live_count() == before
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_object_transform_slots.py -q`
Expected: FAIL — `AttributeError: 'ObjectClass' object has no attribute '_xform'`.

- [ ] **Step 3: Allocate the slot in `ObjectClass.__init__`**

In `engine/appc/objects.py`, add the import at module level and replace the
`self._position` / `self._rotation` initialisation:

```python
import weakref

from engine.appc.transform_store import get_store
```

```python
        # Transform lives in the TransformStore, not on the instance. The
        # handle is (index, generation); the generation makes a stale handle
        # fail loudly instead of reading whatever object recycled the index.
        _store = get_store()
        self._xform = _store.alloc()
        # weakref.finalize, NOT __del__: ObjectClass instances sit in
        # reference cycles (they are event handlers and the event manager
        # holds refs back), and __del__ on a cycle member is unreliable.
        self._xform_finalizer = weakref.finalize(
            self, _release_transform_slot, _store, self._xform)
```

And at module scope:

```python
def _release_transform_slot(store, handle) -> None:
    """Free an object's transform slot. Registered via weakref.finalize, so it
    runs on collection even when the object is part of a cycle."""
    try:
        store.free(*handle)
    except Exception:
        # A store reset (tests) or interpreter teardown can invalidate the
        # handle first; a failed release must never propagate out of a
        # finalizer.
        pass
```

- [ ] **Step 4: Convert the translation accessors**

Replace `SetTranslateXYZ`, `SetTranslate`, `SetWorldLocation`, `GetTranslate`
and `GetWorldLocation` (lines ~284-305), keeping every docstring verbatim:

```python
    def SetTranslateXYZ(self, x: float, y: float, z: float) -> None:
        get_store().set_position(*self._xform, float(x), float(y), float(z))

    def SetTranslate(self, point: TGPoint3) -> None:
        get_store().set_position(*self._xform,
                                 float(point.x), float(point.y), float(point.z))

    def SetWorldLocation(self, pos) -> None:
        # (keep the existing docstring verbatim)
        if hasattr(pos, 'x'):
            get_store().set_position(*self._xform,
                                     float(pos.x), float(pos.y), float(pos.z))
        else:
            get_store().set_position(*self._xform,
                                     float(pos[0]), float(pos[1]), float(pos[2]))

    def GetTranslate(self) -> TGPoint3:
        x, y, z = get_store().get_position(*self._xform)
        return TGPoint3(x, y, z)

    def GetWorldLocation(self) -> TGPoint3:
        x, y, z = get_store().get_position(*self._xform)
        return TGPoint3(x, y, z)
```

- [ ] **Step 5: Convert the rotation accessors**

Replace `SetMatrixRotation`, `GetRotation`, `GetWorldRotation` and the two other
`self._rotation = m` assignments at lines ~363 and ~397 (find them with
`grep -n "_rotation" engine/appc/objects.py`):

```python
    def SetMatrixRotation(self, matrix: TGMatrix3) -> None:
        """Set this object's rotation.

        NOTE the matrix is COPIED into the transform store. This differs from
        the pre-store behaviour, which kept the caller's matrix by reference so
        later mutations of it silently re-oriented the object. Pinned by
        tests/unit/test_object_transform_slots.py.
        """
        get_store().set_rotation(*self._xform, matrix.as_tuple())

    def GetRotation(self) -> TGMatrix3:
        result = TGMatrix3()
        result.set_from_tuple(get_store().get_rotation(*self._xform))
        return result

    def GetWorldRotation(self) -> TGMatrix3:
        result = TGMatrix3()
        result.set_from_tuple(get_store().get_rotation(*self._xform))
        return result
```

For the two other `self._rotation = m` sites, use
`get_store().set_rotation(*self._xform, m.as_tuple())`.

- [ ] **Step 6: Convert the direction helpers to single-column reads**

There are **six** helpers (lines ~497-522), currently reading
`self._rotation.GetCol(n)`. Under the store they must not build a matrix
either — that is the point. Column indices are unchanged: 0 starboard,
1 forward, 2 up. Keep every existing docstring and comment verbatim,
including the `__getattr__` / `_Stub` warning above `GetWorldBackwardTG`.

```python
    def GetWorldForwardTG(self) -> TGPoint3:
        # (keep the existing docstring verbatim)
        x, y, z = get_store().get_rotation_col(*self._xform, 1)
        return TGPoint3(x, y, z)

    # (keep the existing six-line comment about __getattr__ / _Stub verbatim)
    def GetWorldBackwardTG(self) -> TGPoint3:
        x, y, z = get_store().get_rotation_col(*self._xform, 1)
        return TGPoint3(-x, -y, -z)

    def GetWorldUpTG(self) -> TGPoint3:
        x, y, z = get_store().get_rotation_col(*self._xform, 2)
        return TGPoint3(x, y, z)

    def GetWorldDownTG(self) -> TGPoint3:
        x, y, z = get_store().get_rotation_col(*self._xform, 2)
        return TGPoint3(-x, -y, -z)

    def GetWorldRightTG(self) -> TGPoint3:
        x, y, z = get_store().get_rotation_col(*self._xform, 0)
        return TGPoint3(x, y, z)

    def GetWorldLeftTG(self) -> TGPoint3:
        x, y, z = get_store().get_rotation_col(*self._xform, 0)
        return TGPoint3(-x, -y, -z)
```

- [ ] **Step 7: Convert the 29 external private-field sites**

Run: `grep -rn "\._position\b\|\._rotation\b" engine/ | grep -v "^engine/appc/objects.py"`

For each hit apply the mechanical rule:
- read of `obj._position` → `obj.GetTranslate()`
- write of `obj._position = TGPoint3(a, b, c)` → `obj.SetTranslateXYZ(a, b, c)`
- read of `obj._rotation` → `obj.GetWorldRotation()`
- write of `obj._rotation = m` → `obj.SetMatrixRotation(m)`

**Read each site before converting.** A site inside a per-frame loop that reads
`._rotation` several times should call `GetWorldRotation()` **once** into a local
rather than once per use — the accessor is no longer free.

- [ ] **Step 8: Run the new test**

Run: `uv run pytest tests/unit/test_object_transform_slots.py -q`
Expected: PASS.

- [ ] **Step 9: Hunt the aliasing dependency**

Run: `grep -rn "SetMatrixRotation" engine/ sdk/Build/scripts/`

Inspect every caller. The risk is a caller that keeps the matrix it passed and
mutates it afterwards, expecting the object to follow. If any exists, it must be
converted to call `SetMatrixRotation` again after mutating, and noted in the
commit message. Record the finding either way — "checked, none found" is the
outcome to report, not silence.

- [ ] **Step 10: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: only the ledgered failure.

- [ ] **Step 11: Commit**

```bash
git add engine/appc/objects.py engine/appc/properties.py \
        engine/appc/weapon_subsystems.py engine/appc/object_emitter.py \
        engine/appc/subsystems.py engine/appc/projectiles.py \
        engine/host_loop.py tests/unit/test_object_transform_slots.py
git commit -m "feat(transforms): ObjectClass transforms live in the store

Slot allocated in __init__, released by weakref.finalize (not __del__ —
ObjectClass instances sit in reference cycles). Accessors read through and
still return independent copies, so SDK semantics are unchanged.

BEHAVIOUR CHANGE: SetMatrixRotation now COPIES the caller's matrix instead
of storing it by reference. Pinned by test_object_transform_slots.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 12: LIVE CHECKPOINT — hand over**

Stop. Report to the project owner and request a live run. The build must be
current in whichever tree they test from (`cmake --build build -j`); a live
check on a stale binary tells you nothing.

What to look for:
- Ships, torpedoes, characters, planets, backdrops and lights all in the right
  places, in an exterior scene and on the bridge.
- Nothing rotating oddly or drifting — the `SetMatrixRotation` aliasing change
  would show up here.
- Weapons firing from the right hardpoints (the emitter and weapon subsystem
  sites were converted).

Do not start Task 5 until the checkpoint passes.

---

### Task 5: Bulk read API and hot Python sweeps

Adds the bulk primitive and converts the per-ship sweeps that currently make N accessor calls.

**Files:**
- Modify: `native/src/transforms/include/dauntless/transform_store.h`, `native/src/transforms/src/transform_store.cc`
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/appc/transform_store.py` (both backends)
- Modify: `tests/unit/test_transform_store_conformance.py`
- Modify: `engine/appc/collisions.py`, `engine/appc/contact_index.py` (the broadphase and contact sweeps)

**Interfaces:**
- Consumes: everything from Tasks 2–4.
- Produces: `get_positions(handles) -> list[tuple[float, float, float]]` on both backends, where `handles` is a sequence of `(index, generation)` pairs; raises `StaleHandleError` if any handle is stale. Native binding name: `transform_get_positions(handles)`.

- [ ] **Step 1: Write the failing conformance test**

Append to `tests/unit/test_transform_store_conformance.py`:

```python
def test_get_positions_bulk_matches_individual_reads(store):
    handles = []
    for n in range(50):
        i, g = store.alloc()
        store.set_position(i, g, float(n), float(-n), 0.5)
        handles.append((i, g))
    bulk = store.get_positions(handles)
    assert len(bulk) == len(handles)
    for (i, g), got in zip(handles, bulk):
        assert got == store.get_position(i, g)


def test_get_positions_rejects_a_stale_handle(store):
    i, g = store.alloc()
    store.free(i, g)
    with pytest.raises(StaleHandleError):
        store.get_positions([(i, g)])


def test_get_positions_empty_is_empty(store):
    assert store.get_positions([]) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_transform_store_conformance.py -k get_positions -q`
Expected: FAIL — `AttributeError: 'PythonTransformStore' object has no attribute 'get_positions'`.

- [ ] **Step 3: Implement on the Python backend**

```python
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
```

- [ ] **Step 4: Implement on the C++ side and bind it**

In the header:

```cpp
    // Bulk read for per-frame sweeps: one boundary crossing instead of N.
    std::vector<std::array<float, 3>> positions(
        const std::vector<std::pair<std::uint32_t, std::uint32_t>>& handles) const;
```

In the implementation:

```cpp
std::vector<std::array<float, 3>> TransformStore::positions(
        const std::vector<std::pair<std::uint32_t, std::uint32_t>>& handles) const {
    std::vector<std::array<float, 3>> out;
    out.reserve(handles.size());
    for (const auto& h : handles) {
        check(h.first, h.second);
        const Transform& t = slots_[h.first];
        out.push_back({t.pos[0], t.pos[1], t.pos[2]});
    }
    return out;
}
```

Binding:

```cpp
    m.def("transform_get_positions",
          [](const std::vector<std::pair<std::uint32_t, std::uint32_t>>& h) {
              return dauntless::transform_store().positions(h);
          },
          py::arg("handles"),
          "Bulk position read: one crossing instead of N.");
```

Add `transform_get_positions` to `_REQUIRED_BINDINGS` in `engine/host_io.py`,
and add the wrapper to `NativeTransformStore`:

```python
    def get_positions(self, handles) -> list:
        try:
            return [tuple(p) for p in
                    self._h.transform_get_positions(list(handles))]
        except RuntimeError as exc:
            raise StaleHandleError(str(exc)) from exc
```

- [ ] **Step 5: Rebuild and run the conformance suite**

Run: `cmake --build build -j && uv run pytest tests/unit/test_transform_store_conformance.py -v`
Expected: PASS on both backends, no skips.

- [ ] **Step 6: Convert the collision broadphase sweep**

Open `engine/appc/collisions.py` and find where `tick_collisions` (line ~344)
walks objects reading `GetWorldLocation()` per object. Replace the per-object
reads with one `get_positions()` call over the handle list, keeping the rest of
the algorithm identical. Do the same for the contact sweep in
`engine/appc/contact_index.py`.

Do not change any behaviour — the values are the same, only the number of
boundary crossings differs. If a sweep currently reads a position it does not
use, leave that alone; this is not a refactor.

- [ ] **Step 7: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: only the ledgered failure.

- [ ] **Step 8: Commit**

```bash
git add native/src/transforms native/src/host/host_bindings.cc \
        engine/appc/transform_store.py engine/host_io.py \
        engine/appc/collisions.py engine/appc/contact_index.py \
        tests/unit/test_transform_store_conformance.py
git commit -m "perf(transforms): bulk position reads for per-frame sweeps

One boundary crossing per sweep instead of one per object.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Renderer reads the store directly — **LIVE CHECKPOINT**

The largest measured prize in this plan: `render_prep` is 12 ms in combat and 15.8 ms on the bridge, and a large part of it is pulling transforms into Python only to hand them straight back.

**Files:**
- Modify: `native/src/host/host_bindings.cc` (instance→slot binding; world matrix built C++-side)
- Modify: `engine/host_loop.py` (`_world_matrix_from` ~4387, `_ship_world_matrix`, `_astro_world_matrix`, and the render-data builders at ~4025-4043)
- Modify: `engine/host_io.py` (manifest)
- Create: `tests/host/test_instance_transform_slots.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `_dauntless_host.set_instance_transform_slot(iid, index, generation, scale)` — binds a render instance to a store slot plus a uniform scale. The renderer composes the TRS matrix from the store each frame. Passing `index = -1` unbinds, restoring the explicit-matrix path for instances whose transform is not store-backed.

- [ ] **Step 1: Write the failing test**

Create `tests/host/test_instance_transform_slots.py`:

```python
"""A render instance bound to a store slot follows the object without the
transform crossing into Python."""
import pytest

pytest.importorskip("_dauntless_host")

import _dauntless_host as _h

from engine.appc.objects import ObjectClass


@pytest.mark.skipif(not hasattr(_h, "set_instance_transform_slot"),
                    reason="instance transform slot binding not built")
def test_binding_accepts_a_live_handle():
    o = ObjectClass()
    o.SetTranslateXYZ(3.0, 4.0, 5.0)
    index, generation = o._xform
    # iid 0 is the "no instance" sentinel; a real iid comes from the renderer.
    # This asserts the binding validates rather than crashing on a bad iid.
    with pytest.raises(Exception):
        _h.set_instance_transform_slot(999999, index, generation, 1.0)


@pytest.mark.skipif(not hasattr(_h, "set_instance_transform_slot"),
                    reason="instance transform slot binding not built")
def test_unbind_is_accepted():
    # -1 unbinds; must not raise even when nothing was bound.
    _h.set_instance_transform_slot(0, -1, 0, 1.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/host/test_instance_transform_slots.py -q`
Expected: SKIP or FAIL — the binding does not exist.

- [ ] **Step 3: Add the instance→slot binding in C++**

In `native/src/host/host_bindings.cc`, add per-instance slot state beside the
existing instance bookkeeping, and compose the world matrix from the store
inside `frame()` where the instance's model matrix is currently taken from the
Python-supplied value. Row-major TRS, matching `_world_matrix_from`:

```cpp
    m.def("set_instance_transform_slot",
          [](int iid, int index, std::uint32_t generation, float scale) {
              // index < 0 unbinds and restores the explicit-matrix path.
              set_instance_slot(iid, index, generation, scale);
          },
          py::arg("iid"), py::arg("index"), py::arg("generation"),
          py::arg("scale"),
          "Bind a render instance to a transform-store slot. The renderer "
          "composes its world matrix from the store each frame, so the "
          "transform never crosses into Python. index < 0 unbinds.");
```

The composition must reproduce `_world_matrix_from` exactly — rotation
row-major times uniform scale, translation in the fourth column, no reflection
and no transpose (right-handed since 2026-06-18; `glFrontFace(GL_CCW)` handles
NIF winding).

- [ ] **Step 4: Bind slots when instances are realized**

In `engine/host_loop.py`, wherever a render instance is created for an object,
call `host_io.set_instance_transform_slot(iid, *obj._xform, scale)` once at
realize time. Then delete the per-frame transform push for those instances.

Instances whose transform is *not* store-backed (anything not derived from
`ObjectClass`) keep the existing explicit-matrix path — that is what `index = -1`
is for.

- [ ] **Step 5: Add to the binding manifest**

Add `set_instance_transform_slot` to `_REQUIRED_BINDINGS` in `engine/host_io.py`.

- [ ] **Step 6: Rebuild and run the gate**

Run: `cmake --build build -j && scripts/check_tests.sh`
Expected: only the ledgered failure.

- [ ] **Step 7: Capture the win**

Ask the project owner for a profiler capture, same recipe as the baseline:

```
DAUNTLESS_MISSION=engine.dev_missions.combat_stress \
DAUNTLESS_COMBAT_SHIPS=16 DAUNTLESS_COMBAT_AVOID=0
```

Compare `render_prep` against the pre-Task-1 baseline. CPU columns only — the
GPU column is dead on this Mac. Discard runs where untouched phases moved
together by 2-3x; that is contention, not a result.

- [ ] **Step 8: Commit**

```bash
git add native/src/host/host_bindings.cc engine/host_loop.py \
        engine/host_io.py tests/host/test_instance_transform_slots.py
git commit -m "perf(render): renderer reads transforms from the store

Instances bind to a store slot at realize time and the renderer composes
their world matrix in C++, so transforms no longer cross into Python every
frame.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 9: LIVE CHECKPOINT — hand over**

Stop. Request a live run with a current build. What to look for:
- Everything drawn in the right place and at the right scale, exterior and bridge.
- No mirrored or inside-out hulls (would mean the C++ matrix composition got the
  handedness wrong).
- Warp, cutscene and comm-viewscreen scenes, which use the alternate camera and
  set paths.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Phase 0 — `TGMatrix3` flat | Task 1 |
| Phase 1 — `TransformStore`, both backends, conformance | Tasks 2, 3 |
| Phase 2 — `ObjectClass` store-backed, aliasing pin, live gate | Task 4 |
| Phase 3 — bulk paths, renderer reads store, live gate | Tasks 5, 6 |
| Slot lifecycle (generation, `weakref.finalize`, no leak) | Task 3 (C++), Task 4 (Python) |
| Two backends, one contract | Tasks 2, 3 |
| Phases 4–5 (motion port, threading) | **Deliberately out of scope** — second plan |

**Known gaps carried forward, by design:**
- `engine/dev_mode.py`'s unguarded `import _dauntless_host` is *not* fixed here. It is noted in the spec as a separate concern; fixing it would let Task 1 run with no native build at all, but it is not this plan's job.
- The threading-threshold crossover and the post-Task-6 `render_prep` composition remain the spec's open questions; Task 6 Step 7 produces the measurement that informs the first.
