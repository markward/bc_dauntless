# Mouse-wheel Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the mouse wheel scroll panel content when the cursor is over a UI panel/menu, and step the player ship's impulse throttle (up to 9, down through 0 into reverse) when the cursor is over open space.

**Architecture:** The GLFW scroll callback (currently unregistered — the root bug) feeds the existing `Window` accumulator. The host loop consumes the per-frame wheel delta once and routes it: over a CEF surface (pause/config modal open, or cursor inside a HUD-panel bbox) → forward to CEF via a new `SendMouseWheelEvent` binding; otherwise → nudge `_PlayerControl.impulse_level` one notch per detent. Camera scroll-zoom is removed (zoom stays on `=`/`-`).

**Tech Stack:** C++ (GLFW, CEF, pybind11) in `native/`, Python in `engine/`, pytest.

## Global Constraints

- One build tree only: `build/`. Build with `cmake -B build -S . && cmake --build build -j`; run `./build/dauntless`. Never create `native/build/` or alternate binary paths.
- Editing `native/src/host/host_bindings.cc` requires a **`dauntless` rebuild** (the file compiles into both the binary and the `_open_stbc_host` module) — rebuilding only the module leaves `./build/dauntless` stale.
- `.vert`/`.frag` shader edits need a `cmake -B build -S .` reconfigure first — **not relevant here** (no shader edits).
- Internal speed/velocity units are game units; variables are `*_gu`/`*_gups`, never `*_m`/`*_mps`. (This plan touches only the discrete `impulse_level` int, no new speed math.)
- Python tests: run via `uv run pytest <path> -v`. Full suite is memory-safe (~290 MB).

---

### Task 1: Register the GLFW scroll callback (native)

The `Window` accumulator (`add_scroll_y`/`consume_scroll_y`) exists but nothing ever calls `add_scroll_y` — no `glfwSetScrollCallback` is registered. This is the root cause of "scrolling does nothing". Wire it next to the existing cursor-pos callback.

**Files:**
- Modify: `native/src/renderer/window.cc:65-69` (add scroll callback after the cursor callback)

**Interfaces:**
- Consumes: existing `Window::add_scroll_y(double)` (declared `window.h:52`), existing user-pointer set at `window.cc:63`.
- Produces: `consume_scroll_y()` now returns real wheel deltas (positive = scroll up).

- [ ] **Step 1: Add the scroll callback registration**

In `native/src/renderer/window.cc`, immediately after the existing `glfwSetCursorPosCallback(...)` block (ends at line 69), insert:

```cpp
    glfwSetScrollCallback(handle_, [](GLFWwindow* w, double /*xoffset*/, double yoffset) {
        if (auto* self = static_cast<Window*>(glfwGetWindowUserPointer(w))) {
            self->add_scroll_y(yoffset);
        }
    });
```

- [ ] **Step 2: Build**

Run: `cmake --build build -j`
Expected: builds with no errors (`window.cc` recompiles).

- [ ] **Step 3: Verify the callback is wired (smoke)**

