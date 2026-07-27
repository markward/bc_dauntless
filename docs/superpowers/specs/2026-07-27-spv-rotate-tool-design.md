# SPV Rotate Tool — Design

**Date:** 2026-07-27
**Status:** Approved (design); implementation pending
**Builds on:** the SPV Transform + Scale gizmo tools (`docs/superpowers/specs/2026-07-26-spv-transform-gizmo-design.md`, `2026-07-27-spv-scale-tool-design.md`). Reuses the shared gizmo renderer (`handle_kind`), `_active_gizmo()`, the effective-light plumbing, the click-guard, and the top-right panel pattern.

## Goal

A **Rotate** tool (third button in the Transform/Rotate/Scale radio) that rotates a **Cylinder light volume's axis** (its glow direction) via a ring gizmo + a top-right degrees panel, staged and saved through the existing light path. Same pattern as Transform/Scale.

Developer-only, mouse-only. Production byte-identical (hidden unless Rotate active + a cylinder light selected).

## Key decisions (confirmed with Mark)

1. **Light volumes only, this pass — which means Cylinder lights.** Only a Cylinder light carries a rotatable `axis` (`SetGlowRegionAxis`). Box glows are body-axis-aligned (Position + Scale, no orientation) and Spheres are rotationally symmetric, so **Rotate is inert on Box/Sphere lights and on everything else** (subsystems, weapons). No weapon `SetOrientation` this pass (that would need a two-vector writer extension).
2. **Third panel button = Mirror** — negates the axis's **X** component (flip the glow direction to the other side of the ship), matching Transform's Mirror.

## Background facts (verified)

- Cylinder light spec: `{"shape":"Cylinder", "axis":(ax,ay,az), "radius":(r,), "extent":(aft,fore), "position":...}`. `_effective_light(i)` returns it; `region_spec_to_calls` emits `SetGlowRegionAxis(index, ax, ay, az)` for cylinders; Save routes `_pending_light[i]` via `set_region`. So writing a rotated `axis` into the pending spec persists with **no writer change**.
- `resolve_baked_region`/`glow_region_overlay` read the spec `axis` and draw the cylinder wireframe along it — so a rotated axis previews live for free.
- The gizmo renderer already takes a `handle_kind` int (0 = arrows/move, 1 = cubes/scale) through `set_transform_gizmo(...)`; host_loop pushes `_active_gizmo()`'s `handle_kind`. Adding `2 = rings` needs only a new branch in `gizmo_pass.cc` — no binding/wrapper/host_loop change.
- Pure-Python gizmo helpers live in `engine/ui/ship_property_viewer.py` (`gizmo_axes`, `project`, `pick_gizmo_axis`, `axis_drag_param`). The rotate tool adds ring-picking + angular-drag helpers there.

## Components

### A. Rotate value model + dispatch (`ship_property_viewer_panel.py`)

- `ROTATE_STEP` constants are UI-side (in the CEF), not needed here.
- `self._rotate_clipboard = None` — `(kind, axis_tuple)`; reset in `__init__`/`open`/`close`.
- `self._rotate_accum: dict = {}` — descriptor index → `[dx, dy, dz]` degrees accumulated **this session** (display feedback only; reset on `open`/`close`, and per-target when the axis is set absolutely — Mirror/Paste).
- `_rotate_target()`: returns `("light", i)` only when `_active_transform_target()` is a light AND `_effective_light(i)["shape"] == "Cylinder"`; else `None`. (Rotate is cylinder-only.)
- `rotate_values() -> Optional[dict]`: `None` unless `active_tool == "rotate"` AND `_rotate_target()`; else
  `{"fields": [{"label":"X","value":dx},{"label":"Y","value":dy},{"label":"Z","value":dz}], "has_clipboard": bool, "can_paste": clipboard is not None}` where dx/dy/dz come from `_rotate_accum`.
- `_rotate_axis(index, delta_deg)`: rotate the current effective axis about body axis `e_index` by `delta_deg` (Rodrigues; normalize), write it into `_pending_light[i]["axis"]` (spec copy), and `_rotate_accum[i][index] += delta_deg`.
- `_set_axis_absolute(i, axis, reset_accum=True)`: write a normalized axis into `_pending_light[i]["axis"]`; zero `_rotate_accum[i]` (used by Mirror/Paste).
- Dispatch (before `save`):
  - `rotate_nudge:<json {"axis":0|1|2,"delta":deg}>` → `_rotate_axis(axis, delta)`.
  - `rotate_copy` → `_rotate_clipboard = ("cylinder_axis", tuple(effective axis))`.
  - `rotate_paste` → if clipboard: `_set_axis_absolute(i, clipboard_axis)`.
  - `rotate_mirror` → `ax = list(effective axis); ax[0] = -ax[0]; _set_axis_absolute(i, ax)`.
- `render_payload`: add `"rotate_values": self.rotate_values()`; add `self._rotate_clipboard` and a hashable snapshot of `_rotate_accum` to the snapshot tuple.

### B. Rotate gizmo + angular drag (`ship_property_viewer_panel.py` + `ship_property_viewer.py`)

Pure helpers in `ship_property_viewer.py`:
- `pick_gizmo_ring(cursor_x, cursor_y, origin, axes, length, cam, viewport, dsf) -> Optional[int]`: for each body-axis ring (a circle of radius `length` in the plane ⊥ `axes[k]`), sample N points, project, take min cursor-to-segment distance; nearest ring within threshold wins.
- `ring_drag_angle(cursor_x, cursor_y, origin, cam, viewport) -> float`: `atan2(cursor_y − oy, cursor_x − ox)` where `(ox, oy)` is the projected origin — the cursor's screen angle around the gizmo centre.
- `rotate_about_axis(vec, k, angle_rad) -> Vec3`: Rodrigues rotation of body-frame `vec` about basis axis `e_k` (`k` ∈ {0,1,2}), returned normalized.

