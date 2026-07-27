# SPV Scale Tool — Design

**Date:** 2026-07-27
**Status:** Approved (design); implementation pending
**Builds on:** the SPV Transform gizmo + coordinate panel (`docs/superpowers/specs/2026-07-26-spv-transform-gizmo-design.md`, `2026-07-27-spv-transform-coord-panel-design.md`). Reuses the gizmo renderer, the `_active_transform_target` plumbing, the effective-value resolvers, the click-guard, and the top-right panel pattern.

## Goal

A **Scale** tool (the third button in the Transform/Rotate/Scale radio) that follows the Transform pattern — a scale gizmo you drag plus a top-right panel — to edit the selected element's **size**, staged and saved through the existing flow. Shape-aware, because "size" differs per element.

Developer-only, mouse-only. Production byte-identical (hidden unless Scale active + selection).

## Key decisions (confirmed with Mark)

1. **Shape-aware size model.** Scale edits whatever size fields the selected element actually has:

   | Element | Fields | Persists via |
   |---|---|---|
   | Subsystem | Radius | `SetRadius` → `_pending_radius` (existing radius path) |
   | Light — Sphere | Radius | region-0 `radius` → `_pending_light` |
   | Light — Cylinder | Radius, Length | region-0 `radius` + `extent` (Length = fore − aft) |
   | Light — Box | X, Y, Z | region-0 `scale` |

