# Bridge-Default View + ESC Pause Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make bridge the default view, restrict SPACE to bridge↔tactical toggling, and reserve ESC for a placeholder pause menu that fully freezes the game.

**Architecture:** Flip `_ViewModeController`'s default to BRIDGE and remove ESC from view-mode dispatch. Add a parallel `_PauseMenuController` with an edge-triggered ESC toggle and an idempotent side-effects sync that shows/hides a CEF DOM element via a new `cef_execute_javascript` binding. While paused, gate the tick body so simulation systems skip but the renderer + CEF still paint, keeping the world frozen behind the menu.

**Tech Stack:** Python (engine/host_loop.py), pybind11 + CEF (native/src/host/host_bindings.cc, native/src/ui_cef/cef_lifecycle.{h,cc}), HTML/CSS (native/assets/ui-cef/), pytest.

**Spec:** [docs/superpowers/specs/2026-05-25-bridge-default-mode-and-pause-menu-design.md](../specs/2026-05-25-bridge-default-mode-and-pause-menu-design.md)

---

## File map

| File | Role |
|---|---|
| `engine/host_loop.py` | Flip view-mode default, delete `_handle_esc_for_view_mode`, add `_PauseMenuController` + `_apply_pause_menu_side_effects`, gate tick body |
| `tests/host/test_view_mode.py` | Update existing tests to reflect bridge-default + ESC decoupling |
| `tests/host/test_pause_menu.py` | New — unit tests for `_PauseMenuController` and the sync helper |
| `native/src/ui_cef/cef_lifecycle.h` | Declare `execute_javascript(script)` |
| `native/src/ui_cef/cef_lifecycle.cc` | Implement `execute_javascript(script)` against the existing browser handle |
| `native/src/host/host_bindings.cc` | Add `cef_execute_javascript` pybind11 binding (CEF + stub branches) |
| `native/assets/ui-cef/hello.html` | Add hidden `<div id="pause-menu">` placeholder |
| `native/assets/ui-cef/css/hello.css` | Add `#pause-menu` flexbox-centered overlay rule |

---

## Task 1: Flip view-mode default to BRIDGE

**Files:**
- Modify: `engine/host_loop.py:998-999` (`_ViewModeController.__init__`)
- Test:   `tests/host/test_view_mode.py`

- [ ] **Step 1: Update the "starts" test to assert bridge as the default**

Rename `test_view_mode_starts_exterior` to `test_view_mode_starts_in_bridge` and flip the assertions.

```python
def test_view_mode_starts_in_bridge():
    from engine.host_loop import _ViewModeController
    vm = _ViewModeController()
    assert vm.is_bridge is True
    assert vm.is_exterior is False
```

- [ ] **Step 2: Update the SPACE-toggle test for the new initial state**

In `test_view_mode_toggle_on_space_pressed`, the controller now starts in bridge. The first SPACE press goes to exterior; the second returns to bridge.

```python
def test_view_mode_toggle_on_space_pressed():
    from engine.host_loop import _ViewModeController
    vm = _ViewModeController()
    reader = _FakeKeyReader()

    # No space → no change.
    vm.apply(reader)
    assert vm.is_bridge is True

    # Space pressed once → exterior.
    reader.pressed_once.add(reader.keys.KEY_SPACE)
    vm.apply(reader)
    assert vm.is_exterior is True

    # No space → still exterior (edge-triggered, not held).
    vm.apply(reader)
    assert vm.is_exterior is True

    # Space pressed again → back to bridge.
    reader.pressed_once.add(reader.keys.KEY_SPACE)
    vm.apply(reader)
    assert vm.is_bridge is True
```

- [ ] **Step 3: Update `_apply_input` tests that assume exterior is the default**

The three tests in `tests/host/test_view_mode.py` that exercise `_apply_input` with `_ViewModeController()` and expect exterior behavior must explicitly toggle to exterior after construction:

- `test_apply_input_calls_both_in_exterior_mode` — add `vm.toggle()` after `vm = _ViewModeController()` so the test exercises exterior.
- `test_apply_input_in_bridge_keeps_player_integrating_with_no_input` — remove the `vm.toggle()` line (already in bridge).
- `test_apply_input_in_bridge_keeps_ship_moving_under_real_player_control` — remove the `vm.toggle()` line.
- `test_apply_input_preserves_orbit_state_across_bridge_toggle` — remove the `vm.toggle()` line.
- `test_bridge_camera_anchors_at_ship_origin_looking_forward` — remove the `vm.toggle()` line.

