# SPV Transform Coordinate Panel — Design

**Date:** 2026-07-27
**Status:** Approved (design); implementation pending
**Builds on:** the SPV Transform Gizmo (`docs/superpowers/specs/2026-07-26-spv-transform-gizmo-design.md`, merged main `7ea9b2aa`) — reuses its transform-target plumbing (`_active_transform_target`, `_effective_pos`/`set_subsystem_position`, `_effective_light`/`set_light_position`).

## Goal

A coordinate panel in the top-right of the Ship Property Viewer, shown while
transforming (Transform tool active + a subsystem or light node selected). It
lists the selected element's body-frame XYZ, each on a mouse-only nudge stepper
(`−0.1 −0.01 {value} +0.01 +0.1`), and offers **Copy / Paste / Mirror** at the
bottom. Every edit stages into the same pending position the gizmo uses, so it
previews live and saves through the existing Save/amend-confirm flow.

Developer-only, mouse-only (no keyboard→CEF forwarding). Production byte-identical.

## Key decisions (confirmed with Mark)

1. **Clipboard is in-SPV** (a Python variable), not the OS clipboard — easiest,
   no native binding. Lost on restart; scoped to the SPV session.
2. **Mirror negates X**, the port/starboard axis (confirmed by the Galaxy
   AftTorpedo1/2 pair, which differ only in X: `−0.065` vs `+0.065`). Mark
   originally said Y; corrected to X.
3. Panel shows for the **same gate as the gizmo**: `active_tool == "transform"`
   AND a subsystem or light node selected.

## Background facts (verified)

- The selected element's effective body-frame position:
  subsystem → `_effective_pos(i)`; light node → `_effective_light(i)["position"]`.
  Setter: subsystem → `set_subsystem_position(i, xyz)`; light → `set_light_position(i, xyz)`.
  `_active_transform_target()` returns `("light", i)` / `("subsystem", i)` / `None`.
- `render_payload()` returns a `setShipPropertyViewer({...});` JS-call string;
  it re-pushes when its `snapshot` tuple changes. `_pending_pos`/`_pending_light`
  are already in the snapshot, so a gizmo drag re-pushes each frame — the coord
  readout updates live for free.
- Body-frame components: X = starboard (`GetCol(0)`), Y = forward, Z = up.
- Mouse-only steppers already exist (the Set Radius modal): buttons nudge a value.
- The SPV click-guard: `_cursor_over_chrome` (titlebar + left column) and
  `_cursor_over_tools` (bottom-right cluster) mark regions whose clicks belong to
  CEF chrome so they never start an orbit/gizmo drag. A new top-right panel needs
  the same treatment.

## Components

### A. Panel state + dispatch (`ship_property_viewer_panel.py`)

- `self._coord_clipboard: Optional[tuple] = None` — reset in `__init__`/`open`/`close`.
- `_transform_target_pos() -> Optional[tuple]`: the active target's effective XYZ
  (subsystem `_effective_pos(i)`; light `tuple(_effective_light(i)["position"])`),
  or `None` when there's no active transform target.
- `_set_transform_target_pos(xyz)`: dispatch to `set_subsystem_position` /
  `set_light_position` by active target. (Both already exist.)
- `transform_coords() -> Optional[dict]`: `None` unless `active_tool == "transform"`
  AND `_active_transform_target()` is not `None`; else
  `{"x": fx, "y": fy, "z": fz, "has_clipboard": bool(self._coord_clipboard)}`.
- Dispatch actions:
  - `coord_nudge:<json {"axis": 0|1|2, "delta": float}>` → `pos = list(target pos)`;
    `pos[axis] += delta`; `_set_transform_target_pos(tuple(pos))`. Reject bad axis /
    non-float / no target.
  - `coord_copy` → `self._coord_clipboard = self._transform_target_pos()` (no-op if None).
  - `coord_paste` → if `_coord_clipboard` and a target: `_set_transform_target_pos(self._coord_clipboard)`.
  - `coord_mirror` → `pos = list(target pos)`; `pos[0] = -pos[0]`; set.
- `render_payload()`: add `"transform_coords": self.transform_coords()` to the
  payload dict, and add `self._coord_clipboard` to the `snapshot` tuple (so a
  Copy re-pushes to enable Paste). The XYZ readout already re-pushes via the
  existing `_pending_pos`/`_pending_light` snapshot members.

### B. Click-guard (`ship_property_viewer_panel.py`)

