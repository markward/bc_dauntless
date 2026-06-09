# Ship Property Viewer — design

**Date:** 2026-06-08
**Status:** approved (brainstorm), pre-implementation
**Predecessor:** the WIP phaser bank/arc debug visualisation (red arc rings on
the ship) — this replaces that throwaway with a permanent, structured tool.

## Purpose

A developer-mode tool that renders the **player ship in 3D as a hologram** with
its **subsystems overlaid as billboard pins**, and lets the developer click a
pin to inspect that subsystem's properties. It is the seed of an in-game
**engineering view**, and later the **science "scan another ship"** interaction.

v1 ships as a full-viewport modal reachable from the pause menu **in developer
mode only**.

## Non-goals (v1)

- Inspecting ships other than the player (science-scan use is a later phase).
- A "windowed" render-to-texture modal (see *Future: A→B* below — designed for,
  not built).
- Live updates while open: the world **pauses** and we inspect a frozen
  snapshot.
- Health/state colour-coding *on the pins* — pins are neutral; state appears in
  the property readout.
- Editing properties. This is a viewer.

## User-facing behaviour

1. Pause the game (dev mode). A **"Ship Property Viewer"** row appears in the
   pause menu.
2. Selecting it pauses the sim and opens a full-viewport modal: the player ship
   rendered as a translucent blue hologram, framed to fit, with a circular pin
   (white disc + black subsystem glyph) at every subsystem's mount point.
3. **Manual camera:** mouse-drag orbits the ship; scroll wheel zooms. No
   auto-spin.
4. **Click a pin** → a property popover appears near it listing that
   subsystem's properties (name, type, health, power, position, disabled/
   destroyed state). Clicking empty space or another pin dismisses/replaces it.
5. **ESC** or the **Close** control returns to the pause menu; the sim resumes
   when the pause menu itself is dismissed (unchanged pause semantics).

## Architecture overview

```
pause menu (dev) ──► ShipPropertyViewerPanel (Panel, PanelRegistry)
                          │  on open: pause sim, build descriptors
                          ▼
        engine/ui/ship_property_viewer.py  (descriptor builder + pick math)
                          │
          ┌───────────────┼────────────────────────┐
          ▼               ▼                         ▼
   HologramPass     SubsystemPinPass          CEF overlay
   (GL, ship mesh)  (GL, billboards)          (chrome + property popover)
```

Two new GL passes live alongside `native/src/renderer/phaser_pass.cc` and follow
its exact shape: a small self-contained pass, owned by the host, fed a
descriptor list from Python each frame, drawing nothing when the list is empty.

### Render boundary parameterised for the future (A→B seam)

Both passes render through `render(descriptors, camera, viewport_rect,
pipeline)`. In v1 `viewport_rect` is the full window. Migrating to a windowed
"ship-in-a-card" (option B) later means pointing the same passes at an
off-screen framebuffer / sub-rect and compositing — **the pass code does not
change.** Likewise all screen-space math (pin picking) goes through a single
`project(world_pos, camera, viewport_rect) -> (sx, sy, depth)` helper so it is
correct whether the ship fills the screen or sits in a sub-rect.

## Component detail

### 1. HologramPass (`native/src/renderer/hologram_pass.{h,cc}` + shaders)

Re-draws the **player ship mesh** with a holographic Fresnel shader.

- **Opacity from view alignment:** per fragment, `d = |dot(N, V)|` where `N` is
  the world-space surface normal and `V` the normalised fragment→camera
  direction. `opacity = OPACITY_GRAZING - (OPACITY_GRAZING - OPACITY_FACING) *
  d`, i.e. with the chosen endpoints `opacity = 0.5 - 0.45 * d`.
  - **Facing the camera** (`d ≈ 1`) → 95% translucent → opacity **0.05**.
  - **Perpendicular / silhouette** (`d ≈ 0`) → 50% translucent → opacity
    **0.50**.
  - `OPACITY_FACING = 0.05` and `OPACITY_GRAZING = 0.50` are named tunable
    constants.
- **Blue holographic tint;** faces pointing away from the camera (back faces)
  glow through, giving the "solid translucent model, far side visible" read
  (brainstorm option C).
- **Blend:** additive (`GL_SRC_ALPHA, GL_ONE`), `glDepthMask(GL_FALSE)`,
  cull disabled — same strategy as `phaser_pass`, so no transparency sorting is
  needed and grazing edges accumulate into a natural rim glow.
- Uses the ship's existing model→world transform (rotation `R` column-vector
  convention + translation; no scale) — the same matrix the opaque ship render
  already uses. Normals transform by `R`.