Each of the remaining `_compute_camera` tests that constructs a bare `_ViewModeController()` and expects exterior delegation also needs `vm.toggle()` to go to exterior:

- `test_exterior_camera_delegates_to_cam_control`
- `test_exterior_camera_lock_bias_zero_aims_at_target`
- `test_exterior_camera_lock_shifts_look_at_down_along_image_up`
- `test_exterior_camera_lock_disabled_keeps_chase_target`
- `test_exterior_camera_unchanged_when_no_target`
- `test_target_lock_places_ship_between_eye_and_target_when_target_behind_ship`
- `test_target_lock_eye_trajectory_is_smooth_as_target_orbits`
- `test_target_lock_places_eye_on_target_ship_line_extended`
- `test_target_lock_z_lift_raises_eye_in_world_z`
- `test_target_lock_keeps_eye_behind_ship_when_target_in_front`

For tests using a bare `_ViewModeController()` directly inline, refactor with a tiny helper at module scope to keep the diff small:

```python
def _exterior_vm():
    from engine.host_loop import _ViewModeController
    vm = _ViewModeController()
    vm.toggle()  # bridge → exterior
    return vm
```

Then replace each inline `_ViewModeController()` used for exterior tests with `_exterior_vm()`. Bridge tests stay `_ViewModeController()`.

- [ ] **Step 4: Run the test file — expect failures**

Run: `uv run pytest tests/host/test_view_mode.py -x`
Expected: FAIL — the default in `_ViewModeController` is still EXTERIOR.

- [ ] **Step 5: Flip the default in `_ViewModeController.__init__`**

In `engine/host_loop.py`:

```python
def __init__(self):
    self._mode = self.BRIDGE
```

Replace the existing line 999 (`self._mode = self.EXTERIOR`).

- [ ] **Step 6: Run the test file — expect pass**

Run: `uv run pytest tests/host/test_view_mode.py -v`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/host/test_view_mode.py
git commit -m "host_loop: default to bridge view on session start"
```

---

## Task 2: Remove ESC → view-mode coupling

**Files:**
- Modify: `engine/host_loop.py:1040-1045` (delete `_handle_esc_for_view_mode`)
- Modify: `engine/host_loop.py:1983-1984` (delete ESC call site)
- Test:   `tests/host/test_view_mode.py` (delete two tests)

- [ ] **Step 1: Delete the two ESC view-mode tests**

In `tests/host/test_view_mode.py`, delete:
- `test_esc_in_bridge_mode_returns_to_exterior`
- `test_esc_in_exterior_mode_is_a_noop`

These tests pin behavior that we are removing.

- [ ] **Step 2: Delete the `_handle_esc_for_view_mode` function**

In `engine/host_loop.py`, remove the entire function (lines 1040-1045):

```python
def _handle_esc_for_view_mode(view_mode: "_ViewModeController") -> None:
    """ESC in bridge mode returns to exterior. ESC in exterior mode is a
    no-op. The side-effect sync runs on the next tick and releases the
    cursor / disables the bridge pass."""
    if view_mode.is_bridge:
        view_mode.toggle()
```

- [ ] **Step 3: Delete the ESC call site in the main loop**

Remove lines 1983-1984 from `engine/host_loop.py`:

```python
if _h is not None and _h.key_pressed(_h.keys.KEY_ESCAPE):
    _handle_esc_for_view_mode(view_mode)
```

(The pause-menu wiring in Task 7 will reintroduce a different ESC handler at this location.)

- [ ] **Step 4: Run the affected tests**

Run: `uv run pytest tests/host/test_view_mode.py -v`
Expected: all tests pass; the two deleted tests are gone from the output.

- [ ] **Step 5: Confirm no other call sites reference `_handle_esc_for_view_mode`**

Run: `grep -rn "_handle_esc_for_view_mode" engine/ tests/`
Expected: zero matches.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/host/test_view_mode.py
git commit -m "host_loop: decouple ESC from view-mode toggle"
```

---

## Task 3: Add `_PauseMenuController`

**Files:**
- Modify: `engine/host_loop.py` (add new class near `_ViewModeController`)
- Test:   `tests/host/test_pause_menu.py` (new file)

