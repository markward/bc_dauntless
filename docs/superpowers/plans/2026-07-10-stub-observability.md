# Stub Observability (Step 0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrument the engine's core `_Stub` layer so that, when explicitly enabled, a run records which unimplemented engine attributes are accessed and where stubs are truth-tested — then dumps a ranked report at exit — without changing any runtime behavior when disabled.

**Architecture:** A new dependency-free collector module (`engine/core/stub_telemetry.py`) exposes cheap `record_*` hooks and a `dump_report()`. The core `_Stub` and `TGObject.__getattr__` (both in `engine/core/ids.py`) call those hooks guarded by a single module-level `ENABLED` flag. When `ENABLED` is `False` (the default) each hook is one attribute read plus the existing return, so the production path is byte-identical. When enabled (env var or explicit toggle) the collector accumulates two `Counter`s — attribute hits (the implementation roadmap) and boolean-test call sites (the data that later decides whether flipping `_Stub.__bool__` is safe) — and prints a ranked report via `atexit`.

**Tech Stack:** Python 3 (embedded CPython host), stdlib only (`os`, `sys`, `atexit`, `collections.Counter`), pytest.

## Global Constraints

- **OFF by default; production byte-identical.** When telemetry is disabled, `_Stub` and `TGObject.__getattr__` must behave exactly as they do today (same return values, same truthiness, same chaining). Mirror the opt-in pattern of `dev_mode` / the PBR spike.
- **Zero third-party dependencies.** `engine/core/stub_telemetry.py` imports stdlib only, so `engine/core/ids.py` can import it without a cycle. (Only `pillow` is a real project dep — do not add others.)
- **Telemetry must never crash a run.** Every hook body is wrapped so an exception inside telemetry is swallowed, never propagated into the game. This matches the project's instrumentation-safety ethos.
- **Report via `print()`, not `logging`.** The embedded host installs no logging handler; `logging.*` output is invisible. Diagnostics use `print()`.
- **Do not modify `_Stub`'s truthiness, arithmetic, or chaining semantics.** This plan only *observes*. `__bool__` still returns `True`; `__getattr__`/`__call__` still return a `_Stub`.
- **Scope is the object-level core `_Stub` in `engine/core/ids.py` only.** The module-level `_StubModule` (the twin `_plain_stubs` lists in `tools/mission_harness.py` and `tests/conftest.py`) and the App-module `_NamedStub` in `engine/appc/objects.py` are explicitly out of scope for this plan; they are fast-follows that reuse this same collector.

---

### Task 1: The telemetry collector module

