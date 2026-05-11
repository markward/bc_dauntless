# Bridge View PoC — Design

**Status:** Draft, pre-implementation.
**Sub-project:** View modality — introduces the bridge/exterior view
split that the original Star Trek: Bridge Commander uses, as a minimal
proof-of-concept that establishes the dispatch seam without yet
rendering bridge geometry.

## Why this scope

The original Bridge Commander has two main views: an **exterior** view
(third-person follow camera, ship visible) and a **bridge** view
(first-person from the captain's chair, looking out the viewscreen at
the same exterior space scene). Player ship controls work in both, and
many systems (audio listener, HUD, mouse-look targets) behave
differently between them.

We currently have only the exterior view. Retrofitting the bridge/
exterior split later means touching every system that branches on view
state — camera, input, HUD, audio, viewscreen UI. Establishing the
modality now, even with a stub bridge view, means those systems get
wired through a single dispatch point from day one rather than each
inventing its own check.

This PoC is deliberately the smallest implementation that proves the
seam works: a key toggle, a camera switch, a HUD marker, no bridge
geometry. If the seam is right, every later addition (bridge NIF,
viewscreen overlay, mouse-look) plugs into it without restructuring.

## Goals

1. Add a `ViewModeController` to [engine/host_loop.py](../../../engine/host_loop.py)
   that owns the current mode (`EXTERIOR` / `BRIDGE`) and exposes
   `toggle()` plus `is_bridge` / `is_exterior` accessors.
2. Bind **space** (edge-triggered via `key_pressed`) to `toggle()`,
   polled in the same block as `F7`/`F8`/`F9`.
3. In `BRIDGE` mode: still call `_PlayerControl.apply()` so ship
   physics keep integrating (engines coast, position/rotation update
   each tick) but pass it a no-input reader stub so live keys have no
   effect; skip `_CameraControl.apply()` so the orbit camera state is
   preserved untouched. Compute the camera as a forward-facing
   "viewscreen" anchored to the player ship's origin.
4. Render a small "BRIDGE VIEW" UI panel via [engine/ui](../../../engine/ui)
   that is visible only in bridge mode, mirroring how `F7` toggles the
   dust pass.
5. Cover the seam with unit tests in a new
   [tests/host/test_view_mode.py](../../../tests/host/test_view_mode.py)
   (mirroring the sibling pattern of `test_camera_control.py` and
   `test_player_control.py`): toggle behaviour, input-skip behaviour,
   and bridge-camera math. The integration-style
   `test_host_loop_unit.py` continues to cover the booted-renderer
   path.

## Non-goals (PoC)

- **Bridge interior geometry.** No NIF, no chair, no viewscreen frame.
  The camera sits at the ship's origin and looks forward; the exterior
  scene is what you see, just from the inside.
- **Per-ship bridge anchor offsets.** Different ships have bridges in
  different physical locations. PoC uses ship origin uniformly.
- **Mouse-look or arrow-key look-around inside the bridge.** Camera is
  rigidly locked to the ship's forward axis.
- **Audio listener relocation.** Listener stays where the exterior
  camera is; PoC doesn't touch audio.
- **Viewscreen UI overlay** (target reticle, comms panel, etc.).
- **Restoring exterior orbit state across mission swaps**: the camera
  snaps to live ship pose each tick, so swap interaction is automatic.

## Architecture

### `ViewModeController`

A small class in [engine/host_loop.py](../../../engine/host_loop.py),
sibling to `_PlayerControl` and `_CameraControl`:

```python
class _ViewModeController:
    EXTERIOR = 0
    BRIDGE   = 1

    def __init__(self):
        self._mode = self.EXTERIOR

    @property
    def is_bridge(self) -> bool:   return self._mode == self.BRIDGE
    @property
    def is_exterior(self) -> bool: return self._mode == self.EXTERIOR

    def toggle(self) -> None:
        self._mode = self.BRIDGE if self.is_exterior else self.EXTERIOR

    def apply(self, h) -> None:
        """Poll space-pressed and toggle on edge."""
        if h.key_pressed(h.keys.KEY_SPACE):
            self.toggle()
```

### Per-tick dispatch

In `host_loop.run()`'s tick body:

1. Call `view_mode.apply(_h)` next to the existing F7/F8/F9 block.
2. Branch the input block:
   - **Exterior** (default, unchanged): `player_control.apply(...)`,
     `cam_control.apply(...)`.
   - **Bridge**: call `player_control.apply(player, dt, _NO_INPUT)` so
     ship physics keep integrating each tick (engines coast, position
     and rotation update, throttle setting preserved) but live keys
     are ignored; skip `cam_control.apply()` so orbit state is
     preserved untouched for when we toggle back. Angular rates ramp
     toward zero in bridge (no input held → target rates are 0), so an
     active turn straightens out — matching "let go of the helm".