2. **Panel bottom row = Copy / Paste / Uniform** (Mirror is meaningless for a size). Copy/Paste are **kind-matched** (Paste enabled only when the clipboard's field-set matches the current element). **Uniform** (Box only) sets X=Y=Z to the **largest** of the three (never silently shrinks a dimension); no-op on single-value shapes.

3. **Scale gizmo:** the gizmo renderer gains a **cube-tipped** handle variant (vs the move arrows), distinct colour. Dragging an axis scales **multiplicatively**. Mapping: Box → per-axis (`scale[k]`); Sphere/subsystem → any axis scales the radius uniformly; Cylinder → any axis scales the radius (Length is panel-only for v1). The live wireframe shows the change; the panel values update live.

## Background facts (verified)

- The gizmo drag hook is `_handle_gizmo_input(x,y,down,over_chrome,dsf,fb_size)`; it currently reads `self.transform_gizmo()` and applies position via `_apply_axis_drag`. It will be generalized to `_active_gizmo()` + a per-tool drag application.
- `set_transform_gizmo(origin, ax, ay, az, length, highlight)` (host binding + `engine/renderer.py` wrapper + host_loop push) drives the one gizmo slot. A `handle_kind` int (0 arrows / 1 cubes) will be appended.
- Subsystem radius: `_effective_radius(i, baked)` / `_pending_radius[i]` (the Set Radius modal path). Light size: `_effective_light(i)` spec (`shape`, `radius=(r,)`, `extent=(aft,fore)`, `scale=(sx,sy,sz)`) staged into `_pending_light[i]`, saved by `region_spec_to_calls` → `set_region`.
- The top-right coord panel (`transform_coords()` / `#spv-coords`) + its click-guard (`_cursor_over_coords`, gated on `transform_coords() is not None`) + popover-suppression are the pattern the scale panel mirrors. Only one of Transform/Scale is active (radio), so the two panels share the top-right slot and never render together.

## Components

### A. Scale value model + dispatch (`ship_property_viewer_panel.py`)

- `_scale_clipboard: Optional[tuple] = None` — `(kind, values_tuple)`; reset in `__init__`/`open`/`close`.
- `_scale_kind_and_fields(target) -> (kind, fields)`:
  - subsystem → `("radius", [{"label":"Radius","value": r}])` (r = `_effective_radius`).
  - light, by `_effective_light(i)["shape"]`:
    - Sphere → `("radius", [Radius])`
    - Cylinder → `("radius_length", [Radius, Length])` (Length = fore − aft)
    - Box → `("xyz", [X, Y, Z])`
- `scale_values() -> Optional[dict]`: `None` unless `active_tool == "scale"` AND a target; else
  `{"kind": kind, "fields": [{label,value}...], "has_clipboard": bool, "can_paste": clipboard_kind == kind}`.
- `_set_scale_field(index, value)`: `value` floored at a small `SCALE_MIN` (> 0); route by target/kind:
  - subsystem → `_pending_radius[i] = value`.
  - light Sphere → spec `radius=(value,)`; Cylinder index 0 → `radius`, index 1 → `extent=(aft, aft+value)`; Box → `scale[index]=value`. Stage the updated `_effective_light(i)` copy into `_pending_light[i]`.
- Dispatch (before `save`):
  - `scale_nudge:<json {"index":int,"delta":float}>` → field `index` += delta (guard index in range for the kind, floored), set.
  - `scale_copy` → `_scale_clipboard = (kind, tuple(values))`.
  - `scale_paste` → if `_scale_clipboard` and `_scale_clipboard[0] == kind`: set every field from the clipboard values.
  - `scale_uniform` → Box only: `m = max(sx,sy,sz)`; set scale=(m,m,m). No-op otherwise (return True).
- `render_payload`: add `"scale_values": self.scale_values()`; add `self._scale_clipboard` to the `snapshot` tuple.

### B. Scale gizmo + drag (`ship_property_viewer_panel.py`)

- `scale_gizmo() -> Optional[dict]`: `None` unless `active_tool == "scale"` AND a target AND ship has GetWorldRotation; else the same shape as `transform_gizmo()` plus `"handle_kind": 1`. `transform_gizmo()` gains `"handle_kind": 0`.
- `_active_gizmo()`: `transform_gizmo()` when tool == transform; `scale_gizmo()` when tool == scale; else None.
- `_handle_gizmo_input`: replace `self.transform_gizmo()` with `self._active_gizmo()`. On the press-edge grab and on drag, dispatch by `active_tool`:
  - transform → existing `_begin_axis_drag` / `_apply_axis_drag` (unchanged).
  - scale → `_begin_scale_drag(axis, t_grab)` captures the mapped grab value(s) + `t_grab`; on drag `_apply_scale_drag(axis, t_now)` computes `ratio = t_now / max(t_grab, 0.25*length)` and sets the mapped field(s) to `grab_value * ratio` (floored). Axis→field per shape as in decision 3.
- Release uses the shared `_end_axis_drag`.

### C. Native cube-handle mode (`native/`)

- `GizmoPass::Gizmo` gains `int handle_kind{0}`. `render` draws cone tips for kind 0 (current), and small **cube** tips for kind 1, in a distinct colour (e.g. brighter/desaturated) so scale reads differently from move.
- `set_transform_gizmo(..., handle_kind)` appends the param; `clear_transform_gizmo` unchanged. `engine/renderer.py` wrapper + host_loop push forward `handle_kind`.
- host_loop pushes `ship_property_viewer._active_gizmo()` (was `transform_gizmo()`), forwarding its `handle_kind`; clears when None. Empty gizmo (length 0) still draws nothing → production byte-identical.

### D. CEF scale panel + guard/popover (`native/assets/ui-cef/*`, `ship_property_viewer_panel.py`)

- `#spv-scale` (dev-only), same top-right geometry as `#spv-coords`, hidden by default. Rows are **dynamic** (1–3) built from `data.scale_values.fields` (label + value + the `−0.1 −0.01 {value} +0.01 +0.1` stepper firing `scale_nudge:{index,delta}`). Bottom row: **Copy / Paste / Uniform** (`scale_copy`/`scale_paste`/`scale_uniform`); Paste disabled unless `can_paste`; Uniform present always (no-op server-side off-Box).
- `setShipPropertyViewer`: show `#spv-scale` when `data.scale_values` non-null (fill rows + Paste state), else hide; keep `#spv-coords` driven by `data.transform_coords`. Suppress the popover when **either** panel is up (`data.transform_coords || data.scale_values`).
- Click-guard: generalize the `over_coords` gate in `handle_input` to fire when **either** `transform_coords()` or `scale_values()` is non-null (both panels occupy the same top-right box).

## Data flow (drag-scale a Box X axis)

```
grab cube handle on +X
  _handle_gizmo_input: axis=0; tool==scale -> _begin_scale_drag(0, t_grab); grab=scale[0]
drag out
  t_now; ratio = t_now / max(t_grab, 0.25L); scale[0] = grab*ratio (floored)
  -> _pending_light[i] spec updated -> glow wireframe + panel value follow
Save -> region_spec_to_calls(0, spec) -> set_region -> hardpoint_overrides.py
```

## Edge cases

- **Sphere/Cylinder/subsystem drag** scales the radius (uniform) — Length/other fields via the panel.
- **Uniform** is a no-op on non-Box (returns True, no change); the CEF button is always present.
- **Paste kind mismatch** (box clipboard, sphere target) → `can_paste` false → button disabled + dispatch guards.
- **Floor**: every set floors at `SCALE_MIN` so a drag/nudge can't produce a zero or negative size.
- **Only one panel/gizmo at a time** (radio) — Transform and Scale never render together.

## Testing strategy

- **Panel (pytest)**: `scale_values()` None off-tool/no-selection; correct kind/fields per shape (subsystem radius, sphere radius, cylinder radius+length, box xyz); `scale_nudge` moves only the named field + floors; `scale_copy`→`scale_paste` round-trips and is kind-gated (`can_paste`); `scale_uniform` sets box axes to the max, no-op on sphere; `render_payload` carries `scale_values` + re-pushes after Copy; click-guard fires for scale.
- **Gizmo drag (pytest)**: `scale_gizmo()` gate + `handle_kind==1`; a scale drag multiplies the mapped field by the ratio (box per-axis; sphere uniform radius); does not orbit (reuses the guarded hook); `_active_gizmo()` selects by tool.
- **Native (host test)**: `set_transform_gizmo` accepts the `handle_kind` param; empty gizmo renders nothing.
- **CEF**: no automated DOM test (verified in-game); panel state covered in Python.

## Rollout

Continue on `feat/spv-gizmo-tools`, task-by-task via subagent-driven-development, gated by `scripts/check_tests.sh`. Merge is Mark's call after an in-game pass. Never pushed without Mark's say-so.