**Files:**
- Create: `engine/core/stub_telemetry.py`
- Test: `tests/unit/test_stub_telemetry.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces:
  - `ENABLED: bool` — module-level flag, initialized from env var `DAUNTLESS_STUB_TELEMETRY` (truthy unless unset/`""`/`"0"`/`"false"`/`"False"`).
  - `set_enabled(value: bool) -> None` — toggle at runtime (for `dev_mode` and tests).
  - `record_attr(owner_type: str, attr_name: str) -> None` — no-op when disabled; else increments `(owner_type, attr_name)` count.
  - `record_bool(owner_type: str) -> None` — no-op when disabled; else increments the caller-site count (file:lineno of the code that truth-tested the stub).
  - `snapshot() -> dict` — `{"attr_hits": {(owner, attr): n}, "bool_sites": {"file:line": n}}`.
  - `reset() -> None` — clears both counters.
  - `dump_report(stream=None) -> str` — returns the ranked report text and prints it to `stream` (default `sys.stderr`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_stub_telemetry.py
import pytest

from engine.core import stub_telemetry


@pytest.fixture(autouse=True)
def _clean_telemetry():
    prev = stub_telemetry.ENABLED
    stub_telemetry.reset()
    yield
    stub_telemetry.set_enabled(prev)
    stub_telemetry.reset()


def test_disabled_by_default_records_nothing():
    stub_telemetry.set_enabled(False)
    stub_telemetry.record_attr("ShipClass", "GetWarpCore")
    stub_telemetry.record_bool("ShipClass")
    snap = stub_telemetry.snapshot()
    assert snap["attr_hits"] == {}
    assert snap["bool_sites"] == {}


def test_enabled_records_attr_hits_with_counts():
    stub_telemetry.set_enabled(True)
    stub_telemetry.record_attr("ShipClass", "GetWarpCore")
    stub_telemetry.record_attr("ShipClass", "GetWarpCore")
    stub_telemetry.record_attr("Mission", "GetFriendlyGroup")
    snap = stub_telemetry.snapshot()
    assert snap["attr_hits"][("ShipClass", "GetWarpCore")] == 2
    assert snap["attr_hits"][("Mission", "GetFriendlyGroup")] == 1


def test_enabled_records_bool_site():
    stub_telemetry.set_enabled(True)
    stub_telemetry.record_bool("ShipClass")
    sites = stub_telemetry.snapshot()["bool_sites"]
    # Exactly one site recorded, keyed by a non-empty "file:line" string.
    # NOTE: this calls record_bool() directly, so the captured frame is not
    # this test line (the caller-depth is calibrated for the production path
    # _Stub.__bool__ -> record_bool). Asserting the *identity* of the site is
    # done in Task 3's test, which goes through __bool__. Here we only assert a
    # site was captured.
    assert sum(sites.values()) == 1
    assert all(isinstance(key, str) and key for key in sites)


def test_record_never_raises_even_on_bad_input():
    stub_telemetry.set_enabled(True)
    # None args must not blow up the game
    stub_telemetry.record_attr(None, None)
    stub_telemetry.record_bool(None)


def test_dump_report_is_string_and_ranks_by_frequency():
    stub_telemetry.set_enabled(True)
    stub_telemetry.record_attr("A", "rare")
    for _ in range(5):
        stub_telemetry.record_attr("B", "common")
    report = stub_telemetry.dump_report()
    assert isinstance(report, str)
    assert report.index("common") < report.index("rare")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stub_telemetry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.core.stub_telemetry'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/core/stub_telemetry.py
"""Observability for the engine's silent-stub layer.

The core ``_Stub`` (``engine/core/ids.py``) is returned by
``TGObject.__getattr__`` for any unimplemented engine method, so an absent
capability is indistinguishable from a working no-op. This module *observes*
that layer without changing its behavior: when enabled it records which stub
attributes are accessed (the implementation roadmap) and where stubs are
truth-tested (the data that decides whether flipping ``_Stub.__bool__`` is
safe), then dumps a ranked report at exit.

Constraints (see docs/superpowers/plans/2026-07-10-stub-observability.md):
- OFF by default. When disabled every hook is one bool read + return, so the
  production path is byte-identical.
- Stdlib only, so engine/core/ids.py can import it with no cycle.
- Never raises into the game: every hook is wrapped.
- Reports via print(), not logging (the embedded host installs no handler).
"""

from __future__ import annotations

import atexit
import os
import sys
from collections import Counter


def _env_truthy(value: str) -> bool:
    return value not in ("", "0", "false", "False")


ENABLED: bool = _env_truthy(os.environ.get("DAUNTLESS_STUB_TELEMETRY", ""))

_attr_hits: "Counter" = Counter()   # (owner_type, attr_name) -> count
_bool_sites: "Counter" = Counter()  # "file:lineno" -> count
_atexit_registered = False


def set_enabled(value: bool) -> None:
    global ENABLED
    ENABLED = bool(value)
    if ENABLED:
        _ensure_atexit()


def _ensure_atexit() -> None:
    global _atexit_registered
    if not _atexit_registered:
        try:
            atexit.register(_atexit_dump)
            _atexit_registered = True
        except Exception:
            pass


def _atexit_dump() -> None:
    if _attr_hits or _bool_sites:
        try:
            dump_report()
        except Exception:
            pass


def _caller(depth: int) -> str:
    try:
        frame = sys._getframe(depth)
        return "%s:%d" % (frame.f_code.co_filename, frame.f_lineno)
    except Exception:
        return "<unknown>"


def record_attr(owner_type: str, attr_name: str) -> None:
    if not ENABLED:
        return
    try:
        _attr_hits[(owner_type, attr_name)] += 1
    except Exception:
        pass


def record_bool(owner_type: str) -> None:
    if not ENABLED:
        return
    try:
        # depth 3: _caller -> record_bool -> __bool__ -> the truth-test site
        _bool_sites[_caller(3)] += 1
    except Exception:
        pass


def snapshot() -> dict:
    return {
        "attr_hits": dict(_attr_hits),
        "bool_sites": dict(_bool_sites),
    }


def reset() -> None:
    _attr_hits.clear()
    _bool_sites.clear()


def dump_report(stream=None) -> str:
    if stream is None:
        stream = sys.stderr
    lines = ["=== stub telemetry: unimplemented-attribute hits (roadmap) ==="]
    for (owner, attr), count in _attr_hits.most_common():
        lines.append("  %6d  %s.%s" % (count, owner, attr))
    lines.append("=== stub telemetry: boolean-test call sites (truthiness risk) ===")
    for site, count in _bool_sites.most_common():
        lines.append("  %6d  %s" % (count, site))
    report = "\n".join(lines)
    try:
        print(report, file=stream)
    except Exception:
        pass
    return report


if ENABLED:
    _ensure_atexit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_stub_telemetry.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/core/stub_telemetry.py tests/unit/test_stub_telemetry.py
git commit -m "feat(telemetry): stub observability collector (off by default)"
```

