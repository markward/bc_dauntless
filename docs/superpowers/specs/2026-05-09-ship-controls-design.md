# Ship Controls (Movement-Only) — Design Spec

**Date:** 2026-05-09
**Status:** Approved (pending implementation)
**Phase:** 2, follow-on to renderer-host v1

## Goal

Let the player fly the Galaxy around the M1 Basic scene using BC's stock
movement keybindings. v1 is movement-only — pitch, yaw, roll, throttle.
No weapons, no view modes, no targeting, no menus. Camera also gets a
proper third-person follow that tracks ship orientation, so the result
of input is visible.

## Non-goals

- No weapons (phaser, torpedo, pulse)
- No targeting / target subsystem
- No view-mode cycling (bridge, tactical, external orbit, nav-map)
- No HUD or UI
- No mouse input — keyboard only
- No accel/decel curves — direct level-set on each digit press
- No reading BC's actual config files for keybindings (hard-coded for v1)
- No physics integration through `engine/physics/simulation.py` (it's an
  empty placeholder); transform updates apply directly to the player
  ship's `_position` / `_rotation`. When physics lands later, this code
  re-points to issuing forces / setting target velocity instead

## Keybindings (BC stock)

| Key | Effect |
|---|---|
| `W` | pitch down (continuous while held) |
| `S` | pitch up |
| `A` | yaw left |
| `D` | yaw right |
| `Q` | roll left |
| `E` | roll right |
| `0` | full stop (impulse level 0) |
| `1`..`9` | set forward impulse level 1..9 |
| `R` | reverse at fixed level (equivalent to impulse 2 backward) |

## Success criteria (v1 ship gate)

1. With `./build/bin/open_stbc_host` running and the window focused:
   - W/S/A/D/Q/E rotate the Galaxy continuously while held; release
     stops rotation in that axis.
   - 1–9 set forward velocity at progressively higher levels.
   - 0 stops the ship.
   - R reverses the ship at the fixed reverse speed.
   - Pressing 1–9 after R returns the ship to forward at the new level.
2. The third-person follow camera tracks the ship's position and
   orientation: rolling the ship banks the camera's view; pitching
   tilts; yawing pans.
3. With no key held, the ship continues at its set velocity (no auto-
   damping in v1 — this is space, after all). 0 is the only way to
   stop other than reverse cancellation by 1–9.
4. The existing 24 host+tools pytest cases continue to pass.
5. New pytest cases cover the input-binding surface and the player-
   control state machine. New C++ test covers `Window::key_state`.

---

## Architecture

### Component layout

| Layer | Change |
|---|---|
| `native/src/renderer/include/renderer/window.h` & `window.cc` | Add `bool key_state(int glfw_key) const noexcept` wrapping `glfwGetKey`. |
| `native/src/host/host_bindings.cc` | Expose `key_state(key)` and `key_pressed(key)` to Python plus a small `keys` namespace dict carrying GLFW key codes (`KEY_W`, `KEY_S`, `KEY_A`, `KEY_D`, `KEY_Q`, `KEY_E`, `KEY_R`, `KEY_0`–`KEY_9`). The bindings keep an internal `prev_keys` set for edge detection so `key_pressed` returns true on the rising edge only. |
| `engine/host_loop.py` | Add `_PlayerControl` helper class. `run()` constructs one per session. Each tick (after `loop.tick()`, before transform-sync) calls `player_control.apply(player, dt)`. Camera-follow logic uses ship-local axes from the new rotation. |

### Input flow per tick

```
glfwPollEvents (already runs in frame() via Window::poll_events)
  → renderer::Window::key_state(key) reads glfwGetKey
    → _open_stbc_host.key_state(key) / key_pressed(key) called by Python
      → host_loop._PlayerControl.apply(player, dt) updates ship transform
        → next frame() draws the ship at its new pose
```

### Constants

Class attributes on `_PlayerControl`:
```python
TURN_RATE_RAD_PER_S = 1.5   # ~86°/s — half-turn in ~2.1s
IMPULSE_UNIT        = 50.0  # BC units/s per impulse level
REVERSE_LEVEL       = -2    # signed level set by R
```

