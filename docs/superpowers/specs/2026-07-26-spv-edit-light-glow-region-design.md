# SPV Edit Light — Glow-Region Shape & Size Editing — Design

**Date:** 2026-07-26
**Status:** Approved design, ready for implementation plan
**Branch:** `feat/spv-edit-light`
**Builds on:** `2026-07-25-spv-hardpoint-value-override-editing-design.md` (radius
override MVP — the machine-owned file, the execute-to-model writer, the routing
seam, and the staged-edit / Save-confirm flow this feature extends).

## Summary

Let the Ship Property Viewer (SPV) edit a subsystem's **glow/light region** —
its **shape** (Sphere / Cylinder / Box) and its **size** — and persist it into
`engine/appc/hardpoint_overrides.py` using the exact staged-edit + explicit
Save/confirm flow the radius editor already ships. Right-click a light-bearing
subsystem → **Edit Light…** → a mouse-only modal (shape picker + size steppers)
→ **Apply** stages the edit and the SPV's orange glow wireframe updates live →
**Save changes (N)** → confirm → `hardpoint_overrides.py` is rewritten.

The glow regions the SPV edits are the **same** baked `SetGlowRegion*` data the
glow controller drives and the "Glow Regions" overlay already draws — so a staged
edit is visible live in the hologram by construction (Sphere & Cylinder; Box has
no live wireframe yet — see below).

This is the "next stage" the radius design was structured for: the writer already
models `SetGlowRegion*` setters, the routing seam already resolves the target, and
the panel already stages/saves. This design adds the glow-specific UI, one writer
operation (`set_region`), and live-preview wiring.

## Scope decisions (from brainstorming)

1. **Which subsystems get "Edit Light…":** only the three glow-bearing categories
   — **impulse-engine pods, warp pods, and the sensor subsystem** — computed from
   the same `subsystem_glow` helpers `ShipGlowController` registers
   (`warp_pods`, `impulse_engines`, `GetSensorSubsystem`). "Set Radius…" continues
   to appear on every row.
2. **Box has no live preview, and we do NOT fake one.** The debug-volume renderer
   draws only wireframe **cylinders** (`native/src/renderer/debug_volume_pass.cc`);
   `resolve_baked_region` already drops `Box` ("no renderer shape yet"). A Box
   glow is fully editable and saveable (the authored data is valid and takes
   effect wherever real Box glow rendering eventually lands), but the modal shows
   a "live preview unavailable" note and no orange box is drawn. This keeps the
   SPV wireframe honest — it never shows a box that differs from the (absent) real
   glow. **Zero C++ change.**
3. **Region index 0 only.** Impulse/warp/sensor each bake a single region;
   editing index 0 keeps the UI simple. Higher indices are out of scope.

## Mechanism recap (unchanged, relied upon)

`hardpoint_overrides.py` is machine-owned: one `def _<leaf>(find):` per ship, one
block per subsystem, plain Appc setter calls. It already **holds the baked
glow regions** (`tools/bake_impulse_glow.py` / `bake_warp_glow.py` generated the
`SetGlowRegion*` blocks). The SDK-loader hook runs `apply(leaf)` after the
hardpoint re-registers its templates and before `LoadPropertySet`/`SetupProperties`
read them, mutating the shared template — so a saved glow edit takes effect at the
**next ship build (reload)**, matching the persist→reload proof model. Editing a
glow region therefore edits the *same file and same blocks* the bakes wrote.

## Approach: full-region replace (chosen)

On Apply, the panel captures the region's **complete** spec — shape, position,
axis, and the shape's size fields — seeded from the subsystem's current baked
region 0 (or a from-scratch default for an unbaked sensor). On Save, the writer
**replaces region 0 wholesale** via a new `set_region` operation.

Why full-region replace rather than per-setter edits:
- **Clean shape switches.** Switching Cylinder→Box must drop the now-meaningless
  `SetGlowRegionAxis`/`Extent` and add `Scale`; a per-`set_setter` edit would
  leave orphan setters cluttering a file whose whole purpose is being clean and
  deterministic. `set_region` removes all `SetGlowRegion*(0, …)` for the
  subsystem, then writes exactly the setters the chosen shape needs.
- **Preview == saved result by construction.** The live wireframe resolves the
  *pending spec* through the very same `resolve_baked_region` the saved file will
  be read back through. What you see staged is what the file will produce.

Position and axis are **preserved, not user-editable** (out of scope for a size
editor). They are captured into the spec — from the existing region, else the
subsystem's hardpoint mount position (`_position_tuple`) and a default axis
`(0.0, -1.0, 0.0)` — and re-emitted so the region stays coherent. Explicit values
in a machine-owned file are fine (this is exactly what the bake tools emit).

### Setters emitted per shape (region index `i = 0`)

| Shape | Emitted calls (in order) |
|---|---|
| Sphere | `SetGlowRegionShape(0,"Sphere")`, `SetGlowRegionPosition(0,x,y,z)`, `SetGlowRegionRadius(0,r)` |
| Cylinder | `SetGlowRegionShape(0,"Cylinder")`, `SetGlowRegionPosition(0,x,y,z)`, `SetGlowRegionAxis(0,ax,ay,az)`, `SetGlowRegionRadius(0,r)`, `SetGlowRegionExtent(0,aft,fore)` |
| Box | `SetGlowRegionShape(0,"Box")`, `SetGlowRegionPosition(0,x,y,z)`, `SetGlowRegionScale(0,sx,sy,sz)` |

