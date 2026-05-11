# Bridge View PoC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `space`-toggled bridge/exterior view modality to the renderer host as a minimal PoC that establishes the dispatch seam (input, camera, HUD branch on a single `_ViewModeController` flag) without yet rendering bridge geometry.

**Architecture:** A new `_ViewModeController` in [engine/host_loop.py](../../../engine/host_loop.py) owns the mode and is polled on KEY_SPACE next to F7/F8/F9. Two small free helpers in the same module — `_apply_input` and `_compute_camera` — branch on the controller and are unit-testable without booting the renderer. A new "BRIDGE VIEW" `UiPanel` (visibility wired through a new `UiPanel.set_visible` one-liner) makes the mode visible on screen. Behaviour decided in the spec: ship coasts on existing velocity in bridge mode, bridge camera anchors at ship origin looking along ship-Y forward.

**Tech Stack:** Python 3 (engine), pybind11/GLFW (host bindings rebuild for KEY_SPACE), pytest, RmlUi (existing UI layer, already has `set_panel_visible` in both real and `FakeDom` paths).

**Spec:** [docs/superpowers/specs/2026-05-11-bridge-view-poc-design.md](../specs/2026-05-11-bridge-view-poc-design.md)

---

## File map

- **Create**
  - `tests/host/test_view_mode.py` — all five spec-listed unit tests, mirroring the `_FakeKeys` / `_FakeKeyReader` pattern from [tests/host/test_camera_control.py](../../../tests/host/test_camera_control.py).
- **Modify**
  - [engine/host_loop.py](../../../engine/host_loop.py) — add `_ViewModeController`, `_apply_input`, `_compute_camera` helpers; wire all three into `run()` plus the bridge HUD panel.
  - [engine/ui/panel.py](../../../engine/ui/panel.py) — add `UiPanel.set_visible(visible: bool)`.
  - [tests/ui/test_panel.py](../../../tests/ui/test_panel.py) — one new test for `set_visible`.
  - [native/src/host/host_bindings.cc](../../../native/src/host/host_bindings.cc) — expose `KEY_SPACE` next to KEY_F7/F8/F9.

---

## Task 1: `_ViewModeController` class (toggle behaviour)

**Files:**
- Modify: `engine/host_loop.py` (add class near `_PlayerControl` / `_CameraControl`)
- Create: `tests/host/test_view_mode.py`

- [ ] **Step 1: Write the failing tests for default state and edge-triggered toggle**

Create `tests/host/test_view_mode.py`:

```python
"""Unit tests for _ViewModeController — space-bar toggled bridge/exterior
view modality. Mirrors the fake-bindings pattern from
tests/host/test_camera_control.py."""


class _FakeKeys:
    KEY_SPACE = 200


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


def test_view_mode_starts_exterior():
    from engine.host_loop import _ViewModeController
    vm = _ViewModeController()
    assert vm.is_exterior is True
    assert vm.is_bridge is False


def test_view_mode_toggle_on_space_pressed():
    from engine.host_loop import _ViewModeController
    vm = _ViewModeController()
    reader = _FakeKeyReader()

    # No space → no change.
    vm.apply(reader)
    assert vm.is_exterior is True

    # Space pressed once → bridge.
    reader.pressed_once.add(reader.keys.KEY_SPACE)
    vm.apply(reader)
    assert vm.is_bridge is True

    # No space → still bridge (edge-triggered, not held).
    vm.apply(reader)
    assert vm.is_bridge is True

    # Space pressed again → back to exterior.
    reader.pressed_once.add(reader.keys.KEY_SPACE)
    vm.apply(reader)
    assert vm.is_exterior is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/host/test_view_mode.py -v`
Expected: both FAIL with `ImportError: cannot import name '_ViewModeController' from 'engine.host_loop'`.

- [ ] **Step 3: Implement `_ViewModeController` in `engine/host_loop.py`**

Add the class immediately after the `_CameraControl` class (around line 393) so the input-controller siblings are colocated:

```python
class _ViewModeController:
    """Bridge/exterior view modality.

    Edge-triggered on KEY_SPACE. Owns the single mode flag that input,
    camera, and HUD dispatch off — see _apply_input and _compute_camera.

    Bridge mode is currently a stub: the camera anchors at the ship
    origin looking along ship-Y forward, ship input is suppressed (the
    ship coasts on existing velocity), and a "BRIDGE VIEW" HUD panel
    becomes visible. No bridge geometry yet.
    """
    EXTERIOR = 0
    BRIDGE   = 1

    def __init__(self):
        self._mode = self.EXTERIOR

    @property
    def is_exterior(self) -> bool: return self._mode == self.EXTERIOR
    @property
    def is_bridge(self)   -> bool: return self._mode == self.BRIDGE

    def toggle(self) -> None:
        self._mode = self.BRIDGE if self.is_exterior else self.EXTERIOR

    def apply(self, h) -> None:
        """Poll space-pressed and toggle on edge."""
        if h.key_pressed(h.keys.KEY_SPACE):
            self.toggle()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/host/test_view_mode.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_view_mode.py
git commit -m "feat(view-mode): _ViewModeController with space-toggled bridge/exterior modes"
```

---

## Task 2: Expose `KEY_SPACE` in the C++ bindings

**Files:**
- Modify: `native/src/host/host_bindings.cc:387-390`

- [ ] **Step 1: Add the binding**

In [native/src/host/host_bindings.cc](../../../native/src/host/host_bindings.cc), the `keys` submodule definition runs from line ~365 to ~390. Add `KEY_SPACE` at the end of the function-key block, immediately after `KEY_F9` (line 389):

```cpp
    keys.attr("KEY_F7")    = GLFW_KEY_F7;
    keys.attr("KEY_F8")    = GLFW_KEY_F8;
    keys.attr("KEY_F9")    = GLFW_KEY_F9;
    keys.attr("KEY_SPACE") = GLFW_KEY_SPACE;
    keys.attr("KEY_ESCAPE") = GLFW_KEY_ESCAPE;
```

- [ ] **Step 2: Rebuild the C++ extension**

Per `CLAUDE.md`: there is **one** build tree at `build/` — never run cmake from inside `native/`.

Run:
```bash
cmake --build build -j
```
Expected: clean build, no errors. The binary at `build/open_stbc` and the extension at `build/python/_open_stbc_host.cpython-*.so` are refreshed.

- [ ] **Step 3: Smoke-check the binding is exposed**

Run:
```bash
uv run python -c "import sys; sys.path.insert(0, 'build/python'); import _open_stbc_host as h; print('KEY_SPACE =', h.keys.KEY_SPACE)"
```
Expected: prints `KEY_SPACE = 32` (GLFW_KEY_SPACE is 32). Any `AttributeError` means the rebuild didn't pick up the new line — check that the build output mentions `host_bindings.cc.o` and rerun.

- [ ] **Step 4: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(host): expose KEY_SPACE binding for view-mode toggle"
```

---

## Task 3: `_apply_input` helper — bridge mode skips player & camera input

**Files:**
- Modify: `engine/host_loop.py` (add free function near the bottom of the module, before `run()`)
- Modify: `tests/host/test_view_mode.py` (add tests)

This task extracts the input-application step out of `run()` so it's testable without `r.init`. The wiring change in `run()` itself happens in Task 6.

- [ ] **Step 1: Write the failing tests**

Append to `tests/host/test_view_mode.py`:

```python
class _RecordingInputs:
    """Stand-ins for _PlayerControl / _CameraControl that record whether
    apply() was called, without doing any work."""
    class _Player:
        def __init__(self): self.calls = 0
        def apply(self, player, dt, h): self.calls += 1
    class _Camera:
        def __init__(self): self.calls = 0
        def apply(self, dt, h, scroll_y): self.calls += 1

    def __init__(self):
        self.player = self._Player()
        self.camera = self._Camera()


def test_apply_input_calls_both_in_exterior_mode():
    from engine.host_loop import _ViewModeController, _apply_input
    vm = _ViewModeController()  # exterior
    inputs = _RecordingInputs()
    reader = _FakeKeyReader()
    _apply_input(vm, inputs.player, inputs.camera,
                 player=object(), dt=1.0/60, h=reader, scroll_y=0.0)
    assert inputs.player.calls == 1
    assert inputs.camera.calls == 1


