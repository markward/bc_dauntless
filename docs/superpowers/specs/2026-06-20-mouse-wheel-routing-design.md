# Mouse-wheel routing: panel scrolling + ship throttle

**Date:** 2026-06-20
**Status:** Design approved, pending spec review

## Problem

The mouse wheel does nothing in-game. Two behaviours are wanted:

1. **Over a panel** (target list, configuration settings, any in-game HUD panel
   or open menu where content may overflow its parent) — the wheel scrolls the
   panel content.
2. **Outside any panel** — the wheel drives the player ship's throttle: scroll
   up steps the impulse setting toward full (cap 9), scroll down steps it down
   through 0 and into reverse.

## Root cause

Scroll input is dead end-to-end. The `Window` class has the accumulator
infrastructure (`add_scroll_y()` / `consume_scroll_y()` in
`native/src/renderer/window.{cc,h}`) but **no `glfwSetScrollCallback` is ever
registered**, so `add_scroll_y()` is never called. `consume_scroll_y()` always
returns `0.0`. The chase camera's intended scroll-zoom
(`engine/cameras/chase.py`) has therefore never functioned either.

There is also no CEF wheel-event forwarder: `native/src/ui_cef/cef_lifecycle.cc`
exposes `send_mouse_move` and `send_mouse_click` but nothing calls CEF's
`SendMouseWheelEvent`.

## Decisions

- **Camera scroll-zoom is removed.** Scroll outside panels controls ship speed
  only. Camera zoom remains on the existing `=` / `-` keys. The `scroll_y`
  argument is removed from `_apply_input` and `chase.apply`.
- **One notch per scroll detent.** Up = +1 impulse level (cap 9). Down = −1,
  stepping `9 → … → 1 → 0 → reverse(−2)`. This matches the SDK
  `IncreaseSpeed`/`DecreaseSpeed` keyboard handlers and the engine's existing
  discrete `impulse_level` set (`-2` reverse, `0` stop, `1..9` impulse).
- **Scrollable-panel detection reuses the existing per-region bounding boxes**
  (left column / bottom row in `host_loop.py`) plus pause/modal-open state.
  Scroll forwards to CEF whenever the cursor is over *any* in-game panel or any
  open menu — not only panels that currently overflow. Simple and future-proof.

## Design

### 1. Native plumbing (C++ — requires a `dauntless` rebuild)

**a. Wire the scroll callback.** In `native/src/renderer/window.cc`, alongside
the existing `glfwSetCursorPosCallback` registration, register
`glfwSetScrollCallback`. The callback retrieves the `Window` (same user-pointer
pattern as the cursor callback) and calls `add_scroll_y(yoffset)`. This is the
missing plumbing that makes `consume_scroll_y()` return real data.

**b. CEF wheel forwarder.** Add `send_mouse_wheel(int x, int y, int delta_y)` to
`cef_lifecycle.{h,cc}` calling `host->SendMouseWheelEvent(event, deltaX=0,
deltaY=delta_y)`. Expose it as `cef_send_mouse_wheel` in
`native/src/host/host_bindings.cc`, mirroring the existing
`send_mouse_move`/`send_mouse_click` bindings. GLFW detents (±1 per notch) are
scaled to CEF pixel deltas on the Python side (≈ ×40 per notch; tune to feel).

### 2. Python routing (`engine/host_loop.py`)

The main loop already computes, once per tick:

- `scroll_y = _consume_scroll()` — the single per-frame consumer of the
  accumulator.
- The cursor-over-panel bounding boxes (`_cursor_in_left_column`,
  `_cursor_in_bottom_row`, combined as `_cursor_in_panel`).
- Pause-menu / modal open state.

New rule, evaluated only when `scroll_y != 0.0`:

```
if cursor over a scrollable CEF surface
   (pause/config modal open OR _cursor_in_panel):
       cef_send_mouse_wheel(_mx, _my, round(scroll_y) * WHEEL_PX_PER_NOTCH)
       # do NOT touch ship throttle this frame
else (exterior view, player present — same gate as the digit keys):
       notches = round(scroll_y)
       step _PlayerControl.impulse_level by notches:
           up:   min(level + n, 9)
           down: level - n, following the sequence 9..1, 0, reverse(-2)
```

The existing ramp / `GetTargetSpeed()` machinery converts the new
`impulse_level` into velocity. No speed-math changes.

### 3. Edge cases

- **Single consumer.** `consume_scroll_y()` resets the accumulator, so only one
  consumer may read it per frame. Removing camera consumption leaves the routing
  block as the sole consumer.
- **Ship Property Viewer (dev-only).** The SPV panel consumes scroll directly
  for hologram zoom. It is a separate dev modal context; the routing yields to it
  (when SPV is open the main-loop routing does not also consume / drive throttle)
  so scroll is not double-consumed. Verify during implementation.
- **Throttle gate.** Wheel throttle is gated to exterior view + player present,
  identical to the existing digit-key throttle path, so it cannot fire on the
  bridge or before a ship exists.
- **Reverse extent.** Scrolling down stops at `REVERSE_LEVEL = -2` (BC's single
  "reverse ¼ impulse" step); it does not go further.

## Files touched

- `native/src/renderer/window.cc` — register `glfwSetScrollCallback`.
- `native/src/ui_cef/cef_lifecycle.{h,cc}` — `send_mouse_wheel`.
- `native/src/host/host_bindings.cc` — `cef_send_mouse_wheel` binding.
- `engine/host_loop.py` — wheel routing; remove `scroll_y` from `_apply_input`.
- `engine/cameras/chase.py` — remove `scroll_y` zoom param.
- `engine/host_loop.py` (`_PlayerControl`) — wheel-driven `impulse_level` step
  helper (reuse the level sequence used by the digit/R keys).

## Testing

- Python unit test: a wheel-up notch increments `impulse_level` (cap 9); a
  wheel-down notch decrements through 0 into reverse(−2); routing prefers CEF
  forwarding when the cursor is flagged over a panel.
- Manual / live verify (Mark): scroll over the target list and configuration
  panel scrolls their content; scroll over open space changes ship speed; camera
  `=`/`-` zoom still works.

## Out of scope

- Horizontal scrolling (deltaX).
- Per-panel "is this panel actually overflowing" detection — any panel/menu
  region captures the wheel regardless of overflow.
- Trackpad momentum / sub-notch smoothing for throttle (round to whole notches).