Validation (rejected at the panel, greyed in the UI): `r > 0`; `fore > aft`;
each of `sx, sy, sz > 0`. (These mirror `resolve_baked_region`'s own guards.)

## Components

### 1. Writer — `engine/appc/hardpoint_override_writer.py`

Add one pure function:

```python
def set_region(models, leaf, subsystem, index, calls) -> None:
    """Replace all SetGlowRegion*(index, ...) calls for a subsystem with `calls`
    (an ordered list of (setter, args)). Leaves SetRadius and other-index glow
    setters intact. Creates the leaf/subsystem entry if absent."""
```

- Removes existing calls where `setter.startswith("SetGlowRegion")` and
  `args and args[0] == index`.
- Appends `calls` in order (each `args` already begins with `index`).
- `emit`/`read_models` are unchanged; `emit` still `ast.parse`-validates.

### 2. Target — `engine/appc/override_routing.py`

`HardpointOverridesFileTarget.write(leaf, edits)` accepts a **mixed** edit list:

- 3-tuple `(subsystem, setter, args)` → `set_setter` (the radius path — byte-
  identical; existing test unaffected).
- 4-tuple `(subsystem, "__region__", index, calls)` → `set_region`.

Reload → apply each edit → `emit` → atomic `os.replace` (unchanged otherwise).

### 3. Glow-category + current-spec helpers — `engine/appc/subsystem_glow.py`

- `glow_bearing_subsystem_ids(ship) -> set[int]` — `id()` of every warp pod,
  impulse pod, and the sensor subsystem (reuses `warp_pods`, `impulse_engines`,
  `GetSensorSubsystem`; None-safe; never raises).
- Reuse existing `baked_glow_regions(prop)` to read region 0's current spec.

### 4. Descriptors — `engine/ui/ship_property_viewer.py`

After building descriptors, a post-pass annotates light-bearing subsystems:

- `"light": True` on descriptors whose subsystem `id()` is glow-bearing.
- `"light_region": {...}` — the current region-0 spec used to pre-fill the modal:
  `{shape, position, axis, radius, extent, scale}` from `baked_glow_regions(...)[0]`
  when present, else a from-scratch default (`shape="Sphere"`,
  `position=_position_tuple(sub)`, `axis=(0,-1,0)`, sensible default radius).

(The post-pass needs the subsystem objects; it re-walks `_iter_subsystems(ship)`
in the same order as `build_descriptors` and zips onto the produced descriptors,
skipping object-emitter mounts which are never light-bearing.)

### 5. Panel — `engine/ui/ship_property_viewer_panel.py`

- `self._pending_light: dict[int, dict]` — descriptor index → full region spec.
  Reset in `open()`/`close()`; added to the `render_payload` snapshot tuple.
- `dispatch_event`:
  - `set_light:<json {"i", "shape", "radius"?, "aft"?, "fore"?, "sx"?, "sy"?, "sz"?}>`
    — validate index + the shape's fields (reject `r<=0`, `fore<=aft`, any
    `scale<=0`); build the full spec (carry position/axis from the descriptor's
    `light_region`); stage into `_pending_light`; `self._last_pushed = None`.
  - `save` — build `edits` = radius 3-tuples **plus** light 4-tuples
    (`(name, "__region__", 0, region_spec_to_calls(0, spec))`); route as today;
    clear both pending dicts on success; keep both on failure/unresolved leaf.
- `dirty` (per row), `pending_count`, and `_pending_edits()` count **both**
  `_pending_radius` and `_pending_light` — `pending_count` = number of distinct
  dirty descriptor indices; a subsystem with both edits shows a tally of 2.
- Each subsystem row carries `light` (bool) and `light_region` (pending spec when
  staged, else the baked spec) so the CEF context menu can show "Edit Light…" and
  the modal can pre-fill.
- `pending_light_specs() -> {subsystem_name: region_dict}` for the overlay.
- The selected popover overlays a short staged-light summary into `properties`
  when a light edit is pending (e.g. `light: "Cylinder r0.25 [0,2]"`).

### 6. Live wireframe — `engine/ui/glow_region_overlay.py` + `engine/host_loop.py`

- `build_glow_region_overlay(ship, selected_name, show_all, pending=None)`:
  `pending` maps subsystem name → region spec. For a subsystem with a pending
  spec, resolve **that** spec through `resolve_baked_region` (Box → `None` → no
  cylinder, faithful to "don't fake a box") instead of `baked_region_ops(prop)`.
  A subsystem with no pending spec is unchanged.
- host_loop passes `pending=ship_property_viewer.pending_light_specs()` at the
  existing `set_debug_cylinders(build_glow_region_overlay(...))` call site.

### 7. CEF — `index.html` / `js/ship_property_viewer.js` / `css/ship_property_viewer.css`