Run: `grep -n "glfwSetScrollCallback" native/src/renderer/window.cc`
Expected: one match inside the `Window` constructor.

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/window.cc
git commit -m "fix(renderer): register GLFW scroll callback to feed scroll accumulator"
```

---

### Task 2: CEF mouse-wheel forwarder + binding (native)

CEF has no wheel forwarder today (only move/click). Add `send_mouse_wheel` in the CEF lifecycle layer and expose it as `cef_send_mouse_wheel` (both the real and the no-CEF stub binding, so headless builds still import it).

**Files:**
- Modify: `native/src/ui_cef/cef_lifecycle.h:70` (declare after `send_mouse_click`)
- Modify: `native/src/ui_cef/cef_lifecycle.cc:239` (define after `send_mouse_click`)
- Modify: `native/src/host/host_bindings.cc:2486` (real binding after `cef_send_mouse_click`) and `:2547` (stub binding after the `cef_send_mouse_click` stub)

**Interfaces:**
- Consumes: `g_client->browser()->GetHost()->SendMouseWheelEvent(CefMouseEvent, int deltaX, int deltaY)`.
- Produces: Python binding `cef_send_mouse_wheel(x: int, y: int, delta_y: int)` on the host module; positive `delta_y` scrolls up.

- [ ] **Step 1: Declare in the header**

In `native/src/ui_cef/cef_lifecycle.h`, after the `send_mouse_click` declaration (line 70), add:

```cpp
void send_mouse_wheel(int x, int y, int delta_y);
```

- [ ] **Step 2: Define in cef_lifecycle.cc**

In `native/src/ui_cef/cef_lifecycle.cc`, after the `send_mouse_click` function (ends line 239), add:

```cpp
void send_mouse_wheel(int x, int y, int delta_y) {
    if (!g_client || !g_client->browser()) return;
    auto host = g_client->browser()->GetHost();
    if (!host) return;
    CefMouseEvent ev;
    ev.x = x;
    ev.y = y;
    ev.modifiers = 0;
    host->SendMouseWheelEvent(ev, /*deltaX=*/0, /*deltaY=*/delta_y);
}
```

- [ ] **Step 3: Add the real pybind binding**

In `native/src/host/host_bindings.cc`, after the `cef_send_mouse_click` binding (ends line 2486), add:

```cpp
    m.def("cef_send_mouse_wheel",
          [](int x, int y, int delta_y) {
              dauntless::ui_cef::send_mouse_wheel(x, y, delta_y);
          },
          py::arg("x"), py::arg("y"), py::arg("delta_y"),
          "Forward a mouse-wheel event to the CEF overlay. "
          "delta_y: positive scrolls up.");
```

- [ ] **Step 4: Add the no-CEF stub binding**

In the `#else` block of `host_bindings.cc`, after `m.def("cef_send_mouse_click", [](int, int, int, bool) {});` (line 2547), add:

```cpp
    m.def("cef_send_mouse_wheel", [](int, int, int) {});
```

- [ ] **Step 5: Build (full `dauntless` rebuild)**

Run: `cmake --build build -j`
Expected: builds with no errors (`cef_lifecycle.cc` and `host_bindings.cc` recompile; both the binary and the `_open_stbc_host` module relink).

- [ ] **Step 6: Verify the binding is importable**

Run: `uv run python -c "import sys; sys.path.insert(0, 'build/python'); import _open_stbc_host as h; print(hasattr(h, 'cef_send_mouse_wheel'))"`
Expected: `True`

- [ ] **Step 7: Commit**

```bash
git add native/src/ui_cef/cef_lifecycle.h native/src/ui_cef/cef_lifecycle.cc native/src/host/host_bindings.cc
git commit -m "feat(cef): add cef_send_mouse_wheel forwarder + binding"
```

---

### Task 3: `_PlayerControl.nudge_throttle` (Python, TDD)

Add the discrete one-notch-per-detent throttle step. The level set is `-2` (reverse), `0` (stop), `1..9` (impulse) — there is **no** `-1`. Stepping down from `0` jumps to `REVERSE_LEVEL`; stepping up from reverse jumps to `0`. Forward caps at `9`; reverse floors at `REVERSE_LEVEL`.

**Files:**
- Modify: `engine/host_loop.py` — add method to `_PlayerControl` (class starts line 855; place after `__init__` which ends line 893)
- Test: `tests/host/test_player_control.py` (append at end)

**Interfaces:**
- Consumes: `_PlayerControl.impulse_level` (int), `_PlayerControl.REVERSE_LEVEL` (= -2).
- Produces: `_PlayerControl.nudge_throttle(notches: int) -> None`. Positive notches step toward full impulse (cap 9); negative step down through 0 into reverse (floor -2).

- [ ] **Step 1: Write the failing tests**

Append to `tests/host/test_player_control.py`:

