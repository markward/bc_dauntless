# Developer Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a runtime `--developer` CLI flag that gates dev-only keybindings, pause-menu entries, renderer overlays, and CEF UI panels across all three tiers of the stack.

**Architecture:** The flag is parsed once in C++ (`host_main.cc`) into a process-global bool. Three read APIs expose it idiomatically per tier: `dauntless::is_developer_mode()` for native C++, `_dauntless_host.developer_mode` (pybind11 module attr) for Python via `engine.dev_mode.is_enabled()`, and `window.__DAUNTLESS_DEV__` + `document.body.dataset.dev="1"` in the CEF DOM (pushed via `cef_execute_javascript` at document load). Python helpers (`register_dev_keybinding`, `dev_only` decorator) make adding dev surfaces a one-liner.

**Tech Stack:** C++20, pybind11, CPython embed (3.11+), CEF (off-screen rendering), GLFW, pytest, cmake.

**Reference spec:** [docs/superpowers/specs/2026-06-02-developer-flag-design.md](../specs/2026-06-02-developer-flag-design.md).

---

## File Structure

**New files:**
- `native/src/host/developer_mode.h` — header exporting `dauntless::is_developer_mode()` / `set_developer_mode(bool)`.
- `native/src/host/developer_mode.cc` — single TU storing the bool.
- `engine/dev_mode.py` — Python facade: `is_enabled()`, `register_dev_keybinding()`, `dispatch_dev_key()`, `dev_only` decorator, `keybinding_descriptions()`.
- `engine/dev_keybindings.py` — concrete dev keybinding registrations (currently: F10 shield-debug). Importing this module registers them.
- `tests/unit/test_dev_mode.py` — Python unit tests for the dev_mode facade.
- `tests/host/test_developer_mode_binding.py` — verifies `_dauntless_host.developer_mode` attribute exists and is a bool.

**Modified files:**
- `native/src/host/CMakeLists.txt` — add `developer_mode.cc` to `HOST_BINDINGS_SOURCES`.
- `native/src/host/host_main.cc` — argv scan + `set_developer_mode(true)` before `Py_InitializeEx`.
- `native/src/host/host_bindings.cc` — `#include "developer_mode.h"`; in `PYBIND11_MODULE` set `m.attr("developer_mode") = dauntless::is_developer_mode();`.
- `engine/host_loop.py` — call `dev_mode.dispatch_dev_key(...)` in input dispatch; remove inline F10 shield-debug block; push CEF init JS once on CEF load-end when dev mode enabled.
- `engine/ui/pause_menu.py` — conditionally append a "Developer" section header + dev rows when `dev_mode.is_enabled()`.
- `native/assets/ui-cef/css/hello.css` — add `.dev-only { display: none; }` and `body[data-dev="1"] .dev-only { display: block; }` rules.

---

## Task 1: C++ developer-mode storage and getter

**Files:**
- Create: `native/src/host/developer_mode.h`
- Create: `native/src/host/developer_mode.cc`
- Modify: `native/src/host/CMakeLists.txt`

- [ ] **Step 1: Create the header.**

Write to `native/src/host/developer_mode.h`:

```cpp
// native/src/host/developer_mode.h
//
// Process-global developer-mode flag. Parsed once from argv in host_main.cc;
// read by C++ callers (renderer overlays) directly, and exposed to Python via
// the _dauntless_host module's `developer_mode` attribute (see host_bindings.cc).
#pragma once

namespace dauntless {

// Returns true if the binary was launched with --developer.
bool is_developer_mode();

// Set by host_main.cc after parsing argv. Tests should not call this directly;
// they monkey-patch _dauntless_host.developer_mode in Python instead.
void set_developer_mode(bool enabled);

}  // namespace dauntless
```

- [ ] **Step 2: Create the implementation.**

Write to `native/src/host/developer_mode.cc`:

```cpp
// native/src/host/developer_mode.cc
#include "developer_mode.h"

namespace dauntless {

namespace {
bool g_developer_mode = false;
}

bool is_developer_mode() { return g_developer_mode; }
void set_developer_mode(bool enabled) { g_developer_mode = enabled; }

}  // namespace dauntless
```

- [ ] **Step 3: Add to CMakeLists.**

Modify `native/src/host/CMakeLists.txt`. Find the `HOST_BINDINGS_SOURCES` set (top of file) and add `developer_mode.cc`:

```cmake
set(HOST_BINDINGS_SOURCES
    host_bindings.cc
    developer_mode.cc
)
```

- [ ] **Step 4: Rebuild and verify it compiles.**

Run from project root:

```bash
cmake -B build -S . && cmake --build build -j
```

Expected: build succeeds, `build/dauntless` and `build/python/_dauntless_host.cpython-*.so` are updated. No new warnings or errors.

- [ ] **Step 5: Commit.**

```bash
git add native/src/host/developer_mode.h native/src/host/developer_mode.cc native/src/host/CMakeLists.txt
git commit -m "feat(host): add dauntless::is_developer_mode getter scaffolding"
```

---

## Task 2: Expose `developer_mode` attribute on `_dauntless_host`

**Files:**
- Modify: `native/src/host/host_bindings.cc` (add include + `m.attr` line)
- Create: `tests/host/test_developer_mode_binding.py`

- [ ] **Step 1: Write the failing test.**

Write to `tests/host/test_developer_mode_binding.py`:

```python
"""Verifies the _dauntless_host module exposes a developer_mode attribute.

The attribute is set at PYBIND11_MODULE init from
dauntless::is_developer_mode(). When pytest loads the .so standalone (no
host_main.cc), the underlying bool defaults to False.
"""


def test_developer_mode_attribute_exists():
    import _dauntless_host
    assert hasattr(_dauntless_host, "developer_mode")


def test_developer_mode_default_is_false():
    import _dauntless_host
    assert _dauntless_host.developer_mode is False


def test_developer_mode_is_python_writable_for_tests():
    """Python tests monkey-patch the attribute to exercise enabled paths.

    The C++ getter is irrelevant in this scenario; only the Python attr
    matters because engine/dev_mode.py reads via getattr().
    """
    import _dauntless_host
    original = _dauntless_host.developer_mode
    try:
        _dauntless_host.developer_mode = True
        assert _dauntless_host.developer_mode is True
    finally:
        _dauntless_host.developer_mode = original
```

- [ ] **Step 2: Run the test to verify it fails.**

```bash
uv run pytest tests/host/test_developer_mode_binding.py -v
```

Expected: `test_developer_mode_attribute_exists` FAILs with `AttributeError: module '_dauntless_host' has no attribute 'developer_mode'`.

- [ ] **Step 3: Wire the attribute in `host_bindings.cc`.**

In `native/src/host/host_bindings.cc`, add the include near the top with the other `#include` lines:

```cpp
#include "developer_mode.h"
```

Then in the `PYBIND11_MODULE(_dauntless_host, m)` block (currently at line 318), add the attribute set right after `m.doc() = ...`:

```cpp
PYBIND11_MODULE(_dauntless_host, m) {
    m.doc() = "open_stbc renderer host bindings (Phase B: window + frame stub)";

    // Process-global developer-mode flag. Set in host_main.cc from --developer.
    // When loaded standalone (e.g. pytest), defaults to False; tests can
    // monkey-patch this attribute to exercise enabled code paths.
    m.attr("developer_mode") = dauntless::is_developer_mode();

    m.def("init", &init,
          py::arg("width"), py::arg("height"), py::arg("title"),
          "Open a window and initialise the renderer.");
    // ... (rest unchanged)
```

- [ ] **Step 4: Rebuild and re-run the test.**

```bash
cmake --build build -j && uv run pytest tests/host/test_developer_mode_binding.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit.**

```bash
git add native/src/host/host_bindings.cc tests/host/test_developer_mode_binding.py
git commit -m "feat(host): expose developer_mode attribute on _dauntless_host"
```

---

## Task 3: Parse `--developer` in `host_main.cc`

**Files:**
- Modify: `native/src/host/host_main.cc`

- [ ] **Step 1: Add the include.**

In `native/src/host/host_main.cc`, add `#include "developer_mode.h"` near the existing `#include "host_bindings.h"` at the top.

- [ ] **Step 2: Add the argv scan before `Py_InitializeEx`.**

In `native/src/host/host_main.cc`, locate the line `Py_InitializeEx(/*initsigs=*/1);` (around line 121). Immediately before it, after `PyImport_AppendInittab` (line 116-119), add:

```cpp
    // Scan all argv tokens for --developer. Positional-agnostic so it composes
    // with the existing positional --smoke-check / --banner modes (which only
    // read argv[1]). Setting must happen before Py_InitializeEx so the
    // attribute set at PYBIND11_MODULE init reads the final value.
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--developer") {
            dauntless::set_developer_mode(true);
            break;
        }
    }
```

- [ ] **Step 3: Rebuild.**

```bash
cmake --build build -j
```

Expected: builds cleanly.

- [ ] **Step 4: Verify the existing smoke-check mode still exits 0.**

```bash
./build/dauntless --smoke-check
```

Expected: prints a Python repr and exits 0. No regression.

- [ ] **Step 5: Verify the flag composes with smoke-check.**

```bash
./build/dauntless --smoke-check --developer
```

Expected: same successful smoke-check output and exit code 0. (The dev flag is parsed but smoke-check exits before any dev-mode behaviour fires.)

- [ ] **Step 6: Commit.**

```bash
git add native/src/host/host_main.cc
git commit -m "feat(host): parse --developer flag in host_main"
```

---

## Task 4: Python `engine/dev_mode.py` — `is_enabled()`

**Files:**
- Create: `engine/dev_mode.py`
- Create: `tests/unit/test_dev_mode.py`

- [ ] **Step 1: Write the failing test.**

Write to `tests/unit/test_dev_mode.py`:

```python
"""Tests for engine.dev_mode — the Python facade over the --developer flag.

The facade reads _dauntless_host.developer_mode via getattr() so it is safe
against stale .so files (returns False) and so tests can monkey-patch the
attribute without touching the C++ side.
"""
import pytest


@pytest.fixture
def reset_dev_mode():
    """Reset the developer_mode attribute and registry around each test."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    original = getattr(_dauntless_host, "developer_mode", False)
    original_registry = dict(dev_mode._dev_keybindings)
    try:
        yield
    finally:
        _dauntless_host.developer_mode = original
        dev_mode._dev_keybindings.clear()
        dev_mode._dev_keybindings.update(original_registry)


def test_is_enabled_returns_false_when_attribute_false(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = False
    assert dev_mode.is_enabled() is False


def test_is_enabled_returns_true_when_attribute_true(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    assert dev_mode.is_enabled() is True


def test_is_enabled_returns_false_when_attribute_missing(reset_dev_mode):
    """Defensive: stale .so without the attribute returns False, not raise."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    saved = _dauntless_host.developer_mode
    del _dauntless_host.developer_mode
    try:
        assert dev_mode.is_enabled() is False
    finally:
        _dauntless_host.developer_mode = saved
```

- [ ] **Step 2: Run the test to verify it fails.**

```bash
uv run pytest tests/unit/test_dev_mode.py -v
```

Expected: FAILs with `ModuleNotFoundError: No module named 'engine.dev_mode'`.

- [ ] **Step 3: Create `engine/dev_mode.py` with `is_enabled()` only.**

Write to `engine/dev_mode.py`:

```python
"""Developer-mode facade for engine/host_loop callers.

Reads the per-process boolean exposed by the C++ host as
_dauntless_host.developer_mode. Uses getattr with a False default so a stale
.so without the attribute degrades to "production mode" rather than raising.
"""
from typing import Callable

import _dauntless_host

# Mapping of GLFW key code -> (handler, description). Populated by
# register_dev_keybinding() in engine/dev_keybindings.py and elsewhere.
# dispatch_dev_key() consults this table only when is_enabled() is True.
_dev_keybindings: dict[int, tuple[Callable, str]] = {}


def is_enabled() -> bool:
    """True iff the binary was launched with --developer."""
    return bool(getattr(_dauntless_host, "developer_mode", False))
```

- [ ] **Step 4: Re-run the test to verify it passes.**