---

### Task 2: Record unimplemented-attribute access on the core `_Stub`

**Files:**
- Modify: `engine/core/ids.py` (the `_Stub` class ~lines 30–95 and `TGObject.__getattr__` ~lines 106–107)
- Test: `tests/unit/test_stub_telemetry_wiring.py`

**Interfaces:**
- Consumes: `stub_telemetry.record_attr`, `stub_telemetry.set_enabled`, `stub_telemetry.snapshot`, `stub_telemetry.ENABLED` (Task 1).
- Produces:
  - `_Stub.__init__(self, name: str = "?", owner: str = "?")` storing `self._stub_name` and `self._stub_owner`.
  - `_Stub.__getattr__` and `TGObject.__getattr__` call `record_attr` when enabled, still returning a `_Stub`. Behavior unchanged when disabled.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_stub_telemetry_wiring.py
import pytest

from engine.core import stub_telemetry
from engine.core.ids import TGObject, _Stub


@pytest.fixture(autouse=True)
def _clean_telemetry():
    prev = stub_telemetry.ENABLED
    stub_telemetry.reset()
    yield
    stub_telemetry.set_enabled(prev)
    stub_telemetry.reset()


def test_stub_still_truthy_and_chainable_when_disabled():
    stub_telemetry.set_enabled(False)
    obj = TGObject()
    stub = obj.SomeUnimplementedMethod()  # falls through __getattr__ then __call__
    assert bool(stub) is True                 # truthiness unchanged
    assert isinstance(stub.AndThenThis(), _Stub)  # chaining unchanged
    assert stub_telemetry.snapshot()["attr_hits"] == {}


def test_object_attr_access_is_recorded_when_enabled():
    stub_telemetry.set_enabled(True)
    obj = TGObject()
    obj.GetWarpCore  # unimplemented method name
    hits = stub_telemetry.snapshot()["attr_hits"]
    assert hits.get(("TGObject", "GetWarpCore")) == 1


def test_chained_stub_access_records_with_breadcrumb():
    stub_telemetry.set_enabled(True)
    obj = TGObject()
    obj.GetFriendlyGroup().AddName  # chained access through a returned _Stub
    hits = stub_telemetry.snapshot()["attr_hits"]
    # the parent method is recorded on the owning class
    assert hits.get(("TGObject", "GetFriendlyGroup")) == 1
    # the chained access is recorded with a dotted breadcrumb
    assert any(attr.endswith(".AddName") for (_owner, attr) in hits)


def test_internal_stub_bookkeeping_attrs_do_not_recurse():
    # Accessing the private bookkeeping names must raise AttributeError,
    # not build another _Stub (which would infinite-recurse).
    s = _Stub()
    with pytest.raises(AttributeError):
        object.__getattribute__(_Stub, "_stub_name")  # class has no such attr
    # instance access resolves the value set in __init__, never __getattr__
    assert s._stub_name == "?"
    assert s._stub_owner == "?"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stub_telemetry_wiring.py -v`
Expected: FAIL — `test_object_attr_access_is_recorded_when_enabled` fails because `attr_hits` is empty (no wiring yet), and `test_chained_stub_access_records_with_breadcrumb` fails likewise.

- [ ] **Step 3: Write minimal implementation**

In `engine/core/ids.py`, add the import near the top (with the other imports):

```python
from engine.core import stub_telemetry
```

Replace the `_Stub` class opening (the docstring, `__getattr__`, and `__call__`) so it stores identity and records access. The existing block is:

```python
class _Stub:
    """Recursive stub: attribute access and calls return another _Stub.

    Returned by TGObject.__getattr__ for unimplemented engine methods so SDK
    scripts can chain calls like pMission.GetFriendlyGroup().AddName(...).
    """
    def __getattr__(self, name: str) -> "_Stub":
        return _Stub()

    def __call__(self, *args, **kwargs) -> "_Stub":
        return _Stub()