- [ ] **Step 1: Create the test file with the controller's unit tests**

Create `tests/host/test_pause_menu.py`:

```python
"""Unit tests for _PauseMenuController — ESC-toggled pause overlay.
Mirrors the fake-bindings pattern from tests/host/test_view_mode.py."""


class _FakeKeys:
    KEY_ESCAPE = 256


class _FakeKeyReader:
    keys = _FakeKeys()

    def __init__(self):
        self.held = set()
        self.pressed_once = set()

    def key_state(self, key):
        return key in self.held

    def key_pressed(self, key):
        if key in self.pressed_once:
            self.pressed_once.discard(key)
            return True
        return False


def test_pause_menu_starts_closed():
    from engine.host_loop import _PauseMenuController
    p = _PauseMenuController()
    assert p.is_open is False


def test_pause_menu_toggle_on_escape_pressed():
    from engine.host_loop import _PauseMenuController
    p = _PauseMenuController()
    reader = _FakeKeyReader()

    # No esc → no change.
    p.apply(reader)
    assert p.is_open is False

    # Esc pressed once → open.
    reader.pressed_once.add(reader.keys.KEY_ESCAPE)
    p.apply(reader)
    assert p.is_open is True

    # No esc → still open (edge-triggered, not held).
    p.apply(reader)
    assert p.is_open is True

    # Esc pressed again → closed.
    reader.pressed_once.add(reader.keys.KEY_ESCAPE)
    p.apply(reader)
    assert p.is_open is False


def test_pause_menu_held_escape_does_not_re_toggle():
    """Held ESC must not flicker the menu — only edge presses toggle."""
    from engine.host_loop import _PauseMenuController
    p = _PauseMenuController()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_ESCAPE)  # held but no edge
    for _ in range(10):
        p.apply(reader)
    assert p.is_open is False
```

- [ ] **Step 2: Run the test file — expect import failure**

Run: `uv run pytest tests/host/test_pause_menu.py -v`
Expected: FAIL — `ImportError: cannot import name '_PauseMenuController'`.

- [ ] **Step 3: Add `_PauseMenuController` to `engine/host_loop.py`**

Insert immediately after `_ViewModeController` (before `_apply_view_mode_side_effects`):

```python
class _PauseMenuController:
    """ESC-toggled pause-menu overlay.

    Edge-triggered on KEY_ESCAPE. Owns the single boolean that the host
    loop reads to decide whether to advance the simulation this tick —
    see the tick body in host_loop.run(). When open, the world keeps
    rendering (frozen) and the CEF overlay paints a placeholder; AI,
    physics, weapons, combat, ship/camera input, and audio tick all
    skip.
    """

    def __init__(self):
        self._open = False

    @property
    def is_open(self) -> bool: return self._open

    def toggle(self) -> None:
        self._open = not self._open

    def apply(self, h) -> None:
        """Poll escape-pressed and toggle on edge."""
        if h.key_pressed(h.keys.KEY_ESCAPE):
            self.toggle()
```

- [ ] **Step 4: Run the tests — expect pass**

Run: `uv run pytest tests/host/test_pause_menu.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_pause_menu.py
git commit -m "host_loop: add _PauseMenuController (ESC-toggled, edge-triggered)"
```

---

## Task 4: Add `cef_execute_javascript` C++ binding

**Files:**
- Modify: `native/src/ui_cef/cef_lifecycle.h` (add declaration)
- Modify: `native/src/ui_cef/cef_lifecycle.cc` (add implementation)
- Modify: `native/src/host/host_bindings.cc` (add pybind11 binding + stub)

- [ ] **Step 1: Declare `execute_javascript` in `cef_lifecycle.h`**

Add after `void reload();` (line 34):

```cpp
// Execute a JavaScript string in the main frame of the overlay browser.
// No-op if no browser is alive. Used to drive DOM mutation from Python
// (e.g. toggling visibility of pause-menu HTML).
void execute_javascript(const std::string& script);
```

- [ ] **Step 2: Implement `execute_javascript` in `cef_lifecycle.cc`**

Add after the `reload()` function (after line 181):

```cpp
void execute_javascript(const std::string& script) {
    if (!g_client || !g_client->browser()) return;
    auto frame = g_client->browser()->GetMainFrame();
    if (!frame) return;
    frame->ExecuteJavaScript(script, frame->GetURL(), 0);
}
```