Module-level constants in `engine/host_loop.py` (used by camera-follow):
```python
CAM_BACK_DIST = 600.0
CAM_UP_DIST   = 200.0
```

All five tunable by hand for v1. Deferred-work item: "read turn rate
and impulse-unit from `GlobalPropertyTemplates.py` or per-ship
hardpoint properties so they reflect each ship's mass/inertia."

---

## Components

### `renderer::Window` extension

```cpp
// renderer/window.h additions
bool key_state(int glfw_key) const noexcept;
```

```cpp
// renderer/window.cc
bool Window::key_state(int glfw_key) const noexcept {
    if (!handle_) return false;
    return glfwGetKey(handle_, glfw_key) == GLFW_PRESS;
}
```

`glfwGetKey` returns the cached state set by the most recent
`glfwPollEvents` call (which already runs every frame via
`Window::poll_events`). No new event-loop work needed.

### `_open_stbc_host` bindings extension

Three new bindings:

```python
# Returns true while the key is held.
key_state(key: int) -> bool

# Returns true on the rising edge — true for one frame only on press.
# Subsequent calls in the same frame still return true; the latch resets
# at the next frame()/poll cycle.
key_pressed(key: int) -> bool

# Module-level integer constants exposed via the bindings:
KEY_W, KEY_S, KEY_A, KEY_D, KEY_Q, KEY_E, KEY_R
KEY_0, KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_6, KEY_7, KEY_8, KEY_9
```

Implementation owns a TU-local `std::unordered_map<int, bool>
prev_key_state` updated at the start of each `frame()` call. `key_state`
queries `g_window->key_state(key)` directly. `key_pressed` returns
`current && !prev_key_state[key]`.

The constants are exposed as integer attributes on a `keys` sub-object
of the bindings module — pybind11 supports this via `py::class_` or a
plain `py::module_::def_submodule`. Python access pattern:

```python
import _open_stbc_host
_open_stbc_host.keys.KEY_W  # int
```