```python
def test_nudge_up_increments_one_notch():
    pc = _PlayerControl()
    pc.impulse_level = 3
    pc.nudge_throttle(1)
    assert pc.impulse_level == 4


def test_nudge_up_caps_at_nine():
    pc = _PlayerControl()
    pc.impulse_level = 9
    pc.nudge_throttle(1)
    assert pc.impulse_level == 9


def test_nudge_down_from_one_reaches_stop():
    pc = _PlayerControl()
    pc.impulse_level = 1
    pc.nudge_throttle(-1)
    assert pc.impulse_level == 0


def test_nudge_down_from_stop_enters_reverse():
    pc = _PlayerControl()
    pc.impulse_level = 0
    pc.nudge_throttle(-1)
    assert pc.impulse_level == _PlayerControl.REVERSE_LEVEL  # -2


def test_nudge_down_floors_at_reverse():
    pc = _PlayerControl()
    pc.impulse_level = _PlayerControl.REVERSE_LEVEL
    pc.nudge_throttle(-1)
    assert pc.impulse_level == _PlayerControl.REVERSE_LEVEL


def test_nudge_up_from_reverse_returns_to_stop():
    pc = _PlayerControl()
    pc.impulse_level = _PlayerControl.REVERSE_LEVEL
    pc.nudge_throttle(1)
    assert pc.impulse_level == 0


def test_nudge_multiple_notches_applies_each():
    pc = _PlayerControl()
    pc.impulse_level = 0
    pc.nudge_throttle(3)
    assert pc.impulse_level == 3


def test_nudge_zero_is_noop():
    pc = _PlayerControl()
    pc.impulse_level = 5
    pc.nudge_throttle(0)
    assert pc.impulse_level == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/host/test_player_control.py -k nudge -v`
Expected: FAIL with `AttributeError: '_PlayerControl' object has no attribute 'nudge_throttle'`

- [ ] **Step 3: Implement `nudge_throttle`**

In `engine/host_loop.py`, inside `_PlayerControl`, add this method directly after `__init__` (after line 893):

```python
    def nudge_throttle(self, notches: int) -> None:
        """Step the discrete impulse throttle one notch per detent.

        Level set: REVERSE_LEVEL (-2), 0 (stop), 1..9 (impulse). There is
        no -1: down from 0 jumps to reverse, up from reverse returns to 0.
        Forward caps at 9; reverse floors at REVERSE_LEVEL.
        """
        for _ in range(abs(int(notches))):
            if notches > 0:
                if self.impulse_level < 0:
                    self.impulse_level = 0
                elif self.impulse_level < 9:
                    self.impulse_level += 1
            elif notches < 0:
                if self.impulse_level <= 0:
                    self.impulse_level = self.REVERSE_LEVEL
                else:
                    self.impulse_level -= 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/host/test_player_control.py -k nudge -v`
Expected: all 8 PASS

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_player_control.py
git commit -m "feat(host): add _PlayerControl.nudge_throttle one-notch throttle step"
```

---

### Task 4: Remove scroll-zoom from the camera (Python refactor)

Camera zoom-on-scroll is being replaced by throttle-on-scroll. Drop the `scroll_y` parameter from `_CameraControl.apply` and from `_apply_input`, and update the tests. Keyboard zoom (`zoom_in`/`zoom_out`, the `=`/`-` keys) is untouched.

**Files:**
- Modify: `engine/cameras/chase.py:100-123` (remove `scroll_y` param + zoom block)
- Modify: `engine/host_loop.py:2235-2248` (`_apply_input` signature + `chase.apply` call) and `:3601-3603` (call site)
- Modify: `tests/cameras/test_chase.py` (drop `scroll_y=` args; delete the scroll-zoom tests)
- Modify: `tests/host/test_view_mode.py` (drop `scroll_y=` args; fix `_FakeChase.apply` signature)

**Interfaces:**
- Produces: `_CameraControl.apply(self, dt, h) -> None` (no `scroll_y`); `_apply_input(view_mode, player_control, director, *, player, dt, h) -> None` (no `scroll_y`).

- [ ] **Step 1: Update `_CameraControl.apply` in chase.py**

In `engine/cameras/chase.py`, change the signature at line 100 and remove the scroll-zoom block (lines 120-123). Replace:

```python
    def apply(self, dt: float, h, scroll_y: float) -> None:
        """Read arrow keys + C reset + accumulated scroll, update orbit state.

        `h` is the bindings module (or fake) with key_state/key_pressed and a
        `keys` namespace containing KEY_LEFT/RIGHT/UP/DOWN/C.
        `scroll_y` is the total wheel delta accumulated since the last call.
        """