The accessor pattern (`g_client->browser()`) matches what `reload()` and `toggle_devtools()` already use.

- [ ] **Step 3: Add the pybind11 binding under the CEF branch**

In `native/src/host/host_bindings.cc`, after `cef_reload` (line 901), inside the `#ifdef DAUNTLESS_ENABLE_CEF` branch:

```cpp
    m.def("cef_execute_javascript",
          [](const std::string& script) {
              dauntless::ui_cef::execute_javascript(script);
          },
          py::arg("script"),
          "Execute JavaScript in the main frame of the overlay browser.");
```

- [ ] **Step 4: Add the no-op stub for the non-CEF branch**

In the `#else` branch, after `m.def("cef_reload", ...);` (line 912):

```cpp
    m.def("cef_execute_javascript", [](const std::string&) {});
```

- [ ] **Step 5: Build and verify the binding loads**

Run from the project root:

```bash
cmake --build build -j
```

Expected: clean build.

- [ ] **Step 6: Smoke-test the binding from Python**

Run:

```bash
uv run python -c "import sys, pathlib; sys.path.insert(0, str(pathlib.Path('build/python'))); import _dauntless_host; print(hasattr(_dauntless_host, 'cef_execute_javascript'))"
```

Expected: `True`.

- [ ] **Step 7: Commit**

```bash
git add native/src/ui_cef/cef_lifecycle.h native/src/ui_cef/cef_lifecycle.cc native/src/host/host_bindings.cc
git commit -m "ui_cef: add execute_javascript primitive and Python binding"
```

---

## Task 5: Add pause-menu DOM and CSS

**Files:**
- Modify: `native/assets/ui-cef/hello.html`
- Modify: `native/assets/ui-cef/css/hello.css`

- [ ] **Step 1: Add the placeholder element to `hello.html`**

Replace `<body>...</body>` in `native/assets/ui-cef/hello.html` with:

```html
<body>
    <div class="hello">Hello world</div>
    <div id="pause-menu">placeholder - pause menu</div>
</body>
```

- [ ] **Step 2: Add the `#pause-menu` rule to `hello.css`**

Append to `native/assets/ui-cef/css/hello.css`:

```css
#pause-menu {
    /* Hidden by default; Python sets style.display = 'flex' on ESC. */
    display: none;
    position: fixed;
    inset: 0;
    align-items: center;
    justify-content: center;
    font-family: "Antonio", sans-serif;
    font-size: 48px;
    color: #ffffff;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
    background: rgba(0, 0, 0, 0.5);
    z-index: 100;
}
```

- [ ] **Step 3: Commit**

```bash
git add native/assets/ui-cef/hello.html native/assets/ui-cef/css/hello.css
git commit -m "ui-cef: add hidden pause-menu placeholder element"
```

---

## Task 6: Add `_apply_pause_menu_side_effects`

**Files:**
- Modify: `engine/host_loop.py` (add helper alongside `_apply_view_mode_side_effects`)
- Modify: `tests/host/test_pause_menu.py` (new tests for the sync helper)

- [ ] **Step 1: Add tests for the sync helper**

Append to `tests/host/test_pause_menu.py`:

```python
class _RecordingCef:
    """Records cef_execute_javascript calls for assertion."""

    def __init__(self):
        self.scripts = []  # list of script strings

    def cef_execute_javascript(self, script):
        self.scripts.append(script)


def test_pause_menu_side_effects_show_uses_flex():
    """Opening the menu fires a single execute_javascript call whose
    script targets the pause-menu element and sets display to 'flex'."""
    from engine.host_loop import (_PauseMenuController,
                                  _apply_pause_menu_side_effects)
    p = _PauseMenuController()
    p.toggle()  # closed → open
    rc = _RecordingCef()
    _apply_pause_menu_side_effects(p, rc)
    assert len(rc.scripts) == 1
    assert "pause-menu" in rc.scripts[0]
    assert "'flex'" in rc.scripts[0]


def test_pause_menu_side_effects_hide_uses_none():
    """Closing the menu fires a single execute_javascript call whose
    script sets display to 'none'."""
    from engine.host_loop import (_PauseMenuController,
                                  _apply_pause_menu_side_effects)
    p = _PauseMenuController()
    p.toggle()  # closed → open
    rc = _RecordingCef()
    _apply_pause_menu_side_effects(p, rc)   # initial sync (open)
    p.toggle()  # open → closed
    _apply_pause_menu_side_effects(p, rc)   # second sync (closed)
    assert len(rc.scripts) == 2
    assert "'none'" in rc.scripts[1]


def test_pause_menu_side_effects_idempotent_within_a_state():
    """Calling the sync helper twice without toggling must not re-fire
    the JS execution — only state changes should trigger it."""
    from engine.host_loop import (_PauseMenuController,
                                  _apply_pause_menu_side_effects)
    p = _PauseMenuController()
    rc = _RecordingCef()
    _apply_pause_menu_side_effects(p, rc)   # initial sync (closed)
    _apply_pause_menu_side_effects(p, rc)   # no toggle in between
    assert len(rc.scripts) <= 1
```

