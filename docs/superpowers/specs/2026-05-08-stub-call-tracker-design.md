# Stub Call Tracker — Design Spec

**Date:** 2026-05-08
**Status:** Approved

## Goal

Add a `--profile` flag to `tools/gameloop_harness.py` that tracks which unimplemented `App` shim methods (stubs) are called during a full harness run, ranked by the number of distinct missions that exercise them. Output drives Phase 1 implementation priority.

---

## Architecture

Three components interact:

1. **`_NamedStub` (App.py)** — a `_Stub` subclass that carries the access-path name. Names propagate through attribute chains. Only `__call__` triggers a tracker record; attribute traversal alone is silent.
2. **`_StubTracker` (App.py)** — a module-level singleton accumulating `{name → {mission → call_count}}`. Inactive (no-op) until `set_mission()` is called, so non-`--profile` runs have zero overhead.
3. **Harness `--profile` flag** — activates the tracker around each mission, prints a ranked table after the existing pass/fail summary.

---

## `_StubTracker`

Lives in `App.py`, just above the `_Stub` class definition.

```python
class _StubTracker:
    def __init__(self):
        self._data = {}      # {name: {mission: call_count}}
        self._mission = None

    def set_mission(self, name):
        self._mission = name

    def reset_mission(self):
        self._mission = None

    def record(self, name):
        if self._mission is None:
            return
        self._data.setdefault(name, {}).setdefault(self._mission, 0)
        self._data[name][self._mission] += 1

    def report(self):
        rows = []
        for name, missions in self._data.items():
            rows.append((name, len(missions), sum(missions.values())))
        rows.sort(key=lambda r: (-r[1], -r[2], r[0]))
        return rows

    def clear(self):
        self._data.clear()
        self._mission = None

_stub_tracker = _StubTracker()
```

---

## `_NamedStub`

Subclasses `_Stub`, overrides only `__getattr__` and `__call__`. All numeric/comparison operators are inherited from `_Stub` unchanged.

```python
class _NamedStub(_Stub):
    def __init__(self, name):
        self._name = name          # real instance attr — no __getattr__ recursion

    def __getattr__(self, attr):
        return _NamedStub(f"{self._name}.{attr}")

    def __call__(self, *args, **kwargs):
        _stub_tracker.record(self._name)
        return _NamedStub(f"{self._name}()")
```

### Call-site changes in App.py

Two locations return `_Stub()` today; both change to `_NamedStub(name)`:

- Module-level `__getattr__(name)` → `return _NamedStub(name)`
- `_UtopiaModule.__getattr__(self, name)` → `return _NamedStub(name)`

---

## Harness changes (`tools/gameloop_harness.py`)

### `run_mission_with_loop` signature

```python
def run_mission_with_loop(
    module_name: str,
    n_ticks: int = _DEFAULT_TICKS,
    profile: bool = False,
) -> "tuple[str, Exception | None, int]":
```

When `profile=True`:
- After state reset, before `Initialize()`: `App._stub_tracker.set_mission(module_name)`
- In `finally`: `App._stub_tracker.reset_mission()`

Tracker data accumulates across all missions — no per-mission clear.

### `main()` changes

- `--profile` added to argparse; forwarded to `run_mission_with_loop`
- After the existing pass/fail summary block, when `--profile` is active: call `_print_profile_report()`

### `_print_profile_report()`

```
Stub call profile  (36000 ticks × 35 missions)
──────────────────────────────────────────────────────────────
 Rank  Stub method                              Missions  Calls
    1  CharacterClass_GetObject                       35  12600
    2  MusicClass_Play                                33   8820
  ...
```

- Primary sort: mission count descending
- Secondary sort: total calls descending
- Tertiary sort: name ascending (stable tie-break)
- Capped at 50 rows

---

## Tests

### `tests/unit/test_stub_tracker.py` (new file, 4 tests)

| Test | Assertion |
|---|---|
| `test_tracker_inactive_before_set_mission` | `record()` before `set_mission()` → empty report |
| `test_tracker_counts_calls_per_mission` | Two missions, N calls each → correct mission count and total |
| `test_named_stub_records_on_call` | `_NamedStub("Foo")()` appears in report; bare `.Bar` access without call does not |
| `test_named_stub_chain` | `_NamedStub("A").B.C()` records `"A.B.C"` |

### `tests/integration/test_gameloop_harness.py` (1 new test)

| Test | Assertion |
|---|---|
| `test_profile_flag_produces_report` | Run one mission with `profile=True`; `App._stub_tracker.report()` is non-empty; each row is `(str, int, int)` |

No changes to existing tests.