```bash
uv run pytest tests/unit/test_dev_mode.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit.**

```bash
git add engine/dev_mode.py tests/unit/test_dev_mode.py
git commit -m "feat(engine): add dev_mode.is_enabled facade"
```

---

## Task 5: `register_dev_keybinding` + `dispatch_dev_key`

**Files:**
- Modify: `engine/dev_mode.py`
- Modify: `tests/unit/test_dev_mode.py`

- [ ] **Step 1: Write failing tests for the registry.**

Append to `tests/unit/test_dev_mode.py`:

```python
def test_register_and_dispatch_calls_handler_when_enabled(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    calls: list[int] = []
    dev_mode.register_dev_keybinding(42, lambda: calls.append(1), "test key")
    handled = dev_mode.dispatch_dev_key(42)
    assert handled is True
    assert calls == [1]


def test_dispatch_skips_handler_when_disabled(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = False
    calls: list[int] = []
    dev_mode.register_dev_keybinding(42, lambda: calls.append(1), "test key")
    handled = dev_mode.dispatch_dev_key(42)
    assert handled is False
    assert calls == []


def test_dispatch_returns_false_for_unregistered_key(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    handled = dev_mode.dispatch_dev_key(999)
    assert handled is False


def test_keybinding_descriptions_returns_sorted_pairs(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    dev_mode.register_dev_keybinding(10, lambda: None, "B handler")
    dev_mode.register_dev_keybinding(5, lambda: None, "A handler")
    descriptions = dev_mode.keybinding_descriptions()
    assert descriptions == [(5, "A handler"), (10, "B handler")]
```

- [ ] **Step 2: Run tests to verify they fail.**

```bash
uv run pytest tests/unit/test_dev_mode.py -v
```

Expected: the 4 new tests FAIL with `AttributeError: module 'engine.dev_mode' has no attribute 'register_dev_keybinding'`.

- [ ] **Step 3: Implement the registry functions.**

Append to `engine/dev_mode.py`:

```python
def register_dev_keybinding(key: int, handler: Callable, description: str) -> None:
    """Register a handler that runs when `key` is pressed in dev mode.

    `key` is a GLFW key code (see _dauntless_host.keys.KEY_*).
    `description` is shown in the pause menu's developer section.
    Re-registering the same key replaces the prior entry.
    """
    _dev_keybindings[key] = (handler, description)


def dispatch_dev_key(key: int) -> bool:
    """Run the handler registered for `key`. Returns True if a handler ran.

    Returns False when dev mode is off, the key is unregistered, or both.
    The host loop calls this from its input switch before falling through
    to normal gameplay handling.
    """
    if not is_enabled():
        return False
    entry = _dev_keybindings.get(key)
    if entry is None:
        return False
    entry[0]()
    return True


def keybinding_descriptions() -> list[tuple[int, str]]:
    """Return registered (key, description) pairs sorted by key code.

    Used by the pause menu to render the developer section.
    """
    return sorted((k, desc) for k, (_, desc) in _dev_keybindings.items())
```

- [ ] **Step 4: Re-run all dev_mode tests.**

```bash
uv run pytest tests/unit/test_dev_mode.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit.**

```bash
git add engine/dev_mode.py tests/unit/test_dev_mode.py
git commit -m "feat(engine): dev_mode keybinding registry and dispatcher"
```

---

## Task 6: `dev_only` decorator

**Files:**
- Modify: `engine/dev_mode.py`
- Modify: `tests/unit/test_dev_mode.py`

- [ ] **Step 1: Write failing tests.**

Append to `tests/unit/test_dev_mode.py`:

```python
def test_dev_only_runs_when_enabled(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True

    @dev_mode.dev_only
    def f(x):
        return x * 2

    assert f(3) == 6


def test_dev_only_returns_none_when_disabled(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = False

    @dev_mode.dev_only
    def f(x):
        return x * 2

    assert f(3) is None


def test_dev_only_preserves_kwargs(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True

    @dev_mode.dev_only
    def f(a, b=10):
        return a + b

    assert f(1, b=2) == 3
```

- [ ] **Step 2: Run tests to verify they fail.**

```bash
uv run pytest tests/unit/test_dev_mode.py -v -k dev_only
```

Expected: 3 tests FAIL with `AttributeError: module 'engine.dev_mode' has no attribute 'dev_only'`.

- [ ] **Step 3: Implement the decorator.**

Append to `engine/dev_mode.py`:

```python
def dev_only(fn: Callable) -> Callable:
    """Wrap `fn` so it executes only in dev mode (else returns None).

    Intended for temporary behaviour overrides — e.g. forcing invulnerability
    while testing AI, bypassing a damage gate while iterating on a script.
    Wrapping with @dev_only keeps the override callable from leaking into
    production play without per-call `if dev_mode.is_enabled()` boilerplate.
    """
    def wrapper(*args, **kwargs):
        if not is_enabled():
            return None
        return fn(*args, **kwargs)
    return wrapper
```

- [ ] **Step 4: Re-run all dev_mode tests.**

```bash
uv run pytest tests/unit/test_dev_mode.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Commit.**

```bash
git add engine/dev_mode.py tests/unit/test_dev_mode.py
git commit -m "feat(engine): dev_mode.dev_only decorator for gated behaviour"
```

---

## Task 7: Move the F10 shield-debug binding into `engine/dev_keybindings.py`

**Files:**
- Create: `engine/dev_keybindings.py`
- Modify: `engine/host_loop.py` (remove inline F10 block)

This task extracts the existing F10 shield-debug handler at `host_loop.py:2419-2442` into a module that registers it via `dev_mode.register_dev_keybinding`. The handler closes over per-frame state, so we use a small factory function that the host loop calls each frame to bind the current `player` / `session` / `_h` into the handler.

Actually we cannot trivially "register once at import" because the handler needs the current `player` and `session` — values that change every frame. The clean fix is to have `dev_keybindings.py` expose a `register_for_frame(_h, session, player)` callable that re-registers handlers with the current frame state, and the host loop calls it once per tick before invoking `dispatch_dev_key`. This keeps the registry pattern but accommodates per-frame closure.

- [ ] **Step 1: Create the dev keybindings module.**

Write to `engine/dev_keybindings.py`:

```python
"""Dev-only keybinding handlers. Imported by engine.host_loop on startup.

Handlers needing per-frame state (player ship, session) are re-bound every
tick via register_for_frame(); pure-static handlers can be registered once
at module import time.
"""
import engine.dev_mode as dev_mode


def register_for_frame(_h, session, player) -> None:
    """Re-bind handlers that close over per-frame state. Called once per tick
    from the host loop before dev_mode.dispatch_dev_key().
    """
    # F10: debug shield-hit on the shield surface. Real BC weapons impact the
    # bubble at a surface point; firing at the ship center would put the hit
    # too far inside the bubble for the distance falloff to ever exceed zero
    # on the visible shell. Offset along the ship's forward axis by ~1.0 x
    # the ship's GetRadius() so the hit lands near the bubble surface.
    def _f10_shield_debug() -> None:
        if player is None or session is None:
            return
        iid = session.ship_instances.get(player)
        if iid is None:
            return
        from engine.shields import fire_debug_hit
        wp = player.GetWorldLocation()
        try:
            fwd = player.GetWorldRotation().GetCol(1)
            fx, fy, fz = float(fwd.x), float(fwd.y), float(fwd.z)
        except Exception:
            fx, fy, fz = 1.0, 0.0, 0.0
        offset = 1.0 * player.GetRadius()
        fire_debug_hit(
            _h,
            instance_id=iid,
            world_point=(wp.x + fx * offset, wp.y + fy * offset, wp.z + fz * offset),
        )

    dev_mode.register_dev_keybinding(
        _h.keys.KEY_F10, _f10_shield_debug, "Shield-hit debug (F10)"
    )
```

- [ ] **Step 2: Remove the inline F10 block from host_loop.**

In `engine/host_loop.py`, locate the F10 block at lines 2418-2442 (starts with `if not pause.is_open:` then the F10 comment). Delete the F10 conditional block (lines 2419-2442), leaving the `if not pause.is_open:` and the F12 block immediately after it intact. After this edit the section should read:

```python
            if not pause.is_open:
                # F12: toggle CEF DevTools for the UI overlay.
                if _h is not None and _h.key_pressed(_h.keys.KEY_F12):
                    _h.cef_toggle_devtools()
```

- [ ] **Step 3: Run existing host-loop tests to confirm no regression.**

```bash
uv run pytest tests/host/ -v
```

Expected: all tests PASS (the F10 block had no automated test of its own, so removal does not break tests).

- [ ] **Step 4: Commit (handler not yet wired — wiring is Task 8).**

```bash
git add engine/dev_keybindings.py engine/host_loop.py
git commit -m "refactor(host_loop): extract F10 shield-debug to dev_keybindings module"
```

---

## Task 8: Wire `dispatch_dev_key` into the host loop input switch

**Files:**
- Modify: `engine/host_loop.py`

- [ ] **Step 1: Import the modules near the top of `engine/host_loop.py`.**

Add to the imports block (the cluster of `from engine.X import Y` near the top of `engine/host_loop.py`):

```python
import engine.dev_keybindings as dev_keybindings
import engine.dev_mode as dev_mode
```

- [ ] **Step 2: Insert the per-frame dev-key dispatch.**

In `engine/host_loop.py`, locate the `if not pause.is_open:` block (now containing only the F12 devtools toggle after Task 7). Insert dev-key dispatch immediately after the `if not pause.is_open:` line and before the F12 block:

```python
            if not pause.is_open:
                # Dev-mode keybindings (no-op when --developer is not set).
                # register_for_frame re-binds handlers that close over the
                # current player/session each tick; dispatch_dev_key reads
                # _h.key_pressed for every registered key and fires matching
                # handlers. Skipped silently when dev_mode.is_enabled() is False.
                if _h is not None and dev_mode.is_enabled():
                    dev_keybindings.register_for_frame(_h, session, player)
                    for key, _desc in dev_mode.keybinding_descriptions():
                        if _h.key_pressed(key):
                            dev_mode.dispatch_dev_key(key)

                # F12: toggle CEF DevTools for the UI overlay.
                if _h is not None and _h.key_pressed(_h.keys.KEY_F12):
                    _h.cef_toggle_devtools()
```

- [ ] **Step 3: Build + run a quick manual verification.**

```bash
cmake --build build -j
./build/dauntless --developer
```

In the running game: confirm F10 still triggers the shield-debug hit. Quit the game.

Then run without the flag:

```bash
./build/dauntless
```

Confirm F10 is now a no-op (no shield hit fires). Quit.

- [ ] **Step 4: Commit.**

```bash
git add engine/host_loop.py
git commit -m "feat(host_loop): dispatch dev-mode keybindings via dev_mode.dispatch_dev_key"
```

---

## Task 9: Push CEF dev-mode globals on document load

**Files:**
- Modify: `engine/host_loop.py`

The host loop already installs a `cef_set_load_end_handler` callback that invalidates panel snapshots on every document load (line 2208). We wrap that callback to also push the dev-mode globals when enabled.

- [ ] **Step 1: Locate the `_cef_set_load_end` block.**

In `engine/host_loop.py`, find the section near line 2203:

```python
        _cef_set_load_end = getattr(_h, "cef_set_load_end_handler", None) if _h else None
        if _cef_set_load_end is not None:
            # Drop snapshot caches when CEF finishes loading hello.html
            # so the next tick re-emits state. Handles both initial load
            # and Cmd+R reloads.
            _cef_set_load_end(registry.invalidate_all)
```

- [ ] **Step 2: Wrap the callback to also push dev-mode JS.**

Replace the block from Step 1 with:

```python
        _cef_set_load_end = getattr(_h, "cef_set_load_end_handler", None) if _h else None
        if _cef_set_load_end is not None:
            def _on_cef_load_end():
                # Drop snapshot caches so next tick re-emits state. Handles
                # both initial load and Cmd+R reloads.
                registry.invalidate_all()
                # Publish the dev flag to JS/HTML on every document load.
                # When off we leave window.__DAUNTLESS_DEV__ undefined and
                # body[data-dev] unset so CSS hides .dev-only elements by
                # default (fails closed if this push is ever missed).
                if dev_mode.is_enabled() and _h is not None:
                    _h.cef_execute_javascript(
                        "window.__DAUNTLESS_DEV__ = true;"
                        " document.body.dataset.dev = '1';"
                    )
            _cef_set_load_end(_on_cef_load_end)
```

- [ ] **Step 3: Build and run manually.**

```bash
cmake --build build -j
./build/dauntless --developer
```

Press F12 to open the CEF DevTools, then in the Console tab type:

```
window.__DAUNTLESS_DEV__
```

Expected: `true`.

Type:

```
document.body.dataset.dev
```

Expected: `"1"`.

Quit. Run without the flag:

```bash
./build/dauntless
```

Open DevTools (F12), check the same two expressions. Expected: `undefined` and `""` (empty string) respectively.

- [ ] **Step 4: Commit.**

```bash
git add engine/host_loop.py
git commit -m "feat(host_loop): publish developer flag to CEF DOM on load end"
```

---

## Task 10: CSS `.dev-only` rule and pause-menu dev section

**Files:**
- Modify: `native/assets/ui-cef/css/hello.css`
- Modify: `engine/ui/pause_menu.py`

The current pause menu (`engine/ui/pause_menu.py:166-176`) uses `PauseMenuModel.add_item(label, action_id, handler)` to register rows. The JS payload is `{"items":[{"label","action"}], "focused": N}` — there is no row "kind" or styling distinction. To add a visible developer section we:

1. Reserve a no-op handler.
2. Append a separator row `"— DEVELOPER —"` (action_id `dev/_header`).
3. Append one informational row per registered dev keybinding, label `"<description> (F-key)"`, with the same no-op handler. The actual keybinding fires globally via `dispatch_dev_key`; the pause-menu rows are documentation only for now.

CSS `.dev-only` is added in this task too, but the pause-menu rows themselves are rendered through the dynamic `setPauseMenu` payload, not via class-gated HTML — so the CSS rule's first beneficiary is just future static dev panels.

- [ ] **Step 1: Add the CSS rule.**

In `native/assets/ui-cef/css/hello.css`, append to the end of the file:

```css
/* ============================================================
   Developer-mode visibility.
   Elements carrying .dev-only are hidden by default; the host
   loop sets body[data-dev="1"] on CEF load end when --developer
   is set, revealing them. See engine/host_loop.py and
   docs/superpowers/specs/2026-06-02-developer-flag-design.md.
   ============================================================ */
.dev-only {
    display: none;
}
body[data-dev="1"] .dev-only {
    display: revert;
}
```

(Using `display: revert` so each element falls back to its declared display kind — flex containers stay flex, grid stays grid, etc.)

- [ ] **Step 2: Add the import and dev rows to `default_pause_menu`.**

In `engine/ui/pause_menu.py`, add the import near the top of the file (after the existing imports):

```python
import engine.dev_mode as dev_mode
```

Then modify the `default_pause_menu` function (currently at line 166-176) to append the dev section conditionally:

```python
def default_pause_menu(*, on_exit: _Handler, on_cancel: _Handler) -> PauseMenuModel:
    """Build the dauntless default pause menu: Exit Program + Cancel.

    Handlers are injected so the model has no compile-time dependency
    on the host loop. The host loop wires `on_exit` to a quit flag and
    `on_cancel` to the pause-controller toggle.

    When dev_mode.is_enabled(), appends a "— DEVELOPER —" separator and
    one informational row per registered dev keybinding. These rows are
    non-actionable; the actual keybindings fire globally via
    dev_mode.dispatch_dev_key while the menu is closed.
    """
    m = PauseMenuModel()
    m.add_item("Exit Program", "exit",   on_exit)
    m.add_item("Cancel",       "cancel", on_cancel)

    if dev_mode.is_enabled():
        _noop = lambda: None  # noqa: E731 — small inline no-op
        m.add_item("— DEVELOPER —", "dev/_header", _noop)
        for key_code, description in dev_mode.keybinding_descriptions():
            m.add_item(description, "dev/info/" + str(key_code), _noop)

    return m
```

- [ ] **Step 3: Ensure dev rows reflect handlers registered later.**

`default_pause_menu` is called once at host-loop startup, but `engine/dev_keybindings.register_for_frame` runs every tick after the menu is built. To make sure the dev rows include keys registered after menu construction, change the construction order in `engine/host_loop.py` so a one-time `register_for_frame` call happens before `default_pause_menu` is invoked.

Find the line constructing the pause menu in `engine/host_loop.py` (search for `default_pause_menu(`). Immediately before it, while `_h` and `session` are already in scope, add:

```python
        # Pre-register dev keybindings once so default_pause_menu can list
        # them. register_for_frame is also called every tick (see input
        # dispatch) to rebind handlers with the current player/session.
        if _h is not None and dev_mode.is_enabled():
            dev_keybindings.register_for_frame(_h, session, None)
```

(The `player` is unknown at startup, so we pass `None`; the registered handler closures take this as their initial player, but the per-tick rebind in the dispatch loop replaces them once a player exists. The static-row dev menu list only cares about the descriptions and key codes, both of which are stable across rebinds.)

- [ ] **Step 4: Build and verify manually.**

Per project memory, CSS / static-asset changes may need a configure-time copy. Run the full reconfigure if asset changes don't apply:

```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless --developer
```

Press ESC. Expected pause menu items:
- "Exit Program"
- "Cancel"
- "— DEVELOPER —"
- "Shield-hit debug (F10)"

Quit, launch without the flag:

```bash
./build/dauntless
```

Press ESC. Expected items:
- "Exit Program"
- "Cancel"

No DEVELOPER section.

- [ ] **Step 5: Commit.**

```bash
git add native/assets/ui-cef/css/hello.css engine/ui/pause_menu.py engine/host_loop.py
git commit -m "feat(ui): show developer section in pause menu under --developer"
```

- [ ] **Step 4: Build and verify manually.**

```bash
cmake --build build -j   # CSS edits need a cmake reconfigure if assets are copied at configure time
./build/dauntless --developer
```

Press ESC to open the pause menu. Expected: a "DEVELOPER" section is visible at the bottom of the menu listing the F10 shield-hit binding.

Quit, then launch without the flag:

```bash
./build/dauntless
```

Press ESC. Expected: no DEVELOPER section is visible.

If shaders or assets are not picked up after `cmake --build`, re-run the full configure per CLAUDE.md / project memory:

```bash
cmake -B build -S . && cmake --build build -j
```

- [ ] **Step 5: Commit.**

```bash
git add native/assets/ui-cef/css/hello.css engine/ui/pause_menu.py
git commit -m "feat(ui): show developer section in pause menu under --developer"
```

---

## Task 11: Integration sanity-check and final commit

**Files:** none (verification only).

- [ ] **Step 1: Run the full unit and host test suites we touched.**

```bash
uv run pytest tests/unit/test_dev_mode.py tests/host/test_developer_mode_binding.py tests/host/ -v
```

Expected: all pass. No skipped tests beyond the usual environment-dependent ones.

- [ ] **Step 2: Verify smoke-check is unchanged.**

```bash
./build/dauntless --smoke-check
echo "exit: $?"
```

Expected: prints a Python repr; exit code 0.

```bash
./build/dauntless --smoke-check --developer
echo "exit: $?"
```

Expected: same successful output; exit code 0.

- [ ] **Step 3: End-to-end manual run with the flag.**

```bash
./build/dauntless --developer
```

Confirm:
- F10 fires a shield-hit (visible orange ring on the shield bubble).
- ESC opens the pause menu and the DEVELOPER section is visible at the bottom.
- F12 opens DevTools; in the console, `window.__DAUNTLESS_DEV__ === true` and `document.body.dataset.dev === "1"`.

Quit cleanly.

- [ ] **Step 4: End-to-end manual run without the flag.**

```bash
./build/dauntless
```

Confirm:
- F10 is a no-op.
- ESC opens the pause menu; no DEVELOPER section.
- DevTools (F12), `window.__DAUNTLESS_DEV__` is `undefined`; `document.body.dataset.dev` is `""`.

Quit cleanly.

- [ ] **Step 5: Tag the feature as done.**

No code changes; nothing to commit. The plan is complete. Optional: open a PR with the commits from Tasks 1-10.

---

## Notes for the implementer

- **Stale `.so` failure mode.** If `_dauntless_host` doesn't expose `developer_mode` at runtime (e.g. you forgot to rebuild after Task 2), `dev_mode.is_enabled()` returns `False` silently and dev features are inert. Per CLAUDE.md: rebuild from the project root with `cmake -B build -S . && cmake --build build -j`. Do not add a Python-side workaround.
- **CSS / shader reconfigure.** Per project memory: shader edits aren't picked up by `cmake --build` alone; re-run `cmake -B build -S .` first. The CSS file is a static asset and the same rule may apply if CMake copies assets at configure time. If your manual verification shows the new CSS rule isn't applying, run the full reconfigure.
- **`engine/ui/pause_menu.py` row shape.** Task 10 Step 3 assumes a dict shape that may not match the file exactly. Read the actual row-construction code in that file before editing; mirror its existing keys precisely. The header row may need to be a regular non-focusable row rather than a new "header" kind if the renderer doesn't support headers today.
- **Argv parsing positional semantics.** `--developer` is positional-agnostic (any argv slot), but `--smoke-check` and `--banner` remain positional (argv[1] only). Calling `./build/dauntless --developer --smoke-check` will NOT run smoke-check — the developer scan finds the flag but the mode switch sees `argv[1] = "--developer"` and falls through to the normal host loop. Put mode flags before `--developer` on the command line.