def test_apply_input_skips_both_in_bridge_mode():
    from engine.host_loop import _ViewModeController, _apply_input
    vm = _ViewModeController()
    vm.toggle()  # bridge
    inputs = _RecordingInputs()
    reader = _FakeKeyReader()
    _apply_input(vm, inputs.player, inputs.camera,
                 player=object(), dt=1.0/60, h=reader, scroll_y=0.0)
    assert inputs.player.calls == 0
    assert inputs.camera.calls == 0


def test_apply_input_preserves_orbit_state_across_bridge_toggle():
    """Spec test 5: entering bridge mode must not mutate _CameraControl
    orbit state, so toggling back restores the same exterior framing."""
    from engine.host_loop import _ViewModeController, _CameraControl, _apply_input
    cc = _CameraControl()
    cc.orbit_yaw_rad = 1.234
    cc.orbit_pitch_rad = -0.5
    cc.distance = 4242.0
    saved = (cc.orbit_yaw_rad, cc.orbit_pitch_rad, cc.distance)

    vm = _ViewModeController()
    vm.toggle()  # bridge
    reader = _FakeKeyReader()

    # Drive a "tick" with a non-zero scroll delta. In exterior mode that
    # would shrink cc.distance via cc.apply(); in bridge mode _apply_input
    # must not call cc.apply() at all, so the orbit state stays frozen.
    class _NoopPlayer:
        def apply(self, *a, **k): pass
    _apply_input(vm, _NoopPlayer(), cc, player=object(),
                 dt=1.0/60, h=reader, scroll_y=99.0)
    assert (cc.orbit_yaw_rad, cc.orbit_pitch_rad, cc.distance) == saved
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/host/test_view_mode.py -v`
Expected: the three new tests FAIL with `ImportError: cannot import name '_apply_input' from 'engine.host_loop'`.

- [ ] **Step 3: Implement `_apply_input`**

In `engine/host_loop.py`, add immediately above `def run(...)`:

```python
def _apply_input(view_mode, player_control, cam_control,
                 *, player, dt, h, scroll_y) -> None:
    """Per-tick input dispatch.

    Exterior mode drives both ship and camera from the keyboard. Bridge
    mode skips both — the ship coasts on its existing velocity / angular
    rates, and the orbit camera state is preserved untouched so toggling
    back returns to the same framing.
    """
    if view_mode.is_exterior:
        player_control.apply(player, dt, h)
        cam_control.apply(dt, h, scroll_y)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/host/test_view_mode.py -v`
Expected: all five tests in the file PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_view_mode.py
git commit -m "feat(view-mode): _apply_input helper skips ship+camera input in bridge mode"
```

---

## Task 4: `_compute_camera` helper — bridge anchors at ship origin

**Files:**
- Modify: `engine/host_loop.py`
- Modify: `tests/host/test_view_mode.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/host/test_view_mode.py`:

```python
def test_bridge_camera_anchors_at_ship_origin_looking_forward():
    """Spec test 4: bridge camera eye = ship loc, target along ship
    forward (row 1), up along ship up (row 2)."""
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.appc.math import TGPoint3, TGMatrix3

    class _FakePlayer:
        def __init__(self, loc, rot):
            self._loc, self._rot = loc, rot
        def GetWorldLocation(self): return self._loc
        def GetWorldRotation(self): return self._rot

    loc = TGPoint3(100.0, 200.0, 300.0)
    rot = TGMatrix3()  # identity — forward = (0,1,0), up = (0,0,1)
    player = _FakePlayer(loc, rot)

    vm = _ViewModeController()
    vm.toggle()  # bridge

    eye, target, up_vec = _compute_camera(
        vm, cam_control=None, player=player, dt=1.0/60)

    assert eye    == (100.0, 200.0, 300.0)
    assert target == (100.0, 201.0, 300.0)  # +1 along world-Y (= ship forward)
    assert up_vec == (0.0,   0.0,   1.0)


def test_exterior_camera_delegates_to_cam_control():
    """Sanity check: exterior mode still routes through _CameraControl."""
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.appc.math import TGPoint3, TGMatrix3

    class _FakePlayer:
        def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
        def GetWorldRotation(self): return TGMatrix3()

    class _RecordingCam:
        def __init__(self): self.calls = []
        def compute_camera(self, loc, rot, dt):
            self.calls.append((loc, rot, dt))
            return ((1, 2, 3), (4, 5, 6), (0, 0, 1))

    cam = _RecordingCam()
    eye, target, up_vec = _compute_camera(
        _ViewModeController(), cam_control=cam,
        player=_FakePlayer(), dt=1.0/60)
    assert len(cam.calls) == 1
    assert (eye, target, up_vec) == ((1, 2, 3), (4, 5, 6), (0, 0, 1))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/host/test_view_mode.py -v`