```

with:

```python
    def apply(self, dt: float, h) -> None:
        """Read arrow keys + C reset, update orbit state.

        `h` is the bindings module (or fake) with key_state/key_pressed and a
        `keys` namespace containing KEY_LEFT/RIGHT/UP/DOWN/C. Wheel zoom was
        removed (the wheel now drives ship throttle); keyboard =/- zoom via
        zoom_in()/zoom_out() is unchanged.
        """
```

Then delete the scroll-zoom block (lines 120-123):

```python
        if scroll_y != 0.0:
            self.distance *= self.ZOOM_FACTOR_PER_NOTCH ** scroll_y
            if self.distance < self.distance_min: self.distance = self.distance_min
            if self.distance > self.distance_max: self.distance = self.distance_max
```

(Leave `ZOOM_FACTOR_PER_NOTCH` and `zoom_in`/`zoom_out` at lines 31, 82, 87 in place — the `=`/`-` keys still use them.)

- [ ] **Step 2: Update `_apply_input` in host_loop.py**

In `engine/host_loop.py`, change `_apply_input` (lines 2235-2248). Replace the signature and the chase call:

```python
def _apply_input(view_mode, player_control, director,
                 *, player, dt, h, scroll_y) -> None:
```
→
```python
def _apply_input(view_mode, player_control, director,
                 *, player, dt, h) -> None:
```

and
```python
        director.chase.apply(dt, h, scroll_y)
```
→
```python
        director.chase.apply(dt, h)
```

- [ ] **Step 3: Update the `_apply_input` call site**

In `engine/host_loop.py` at lines 3601-3603, replace:

```python
                    _apply_input(view_mode, player_control, director,
                                 player=player, dt=_player_dt, h=_h,
                                 scroll_y=scroll_y)
```
with:
```python
                    _apply_input(view_mode, player_control, director,
                                 player=player, dt=_player_dt, h=_h)
```

(`scroll_y` is still consumed earlier and is routed in Task 5 — do not delete the `_consume_scroll()` line.)

- [ ] **Step 4: Update test_chase.py**

In `tests/cameras/test_chase.py`:
- Delete the three scroll-zoom tests (the functions covering lines 120-154: the ones whose bodies call `cc.apply(... scroll_y=3.0)`, `scroll_y=-2.0`, `scroll_y=1000.0`, `scroll_y=-1000.0` — i.e. the test at line 122 and its neighbours that assert on `cc.distance` changing from scroll).
- In every remaining `cc.apply(dt=1.0/60, h=reader, scroll_y=0.0)` call (lines 62, 72, 83, 95, 107, 117, 541), remove the `, scroll_y=0.0` argument.

- [ ] **Step 5: Update test_view_mode.py**

In `tests/host/test_view_mode.py`:
- Change `_FakeChase.apply` (line 72) from `def apply(self, dt, h, scroll_y): self.calls += 1` to `def apply(self, dt, h): self.calls += 1`.
- In each `_apply_input(...)` call (lines 98-99, 114-115, 143-144, 187), remove the `, scroll_y=...` argument (`scroll_y=0.0` and `scroll_y=99.0`).

- [ ] **Step 6: Run the camera + view-mode tests**

Run: `uv run pytest tests/cameras/test_chase.py tests/cameras/test_director.py tests/host/test_view_mode.py -v`
Expected: all PASS (no errors about unexpected/missing `scroll_y`).

- [ ] **Step 7: Commit**

```bash
git add engine/cameras/chase.py engine/host_loop.py tests/cameras/test_chase.py tests/host/test_view_mode.py
git commit -m "refactor(camera): remove wheel scroll-zoom (wheel now drives throttle)"
```

---

### Task 5: Wheel routing helper + host-loop wiring (Python)

Add a pure routing helper (unit-tested) and wire it into the per-frame loop: forward to CEF when paused or cursor-over-panel, else nudge the throttle.

**Files:**
- Modify: `engine/host_loop.py` — add module-level constant + `_route_scroll_wheel` helper (place near other host-loop helpers, e.g. just above `_apply_input` at line 2235); add `_cef_send_wheel` getattr (near line 3217); init `_mx,_my,_cursor_in_panel` defaults before the pause/unpaused mouse branches (before line 3310); call the helper after `scroll_y = _consume_scroll()` (line 3544)
- Test: `tests/host/test_scroll_routing.py` (new)

**Interfaces:**
- Consumes: `_PlayerControl.nudge_throttle` (Task 3); `cef_send_mouse_wheel` binding (Task 2, via `_cef_send_wheel`); `_cursor_in_panel`/`_mx`/`_my` computed in the existing mouse-forward block (lines 3409-3453); `pause.is_open`; `view_mode.is_exterior`.
- Produces: `_route_scroll_wheel(scroll_y, *, route_to_panel, mx, my, send_wheel, player_control, can_throttle) -> None`; module constant `_WHEEL_PX_PER_NOTCH`.

- [ ] **Step 1: Write the failing tests**

Create `tests/host/test_scroll_routing.py`:

```python
"""Unit tests for _route_scroll_wheel — the per-frame mouse-wheel router."""
from engine.host_loop import _route_scroll_wheel, _PlayerControl, _WHEEL_PX_PER_NOTCH