- [ ] **Step 2: Run tests — expect import failure**

Run: `uv run pytest tests/host/test_pause_menu.py -v`
Expected: FAIL — `ImportError: cannot import name '_apply_pause_menu_side_effects'`.

- [ ] **Step 3: Add the helper to `engine/host_loop.py`**

Insert immediately after `_apply_view_mode_side_effects`:

```python
def _apply_pause_menu_side_effects(pause: "_PauseMenuController", h) -> None:
    """Mirror the pause flag into the CEF overlay (show/hide the
    pause-menu div). Idempotent — only fires when the state has changed
    since the last call. `h` is the bindings module (or fake) exposing
    cef_execute_javascript.
    """
    target = pause.is_open
    last = getattr(pause, "_last_synced_is_open", None)
    if last == target:
        return
    display = "'flex'" if target else "'none'"
    h.cef_execute_javascript(
        "document.getElementById('pause-menu').style.display = " + display + ";"
    )
    pause._last_synced_is_open = target
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/host/test_pause_menu.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_pause_menu.py
git commit -m "host_loop: add idempotent pause-menu CEF side-effects sync"
```

---

## Task 7: Wire pause-menu into the tick loop

**Files:**
- Modify: `engine/host_loop.py` (instantiate controller, gate tick body)

- [ ] **Step 1: Instantiate `_PauseMenuController` in `run()`**