Expected: the two new tests FAIL with `ImportError: cannot import name '_compute_camera' from 'engine.host_loop'`.

- [ ] **Step 3: Implement `_compute_camera`**

In `engine/host_loop.py`, add immediately below `_apply_input`:

```python
def _compute_camera(view_mode, cam_control, *, player, dt) -> tuple:
    """Per-tick camera dispatch.

    Exterior mode delegates to _CameraControl.compute_camera (orbit +
    spring-lag). Bridge mode anchors at the ship origin looking along
    ship-Y forward (row 1 of the rotation matrix) with ship-Z as up
    (row 2). Returns (eye, target, up) as 3-tuples in world space, the
    same shape r.set_camera consumes.
    """
    loc = player.GetWorldLocation()
    rot = player.GetWorldRotation()
    if view_mode.is_bridge:
        fwd = rot.GetRow(1)
        up  = rot.GetRow(2)
        eye    = (loc.x, loc.y, loc.z)
        target = (loc.x + fwd.x, loc.y + fwd.y, loc.z + fwd.z)
        up_vec = (up.x, up.y, up.z)
        return eye, target, up_vec
    return cam_control.compute_camera(loc, rot, dt=dt)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/host/test_view_mode.py -v`
Expected: all seven tests in the file PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_view_mode.py
git commit -m "feat(view-mode): _compute_camera helper with bridge-anchor math"
```

---

## Task 5: `UiPanel.set_visible` one-liner

**Files:**
- Modify: `engine/ui/panel.py`
- Modify: `tests/ui/test_panel.py`

The bindings module already has `set_panel_visible` (real path: [engine/ui/bindings.py:37](../../../engine/ui/bindings.py#L37); fake path: [engine/ui/_dom.py:75](../../../engine/ui/_dom.py#L75)). This task just adds the `UiPanel`-level shim that the host loop will call.

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/test_panel.py`:

```python
def test_panel_set_visible_toggles_dom_state(fake_dom):
    """UiPanel.set_visible flips the panel's visibility in the DOM."""
    from engine.ui.panel import UiPanel
    panel = UiPanel(id="hud", anchor="top",
                    width_vw=20.0, height_vh=6.0, title="X")
    # Panels are visible by default.
    assert fake_dom._panels[panel.panel_id].visible is True
    panel.set_visible(False)
    assert fake_dom._panels[panel.panel_id].visible is False
    panel.set_visible(True)
    assert fake_dom._panels[panel.panel_id].visible is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/ui/test_panel.py::test_panel_set_visible_toggles_dom_state -v`
Expected: FAIL with `AttributeError: 'UiPanel' object has no attribute 'set_visible'`.

- [ ] **Step 3: Implement `UiPanel.set_visible`**

In [engine/ui/panel.py](../../../engine/ui/panel.py), add the method after `set_collapsed` (around line 113, before `set_title`):

```python
    def set_visible(self, visible: bool) -> None:
        """Show or hide the entire panel. Wraps bindings.set_panel_visible."""
        bindings.set_panel_visible(self.panel_id, visible)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/ui/test_panel.py::test_panel_set_visible_toggles_dom_state -v`
Expected: PASS.

- [ ] **Step 5: Run the full ui test suite to confirm no regressions**

Run: `uv run pytest tests/ui/ -v`
Expected: all tests PASS (the new one plus the existing suite).

- [ ] **Step 6: Commit**

```bash
git add engine/ui/panel.py tests/ui/test_panel.py
git commit -m "feat(ui): UiPanel.set_visible wrapper around bindings.set_panel_visible"
```