- Constants near the existing `TOOLS_*` block for the top-right panel box
  (logical points): `COORDS_MARGIN_PT`, `COORDS_W_PT`, `COORDS_H_PT`, anchored to
  the top-right corner just below the titlebar. Exact values are chosen to match
  the CEF panel's rendered size (Component C) — the plan pins both to the same
  numbers.
- `_cursor_over_coords(x, y, dsf, fb_w, fb_h) -> bool`: cursor (framebuffer px)
  inside that box; `False` when the viewport size is unknown. Include it in the
  `over_chrome` computation in `handle_input` so a click on the coord panel never
  starts an orbit or gizmo-axis drag. (The panel only occupies real screen space
  while it's visible, but guarding the region unconditionally is safe — it's a
  small top-right rectangle the user only clicks intentionally; matching
  `_cursor_over_tools`, which also guards unconditionally.)

### C. CEF panel (`native/assets/ui-cef/{index.html,css,js}`)

- `#spv-coords` (class `dev-only`), positioned top-right (below the titlebar),
  hidden by default. Three rows (X/Y/Z), each: `−0.1  −0.01  <value>  +0.01  +0.1`
  buttons + a value span. A bottom row: **Copy**, **Paste**, **Mirror** buttons.
- JS: a `shipPropertyViewerCoordNudge(axis, delta)` fires
  `dauntlessEvent('ship-property-viewer/coord_nudge:' + JSON.stringify({axis, delta}))`;
  `shipPropertyViewerCoord{Copy,Paste,Mirror}` fire `coord_copy`/`coord_paste`/`coord_mirror`
  (same channel idiom as the existing toggles/tools). In the render-apply function
  (`setShipPropertyViewer`), read `data.transform_coords`: `null` → hide `#spv-coords`;
  else show it, set each row's value text (2–3 decimals), and enable/disable the
  Paste button from `has_clipboard`.
- CSS: reuse the existing SPV chrome look; a compact panel, `pointer-events:auto`.
  Its rendered footprint (margin, width, height) must match the Python
  `COORDS_*` constants so the click-guard covers it.

### D. Host loop

No change. `transform_coords` rides the existing `render_payload` → CEF push; the
readout updates live because `_pending_pos`/`_pending_light` already invalidate the
snapshot each frame during a drag.

## Data flow (nudge X down by 0.1)

```
click [−0.1] on the X row
  JS: dauntlessEvent('ship-property-viewer/coord_nudge:{"axis":0,"delta":-0.1}')
  dispatch_event -> pos=list(_transform_target_pos()); pos[0]-=0.1; _set_transform_target_pos(pos)
  -> set_subsystem_position / set_light_position -> _pending_pos / _pending_light
  render_payload re-pushes: transform_coords readout + gizmo/pin/sphere all move
Save -> amend-confirm -> SetPosition / region-0 position -> hardpoint_overrides.py
```

## Edge cases

- **No target / wrong tool**: `transform_coords()` returns `None` → panel hidden;
  all `coord_*` dispatches no-op safely (guard on `_transform_target_pos()` / target).
- **Paste with empty clipboard**: button disabled in CEF; dispatch also guards
  (`if not self._coord_clipboard: return`).
- **Mirror at X=0**: negating 0 stays 0 (harmless).
- **Light vs subsystem**: both are transform targets; Copy/Paste can move coords
  between a subsystem and a light (both are absolute body-frame positions) — a
  useful side effect, not a special case.
- **Clipboard survives selection changes** (session-scoped) so you can copy one
  element's coords and paste onto another; cleared on `open`/`close`.

## Testing strategy

- **Panel (pytest)**: `transform_coords()` None off-tool / no-selection, dict with
  correct XYZ + `has_clipboard` when transforming; `coord_nudge` moves only the
  named axis via the active target (subsystem AND light); `coord_copy` then
  `coord_paste` round-trips; `coord_paste` no-ops with empty clipboard; `coord_mirror`
  negates X only; `render_payload` carries `transform_coords` and re-pushes after a
  Copy. Reuse the `_payload_data` unwrap helper (payload is a JS-call string).
- **Click-guard (pytest)**: `_cursor_over_coords` True inside the top-right box,
  False outside; a press there does not orbit/pick (extend the existing guard test).
- **CEF**: no automated DOM test (verified in-game); the panel state is covered in
  Python.

## Rollout

Continue on `feat/spv-gizmo-tools`, task-by-task via subagent-driven-development,
gated by `scripts/check_tests.sh`. Merge is Mark's call after an in-game pass.
Never pushed without Mark's say-so.