Find the line `view_mode = _ViewModeController()` ([engine/host_loop.py:1910](../../engine/host_loop.py#L1910)) and add directly below:

```python
        view_mode      = _ViewModeController()
        pause          = _PauseMenuController()
        bridge_camera  = _BridgeCamera()
```

- [ ] **Step 2: Replace the SPACE+side-effect block with the pause-gated layout**

Find the block at [engine/host_loop.py:1938-1945](../../engine/host_loop.py#L1938-L1945):

```python
            # SPACE toggles bridge/exterior view modality. Polled before
            # the F-key handlers so the modality switch happens first in
            # the tick. _apply_view_mode_side_effects mirrors the flag
            # into renderer state (bridge pass enable + cursor lock) and
            # is idempotent — only fires when the mode changed.
            if _h is not None:
                view_mode.apply(_h)
                _apply_view_mode_side_effects(view_mode, _h)
```

Replace with:

```python
            # ESC is always live — drives the pause-menu overlay.
            # SPACE only toggles view-mode when the game is unpaused, so
            # the modality flag and its renderer side-effects can never
            # diverge from what's visible.
            if _h is not None:
                pause.apply(_h)
                _apply_pause_menu_side_effects(pause, _h)
                if not pause.is_open:
                    view_mode.apply(_h)
                    _apply_view_mode_side_effects(view_mode, _h)
```

- [ ] **Step 3: Gate the simulation systems on `not pause.is_open`**

Wrap the sim-advancing portion of the tick body in `if not pause.is_open:`. The pause-able block spans the F10 / F12 / Cmd+R handlers through `_advance_combat` and the transform-sync loop — everything that *advances* state. Camera + lighting + render must keep running so the world stays painted behind the menu.

Concretely:

Before — the relevant tick body sequence (after the SPACE block) is:

```
F10 handler
F12 handler
Cmd+R handler
(ESC handler — already removed in Task 2)
scroll consume
_apply_alert_keys + _apply_input          ← skip when paused
_poll_mouse_buttons                       ← skip when paused
_advance_weapons                          ← skip when paused
_advance_combat                           ← skip when paused
session.ship_instances transform sync     ← skip when paused
session.planet_instances transform sync   ← skip when paused
fixed_camera / _compute_camera + r.set_*  ← keep
tick_audio                                ← skip when paused
_resolve_active_set                       ← keep (used by lighting)
_update_ui_for_tick                       ← skip when paused
lighting / bridge_lighting / backdrops    ← keep
suns / lens_flares                        ← keep
r.frame()                                 ← keep
```

The `loop.tick()` call at the top of the body also advances Python AI and the timer manager — that must skip too.

Implementation strategy: put **one** outer guard around `loop.tick()` and the controller-swap block (since they happen before the SPACE/pause logic) is impractical because pause must be detected *before* deciding to advance the loop. Instead, restructure as:

After the `while not r.should_close():` line, restructure the body so the pause check happens first:

```python
        while not r.should_close():
            # Drive pause-menu and view-mode toggles before any other
            # tick work. ESC is always live; SPACE only toggles when
            # unpaused.
            if _h is not None:
                pause.apply(_h)
                _apply_pause_menu_side_effects(pause, _h)
                if not pause.is_open:
                    view_mode.apply(_h)
                    _apply_view_mode_side_effects(view_mode, _h)

            if not pause.is_open:
                loop.tick()

                had_pending_swap = controller.pending_swap is not None
                controller._drain_pending_swap()
                if had_pending_swap:
                    cam_control.snap()
            else:
                had_pending_swap = False

            session = controller.session
            player = session.player if session is not None else None
            if had_pending_swap and player is not None:
                cam_control.set_ship_radius(player.GetRadius())
```

(Move `session = controller.session` and `player = ...` out of the pause-gated block so the render section below can still read the latest snapshot.)

Then wrap the remaining sim-advancing systems with `if not pause.is_open:`. The whole block from the F10 handler through `_advance_combat` and the transform-sync loops should be inside the guard. The camera+lighting+render section below stays unguarded.

- [ ] **Step 4: Concretely place the `if not pause.is_open:` guard**

The full restructured body (replace lines 1929-2046 with this — line numbers will shift; locate by the surrounding `loop.tick()` and `r.frame()` calls):

```python
            # --- Input dispatch + modality (always runs) ---
            if _h is not None:
                pause.apply(_h)
                _apply_pause_menu_side_effects(pause, _h)
                if not pause.is_open:
                    view_mode.apply(_h)
                    _apply_view_mode_side_effects(view_mode, _h)

            # --- Sim advance (skipped while paused) ---
            if not pause.is_open:
                loop.tick()

                had_pending_swap = controller.pending_swap is not None
                controller._drain_pending_swap()
                if had_pending_swap:
                    cam_control.snap()
            else:
                had_pending_swap = False

            session = controller.session
            player = session.player if session is not None else None
            if had_pending_swap and player is not None:
                cam_control.set_ship_radius(player.GetRadius())

            if not pause.is_open:
                # F10: debug shield-hit ... (existing block unchanged)
                if (_h is not None
                        and _h.key_pressed(_h.keys.KEY_F10)
                        and player is not None
                        and session is not None):
                    iid = session.ship_instances.get(player)
                    if iid is not None:
                        from engine.shields import fire_debug_hit
                        wp = player.GetWorldLocation()
                        try:
                            fwd = player.GetWorldRotation().GetRow(1)
                            fx, fy, fz = float(fwd.x), float(fwd.y), float(fwd.z)
                        except Exception:
                            fx, fy, fz = 1.0, 0.0, 0.0
                        offset = 1.0 * player.GetRadius()
                        fire_debug_hit(_h, instance_id=iid,
                                       world_point=(wp.x + fx * offset,
                                                    wp.y + fy * offset,
                                                    wp.z + fz * offset))

                # F12: toggle CEF DevTools for the UI overlay.
                if _h is not None and _h.key_pressed(_h.keys.KEY_F12):
                    _h.cef_toggle_devtools()

                # Cmd+R / Ctrl+R: hot-reload the CEF overlay's HTML.
                if _h is not None and _h.key_pressed(_h.keys.KEY_R):
                    _cmd_held = _h.key_state(_h.keys.KEY_LEFT_SUPER) if hasattr(_h.keys, "KEY_LEFT_SUPER") else False
                    _ctrl_held = _h.key_state(_h.keys.KEY_LEFT_CONTROL) if hasattr(_h.keys, "KEY_LEFT_CONTROL") else False
                    if _cmd_held or _ctrl_held:
                        _h.cef_reload()

                # Apply keyboard input to the player ship's transform and to the
                # orbit camera. Scroll delta is consumed once per tick.
                scroll_y = _consume_scroll() if _consume_scroll is not None else 0.0

                if player is not None and _h is not None:
                    _apply_alert_keys(_h, player)
                    _apply_input(view_mode, player_control, cam_control,
                                 player=player, dt=TICK_DT, h=_h,
                                 scroll_y=scroll_y)

                _poll_mouse_buttons(_h)

                _advance_weapons(_all_ships_for_tick(), TICK_DT)
                _advance_combat(
                    _all_ships_for_tick(), TICK_DT, host=_h,
                    ship_instances=(session.ship_instances if session is not None else None),
                )

                # Sync transforms for known instances.
                if session is not None:
                    for ship, iid in session.ship_instances.items():
                        ns = session.ship_natural_scale.get(ship, 1.0)
                        r.set_world_transform(iid, _ship_world_matrix(ship, ns))
                    for planet, iid in session.planet_instances.items():
                        ns = session.planet_natural_scale.get(planet, 1.0)
                        r.set_world_transform(iid, _astro_world_matrix(planet, ns))

            # --- Render (always runs, including while paused) ---
            if fixed_camera:
                fixed_radius = player.GetRadius() if player is not None else 1.0
                eye = (0.0, 0.0, CAM_MAX_RADII * fixed_radius)
                target = (0.0, 0.0, 0.0)
                up_vec = (0.0, 1.0, 0.0)
            elif player is not None:
                eye, target, up_vec = _compute_camera(
                    view_mode, cam_control,
                    player=player, dt=TICK_DT)
                if view_mode.is_bridge:
                    mouse_dx, mouse_dy = _h.consume_mouse_delta() if _h else (0.0, 0.0)
                    bridge_camera.apply(mouse_dx, mouse_dy)
                    b_eye, b_target, b_up = bridge_camera.compute_camera()
                    r.set_bridge_camera(
                        eye=b_eye, target=b_target, up=b_up,
                        fov_y_rad=_BridgeCamera.FOV_Y_RAD,
                        near=_BridgeCamera.NEAR,
                        far=_BridgeCamera.FAR,
                    )
            else:
                eye = (0.0, 30.0, 200.0)
                target = (0.0, 0.0, 0.0)
                up_vec = (0.0, 1.0, 0.0)
            r.set_camera(eye=eye, target=target, up=up_vec,
                         fov_y_rad=1.0472, near=1.0, far=5000.0)

            # Audio listener (skipped while paused — silence the rumble)
            if not pause.is_open:
                _fx0 = target[0] - eye[0]
                _fy0 = target[1] - eye[1]
                _fz0 = target[2] - eye[2]
                _flen = _math.sqrt(_fx0*_fx0 + _fy0*_fy0 + _fz0*_fz0) or 1.0
                tick_audio(
                    camera_position=eye,
                    camera_forward=(_fx0/_flen, _fy0/_flen, _fz0/_flen),
                    camera_up=up_vec,
                    dt=TICK_DT,
                    player=player,
                )

            active_set = _resolve_active_set(player)

            if not pause.is_open:
                _update_ui_for_tick(player, view_mode, session, active_set)

            ambient, directionals = _aggregate_lights(active_set)
            r.set_lighting(ambient, directionals)

            bridge_ambient, bridge_directionals = _aggregate_bridge_lights()
            if player is not None:
                try:
                    if player.GetAlertLevel() == 2:  # ShipClass.RED_ALERT
                        bridge_ambient = tuple(c * 0.5 for c in bridge_ambient)
                except Exception:
                    pass
            r.set_bridge_lighting(bridge_ambient, bridge_directionals)

            backdrops = _aggregate_backdrops(active_set)
            r.set_backdrops(backdrops)

            suns = _aggregate_suns()
            r.set_suns(suns)

            lens_flares = _aggregate_lens_flares()
            r.set_lens_flares(lens_flares)

            if verbose and ticks == 0:
                print(f"[host_loop] tick 0 camera eye={eye} target={target}", flush=True)
                print(f"[host_loop] tick 0 lighting ambient={ambient} "
                      f"directionals={directionals}", flush=True)
                print(f"[host_loop] tick 0 backdrops: "
                      f"{len(backdrops)} layer(s)", flush=True)
                print(f"[host_loop] tick 0 suns: {len(suns)} sun(s)", flush=True)
                print(f"[host_loop] tick 0 lens flares: "
                      f"{len(lens_flares)} flare(s)", flush=True)

            r.frame()
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
```

Notes:
- The audio tick is gated because the engine rumble should silence while paused (and because `tick_audio` advances internal envelopes).
- `_update_ui_for_tick` is gated because the HUD reflects live game state.
- Lighting / backdrops / suns / lens_flares are *not* gated — they read the current `session` snapshot and produce identical output across paused ticks (no advancing state inside them), so calling them is harmless and keeps the rendered frame complete.

- [ ] **Step 5: Run the existing pytest suite**

Run: `uv run pytest tests/host/ -x`
Expected: all tests pass. The pause controller is wired into the loop body; the unit tests don't drive the loop, so they're unaffected.

- [ ] **Step 6: Run the full pytest suite**

Run: `uv run pytest -x`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py
git commit -m "host_loop: ESC toggles pause overlay that freezes the tick body"
```

---

## Task 8: Manual verification

**Files:** none (manual smoke test).

- [ ] **Step 1: Build**

Run: `cmake --build build -j`
Expected: clean build.

- [ ] **Step 2: Launch the game**

Run: `./build/dauntless`
Expected:
- Game opens directly into the bridge view (cursor locked, bridge geometry visible, bridge ambient hum playing). No SPACE press required.

- [ ] **Step 3: SPACE — bridge → tactical**

Press SPACE.
Expected: switches to the tactical exterior view (cursor unlocked, orbit camera around player ship, ambient hum stops, engine rumble audible).

- [ ] **Step 4: SPACE — tactical → bridge**

Press SPACE again.
Expected: returns to bridge. Cursor locks; ambient hum returns; engine rumble silences.

- [ ] **Step 5: ESC in bridge — opens pause menu**

Press ESC while in bridge.
Expected:
- "placeholder - pause menu" text appears centered, with a half-transparent dark backdrop.
- The world freezes (no ship motion, no AI activity, no weapon charging).
- The bridge view stays painted under the overlay.

- [ ] **Step 6: ESC again — closes pause menu, resumes**

Press ESC again.
Expected: overlay disappears; simulation resumes (any in-flight throttle / motion picks back up).

- [ ] **Step 7: ESC in tactical — opens pause menu**

Press SPACE to switch to tactical, then ESC.
Expected: pause overlay appears over the tactical view; simulation freezes. ESC again resumes.

- [ ] **Step 8: SPACE while paused is suppressed**

While the pause overlay is visible, press SPACE.
Expected: view mode does NOT toggle. The overlay stays open. (ESC is the only way out.)

- [ ] **Step 9: C still cycles camera in tactical**

In tactical mode (overlay closed), press C.
Expected: camera mode cycles as before — this plan does not touch the C handler.

- [ ] **Step 10: Commit any verification notes** (optional)

If anything needs updating in CLAUDE.md or docs based on what you observed, commit that as a separate change with message `docs: post-implementation notes for bridge-default mode`.

---

## Self-review notes

- **Spec coverage:** Each of the spec's six requirements maps to a task:
  - "Bridge is the default" → Task 1
  - "SPACE is a pure bridge↔tactical toggle" → Task 1 (relies on existing apply, plus Task 7's gating)
  - "ESC is removed from view-mode dispatch" → Task 2
  - "ESC opens / closes a placeholder pause menu" → Tasks 3, 6, 7
  - CEF JS-eval primitive → Task 4
  - HTML/CSS placeholder → Task 5
  - Test updates → Tasks 1, 2, 3, 6
  - Manual verification → Task 8
- **No placeholders:** every step includes the actual file paths, full code, and expected commands/output.
- **Type consistency:** `_PauseMenuController`, `is_open`, `_apply_pause_menu_side_effects`, `cef_execute_javascript`, `#pause-menu` are used consistently across tasks 3, 6, 7, and the HTML/CSS in task 5.