class _FakeWheel:
    def __init__(self):
        self.calls = []

    def __call__(self, x, y, delta_y):
        self.calls.append((x, y, delta_y))


def test_zero_scroll_does_nothing():
    pc = _PlayerControl(); pc.impulse_level = 4
    wheel = _FakeWheel()
    _route_scroll_wheel(0.0, route_to_panel=False, mx=10, my=20,
                        send_wheel=wheel, player_control=pc, can_throttle=True)
    assert pc.impulse_level == 4
    assert wheel.calls == []


def test_over_panel_forwards_to_cef_not_throttle():
    pc = _PlayerControl(); pc.impulse_level = 4
    wheel = _FakeWheel()
    _route_scroll_wheel(1.0, route_to_panel=True, mx=10, my=20,
                        send_wheel=wheel, player_control=pc, can_throttle=True)
    assert pc.impulse_level == 4  # throttle untouched
    assert wheel.calls == [(10, 20, _WHEEL_PX_PER_NOTCH)]


def test_over_panel_scales_and_signs_delta():
    wheel = _FakeWheel()
    _route_scroll_wheel(-2.0, route_to_panel=True, mx=5, my=6,
                        send_wheel=wheel, player_control=None, can_throttle=False)
    assert wheel.calls == [(5, 6, -2 * _WHEEL_PX_PER_NOTCH)]


def test_open_space_scroll_up_increments_throttle():
    pc = _PlayerControl(); pc.impulse_level = 4
    wheel = _FakeWheel()
    _route_scroll_wheel(1.0, route_to_panel=False, mx=0, my=0,
                        send_wheel=wheel, player_control=pc, can_throttle=True)
    assert pc.impulse_level == 5
    assert wheel.calls == []


def test_open_space_scroll_down_decrements_throttle():
    pc = _PlayerControl(); pc.impulse_level = 1
    _route_scroll_wheel(-1.0, route_to_panel=False, mx=0, my=0,
                        send_wheel=_FakeWheel(), player_control=pc, can_throttle=True)
    assert pc.impulse_level == 0


def test_throttle_blocked_when_cannot_throttle():
    pc = _PlayerControl(); pc.impulse_level = 4
    _route_scroll_wheel(1.0, route_to_panel=False, mx=0, my=0,
                        send_wheel=_FakeWheel(), player_control=pc, can_throttle=False)
    assert pc.impulse_level == 4  # bridge view / no player → no throttle


def test_multi_notch_open_space():
    pc = _PlayerControl(); pc.impulse_level = 0
    _route_scroll_wheel(3.0, route_to_panel=False, mx=0, my=0,
                        send_wheel=_FakeWheel(), player_control=pc, can_throttle=True)
    assert pc.impulse_level == 3


