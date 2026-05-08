# Stub Call Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--profile` flag to `tools/gameloop_harness.py` that records which unimplemented `App` shim methods are called across all missions and prints a ranked summary table.

**Architecture:** `_StubTracker` (a module-level singleton in `App.py`) accumulates `{stub_name → {mission → call_count}}`. `_NamedStub` (a `_Stub` subclass) carries its access-path name and calls `_stub_tracker.record()` on `__call__`. `App.__getattr__` and `_UtopiaModule.__getattr__` are changed to return `_NamedStub` instead of bare `_Stub`. The harness sets the current mission context before each run and prints the ranked table when `--profile` is given. `App` is imported at the top of `gameloop_harness.py` so it is captured in `_BASELINE_MODULES` and persists across mission runs (required for tracker data to accumulate).

**Tech Stack:** Python 3.11+, pytest, existing `App.py` shim, `tools/gameloop_harness.py`, `tools/mission_harness.py`.

---

## File Map

- **Modify:** `App.py` — add `_StubTracker` class + `_stub_tracker` singleton (before `_Stub`); add `_NamedStub` class (after `_Stub`); change `_UtopiaModule.__getattr__` and module-level `__getattr__` to return `_NamedStub(name)`.
- **Modify:** `tools/gameloop_harness.py` — add `import App` at module level; add `profile: bool = False` param to `run_mission_with_loop`; add `_print_profile_report()`; add `--profile` flag to argparse and `main()`.
- **Create:** `tests/unit/test_stub_tracker.py` — 4 unit tests for `_StubTracker` and `_NamedStub`.
- **Modify:** `tests/integration/test_gameloop_harness.py` — 1 new integration test for the `profile` flag.

---

### Task 1: `_StubTracker` — write tests then implement

**Files:**
- Create: `tests/unit/test_stub_tracker.py`
- Modify: `App.py` (insert `_StubTracker` before line 130 `# ── Fallback stub ──`)

- [ ] **Step 1: Write the failing test file**

Create `tests/unit/test_stub_tracker.py`:

```python
import pytest
import App


@pytest.fixture(autouse=True)
def reset_tracker():
    App._stub_tracker.clear()
    yield
    App._stub_tracker.clear()


def test_tracker_inactive_before_set_mission():
    App._stub_tracker.record("SomeMethod")
    assert App._stub_tracker.report() == []


def test_tracker_counts_calls_per_mission():
    App._stub_tracker.set_mission("mission_a")
    App._stub_tracker.record("Foo")
    App._stub_tracker.record("Foo")
    App._stub_tracker.set_mission("mission_b")
    App._stub_tracker.record("Foo")
    rows = App._stub_tracker.report()
    assert len(rows) == 1
    name, mission_count, total_calls = rows[0]
    assert name == "Foo"
    assert mission_count == 2
    assert total_calls == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_stub_tracker.py -v
```

Expected: both tests fail with `AttributeError: module 'App' has no attribute '_stub_tracker'`.

- [ ] **Step 3: Add `_StubTracker` to `App.py`**

In `App.py`, insert the following block immediately before the line `# ── Fallback stub ──` (currently line 130):

```python
# ── Stub call tracker ─────────────────────────────────────────────────────────
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

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_stub_tracker.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
uv run pytest -q
```

Expected: all existing tests pass, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_stub_tracker.py App.py
git commit -m "feat: add _StubTracker to App.py"
```

---

### Task 2: `_NamedStub` — write tests then implement, wire up, fix App persistence

**Files:**
- Modify: `tests/unit/test_stub_tracker.py` (add 2 more tests)
- Modify: `App.py` (add `_NamedStub` after `_Stub`; change 2 `__getattr__` call sites)
- Modify: `tools/gameloop_harness.py` (add `import App` at module level)

- [ ] **Step 1: Add two failing tests to `tests/unit/test_stub_tracker.py`**

Append these two tests to the end of `tests/unit/test_stub_tracker.py`:

```python
def test_named_stub_records_on_call():
    App._stub_tracker.set_mission("test_mission")
    App._NamedStub("Foo")()
    _ = App._NamedStub("Foo").Bar  # attribute access without calling — must not record
    rows = App._stub_tracker.report()
    names = [name for name, _, _ in rows]
    assert "Foo" in names
    assert "Foo.Bar" not in names