(The exact pybind11 idiom — submodule vs. simple attributes —
is an implementation choice for the plan; both compile equivalently
from the caller's perspective.)

### `_PlayerControl` (in `engine/host_loop.py`)

```python
class _PlayerControl:
    """Per-tick keyboard → ship-transform integrator. Direct transform
    manipulation (no physics integration). When Phase 1 physics lands,
    this class switches to setting target velocity / heading instead."""

    TURN_RATE_RAD_PER_S = 1.5
    IMPULSE_UNIT        = 50.0
    REVERSE_LEVEL       = -2

    def __init__(self):
        self.impulse_level = 0  # signed: -2..9; 0 = stop

    def apply(self, player, dt: float, h) -> None:
        """Read keys via host module `h`, update ship transform.

        `h` is the _open_stbc_host module (or any duck-typed key reader
        with key_state / key_pressed and KEY_* constants).
        """
        # 1. Throttle (one-shot edges)
        if h.key_pressed(h.keys.KEY_R):    self.impulse_level = self.REVERSE_LEVEL
        elif h.key_pressed(h.keys.KEY_0):  self.impulse_level = 0
        else:
            for digit, code in enumerate(
                [h.keys.KEY_1, h.keys.KEY_2, h.keys.KEY_3, h.keys.KEY_4,
                 h.keys.KEY_5, h.keys.KEY_6, h.keys.KEY_7, h.keys.KEY_8,
                 h.keys.KEY_9], start=1):
                if h.key_pressed(code):
                    self.impulse_level = digit
                    break

        # 2. Angular rates (continuous while held)
        pitch_rate = 0.0
        yaw_rate   = 0.0
        roll_rate  = 0.0
        if h.key_state(h.keys.KEY_W): pitch_rate -= self.TURN_RATE_RAD_PER_S
        if h.key_state(h.keys.KEY_S): pitch_rate += self.TURN_RATE_RAD_PER_S
        if h.key_state(h.keys.KEY_A): yaw_rate   -= self.TURN_RATE_RAD_PER_S
        if h.key_state(h.keys.KEY_D): yaw_rate   += self.TURN_RATE_RAD_PER_S
        if h.key_state(h.keys.KEY_Q): roll_rate  -= self.TURN_RATE_RAD_PER_S
        if h.key_state(h.keys.KEY_E): roll_rate  += self.TURN_RATE_RAD_PER_S

        # 3. Rotation integration (post-multiply in ship-local frame)
        from engine.appc.math import TGMatrix3, TGPoint3
        X_AXIS = TGPoint3(1.0, 0.0, 0.0)
        Y_AXIS = TGPoint3(0.0, 1.0, 0.0)
        Z_AXIS = TGPoint3(0.0, 0.0, 1.0)

        R = player.GetWorldRotation()
        if pitch_rate or yaw_rate or roll_rate:
            R_pitch = TGMatrix3(); R_pitch.MakeRotation(pitch_rate * dt, X_AXIS)
            R_yaw   = TGMatrix3(); R_yaw.MakeRotation(yaw_rate   * dt, Z_AXIS)
            R_roll  = TGMatrix3(); R_roll.MakeRotation(roll_rate  * dt, Y_AXIS)
            R = R.MultMatrix(R_pitch).MultMatrix(R_yaw).MultMatrix(R_roll)
            player.SetMatrixRotation(R)

        # 4. Position integration (forward = ship-local Y axis in world)
        if self.impulse_level != 0:
            forward = R.GetRow(1)
            speed   = self.impulse_level * self.IMPULSE_UNIT
            p = player.GetTranslate()
            player.SetTranslateXYZ(
                p.x + forward.x * speed * dt,
                p.y + forward.y * speed * dt,
                p.z + forward.z * speed * dt,
            )
```

Order of axis composition (pitch → yaw → roll) is a deliberate choice
matching flight-sim convention; at 60Hz with `TURN_RATE_RAD_PER_S=1.5`
the per-tick delta is 0.025 rad, well below the threshold where
composition order produces visible artifacts.

### Camera-follow update (in `engine/host_loop.py:run`)

Replace the current world-axis offset with a ship-local-axis offset:

```python
elif player is not None:
    R = player.GetWorldRotation()
    forward = R.GetRow(1)
    up      = R.GetRow(2)
    p = player.GetWorldLocation()
    eye = (p.x - forward.x * CAM_BACK_DIST + up.x * CAM_UP_DIST,
           p.y - forward.y * CAM_BACK_DIST + up.y * CAM_UP_DIST,
           p.z - forward.z * CAM_BACK_DIST + up.z * CAM_UP_DIST)
    target = (p.x, p.y, p.z)
    up_vec = (up.x, up.y, up.z)  # ship-up so banking is visible
    r.set_camera(eye=eye, target=target, up=up_vec,
                 fov_y_rad=1.0472, near=1.0, far=100000.0)
```

`OPEN_STBC_HOST_FIXED_CAMERA=1` continues to override this with the
known-good test camera at `(0, 0, 1500) → origin`.

---

## Tick frame integration point

```python
loop = GameLoop()
player_control = _PlayerControl()
TICK_DT = 1.0 / 60.0

while not r.should_close():
    loop.tick()

    # Apply keyboard input to the player ship before transform sync.
    if player is not None:
        import _open_stbc_host as _h
        player_control.apply(player, TICK_DT, _h)

    # Sync transforms for known instances.
    for ship, iid in instances.items():
        r.set_world_transform(iid, _world_matrix_row_major(ship))

    # Camera follow (ship-local axes; see camera section above).
    ...

    r.frame()
```

---

## Tests

| Layer | Test | What it asserts |
|---|---|---|
| Renderer C++ | `Window.KeyStateReturnsFalseForUnpressedKeys` | Hidden window, query several keys, all return false. Ensures `glfwGetKey` is wired up and the function compiles + links. |
| Bindings | `tests/host/test_input_bindings.py::test_key_constants_exist` | After import, `_open_stbc_host.keys.KEY_W` etc. are integers and distinct. |
| Bindings | `tests/host/test_input_bindings.py::test_key_state_false_when_no_focus` | After `init`, `key_state(KEY_W)` returns False (no keys held in offscreen test). |
| Bindings | `tests/host/test_input_bindings.py::test_key_pressed_returns_false_when_not_held` | `key_pressed(KEY_W)` returns False initially and stays False across frame() calls when the key isn't held. (Real rising-edge testing requires injected key events; in offscreen tests with no focused window, glfwGetKey always returns RELEASE — so this test verifies the no-input baseline only. The `_PlayerControl` unit tests use a mock key reader to exercise the rising-edge logic itself.) |
| host_loop unit | `tests/host/test_player_control.py::test_throttle_state_machine` | Mock `_h` reader returning configured key events; press 5 → level=5; press R → level=-2; press 0 → level=0; press 7 → level=7. |
| host_loop unit | `tests/host/test_player_control.py::test_pitch_integration` | Player starting at identity rotation; hold W (pitch down) for `dt=1.0/60` for 60 ticks; final rotation should equal a 1.5-rad pitch-down rotation (compare ship-forward direction). |
| host_loop unit | `tests/host/test_player_control.py::test_yaw_integration` | Same pattern with A held; ship-forward should rotate around world up. |
| host_loop unit | `tests/host/test_player_control.py::test_roll_integration` | Same pattern with Q held; ship-up should rotate around ship-forward. |
| host_loop unit | `tests/host/test_player_control.py::test_position_integration` | At identity rotation, level 5 for one second of dt advances position by `5 * IMPULSE_UNIT * 1.0` along world +Y. |
| host_loop unit | `tests/host/test_player_control.py::test_no_input_no_movement` | No keys held; player position and rotation unchanged after multiple `apply` calls. |
| End-to-end | extension to `test_run_M1_Basic_for_a_few_ticks` | Player position unchanged across 5 ticks with no input (regression check that the new code path doesn't introduce drift). |

`Window::key_state` returns false in offscreen tests because GLFW only
reports key events for the focused window; offscreen windows never
gain focus. The integration tests rely on a mock key reader; real
keyboard testing is the manual ship-gate run.

---

## Deferred / future work

Add to `native/src/host/docs/deferred_work.md` and the renderer-host spec:

1. **Read turn rate / max impulse from BC config.** `IMPULSE_UNIT` and
   `TURN_RATE_RAD_PER_S` are tunable constants in `_PlayerControl`;
   should come from the ship's `ImpulseEngineSubsystem` properties or
   `GlobalPropertyTemplates.py` once Phase 1 wires those up.
2. **Switch to physics integration.** When `engine/physics/simulation.py`
   gets a real PyBullet integrator, `_PlayerControl.apply` should set
   target velocity / target angular velocity on the ship's impulse
   subsystem instead of writing the transform directly. The current
   direct-write path becomes a fallback for missions without physics.
3. **BC config-file keybindings.** Read user-customized bindings from
   `data/scripts/Custom/Bridge/Keymap.py` (or wherever BC stores them)
   so players who remap keys see those bindings honored.
4. **Mouse input.** Stock BC supports yaw/pitch via mouse-look; v1 is
   keyboard-only.
5. **Acceleration / deceleration curves.** v1 sets impulse level
   instantaneously; BC ramps. Adding ramps requires the physics work
   above.
6. **View mode cycling** (bridge/tactical/external/nav-map). Each needs
   its own camera controller and — for bridge view — the bridge model
   loaded as an instance.
7. **Weapons / targeting / HUD.** Full BC input surface; out of scope
   for this spec.
8. **Auto-damping toggle.** Some space sims auto-damp angular velocity
   when no input is held; v1 doesn't (release = stop turning, but no
   re-centering).

---

## Update protocol

When a deferred-work item is added, removed, or moves on/off the list,
update both this spec's "Deferred / future work" section and the
matching `docs/architecture/sub_project_status.md` row if a headline
status changes.