def test_panel_route_with_no_send_wheel_is_safe():
    # No CEF binding available → no crash, no throttle change.
    pc = _PlayerControl(); pc.impulse_level = 4
    _route_scroll_wheel(1.0, route_to_panel=True, mx=0, my=0,
                        send_wheel=None, player_control=pc, can_throttle=True)
    assert pc.impulse_level == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/host/test_scroll_routing.py -v`
Expected: FAIL with `ImportError: cannot import name '_route_scroll_wheel'`

- [ ] **Step 3: Add the constant + helper**

In `engine/host_loop.py`, just above `def _apply_input(` (line 2235), add:

```python
# Pixels of CEF scroll per wheel detent (GLFW yoffset == 1.0). Positive
# delta_y scrolls panel content up. Tune to feel; sign confirmed in live
# verify.
_WHEEL_PX_PER_NOTCH = 40


def _route_scroll_wheel(scroll_y, *, route_to_panel, mx, my,
                        send_wheel, player_control, can_throttle) -> None:
    """Route one frame's accumulated mouse-wheel delta.

    route_to_panel True (a pause/config modal is open, or the cursor is over
    a HUD panel) → forward to CEF as a scaled pixel delta. Otherwise, when
    can_throttle (exterior view + a live player), step the ship throttle one
    impulse notch per detent. A no-op when scroll_y is 0.
    """
    if not scroll_y:
        return
    if route_to_panel:
        if send_wheel is not None:
            send_wheel(int(mx), int(my),
                       int(round(scroll_y * _WHEEL_PX_PER_NOTCH)))
        return
    if can_throttle and player_control is not None:
        notches = int(round(scroll_y))
        if notches:
            player_control.nudge_throttle(notches)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/host/test_scroll_routing.py -v`
Expected: all 8 PASS

- [ ] **Step 5: Commit the helper**

```bash
git add engine/host_loop.py tests/host/test_scroll_routing.py
git commit -m "feat(host): add _route_scroll_wheel router (CEF panel scroll vs throttle)"
```

- [ ] **Step 6: Bind `_cef_send_wheel`**

In `engine/host_loop.py`, after the existing CEF mouse getattrs (line 3217: `_cef_send_mouse_click = getattr(...)`), add:

```python
        _cef_send_wheel       = getattr(_h, "cef_send_mouse_wheel", None) if _h else None
```

- [ ] **Step 7: Initialise per-frame cursor/panel defaults**

In `engine/host_loop.py`, immediately before the `if pause.is_open:` block at line 3310, add (matching its indentation — inside the per-frame body, before either mouse branch runs):

```python
                # Per-frame cursor + panel-hit state, defaulted so the
                # scroll router (below) has them defined regardless of which
                # mouse-forward branch runs this frame.
                _mx, _my = 0, 0
                _cursor_in_panel = False
```

(The paused branch at 3327 and the unpaused branch at 3410 already assign `_mx, _my`; the unpaused branch assigns `_cursor_in_panel` at 3451.)

- [ ] **Step 8: Wire the router after scroll consumption**

In `engine/host_loop.py`, the line at 3544 is:

```python
                scroll_y = _consume_scroll() if _consume_scroll is not None else 0.0
```

Immediately after it (before the `if player is not None and _h is not None:` block at 3546), add:

```python
                # Route the wheel: over a CEF surface (pause/config modal or
                # cursor over a HUD panel) → scroll that panel; over open
                # space → step the ship throttle. Replaces the old camera
                # scroll-zoom. can_throttle mirrors the digit-key gate
                # (exterior view + live player).
                _route_scroll_wheel(
                    scroll_y,
                    route_to_panel=(pause.is_open or _cursor_in_panel),
                    mx=_mx, my=_my,
                    send_wheel=_cef_send_wheel,
                    player_control=player_control,
                    can_throttle=(player is not None and view_mode.is_exterior),
                )
```

Also update the comment block at lines 3541-3543 (which says the scroll delta feeds the camera director) to reflect routing — replace "Scroll delta is consumed once per tick; old bindings without the binding return 0.0 via the fallback." with "Scroll delta is consumed once per tick and routed below (panel scroll vs ship throttle); old bindings without the accumulator return 0.0 via the fallback."

- [ ] **Step 9: Run the full host + camera test suites**

Run: `uv run pytest tests/host/ tests/cameras/ -v`
Expected: all PASS (no regressions; new routing + nudge + chase tests green).

- [ ] **Step 10: Commit the wiring**

```bash
git add engine/host_loop.py
git commit -m "feat(host): wire mouse-wheel routing into the frame loop"
```

---

### Task 6: Live verification (manual — Mark)

Automated tests cover the logic; the GLFW/CEF plumbing and the CEF scroll-delta sign need eyes on the running game. This task has no code; it is the acceptance checklist.

**Files:** none.

- [ ] **Step 1: Build and run**

Run: `cmake --build build -j && ./build/dauntless`

- [ ] **Step 2: Verify panel scrolling**

Open the configuration settings panel (and/or a target list with overflowing content). Scroll the wheel with the cursor over the panel.
Expected: the panel content scrolls. If it scrolls the wrong direction, flip the sign of `_WHEEL_PX_PER_NOTCH` usage in `_route_scroll_wheel` (negate the `delta_y`), rebuild, recheck.

- [ ] **Step 3: Verify throttle**

In exterior view with the cursor over open space, scroll up.
Expected: ship impulse steps up notch-by-notch toward 9 (watch the speed readout); scroll down steps down through 0 and into reverse. Cursor over a HUD panel must NOT change speed.

- [ ] **Step 4: Verify camera zoom still works on keys**

Press `=` / `-` in exterior view.
Expected: camera zooms in/out (unchanged). The wheel no longer zooms.

- [ ] **Step 5: Record the outcome**

Note any sign/scale tweaks made and that live verify passed. If `_WHEEL_PX_PER_NOTCH` or its sign changed, commit that adjustment:

```bash
git add engine/host_loop.py
git commit -m "fix(host): tune mouse-wheel CEF scroll delta after live verify"
```

---

## Self-Review

**Spec coverage:**
- Panel scroll → CEF: Tasks 2 (binding) + 5 (routing, `route_to_panel`). ✓
- Throttle on open-space scroll, up to 9 / down to reverse: Tasks 3 (`nudge_throttle`) + 5 (routing). ✓
- Root cause (dead GLFW callback): Task 1. ✓
- Camera scroll-zoom removed, `=`/`-` retained: Task 4. ✓
- Reuse existing panel bboxes + pause/modal state: Task 5 (consumes existing `_cursor_in_panel`, `pause.is_open`). ✓
- Single per-frame consumer: Task 4 keeps the one `_consume_scroll()`; Task 5 routes it. ✓
- Ship Property Viewer (dev) keeps its own scroll: untouched (it reads `consume_scroll_y` directly inside its panel; this plan does not alter that path, and SPV is a dev modal where `view_mode.is_exterior`/panel state differ). Noted in spec edge cases. ✓
- Throttle gated to exterior + player present: Task 5 `can_throttle`. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code. ✓

**Type consistency:** `nudge_throttle(notches: int)` defined in Task 3, called in Task 5 helper and tests. `_route_scroll_wheel(scroll_y, *, route_to_panel, mx, my, send_wheel, player_control, can_throttle)` defined in Task 5 Step 3, matches the Step 1 tests and the Step 8 call site. `cef_send_mouse_wheel(x, y, delta_y)` defined in Task 2, consumed as `_cef_send_wheel` in Task 5. `_CameraControl.apply(dt, h)` and `_apply_input(..., *, player, dt, h)` consistent across Task 4 edits + test updates. `_WHEEL_PX_PER_NOTCH` defined Task 5 Step 3, imported in Task 5 Step 1 tests. ✓

**Note on SPV double-consume:** The spec flags verifying that the dev-only Ship Property Viewer's own `consume_scroll_y` read does not race the new router. SPV is opened from the dev pause menu with the sim frozen; when its panel is active the main-loop router's `can_throttle` is false (not plain exterior gameplay) and `pause.is_open`/panel state routes any stray delta to CEF rather than throttle. No code change needed, but confirm during Task 6 if `--developer` is used.