def test_named_stub_chain():
    App._stub_tracker.set_mission("test_mission")
    App._NamedStub("A").B.C()
    rows = App._stub_tracker.report()
    assert len(rows) == 1
    assert rows[0][0] == "A.B.C"
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
uv run pytest tests/unit/test_stub_tracker.py::test_named_stub_records_on_call tests/unit/test_stub_tracker.py::test_named_stub_chain -v
```

Expected: both fail with `AttributeError: module 'App' has no attribute '_NamedStub'`.

- [ ] **Step 3: Add `_NamedStub` to `App.py`**

In `App.py`, insert the following block immediately after the closing line of the `_Stub` class (after the `def __ne__` line, before `def __getattr__(name):`):

```python

class _NamedStub(_Stub):
    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return _NamedStub(f"{self._name}.{attr}")

    def __call__(self, *args, **kwargs):
        _stub_tracker.record(self._name)
        return _NamedStub(f"{self._name}()")

```

- [ ] **Step 4: Change `_UtopiaModule.__getattr__` to return a named stub**

In `App.py`, change `_UtopiaModule.__getattr__` from:

```python
    def __getattr__(self, name):
        return _Stub()
```

to:

```python
    def __getattr__(self, name):
        return _NamedStub(name)
```

- [ ] **Step 5: Change module-level `__getattr__` to return a named stub**

In `App.py`, change the module-level `__getattr__` at the bottom of the file from:

```python
def __getattr__(name):
    return _Stub()
```

to:

```python
def __getattr__(name):
    return _NamedStub(name)
```

- [ ] **Step 6: Add `import App` at module level of the harness**

In `tools/gameloop_harness.py`, the tracker lives in `App.py`. By default, `App` is wiped from `sys.modules` between missions by the cleanup loop. Adding `import App` at module level ensures `App` is present when `setup_sdk()` captures `_BASELINE_MODULES`, so it is treated as a baseline module and preserved across runs — allowing tracker data to accumulate.

In `tools/gameloop_harness.py`, after the line `import tools.mission_harness as _mh`, add:

```python
import App as _App  # imported at module level so App is in _BASELINE_MODULES and persists across runs
```

- [ ] **Step 7: Run all tests to verify everything passes**

```bash
uv run pytest -q
```

Expected: all tests pass including the two new named-stub tests, 0 failures.

- [ ] **Step 8: Commit**

```bash
git add App.py tools/gameloop_harness.py tests/unit/test_stub_tracker.py
git commit -m "feat: add _NamedStub and wire up stub call tracking in App.py"
```

---

### Task 3: `--profile` flag — write integration test then implement

**Files:**
- Modify: `tests/integration/test_gameloop_harness.py` (add 1 test)
- Modify: `tools/gameloop_harness.py` (add `profile` param, `_print_profile_report`, `--profile` argparse)

- [ ] **Step 1: Add the failing integration test**

In `tests/integration/test_gameloop_harness.py`, append:

```python
def test_profile_flag_produces_report(sdk_setup):
    import App
    App._stub_tracker.clear()
    from tools.gameloop_harness import run_mission_with_loop
    status, exc, ticks = run_mission_with_loop(
        "Custom.Tutorial.Episode.M1Basic.M1Basic", n_ticks=60, profile=True
    )
    assert status == "pass"
    rows = App._stub_tracker.report()
    assert len(rows) > 0
    for name, mission_count, total_calls in rows:
        assert isinstance(name, str)
        assert isinstance(mission_count, int)
        assert isinstance(total_calls, int)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/integration/test_gameloop_harness.py::test_profile_flag_produces_report -v
```

Expected: fails with `TypeError: run_mission_with_loop() got an unexpected keyword argument 'profile'`.

- [ ] **Step 3: Add `profile` parameter to `run_mission_with_loop`**

In `tools/gameloop_harness.py`, change the function signature from:

```python
def run_mission_with_loop(
    module_name: str, n_ticks: int = _DEFAULT_TICKS
) -> "tuple[str, Exception | None, int]":
```

to:

```python
def run_mission_with_loop(
    module_name: str, n_ticks: int = _DEFAULT_TICKS, profile: bool = False
) -> "tuple[str, Exception | None, int]":
```

Then, inside `run_mission_with_loop`, add tracker activation immediately after the state-reset block (after `App._next_event_type_id = 200`) and deactivation in the `finally` block.

The state-reset block currently ends with:

```python
    App._next_event_type_id = 200

    ticks_done = 0