---

## Task 6: Wire it all into `host_loop.run()`

**Files:**
- Modify: `engine/host_loop.py` — `run()` body around lines 822–999.

This task is the integration glue. It is not separately unit-tested (it runs inside `r.init`). The smoke test in Task 7 validates that the wired-up renderer still tickets cleanly.

- [ ] **Step 1: Add the bridge HUD panel construction**

In [engine/host_loop.py](../../../engine/host_loop.py), inside `run()` immediately after the `debug_panel` block (around line 854 — after the `demo_panel.collapsible("Subspace Echo 47", ...)` line), add:

```python
        # Bridge view marker — visible only when KEY_SPACE has toggled
        # _ViewModeController into bridge mode. PoC: text-only, no
        # bridge geometry yet.
        bridge_hud = ui.UiPanel(id="bridge_hud", anchor="top",
                                width_vw=20.0, height_vh=6.0,
                                title="BRIDGE VIEW")
        bridge_hud.set_visible(False)
```

- [ ] **Step 2: Construct `_ViewModeController` next to the other controllers**

Right after the line `cam_control    = _CameraControl()` (around line 888), add:

```python
        view_mode      = _ViewModeController()
```

- [ ] **Step 3: Poll KEY_SPACE in the function-key block**

In the F7/F8/F9 handler block (around lines 920–928), add the SPACE poll. Place it before the F-key handlers so the modality switch happens first in the tick:

```python
            if _h is not None:
                view_mode.apply(_h)
            # F7 toggles space dust; F8 toggles the RmlUi debugger
            # overlay; F9 toggles whole-UI visibility; ESC dismisses the
            # mission picker (no-op when it isn't open).
            if _h is not None and _h.key_pressed(_h.keys.KEY_F7):
                ...
```

(Leave the existing F7/F8/F9/ESC blocks unchanged.)

- [ ] **Step 4: Replace the input block with `_apply_input`**

Locate the existing input block (around lines 933–936):

```python
            scroll_y = _consume_scroll() if _consume_scroll is not None else 0.0
            if player is not None and _h is not None:
                player_control.apply(player, TICK_DT, _h)
                cam_control.apply(TICK_DT, _h, scroll_y)
```

Replace the inner `if` body with the helper:

```python
            scroll_y = _consume_scroll() if _consume_scroll is not None else 0.0
            if player is not None and _h is not None:
                _apply_input(view_mode, player_control, cam_control,
                             player=player, dt=TICK_DT, h=_h,
                             scroll_y=scroll_y)
```

- [ ] **Step 5: Replace the camera-compute block with `_compute_camera`**

Locate the existing camera block (around lines 946–957):

```python
            if fixed_camera:
                eye = (0.0, 0.0, 1500.0 * SHIP_SCALE)
                target = (0.0, 0.0, 0.0)
                up_vec = (0.0, 1.0, 0.0)
            elif player is not None:
                eye, target, up_vec = cam_control.compute_camera(
                    player.GetWorldLocation(), player.GetWorldRotation(),
                    dt=TICK_DT)
            else:
                eye = (0.0, 30.0, 200.0)
                target = (0.0, 0.0, 0.0)
                up_vec = (0.0, 1.0, 0.0)
```