3. Branch the camera block:
   - **Exterior**: existing `cam_control.compute_camera(...)`.
   - **Bridge**: derive directly from the player ship transform —
     ```
     loc = player.GetWorldLocation()
     R   = player.GetWorldRotation()
     fwd = R.GetRow(1)   # ship-local +Y in world space
     up  = R.GetRow(2)   # ship-local +Z in world space
     eye    = (loc.x, loc.y, loc.z)
     target = (loc.x + fwd.x, loc.y + fwd.y, loc.z + fwd.z)
     up_vec = (up.x, up.y, up.z)
     ```
     `target` only needs to be a point along the forward axis; the unit
     forward vector is sufficient (`r.set_camera` doesn't care about
     distance, only direction).
4. Toggle the bridge HUD panel's visibility from the controller's mode.
5. The `fixed_camera` debug path is unchanged and takes precedence over
   both modes (it's a development override, not a real view).

### Bridge HUD panel

Created at startup alongside `demo_panel` and `debug_panel`:

```python
bridge_hud = ui.UiPanel(id="bridge_hud", anchor="top",
                        width_vw=20.0, height_vh=6.0,
                        title="BRIDGE VIEW")
bridge_hud.set_visible(False)  # exterior is default
```

Per tick, after the dispatch block: `bridge_hud.set_visible(view_mode.is_bridge)`.

`UiPanel` doesn't currently expose a `set_visible` method, but the
underlying `engine.ui.bindings.set_panel_visible(panel_id, bool)` does.
This PoC adds a one-liner `UiPanel.set_visible(self, visible: bool)`
that calls through to it — `UiPanel` is the natural API surface for
panel-level visibility, and adding it here is in keeping with the
existing per-panel methods (`set_title`, `set_collapsed`, `clear`).

### Mission-swap interaction

The bridge camera reads `player.GetWorldLocation()` /
`GetWorldRotation()` live each tick, so when a mission swap replaces
the player ship, the bridge view auto-follows the new ship without any
explicit snap. `cam_control.snap()` continues to fire on swap as it
does today; that only affects the exterior orbit camera and is
harmless when bridge mode is active.

## Testing

All tests in a new file
[tests/host/test_view_mode.py](../../../tests/host/test_view_mode.py),
following the existing fake-bindings pattern used by the
`_PlayerControl` and `_CameraControl` test modules:

1. **`test_view_mode_starts_exterior`** — fresh controller is in
   exterior mode; `is_exterior` is True, `is_bridge` is False.
2. **`test_view_mode_toggle_on_space`** — fake bindings with
   `key_pressed(SPACE) → True` flips the mode; calling `apply` again
   with `False` leaves it unchanged (edge-triggered, not held).
3. **`test_bridge_mode_passes_no_input_reader_to_player_control`** —
   given a recording fake `_PlayerControl` and a controller in
   `BRIDGE`, the per-tick dispatch calls `apply` once with
   `_NO_INPUT` (not the live reader), and does not call `apply` on
   `_CameraControl`. A second test drives the real `_PlayerControl`
   against a fake ship and asserts that engines keep coasting (ship
   position advances) across multiple bridge-mode ticks — the
   regression that the original "skip both" implementation broke.
4. **`test_bridge_camera_anchors_at_ship_origin`** — given a fake ship
   with known location and rotation, the bridge-mode camera math
   produces eye = ship loc, target along ship forward, up along ship
   up.
5. **`test_bridge_mode_preserves_orbit_state`** — entering bridge mode
   while `_CameraControl` has non-default `orbit_yaw_rad` /
   `distance` does not mutate them; toggling back restores the same
   exterior framing.

The per-tick dispatch logic (currently inline in `run()`) is extracted
into a small free function or method so tests 3 and 5 can drive it
without booting the renderer. Exact extraction shape is an
implementation choice; the spec only requires that the tests above are
expressible without `r.init`.

## Files touched

- [engine/host_loop.py](../../../engine/host_loop.py) — add
  `_ViewModeController`, integrate into `run()`, extract the dispatch
  block enough that tests can hit it directly.
- [tests/host/test_view_mode.py](../../../tests/host/test_view_mode.py) —
  new file with the five tests listed above.
- [engine/ui/panel.py](../../../engine/ui/panel.py) — add a one-line
  `UiPanel.set_visible(visible: bool)` wrapping
  `bindings.set_panel_visible(self._panel_id, visible)`.

## Out of scope, called out for later

These are the natural next steps once the seam is in place; none of
them are part of this PoC:

- Bridge interior NIF + per-ship anchor offset (look up where each
  ship's bridge actually sits in its mesh).
- Viewscreen frame UI (the visible black bezel around the forward
  view).
- Mouse-look or hat-switch look-around within the bridge.
- Audio listener follows the bridge camera.
- Targeting reticle, comms overlay, and other in-bridge HUD.
- NPC bridge crew rendering.