### 2. SubsystemPinPass (`native/src/renderer/subsystem_pin_pass.{h,cc}` + shaders)

Camera-facing **billboard** quads, one per subsystem descriptor.

- **Pin = white disc + black glyph.** The glyph is the subsystem's class-derived
  **Damage** icon (the 10 monochrome 16×16 TGAs at `game/data/Icons/Damage/`:
  Hull, Impulse, Phaser, Power, Sensor, Shield, System, Torpedo, Warp,
  Disruptor). Loaded once as GL textures via the existing
  `assets::decode_tga` / `upload_image` path used by `phaser_pass`. The shader
  composites black ink (from the TGA) over a white circular disc.
- **Always visible:** drawn after the hologram with depth-test **off**, so pins
  on the far side of the hull are not occluded (engineering view wants every
  subsystem visible through the translucent hull).
- **World-scaled size:** billboards have a fixed size in game units anchored to
  the hull, so they grow/shrink with zoom and distance like real pinned objects
  (tunable `kPinWorldSize`). Click tolerance (`PIN_RADIUS_PX`) is a separate
  screen-space value. (Constant-screen-size is the easy alternative — multiply
  the world size by camera distance — if world-scaling reads poorly in-app.)
- Descriptor: `{ world_pos: vec3, icon_id: int (0..9), highlighted: bool }`.
  `highlighted` lets the selected pin draw with a brighter ring.

### 3. Descriptor builder + pick math (`engine/ui/ship_property_viewer.py`)

Pure-Python, unit-testable. On viewer open it walks the player ship's
subsystems — reusing the ship-status-panel enumeration pattern
([ship_display_panel.py](../../../engine/ui/ship_display_panel.py) `_damage_icon_descriptors` /
`_iter_damage_subsystems`) — and for each subsystem that has a real 3D mount
(`GetPosition()` is not None) emits:

```python
{
  "name":        sub.GetName(),
  "icon_id":     damage_icons.icon_num_for_subsystem(sub),  # class-derived glyph
  "world_pos":   model_to_world(sub.GetPosition(), ship),   # see below
  "state":       _row_state(sub),                           # healthy/damaged/disabled/destroyed
  "properties":  { ... },  # name, type, health, power, position, disabled, destroyed
}
```