Panel:
- `rotate_gizmo() -> Optional[dict]`: `None` unless `active_tool == "rotate"` AND `_rotate_target()` AND ship rotation; else `{origin, axes, length, highlight, "handle_kind": 2}` (origin = light world position; axes = `gizmo_axes(R)`).
- `_active_gizmo()`: add the `rotate` → `rotate_gizmo()` branch.
- `_begin_ring_drag(ring)`: capture `_axis_drag = ring`, `_ring_grab_angle = ring_drag_angle(...)`, `_ring_grab_axis = current effective axis`, `_ring_grab_accum = list(_rotate_accum[i])`, and the camera-facing sign `sign(dot(world_axis_k, view_dir))`.
- `_apply_ring_drag(cursor)`: `dθ_screen = unwrap(ring_drag_angle(cursor) − _ring_grab_angle)`; `dθ_body = dθ_screen * sign`; new axis = `rotate_about_axis(_ring_grab_axis, ring, dθ_body)`; write to `_pending_light[i]["axis"]`; `_rotate_accum[i][ring] = _ring_grab_accum[ring] + degrees(dθ_body)`.
- `_handle_gizmo_input`: add a rotate branch — on the press-edge grab, when `active_tool == "rotate"` use `pick_gizmo_ring` + `_begin_ring_drag`; on drag use `_apply_ring_drag`; release via the shared `_end_axis_drag`. Hover uses `pick_gizmo_ring` for the ring highlight. (Move/scale branches unchanged.)
- Generalize the `over_coords` guard and popover suppression to also fire when `rotate_values() is not None`.

### C. Native ring render mode (`native/src/renderer/gizmo_pass.cc`)

- Add a `handle_kind == 2` branch: draw **three rings** — a circle (segmented `GL_LINE_LOOP`/`GL_LINES`) of radius `length` in each body-axis plane (ring for axis k lies ⊥ `axis[k]`), coloured X/Y/Z, the hovered ring brightened. No shafts/tips. Depth-test off, state save/restore as the other modes. `handle_kind` 0/1 unchanged. No binding/host_loop change (they already forward `handle_kind`).

### D. CEF rotate panel (`native/assets/ui-cef/*`)

- `#spv-rotate` (class `spv-coords dev-only`, hidden) in `#spv-root`, same top-right slot. Three rows **X / Y / Z**, each `−5° −1° {value}° +1° +5°` firing `rotate_nudge:{axis,delta}`. Bottom row **Copy / Paste / Mirror** (`rotate_copy`/`rotate_paste`/`rotate_mirror`); Paste disabled unless `can_paste`.
- `setShipPropertyViewer`: show `#spv-rotate` when `data.rotate_values` non-null (fill the three accumulated-degree readouts, gate Paste), else hide. Suppress the popover when `transform_coords || scale_values || rotate_values`. The three tool panels (`#spv-coords`, `#spv-scale`, `#spv-rotate`) are mutually exclusive by the tool radio.

## Data flow (drag the Z ring)

```
grab Z ring -> pick_gizmo_ring -> 2 ; _begin_ring_drag(2): grab angle + axis + sign
drag -> dθ_screen ; dθ_body = dθ_screen*sign ; axis' = rotate_about_axis(grab_axis, 2, dθ_body)
     -> _pending_light[i]["axis"] = axis' ; glow wireframe rotates ; panel Z readout updates
Save -> region_spec_to_calls -> SetGlowRegionAxis(0, ax,ay,az) -> set_region -> hardpoint_overrides.py
```

## Edge cases

- **Non-cylinder / non-light selection**: `_rotate_target()` None → gizmo + panel hidden; all `rotate_*` dispatches no-op.
- **Axis degenerate** (zero vector): `rotate_about_axis` guards; normalize falls back to the previous axis.
- **Screen-angle wrap**: `_apply_ring_drag` unwraps the delta across ±π.
- **Ring nearly edge-on** (axis ~⊥ to screen): the ring projects to a thin line; picking still works (min segment distance), drag may be less precise — acceptable, the panel gives exact control.
- **Accumulator vs absolute**: Mirror/Paste set the axis absolutely and zero that target's accumulator (the readout restarts from the new baseline). Copy copies the axis vector.
- **Only one panel/gizmo at a time** (radio).

## Testing strategy

- **Panel (pytest)**: `rotate_values()` None off-tool / non-cylinder / box / sphere; present for a cylinder; `rotate_nudge` rotates the axis about the named body axis by the given degrees (assert the resulting unit axis via Rodrigues) and bumps the accumulator; `rotate_mirror` negates axis X and zeroes the accumulator; `rotate_copy`→`rotate_paste` round-trips the axis; `render_payload` carries `rotate_values` + re-pushes; guard fires for rotate.
- **Gizmo helpers (pytest)**: `rotate_about_axis` matches a known Rodrigues result; `pick_gizmo_ring` hits the correct ring for a synthetic camera; `ring_drag_angle` returns the screen angle; `rotate_gizmo()` gate + `handle_kind == 2`; a ring drag rotates the axis and does not orbit.
- **Native (host test)**: existing `set_transform_gizmo` accepts `handle_kind`; `handle_kind == 2` renders nothing when length 0 (production byte-identical).
- **CEF**: no automated DOM test (verified in-game); panel state covered in Python.

## Rollout

Continue on `feat/spv-gizmo-tools`, task-by-task via subagent-driven-development, gated by `scripts/check_tests.sh`. Merge is Mark's call after an in-game pass. Never pushed without Mark's say-so.
