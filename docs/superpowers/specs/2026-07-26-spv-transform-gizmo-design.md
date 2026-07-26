# SPV Transform Gizmo — Design

**Date:** 2026-07-26
**Status:** Approved (design); implementation pending
**Builds on:** [SPV hardpoint value-override editing](2026-07-25-spv-hardpoint-value-override-editing-design.md),
[SPV Edit Light / glow region](2026-07-26-spv-edit-light-glow-region-design.md),
the light-volume-nodes redesign, and the SPV selection tweaks (all merged, local main `307dd1aa`).

## Goal

A Blender/3ds-Max-style 3-axis **position gizmo** in the Ship Property
Viewer (SPV): with the Transform tool active and a subsystem or light
volume selected, three directional arrows render at the object; clicking
and dragging an arrow slides the object along that axis, editing its XYZ
location in the hardpoint. Edits stage like radius/light edits and persist
to the machine-owned `hardpoint_overrides.py` through the existing
Save/confirm flow. **Rotate** and **Scale** tools are stubbed now (present
but inert) so the toolbar is structured for them later.

Developer-only, mouse-only (the engine has no keyboard→CEF forwarding). The
production render path stays byte-identical when the gizmo is empty.

## Non-goals

- No rotation or scale editing (buttons are inert stubs this pass).
- No plane handles, no free-move (screen-plane) handle, no numeric entry.
  Single-axis drag only.
- No snapping/grid this pass (freeform drag, Blender default).
- No change to in-scene glow rendering, combat, or any production path.

## Key decisions (confirmed with Mark)

1. **Axes are ship-body frame**, not world. Arrows align to the hull's
   starboard/forward/up. Dragging axis *k* changes component *k* of the
   stored body-frame position 1:1 (no re-projection). This matches how the
   hardpoint stores positions and how `subsystem_world_position` composes
   them.