```

Replace it with:

```python
class _Stub:
    """Recursive stub: attribute access and calls return another _Stub.

    Returned by TGObject.__getattr__ for unimplemented engine methods so SDK
    scripts can chain calls like pMission.GetFriendlyGroup().AddName(...).

    Carries its own (name, owner) identity purely so stub_telemetry can report
    *what* was accessed; this does not change any behavior when telemetry is
    disabled.
    """

    def __init__(self, name: str = "?", owner: str = "?") -> None:
        self._stub_name = name
        self._stub_owner = owner

    def __getattr__(self, name: str) -> "_Stub":
        if name in ("_stub_name", "_stub_owner"):
            # Break the recursion if these are accessed before __init__ ran
            # (e.g. during unpickling) — never build a stub for them.
            raise AttributeError(name)
        if stub_telemetry.ENABLED and not (name.startswith("__") and name.endswith("__")):
            stub_telemetry.record_attr(self._stub_owner, self._stub_name + "." + name)
        return _Stub(name, self._stub_owner)

    def __call__(self, *args, **kwargs) -> "_Stub":
        return _Stub(self._stub_name, self._stub_owner)
```

Then update `TGObject.__getattr__` (currently `return _Stub()`):

```python
    def __getattr__(self, name: str) -> _Stub:
        if stub_telemetry.ENABLED and not (name.startswith("__") and name.endswith("__")):
            stub_telemetry.record_attr(type(self).__name__, name)
        return _Stub(name, type(self).__name__)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_stub_telemetry_wiring.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/core/ids.py tests/unit/test_stub_telemetry_wiring.py
git commit -m "feat(telemetry): record unimplemented-attribute access on _Stub"
```

---

### Task 3: Record boolean-tests of the core `_Stub`

**Files:**
- Modify: `engine/core/ids.py` (`_Stub.__bool__` ~lines 42–43)
- Test: `tests/unit/test_stub_telemetry_bool.py`

**Interfaces:**
- Consumes: `stub_telemetry.record_bool`, `stub_telemetry.ENABLED` (Task 1); `_Stub` (Task 2).
- Produces: `_Stub.__bool__` records the caller site when enabled and **still returns `True`** (unchanged).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_stub_telemetry_bool.py
import pytest

from engine.core import stub_telemetry
from engine.core.ids import _Stub


@pytest.fixture(autouse=True)
def _clean_telemetry():
    prev = stub_telemetry.ENABLED
    stub_telemetry.reset()
    yield
    stub_telemetry.set_enabled(prev)
    stub_telemetry.reset()


def test_bool_still_true_and_unrecorded_when_disabled():
    stub_telemetry.set_enabled(False)
    s = _Stub("GetShields", "ShipClass")
    assert bool(s) is True
    if s:  # truth-test site, but disabled
        pass
    assert stub_telemetry.snapshot()["bool_sites"] == {}


def test_bool_records_caller_site_when_enabled_and_stays_true():
    stub_telemetry.set_enabled(True)
    s = _Stub("GetShields", "ShipClass")
    result = bool(s)  # <-- this line should be the recorded site
    assert result is True
    sites = stub_telemetry.snapshot()["bool_sites"]
    assert sum(sites.values()) == 1
    assert any("test_stub_telemetry_bool.py" in key for key in sites)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stub_telemetry_bool.py -v`
Expected: FAIL — `test_bool_records_caller_site_when_enabled_and_stays_true` fails because `bool_sites` is empty (no wiring yet).

- [ ] **Step 3: Write minimal implementation**

In `engine/core/ids.py`, replace `_Stub.__bool__` (currently):

```python
    def __bool__(self) -> bool:
        return True
```

with:

```python
    def __bool__(self) -> bool:
        if stub_telemetry.ENABLED:
            stub_telemetry.record_bool(self._stub_owner)
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_stub_telemetry_bool.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add engine/core/ids.py tests/unit/test_stub_telemetry_bool.py
git commit -m "feat(telemetry): record boolean-tests of _Stub (truthiness data)"
```

---

### Task 4: Dev-mode enable + end-to-end report over a real stub run

**Files:**
- Modify: `engine/dev_mode.py` (add a telemetry enable hook near the other dev-mode toggles)
- Test: `tests/unit/test_stub_telemetry_report.py`