```

Change it to:

```python
    App._next_event_type_id = 200
    if profile:
        App._stub_tracker.set_mission(module_name)

    ticks_done = 0
```

And change the `finally` block from:

```python
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        _set_current_game(None)
        for key in [k for k in sys.modules if k not in _mh._BASELINE_MODULES]:
            del sys.modules[key]
```

to:

```python
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        if profile:
            App._stub_tracker.reset_mission()
        _set_current_game(None)
        for key in [k for k in sys.modules if k not in _mh._BASELINE_MODULES]:
            del sys.modules[key]
```

- [ ] **Step 4: Add `_print_profile_report` to `tools/gameloop_harness.py`**

In `tools/gameloop_harness.py`, add the following function after `_loop_error_key` and before `main()`:

```python
_PROFILE_ROWS = 50


def _print_profile_report(n_ticks: int, n_missions: int) -> None:
    rows = _App._stub_tracker.report()
    print(f"\nStub call profile  ({n_ticks} ticks × {n_missions} missions)")
    print("─" * 62)
    print(f"  {'Rank':>4}  {'Stub method':<40}  {'Missions':>8}  {'Calls':>5}")
    for rank, (name, mission_count, total_calls) in enumerate(rows[:_PROFILE_ROWS], 1):
        print(f"  {rank:>4}  {name:<40}  {mission_count:>8}  {total_calls:>5}")
    if len(rows) > _PROFILE_ROWS:
        print(f"  ... {len(rows) - _PROFILE_ROWS} more rows omitted")
```

- [ ] **Step 5: Thread `profile` through `main()` and add `--profile` to argparse**

In `tools/gameloop_harness.py`, change the `main()` signature from:

```python
def main(n_ticks: int = _DEFAULT_TICKS) -> None:
```

to:

```python
def main(n_ticks: int = _DEFAULT_TICKS, profile: bool = False) -> None:
```

Inside `main()`, change the per-mission call from:

```python
        status, exc, ticks = run_mission_with_loop(name, n_ticks)
```

to:

```python
        status, exc, ticks = run_mission_with_loop(name, n_ticks, profile=profile)
```

After the existing error-summary block (after the `for msg, count in errors.most_common(15):` block), add:

```python
    if profile:
        _print_profile_report(n_ticks, len(missions))
```

In the `if __name__ == "__main__":` block, change:

```python
    parser = argparse.ArgumentParser(description="open_stbc game-loop harness")
    parser.add_argument(
        "--ticks", type=int, default=_DEFAULT_TICKS,
        help=f"ticks per mission (default {_DEFAULT_TICKS} = ~5s at 60 Hz)"
    )
    args = parser.parse_args()
    main(args.ticks)
```

to:

```python
    parser = argparse.ArgumentParser(description="open_stbc game-loop harness")
    parser.add_argument(
        "--ticks", type=int, default=_DEFAULT_TICKS,
        help=f"ticks per mission (default {_DEFAULT_TICKS} = ~5s at 60 Hz)"
    )
    parser.add_argument(
        "--profile", action="store_true",
        help="print ranked stub call profile after the run"
    )
    args = parser.parse_args()
    main(args.ticks, profile=args.profile)
```

- [ ] **Step 6: Run the full test suite**

```bash
uv run pytest -q
```

Expected: all tests pass, 0 failures.

- [ ] **Step 7: Smoke test — run the harness with `--profile`**

```bash
uv run python tools/gameloop_harness.py --profile --ticks 60
```

Expected output ends with a table like:

```
Stub call profile  (60 ticks × 35 missions)
──────────────────────────────────────────────────────────────
  Rank  Stub method                              Missions  Calls
     1  CharacterClass_GetObject                       35    420
     2  ...
```

Verify: at least one row appears, rank column is numeric, Missions ≤ 35, Calls > 0.

- [ ] **Step 8: Commit**

```bash
git add tools/gameloop_harness.py tests/integration/test_gameloop_harness.py
git commit -m "feat: add --profile flag to gameloop_harness for stub call ranking"
```