- **`subsystem_world_position(sub)`** applies the ship's world rotation +
  translation to the subsystem's model-local mount point — **no scale factor**
  (`world = ship.GetWorldLocation() + GetWorldRotation()·GetPosition()`, per the
  hardpoint-scale instrumentation documented at
  [subsystems.py:769](../../../engine/appc/subsystems.py#L769)). This is the same
  transform the phaser `_emitter_world_position` uses; extract the general form
  into one shared helper.
- Pins feed `SubsystemPinPass`; the `properties` dicts feed the CEF popover.
- **Picking:** on a click, project every pin's `world_pos` through
  `project(world_pos, camera, viewport_rect)`, take the nearest pin whose
  screen-space disc contains the cursor, and tell the panel to open that
  subsystem's popover + flag the pin `highlighted`.

### 4. ShipPropertyViewerPanel (`engine/ui/ship_property_viewer_panel.py`)

A `Panel` subclass pumped by `PanelRegistry`, mirroring `DeveloperOptionsPanel` /
`dev_mission_picker`:

- `open()` — capture the frozen snapshot, build descriptors, push pin list to the
  pass, pause sim, hide the pause menu.
- `close()` — clear descriptors/pins, restore the pause menu.
- `render_payload()` — emits the CEF call (title, visibility, selected
  subsystem's property table for the popover, popover anchor in screen coords).
  Snapshot-diffed like the other panels (`_last_pushed`) to avoid redundant JS.
- `handle_input(h)` — ESC closes; mouse handling drives orbit/zoom and pin
  picking.
- `dispatch_event(action)` — `cancel`, `select_pin:<index>`, etc.

### 5. CEF overlay (`native/assets/ui-cef/js/ship_property_viewer.js` + HTML/CSS)

Transparent full-viewport layer over the GL render:

- Title bar ("Ship Property Viewer") + Close control.
- A property **popover** positioned at the picked pin's screen coords, listing
  the selected subsystem's properties. Styled with the shared modal CSS tokens
  used by the existing panels (`cp-*` / pause-menu styling).
- The 3D ship and pins are GL, **not** DOM — the overlay only draws chrome and
  the popover. Pins themselves are not DOM elements.

### 6. Pause-menu registration

Registered dev-only via `dev_mode.register_dev_pause_menu_entry("Ship Property
Viewer", handler)` in `host_loop.py` inside `if dev_mode.is_enabled():` — the
same path used by Developer Options and the dev mission loader. Production builds
never see the row, and the passes/panel are never constructed.

## Host wiring (C++)

Mirror the phaser plumbing in `native/src/host/host_bindings.cc`:

- Own `g_hologram_pass` / `g_subsystem_pin_pass` (constructed at renderer init,
  reset at teardown).
- `m.def("set_hologram_ship", ...)` — set/clear which ship mesh to draw as a
  hologram (by the existing model/instance handle) + its world transform.
- `m.def("set_subsystem_pins", descriptors)` — replace the pin descriptor list
  (clear when the viewer closes).
- In the frame render, after the normal scene, call
  `g_hologram_pass->render(...)` then `g_subsystem_pin_pass->render(...)` when
  active.
- **No projection binding needed.** The viewer owns its orbit camera params and
  feeds them to `set_camera`; pin-picking projects the same params in pure Python
  (unit-testable), so GL and pick projection match by construction.

All bindings are inert when the viewer is closed (empty lists / null ship).

## Data / control flow (open → interact → close)

1. Dev selects the pause-menu row → `ShipPropertyViewerPanel.open()`.
2. Panel pauses sim, builds descriptors from the player ship snapshot, calls
   `set_hologram_ship(...)` + `set_subsystem_pins(...)`.
3. Each frame: GL draws the scene; hologram + pin passes draw on top; CEF draws
   chrome. Drag/scroll update the camera; ESC/Close end the session.
4. Click → Python projects pins, picks nearest hit, sets `highlighted`, pushes
   the property popover payload to CEF.
5. `close()` clears the passes and restores the pause menu.

## Error handling / edge cases

- **Subsystems without a 3D mount** (`GetPosition()` is None, or model-local
  origin only): skipped from pins (cannot be placed), consistent with the
  status panel skipping `Position2D == (0,0)`.
- **Glyph TGA missing** (modded/partial install): pin draws the white disc with
  no glyph rather than crashing — same tolerance as `phaser_pass` on a missing
  texture.
- **No player ship** (e.g. opened on a menu with no ship loaded): the row still
  appears but opening yields an empty hologram + "no ship" notice; no crash.
- **Overlapping pins:** picking takes the nearest-by-screen-distance hit; pins
  draw constant-size so dense clusters remain individually clickable when zoomed.

## Testing strategy

Python seams (unit-tested, focused subsets per the project's pytest-memory
constraint):

- **Descriptor builder:** given a stub ship with known subsystems, asserts the
  right subsystems are included/excluded, correct class-derived `icon_id`,
  correct `state`, and correct `world_pos` from a known transform.
- **`model_to_world`:** a body-frame mount maps to the expected world point under
  a known `R`/translation/scale (column-vector convention).
- **`project` + pick:** a pin at a known world point projects to the expected
  screen pixel; a click inside its disc selects it, a click outside does not;
  nearest-hit wins on overlap.
- **Panel lifecycle:** open/close toggles visibility, pushes/clears pins, diffs
  `render_payload` snapshots, hides/restores the pause menu.
- **Dev gating:** the pause-menu row registers only when `dev_mode.is_enabled()`.

GL passes (hologram shader, billboard rendering) are verified by running the
app and observing the render, per the project's shader-rebuild workflow
(`cmake -B build -S .` before `cmake --build` when shaders change).

## Future: A→B and science scan

- **A→B (windowed render-to-texture):** because both passes take
  `(camera, viewport_rect)` and all screen math goes through `project(...)`,
  moving the ship into a bordered card is an FBO + composite change, not a
  rewrite.
- **Science scan:** the descriptor builder already takes "a ship"; pointing it at
  a *target* ship (with scan-gated property visibility) is the natural extension.
  Pin-picking is exactly the "click the thing in space" interaction science
  needs.

## File inventory

New:
- `native/src/renderer/hologram_pass.{h,cc}` + `shaders/hologram.{vert,frag}`
- `native/src/renderer/subsystem_pin_pass.{h,cc}` + `shaders/subsystem_pin.{vert,frag}`
- `engine/ui/ship_property_viewer.py` (descriptor builder + pick math)
- `engine/ui/ship_property_viewer_panel.py` (Panel subclass)
- `native/assets/ui-cef/js/ship_property_viewer.js` + HTML/CSS chrome
- tests under `tests/` for the Python seams

Touched:
- `native/src/host/host_bindings.cc` (own passes, `set_hologram_ship`,
  `set_subsystem_pins`, projection binding, frame render hook)
- `engine/host_loop.py` (dev-only pause-menu registration + panel construction)
- possibly a shared `model_to_world` helper extracted from the phaser-beam code
- `CLAUDE.md` reference table (new row, on completion)