**Interfaces:**
- Consumes: `stub_telemetry.set_enabled`, `stub_telemetry.dump_report`, `stub_telemetry.snapshot`, `stub_telemetry.reset` (Task 1); `TGObject` (Task 2).
- Produces: `dev_mode.enable_stub_telemetry() -> None` — a single call that turns telemetry on (gated so it is a no-op unless `--developer`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_stub_telemetry_report.py
import pytest

from engine.core import stub_telemetry
from engine.core.ids import TGObject
from engine import dev_mode


@pytest.fixture(autouse=True)
def _clean_telemetry():
    prev = stub_telemetry.ENABLED
    stub_telemetry.reset()
    yield
    stub_telemetry.set_enabled(prev)
    stub_telemetry.reset()


def test_end_to_end_report_names_hot_unimplemented_methods():
    stub_telemetry.set_enabled(True)
    ship = TGObject()
    for _ in range(3):
        ship.GetCloakingSubsystem   # simulate repeated hot access
    ship.NumProbes
    report = stub_telemetry.dump_report()
    assert "GetCloakingSubsystem" in report
    assert "NumProbes" in report
    # hotter method ranks above the colder one
    assert report.index("GetCloakingSubsystem") < report.index("NumProbes")


def test_dev_mode_enable_is_noop_without_developer(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    stub_telemetry.set_enabled(False)
    dev_mode.enable_stub_telemetry()
    assert stub_telemetry.ENABLED is False


def test_dev_mode_enable_turns_telemetry_on_in_developer(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    stub_telemetry.set_enabled(False)
    dev_mode.enable_stub_telemetry()
    assert stub_telemetry.ENABLED is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stub_telemetry_report.py -v`
Expected: FAIL — `AttributeError: module 'engine.dev_mode' has no attribute 'enable_stub_telemetry'`

- [ ] **Step 3: Write minimal implementation**

In `engine/dev_mode.py`, add near the other dev-mode helpers:

```python
def enable_stub_telemetry() -> None:
    """Turn on stub-observability telemetry, but only under --developer.

    No-op in production so the stub layer stays byte-identical. See
    docs/superpowers/plans/2026-07-10-stub-observability.md.
    """
    if not is_enabled():
        return
    from engine.core import stub_telemetry
    stub_telemetry.set_enabled(True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_stub_telemetry_report.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Run the full gate to confirm no regression**

Run: `scripts/check_tests.sh`
Expected: exits 0 (no failure outside `tests/known_failures.txt`). If any pre-existing test asserts stub truthiness or emptiness, it must still pass — this plan changed no behavior when telemetry is disabled, and the test suite runs with telemetry disabled by default.

- [ ] **Step 6: Commit**

```bash
git add engine/dev_mode.py tests/unit/test_stub_telemetry_report.py
git commit -m "feat(telemetry): dev-mode gated enable + end-to-end stub report"
```

---

## Self-Review

**1. Spec coverage.** The "spec" is this session's design: (a) observe the object-level `_Stub` surface — Tasks 2 & 3; (b) off by default / byte-identical — Global Constraints + `test_disabled_by_default_*` + `test_stub_still_truthy_*`; (c) roadmap output ranked by frequency — Task 1 `dump_report` + Task 4 end-to-end; (d) truthiness-decision data (bool call sites) — Task 3; (e) never crash the game — Task 1 wrapped hooks + `test_record_never_raises_*`; (f) print() not logging — `dump_report`; (g) dev-mode gating — Task 4. Module-level `_StubModule` and App `_NamedStub` are explicitly deferred (Global Constraints) — a documented gap, not an omission.

**2. Placeholder scan.** No TBD/TODO; every code step shows complete code; no "similar to Task N"; all referenced names (`record_attr`, `record_bool`, `set_enabled`, `snapshot`, `reset`, `dump_report`, `ENABLED`, `_stub_name`, `_stub_owner`, `enable_stub_telemetry`) are defined in an earlier task.

**3. Type consistency.** `record_attr(owner_type, attr_name)`, `record_bool(owner_type)`, `set_enabled(value)`, `dump_report(stream=None) -> str`, `snapshot() -> dict` are used identically in Tasks 2–4 as defined in Task 1. `_Stub.__init__(name, owner)` matches every construction site (`_Stub(name, owner)`, `_Stub()` with defaults). `dev_mode.is_enabled()` is the existing gate referenced by `enable_stub_telemetry`.

**Note for the executor:** confirm the exact current line numbers in `engine/core/ids.py` before editing (the file may have shifted); match on the code text shown, not the line numbers.