- **Context menu:** add `<div ... onclick="shipPropertyViewerCtxLight()">Edit
  Light…</div>`, shown only when the right-clicked row's `light` flag is set
  (seed `spvRowLight[index]` during list render, like `spvRowRadii`; toggle the
  item's `display` in `shipPropertyViewerRowMenu`).
- **Light modal (`#spv-light`), mouse-only** — no typed field (there is no
  keyboard→CEF forwarding):
  - **Shape picker:** three buttons (Sphere / Cylinder / Box); clicking one sets
    the active shape and swaps which stepper rows are visible.
  - **Size steppers** (`[−] value [+]`, mirroring the radius stepper):
    - Sphere: `radius`.
    - Cylinder: `radius`, extent `aft`, extent `fore`.
    - Box: `sx`, `sy`, `sz` (half-extents).
  - Box shows a small "Live preview unavailable" note.
  - Apply (`shipPropertyViewerLightApply`) fires
    `set_light:<json>` with the active shape + its fields; Cancel closes.
  - Fires `overlay:1`/`overlay:0` like the radius modal so orbit is suppressed;
    ESC is owned by the panel's `handle_key_esc` (unchanged single-owner path).
  - Pre-fill from the right-clicked row's `light_region` (falls back to defaults).
- **Save bar / confirm modal:** unchanged — light edits flow through
  `pending_count` and the `pending` tally list already rendered by the confirm
  modal.
- CSS: reuse the `spv-modal*` / `spv-ctxmenu*` classes; add a compact
  shape-picker button row and multi-stepper layout.

## Data flow

```
right-click impulse pod row (light=true)
  → context menu shows "Edit Light…"
  → modal pre-filled from row.light_region (Cylinder r0.25 [0,2])
  → pick shape, step size (mouse only)
  → Apply → dauntlessEvent 'set_light:{i:.., shape:"Cylinder", radius:.., aft:.., fore:..}'
      → panel validates + stages _pending_light[i] = full spec
      → render_payload: row dirty, pending_count=1, popover light summary
      → host_loop passes pending_light_specs() into build_glow_region_overlay
      → orange wireframe updates live (Sphere/Cylinder; Box = none)
  → "Save changes (1)" → confirm modal lists "Center Impulse (1)"
  → Save → resolve_override_target(ship).write(leaf,
             [("Center Impulse", "__region__", 0, [<calls>])])
      → set_region rewrites region 0 → emit → atomic write
  → next ship build applies the new glow region
```

## Testing

- **Writer (`set_region`, pure):** clean shape switch drops old size setters and
  writes the new shape's; index isolation (editing index 0 leaves index 1 and
  `SetRadius` intact); creates a block when the subsystem is absent; `emit`
  round-trips to a fixed point after a region edit.
- **Target:** a `__region__` 4-tuple persists a glow edit to a temp file and reads
  back the expected setters; a mixed list (radius 3-tuple + light 4-tuple) applies
  both; the radius-only path is byte-identical (existing test still green).
- **Helper:** `glow_bearing_subsystem_ids` returns exactly the warp/impulse/sensor
  ids for a stub ship; None-safe on a ship missing the getters.
- **Panel:** `set_light` stages a full spec and marks the row dirty; validation
  rejects `fore<=aft` / `r<=0` / `scale<=0`; Box stages with no size-preview
  dependency; `save` routes the `__region__` edit and clears; `pending_count` and
  the tally count light + radius together; close-without-save discards; overlay
  suppression unchanged.
- **Overlay:** a pending Cylinder spec overrides the baked ops for that subsystem;
  a pending Box yields no cylinder; other subsystems unchanged; `pending=None`
  behaves exactly as today.
- **Gate:** `scripts/check_tests.sh` green (only the 7 baselined headless-GL
  FrameTests may fail). **Live-verify** under `--developer` on Galaxy: right-click
  Center Impulse → Edit Light → change radius/extent → Apply (wireframe updates) →
  switch to Box (note shown, wireframe gone) → back to Cylinder → Save → confirm →
  inspect the regenerated `_galaxy` block → reload → glow persists.

## Risks / out of scope

- **From-scratch region on an unbaked sensor** (only 5 Federation ships bake
  sensor spheres). Handled: `light_region` defaults seed the modal; a Cylinder
  from scratch gets the default axis `(0,-1,0)`. Low risk; the common case is
  editing an existing baked region.
- **Explicit position/axis in the file.** Full-region replace writes `Position`
  (and, for Cylinder, `Axis`) even when previously implicit. Intentional — keeps
  the region self-contained and matches the bake tools; diffs are a few lines, not
  one, which the deterministic emit + git history absorb.
- **Out of scope:** position/axis *editing*; region indices > 0; live-while-you-
  step preview (Apply-then-preview only); Box wireframe/glow **rendering** (a
  separate capability — this feature only authors the data); modded-ship target.

## Future work

- Real Box glow rendering (shader + a Box debug wireframe) — then the modal's
  "live preview unavailable" note is removed and Box previews like the others.
- Live-while-you-step preview (stream staged specs on each stepper click).
- Position/axis editing and multi-region (index > 0) support.