2. **Active-tool + selection visibility.** Transform/Rotate/Scale are a
   mutually-exclusive radio. The gizmo shows only when Transform is active
   AND a subsystem or light node is selected. Clicking the active tool
   again turns it off (back to plain orbit/select — today's behaviour).

## Background facts (verified in the tree)

- Subsystem position is a body-frame `SetPosition(x, y, z)` setter on the
  subsystem's property (`engine/appc/properties.py:36`). World position =
  `ship_world_loc + R · body_pos` via `subsystem_world_position`.
- Light-volume position is the glow region's `position` field
  (`SetGlowRegionPosition(index, x, y, z)`), an **absolute body-frame**
  position that defaults to the subsystem mount
  (`resolve_baked_region`: `pos = raw.get("position") or default_pos`).
- The override writer routes a 3-tuple `(subsystem, setter, args)` →
  `set_setter`, and a 4-tuple `(subsystem, "__region__", index, calls)` →
  `set_region` (`engine/appc/override_routing.py`). `set_setter`'s
  `_replace_key` collapses non-indexed setters to `(setter,)`, so a new
  `SetPosition` replaces any prior one — one `SetPosition` per subsystem.
- The SPV already has, in pure Python, an `OrbitCamera`, a
  `project(world, cam, viewport) -> (sx, sy, depth, visible)`, and
  `pick_pin(cursor_x, cursor_y, ...)` doing screen-space nearest-pin
  picking (`engine/ui/ship_property_viewer.py`). Orbit-drag and pin
  selection are driven host-side in `engine/host_loop.py`.
- Wireframe debug volumes render via `DebugVolumePass`
  (`native/src/renderer/debug_volume_pass.cc`) with per-primitive colour +
  alpha, depth-test off, only in viewer mode; pushed from Python via
  `set_debug_{cylinders,boxes,spheres}` and gated getattr-guarded wrappers
  in `engine/renderer.py`.
- Effective-value resolvers already exist: `_effective_radius`/
  `_saved_radius` and `_effective_light`/`_saved_light`
  (`pending → saved → baked`) in `ship_property_viewer_panel.py`.

## Components

### A. Tool state (CEF + panel)

**CEF (`native/assets/ui-cef/`):** a new tool group **above** `#spv-tools`
with three buttons — Transform (move glyph), Rotate, Scale. Mutually
exclusive: the active one carries `.active`; clicking it again clears it.
Each click fires an event the panel handles (e.g.
`ship-property-viewer/tool` with payload `transform|rotate|scale|none`).
Rotate/Scale buttons are inert this pass — clickable (they can become the
active tool) but their tool does nothing: no gizmo, no staged edit.
Dev-only (`.dev-only`, inside `#spv-root`).

**Panel (`ship_property_viewer_panel.py`):** an `active_tool` field
(`None | "transform" | "rotate" | "scale"`; default `None`). A dispatch
case `set_tool` that toggles it (selecting the active tool → `None`).
`render_payload` carries `active_tool` so the CEF button states reflect it.

### B. Gizmo geometry + picking + drag (`ship_property_viewer.py`)

Pure-Python logic core, mirroring `project`/`pick_pin`. New helpers:

- `gizmo_axes(R) -> (axis_x, axis_y, axis_z)` — the three unit world-space
  body axes from the rotation matrix columns (`GetCol(0/1/2)`).
- `gizmo_screen_length(origin, cam, viewport) -> float` — world length that
  projects to a constant on-screen pixel size (usable at any zoom), so the
  arrows stay a fixed apparent size like Blender's.
- `pick_gizmo_axis(cursor_x, cursor_y, origin, axes, length, cam, viewport,
  device_scale_factor) -> Optional[int]` — the axis (0/1/2) whose
  screen-projected shaft segment is within a click threshold of the cursor,
  nearest wins; `None` if none. Segment = `project(origin)` →
  `project(origin + axis*length)`; distance-to-segment in screen px.
- `axis_drag_delta(cursor_x, cursor_y, origin, axis, cam, viewport) ->
  float` — the body-axis parameter *t* of the point on the world-axis line
  `origin + t*axis` closest to the camera ray through the cursor. Because
  `axis` is unit and rotation preserves length, world-Δ == body-Δ, so the
  caller does `body_pos[k] += t_now − t_grab`.

No new selection concept: the gizmo attaches to whatever is selected
(`selected_index` subsystem or `_selected_light_index` light node).

### C. Effective position + persistence (`ship_property_viewer_panel.py`)

A `pending → saved → baked` position resolver mirroring radius:

- `_pending_pos: dict[key -> (x,y,z)]`, `_saved_pos: dict[key -> (x,y,z)]`.
  Key identifies the transform target: a subsystem descriptor index, or a
  light-node identity (subsystem index + light marker).
- `_effective_pos(target) -> (x,y,z)` returns pending → saved → baked
  (baked = the live `GetPosition()` for a subsystem, or the region-0
  `position` for a light). This value is what the gizmo origin, the pin,
  the radius sphere, and the glow overlay all read, so a live drag moves
  everything together.
- Drag API the host calls: `begin_axis_drag(axis)`, `update_axis_drag(t)`
  (live, writes `_pending_pos` for the current target), `end_axis_drag()`
  (keeps the pending value; marks the row dirty).
- **Save routing** (extends the existing staged-edit list):
  - Subsystem target → `(subsystem, "SetPosition", (x, y, z))` →
    `set_setter`.
  - Light target → region-0 spec with its `position` replaced by the
    pending value → `region_spec_to_calls(0, spec)` →
    `(subsystem, "__region__", 0, calls)` → `set_region`. (A light that is
    also being shape/size-edited merges into one region write — the spec is
    the single source, position included.)
- Pending count includes position edits, so the Save bar and amend-confirm
  already surface them. `_saved_pos` keeps the just-saved value driving the
  preview for the rest of the SPV session (same persist→reload model as
  radius/light: the in-scene value updates on the next mission/ship build).

### D. Rendering (`native/`)

A new **`GizmoPass`** (`native/src/renderer/gizmo_pass.{h,cc}`), sibling of
`DebugVolumePass`:

- Input: an origin, three world-space axis directions, a world length, and
  a highlighted-axis index (−1 = none).
- Draws each axis as a solid shaft (`GL_LINES`) from origin to
  `origin + axis*length` plus a small cone/arrowhead, coloured X=red,
  Y=green, Z=blue; the highlighted axis brightens.
- Depth-test off (always on top), rendered only in viewer mode, after the
  debug volumes.

Host binding `set_transform_gizmo(origin, axis_x, axis_y, axis_z, length,
highlight_axis)` stores the gizmo; an empty/cleared gizmo draws nothing.
Getattr-guarded `engine/renderer.py` wrapper in the optional-bindings set
(so a stale binary silently no-ops, never crashes). `clear_transform_gizmo`
(or pushing an empty gizmo) hides it.

### E. Host wiring (`engine/host_loop.py`)

In the existing SPV block (where orbit + pin picking already run), when
`ship_property_viewer.active_tool == "transform"` and something is
selected:

1. Compute the gizmo origin (selected object's effective world position)
   and axes (`gizmo_axes(R)`), push via `set_transform_gizmo`, with the
   hovered axis highlighted (hover = `pick_gizmo_axis` at the current
   cursor when not dragging).
2. On LMB-down: if `pick_gizmo_axis` hits an axis, `begin_axis_drag(axis)`,
   record `t_grab = axis_drag_delta(...)`, and **suppress orbit** for the
   duration of the drag.
3. While dragging: `t_now = axis_drag_delta(...)`; call
   `update_axis_drag(t_now − t_grab + base_t)` (panel applies it to the
   target's effective position). Pins/sphere/glow follow because they read
   the effective position.
4. On LMB-up: `end_axis_drag()`; orbit re-enabled.

When Transform is inactive or nothing is selected, clear the gizmo and
behave exactly as today.

## Data flow (drag one axis of a subsystem)

```
LMB-down on green shaft
  host: pick_gizmo_axis -> 1 ; begin_axis_drag(1) ; t_grab = axis_drag_delta(...)
drag
  host: t = axis_drag_delta(...) ; update_axis_drag(t - t_grab + base)
  panel: _pending_pos[target] = (x, baked_y + delta, z)
  render: gizmo origin, pin, sphere all read _effective_pos -> move together
LMB-up
  panel: end_axis_drag() -> pending kept, row dirty, pending_count += (if new)
Save -> amend-confirm
  routing: (subsystem, "SetPosition", (x, y', z)) -> set_setter -> emit -> hardpoint_overrides.py
```

## Edge cases

- **Position-less subsystems** are already excluded from descriptors — no
  gizmo, nothing to transform.
- **Child subsystems** (pods/banks/tubes) have their own property
  `SetPosition`; transforming them edits that property. Same path.
- **Light + subsystem both selected**: impossible — `selected_index` and
  `_selected_light_index` are mutually exclusive. The gizmo binds to
  whichever is active.
- **Coexisting edits**: a subsystem may have pending radius AND position;
  they're independent setters and both appear in the pending set / one
  Save.
- **Light with pending shape/size AND position**: both live in the same
  region-0 spec; Save emits one `set_region` with the merged spec.
- **Stale binary** (no `set_transform_gizmo`): getattr-guarded wrapper
  no-ops; SPV still works without the gizmo.

## Residual risk (addressed in Task 1)

The writer's `read_models` stores multi-arg setters as
`(setter, args[:-1]) -> args[-1]` — designed for indexed single-value
setters, not a 3-arg `SetPosition`. Editing never depends on this (the
gizmo pre-fills from the live `GetPosition()`), but the writer's canonical
fixed point `emit(read_models(module)) == source` must still hold with a
`SetPosition` override present. Task 1 adds that round-trip test and, if it
fails, makes the minimal writer fix so a `SetPosition(x, y, z)` override
round-trips cleanly.

## Testing strategy

- **Writer round-trip** (Task 1): `SetPosition` override survives
  `emit(read_models(...))` unchanged; `set_setter` replaces a prior
  `SetPosition`.
- **Gizmo geometry/picking/drag** (pure Python): axes = R columns; a click
  on a projected shaft picks that axis; a click off all shafts picks
  `None`; `axis_drag_delta` returns the correct body-axis parameter for a
  synthetic camera/cursor; nearest-axis wins on overlap.
- **Panel**: tool toggle (radio + turn-off); `_effective_pos`
  pending→saved→baked; drag API updates pending; Save routes a subsystem
  position → `SetPosition` and a light position → region-0; pending count
  includes position; Rotate/Scale stage nothing.
- **Host (native) test**: `set_transform_gizmo` accepts and stores; empty
  gizmo renders nothing (production byte-identical).
- **CEF**: unit-level DOM/state tests are not the norm here; covered by
  Mark's in-game pass. Panel `render_payload` carries `active_tool` and the
  gizmo highlight so the button states are testable in Python.

## Rollout

Feature branch (e.g. `feat/spv-transform-gizmo`) off local `main`, executed
task-by-task via subagent-driven-development, gated by
`scripts/check_tests.sh`. Merge is Mark's call after an in-game pass. Never
pushed without Mark's say-so.