Replace the `elif player is not None:` branch only (leave `fixed_camera` and the no-player fallback alone — they're orthogonal):

```python
            if fixed_camera:
                eye = (0.0, 0.0, 1500.0 * SHIP_SCALE)
                target = (0.0, 0.0, 0.0)
                up_vec = (0.0, 1.0, 0.0)
            elif player is not None:
                eye, target, up_vec = _compute_camera(
                    view_mode, cam_control,
                    player=player, dt=TICK_DT)
            else:
                eye = (0.0, 30.0, 200.0)
                target = (0.0, 0.0, 0.0)
                up_vec = (0.0, 1.0, 0.0)
```

- [ ] **Step 6: Toggle the bridge HUD visibility per tick**

Immediately after the `r.set_camera(...)` call (around line 958), add:

```python
            bridge_hud.set_visible(view_mode.is_bridge)
```

- [ ] **Step 7: Run the unit tests for the helpers, controllers, and panel**

Run: `uv run pytest tests/host/test_view_mode.py tests/host/test_camera_control.py tests/host/test_player_control.py tests/ui/test_panel.py -v`
Expected: all PASS. (The pre-existing `_PlayerControl` / `_CameraControl` tests must remain green — Task 6 only changes the call sites in `run()`, not those classes.)

- [ ] **Step 8: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host): wire _ViewModeController + bridge HUD into run() tick"
```

---

## Task 7: Smoke-test the live host loop and verify the modality

**Files:** None modified. This is a manual + scripted verification step.

- [ ] **Step 1: Run the existing host smoke test**

Run: `uv run pytest tests/host/test_host_loop_unit.py -v`
Expected: all tests PASS (notably `test_run_M1_Basic_for_a_few_ticks` and `test_run_M1_Basic_player_unmoved_without_input`). These boot the renderer with no input and assert the player stays put — bridge mode is off by default so behaviour must be unchanged.

- [ ] **Step 2: Run the full test suite to catch unrelated regressions**

Run: `uv run pytest -q`
Expected: all PASS (or at most pre-existing failures unrelated to this work; if the `git diff` since `main` is clean apart from this work, anything new that fails is on us).

- [ ] **Step 3: Visually verify the modality (per CLAUDE.md UI rule)**

Per CLAUDE.md: *"For UI or frontend changes, start the dev server and use the feature in a browser before reporting the task as complete."* For this engine the equivalent is launching the host binary and exercising the toggle by hand.

Note: per a saved memory, headless-mode pixel reads on macOS are unreliable, so this verification must be a real visible window — no `OPEN_STBC_HOST_HEADLESS=1`.

Run:
```bash
./build/open_stbc
```

Manually verify (the agent should ask the user to do this if the agent can't drive a window):

  1. Window opens with the third-person exterior view of the ship and the existing HUD panels (Targets, Debug). No "BRIDGE VIEW" panel is visible.
  2. Press **W**/**S**/**A**/**D**/digits — ship pitches/yaws/throttles as today. Arrow keys orbit the camera.
  3. Press **space**. The "BRIDGE VIEW" panel appears at the top of the window. The exterior scene is still rendered but from inside the ship looking forward (camera anchored at ship origin, looking along the ship's nose). Arrow keys no longer orbit; W/A/S/D no longer steer; digit keys do not change throttle. If the ship was moving when space was pressed, it continues to coast in its current direction.
  4. Press **space** again. The "BRIDGE VIEW" panel disappears. Camera returns to the same exterior orbit framing it had before (yaw/pitch/distance preserved). W/A/S/D and arrow keys work again.
  5. Optional sanity: press **F7**, **F8**, **F9**, **C**, **ESC** — none of these are affected; they still toggle dust / debugger / UI / reset orbit / dismiss picker as before.

If any of the above does not behave as listed, do **not** mark this step complete — diagnose and fix in a follow-up task before claiming done.

- [ ] **Step 4: Report manual-verification status to the user**

Per CLAUDE.md: *"if you can't test the UI, say so explicitly rather than claiming success."* If the agent ran the binary itself, summarise what it observed; if not, ask the user to perform the steps in Step 3 and confirm.

- [ ] **Step 5: No commit**

Smoke and manual verification do not produce code; nothing to commit.

---

## Done criteria

- All five spec-listed unit tests are present in `tests/host/test_view_mode.py` and pass (test 1 → starts exterior; test 2 → toggles on space; test 3 → bridge skips player input; test 4 → bridge camera anchors at ship origin; test 5 → orbit state preserved across bridge toggle). Plus the two extra coverage tests added in Task 3 / Task 4.
- `UiPanel.set_visible` exists and has a unit test.
- `KEY_SPACE` is exposed by the C++ bindings and `import _open_stbc_host; _h.keys.KEY_SPACE` resolves to 32.
- `host_loop.run()` constructs a `_ViewModeController` and a bridge HUD panel, polls KEY_SPACE per tick, and dispatches input + camera through the new helpers.
- Live host binary toggles between exterior and bridge views on space-press exactly as described in Task 7 Step 3.
- No regressions in `tests/host/`, `tests/ui/`, or the broader `pytest -q` run.
