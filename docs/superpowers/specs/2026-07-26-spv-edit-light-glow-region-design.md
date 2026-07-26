# SPV Edit Light — Glow-Region Shape & Size Editing (with real Box glow) — Design

**Date:** 2026-07-26
**Status:** Approved design, ready for implementation plan
**Branch:** `feat/spv-edit-light`
**Builds on:** `2026-07-25-spv-hardpoint-value-override-editing-design.md` (radius
override MVP — the machine-owned file, the execute-to-model writer, the routing
seam, and the staged-edit / Save-confirm flow this feature extends).

## Summary

Let the Ship Property Viewer (SPV) edit a subsystem's **glow/light region** — its
**shape** (Sphere / Cylinder / Box) and its **size** — and persist it into
`engine/appc/hardpoint_overrides.py` using the staged-edit + explicit
Save/confirm flow the radius editor already ships.

Today the engine renders only **two** glow-region shapes — Sphere and Cylinder
(both are the capsule test in `opaque.frag`). "Box" is a valid *authored* shape in
the hardpoint schema (`SetGlowRegionShape(i,"Box")` + `SetGlowRegionScale`) that
currently renders as **nothing**. So this feature has two phases:

- **Phase 0 — Real Box glow rendering.** Make Box a genuine third renderable
  shape: a box test in the glow shader, a box primitive in the native region
  storage, a box op in `resolve_baked_region`, and a wireframe box in the SPV
  debug-volume overlay. After Phase 0 the in-game glow AND the SPV preview both
  show a real box — no fake/debug-only box that differs from the shipped glow.
- **Phase 1 — Edit Light UI.** Right-click a light-bearing subsystem →
  **Edit Light…** → a mouse-only modal (shape picker + size steppers) → **Apply**
  stages the edit and the orange glow wireframe updates live → **Save changes (N)**
  → confirm → `hardpoint_overrides.py` is rewritten.

The glow regions the SPV edits are the same baked `SetGlowRegion*` data the glow
controller drives and the "Glow Regions" overlay already draws, so a staged edit
is visible live in the hologram by construction — for all three shapes once Phase
0 lands.

## Scope decisions (from brainstorming)

1. **Which subsystems get "Edit Light…":** only the three glow-bearing categories —
   **impulse-engine pods, warp pods, and the sensor subsystem** — computed from the
   same `subsystem_glow` helpers `ShipGlowController` registers (`warp_pods`,
   `impulse_engines`, `GetSensorSubsystem`). "Set Radius…" continues to appear on
   every row.
2. **Box is a real third shape** (Phase 0), not a fake preview. All three shapes
   render in-scene and preview live.
3. **Box is body-axis-aligned.** BC's Box schema is Position + Scale (half-extents),
   with **no** axis — so the box aligns to the subsystem/body frame (the ship's
   rotation then applies when drawn). No box-orientation editor.
4. **Region index 0 only.** Impulse/warp/sensor each bake a single region; editing
   index 0 keeps the UI simple. Higher indices are out of scope.

## Mechanism recap (unchanged, relied upon)

`hardpoint_overrides.py` is machine-owned: one `def _<leaf>(find):` per ship, one
block per subsystem, plain Appc setter calls. It already **holds the baked glow
regions** (`tools/bake_impulse_glow.py` / `bake_warp_glow.py` generated the
`SetGlowRegion*` blocks). The SDK-loader hook runs `apply(leaf)` after the hardpoint
re-registers its templates and before `LoadPropertySet`/`SetupProperties` read them,
mutating the shared template — so a saved glow edit takes effect at the **next ship
build (reload)**, matching the persist→reload proof model. Editing a glow region
edits the *same file and same blocks* the bakes wrote.

---

# Phase 0 — Real Box glow rendering

The current glow path (in-scene) is capsule-only, confirmed end to end:
`resolve_baked_region` drops Box ([subsystem_glow.py](../../../engine/appc/subsystem_glow.py));
`_register_baked` dispatches only sphere/cylinder ops; `glow_region.cc` builds only
sphere + capsule; `opaque.frag`'s `glow_region_mult` is a capsule inside-test with
capsule-shaped uniforms. Phase 0 adds a box branch to each layer.

## 0.1 Shader — `native/src/renderer/shaders/opaque.frag`

The per-region uniforms are four vec4s (`u_glow_region_a..d`), and **all 16 floats
are used** by the capsule path. Add a **fifth** vec4 array rather than repacking:

```glsl
uniform vec4 u_glow_region_e[MAX_GLOW_REGIONS];  // shape_flag, half_extent.xyz
```

In `glow_region_mult`, branch the inside-test on `u_glow_region_e[i].x`
(0 = capsule/sphere, 1 = box); everything after the inside-test (gain gate, dim /
flicker / destroy state machine, `mult = min(...)`) is **unchanged** and shape-
agnostic:

```glsl
vec3  d = p_body - center;
if (u_glow_region_e[i].x > 0.5) {                 // body-axis-aligned box
    vec3 h = u_glow_region_e[i].yzw;
    vec3 a = abs(d);
    if (a.x > h.x || a.y > h.y || a.z > h.z) continue;
} else {                                          // existing capsule/sphere test
    float t = dot(d, axis);
    vec3  perp = d - t * axis;
    if (dot(perp, perp) > radius * radius) continue;
    if (t < aft || t > fore) continue;
}
```

Capsule/sphere regions leave `u_glow_region_e` at `(0,0,0,0)` → the box branch is
never taken → the production path is **byte-identical** (verified by the existing
FrameTests plus the 7 baselined ones). Requires a `cmake -B build -S .` reconfigure
(shader change) before `cmake --build`.

## 0.2 Native region storage + upload

- `scenegraph::Instance::GlowRegion` gains `float shape = 0.0f;` and
  `glm::vec3 half_extents{0.0f};`.
- `frame.cc` (the packing block ~L334) fills a 5th array
  `ne[nn] = glm::vec4(n.shape, n.half_extents)` and calls
  `set_vec4_array("u_glow_region_e", ne, nn)` inside the existing `nn > 0` guard.
- `add_box_region(instance_id, center, half_extents) -> int` host binding
  (`host_bindings.cc`, mirroring `add_sphere_region`): allocates a region slot with
  `shape = 1`, `half_extents = scale·inv_instance_scale` (same body-unit conversion
  the sphere/cylinder bindings apply), `active = true`, default dim/gain state.
- `engine/renderer.py`: `add_box_region(instance_id, center, half_extents)` wrapper
  added to `_REQUIRED_BINDINGS`.

## 0.3 Python resolve + register

- `resolve_baked_region` gains a `box` branch returning
  `("box", center, half_extents)` — reads `SetGlowRegionScale(i, sx, sy, sz)` as
  half-extents; position defaults to the hardpoint mount; rejects any
  non-positive extent.
- `ShipGlowController._register_baked` dispatches `op[0] == "box"` →
  `self._r.add_box_region(iid, center, half_extents)`.

## 0.4 SPV debug wireframe box

The debug-volume overlay (`set_debug_cylinders` → `DebugVolumePass`) draws only
cylinders. Add a parallel box channel so the SPV can outline a box region:

- `DebugVolumePass` gains a `DebugBox { glm::vec3 center; glm::vec3 ex, ey, ez;
  glm::vec3 color; }` list — `ex/ey/ez` are **world-space half-extent edge vectors**
  (already rotated by the ship's `R`) so the wire box follows ship rotation; the
  pass draws the 12 edges of `center ± ex ± ey ± ez`.
- `set_debug_boxes(boxes)` / `clear_debug_boxes()` host bindings + `engine/renderer.py`
  wrappers; `host_bindings.cc` frame draw calls the box render alongside the
  cylinder render (viewer-mode only, same gate as the cylinders).
- `engine/ui/glow_region_overlay.py` emits a box dict for a `("box", center,
  half_extents)` op: world center via `_body_to_world`, and `ex/ey/ez` =
  `R · (hx,0,0)`, `R · (0,hy,0)`, `R · (0,0,hz)` via `_rotate_dir`·magnitude. The
  overlay returns `(cylinders, boxes)`; host_loop pushes both.

## 0.5 Phase 0 testing

- **Python:** `resolve_baked_region` returns a `box` op for `Box` + `Scale`, and
  `None` for non-positive scale; `_register_baked` calls `add_box_region` for a box
  op (fake renderer records the call); `glow_region_overlay` emits a box dict with
  correct world center + edge vectors for a box region and rotates with `R`.
- **C++ (`FrameTest`):** a box glow region dims the hull inside the box and leaves
  it untouched outside; an empty `u_glow_region_e` (capsule path) renders identically
  to today (guard against a regression in the shared state machine).
- **Gate:** `scripts/check_tests.sh` green (only the 7 baselined FrameTests may
  fail). Live-verify a box region renders in-scene (bake a temporary box on an
  impulse pod, confirm the glow).

---

# Phase 1 — Edit Light UI (all three shapes)

## Approach: full-region replace (chosen)

On Apply, the panel captures the region's **complete** spec — shape, position, axis,
and the shape's size fields — seeded from the subsystem's current baked region 0 (or
a from-scratch default for an unbaked sensor). On Save, the writer **replaces region
0 wholesale** via a new `set_region` operation.

Why full-region replace rather than per-setter edits:
- **Clean shape switches.** Switching Cylinder→Box must drop the now-meaningless
  `SetGlowRegionAxis`/`Extent` and add `Scale`; per-`set_setter` edits would leave
  orphan setters cluttering a file whose whole purpose is being clean and
  deterministic. `set_region` removes all `SetGlowRegion*(0, …)` for the subsystem,
  then writes exactly the setters the chosen shape needs.
- **Preview == saved result by construction.** The live wireframe resolves the
  *pending spec* through the very same `resolve_baked_region` the saved file will be
  read back through.

Position/axis are **preserved, not user-editable** — captured into the spec (from
the existing region, else the hardpoint mount position and a default axis
`(0,-1,0)`) and re-emitted so the region stays coherent. Explicit values in a
machine-owned file are fine (it's exactly what the bake tools emit).

### Setters emitted per shape (region index `i = 0`)

| Shape | Emitted calls (in order) |
|---|---|
| Sphere | `SetGlowRegionShape(0,"Sphere")`, `SetGlowRegionPosition(0,x,y,z)`, `SetGlowRegionRadius(0,r)` |
| Cylinder | `SetGlowRegionShape(0,"Cylinder")`, `SetGlowRegionPosition(0,x,y,z)`, `SetGlowRegionAxis(0,ax,ay,az)`, `SetGlowRegionRadius(0,r)`, `SetGlowRegionExtent(0,aft,fore)` |
| Box | `SetGlowRegionShape(0,"Box")`, `SetGlowRegionPosition(0,x,y,z)`, `SetGlowRegionScale(0,sx,sy,sz)` |

Validation (rejected at the panel, greyed in the UI): `r > 0`; `fore > aft`; each
of `sx, sy, sz > 0`.

## Components

### 1. Writer — `engine/appc/hardpoint_override_writer.py`

Add one pure function:

```python
def set_region(models, leaf, subsystem, index, calls) -> None:
    """Replace all SetGlowRegion*(index, ...) calls for a subsystem with `calls`
    (an ordered list of (setter, args)). Leaves SetRadius and other-index glow
    setters intact. Creates the leaf/subsystem entry if absent."""
```

Removes existing calls where `setter.startswith("SetGlowRegion")` and
`args and args[0] == index`; appends `calls` in order. `emit`/`read_models`
unchanged; `emit` still `ast.parse`-validates.

### 2. Target — `engine/appc/override_routing.py`

`HardpointOverridesFileTarget.write(leaf, edits)` accepts a **mixed** edit list:

- 3-tuple `(subsystem, setter, args)` → `set_setter` (radius path — byte-identical;
  existing test unaffected).
- 4-tuple `(subsystem, "__region__", index, calls)` → `set_region`.

Reload → apply each edit → `emit` → atomic `os.replace`.

### 3. Glow-category + current-spec helpers — `engine/appc/subsystem_glow.py`

- `glow_bearing_subsystem_ids(ship) -> set[int]` — `id()` of every warp pod, impulse
  pod, and the sensor subsystem (reuses `warp_pods`/`impulse_engines`/
  `GetSensorSubsystem`; None-safe; never raises).
- Reuse `baked_glow_regions(prop)` to read region 0's current spec.

### 4. Descriptors — `engine/ui/ship_property_viewer.py`

A post-pass annotates light-bearing subsystems: `"light": True`, and
`"light_region": {shape, position, axis, radius, extent, scale}` from
`baked_glow_regions(...)[0]` when present, else a from-scratch default
(`shape="Sphere"`, `position=_position_tuple(sub)`, `axis=(0,-1,0)`, sensible default
radius). The post-pass re-walks `_iter_subsystems(ship)` in the same order as
`build_descriptors` and zips onto the produced descriptors, skipping object-emitter
mounts (never light-bearing).

### 5. Panel — `engine/ui/ship_property_viewer_panel.py`

- `self._pending_light: dict[int, dict]` — descriptor index → full region spec; reset
  in `open()`/`close()`; added to the `render_payload` snapshot tuple.
- `dispatch_event`:
  - `set_light:<json {"i","shape","radius"?,"aft"?,"fore"?,"sx"?,"sy"?,"sz"?}>` —
    validate index + the shape's fields (reject `r<=0`, `fore<=aft`, any `scale<=0`);
    build the full spec (carry position/axis from the descriptor's `light_region`);
    stage; `self._last_pushed = None`.
  - `save` — build `edits` = radius 3-tuples **plus** light 4-tuples
    (`(name, "__region__", 0, region_spec_to_calls(0, spec))`); route as today; clear
    both pending dicts on success; keep both on failure/unresolved leaf.
- `dirty` (per row), `pending_count`, and `_pending_edits()` count **both**
  `_pending_radius` and `_pending_light`; `pending_count` = distinct dirty descriptor
  indices; a subsystem with both shows a tally of 2.
- Each subsystem row carries `light` (bool) and `light_region` (pending spec when
  staged, else the baked spec) for the context menu + modal pre-fill.
- `pending_light_specs() -> {subsystem_name: region_dict}` for the overlay.
- The selected popover overlays a short staged-light summary into `properties` when a
  light edit is pending (e.g. `light: "Cylinder r0.25 [0,2]"`).

### 6. Live wireframe — `engine/ui/glow_region_overlay.py` + `engine/host_loop.py`

- `build_glow_region_overlay(ship, selected_name, show_all, pending=None) ->
  (cylinders, boxes)`: `pending` maps subsystem name → region spec. For a subsystem
  with a pending spec, resolve **that** spec (Sphere/Cylinder → cylinder wire; Box →
  box wire) instead of `baked_region_ops(prop)`. `pending=None` behaves exactly as
  today (plus the box channel from Phase 0).
- host_loop passes `pending=ship_property_viewer.pending_light_specs()` and pushes
  both `set_debug_cylinders` and `set_debug_boxes`.

### 7. CEF — `index.html` / `js/ship_property_viewer.js` / `css/ship_property_viewer.css`

- **Context menu:** add `Edit Light…`, shown only when the right-clicked row's `light`
  flag is set (seed `spvRowLight[index]` during list render, like `spvRowRadii`;
  toggle the item's `display` in `shipPropertyViewerRowMenu`).
- **Light modal (`#spv-light`), mouse-only** — no typed field:
  - **Shape picker:** three buttons (Sphere / Cylinder / Box); clicking one sets the
    active shape and swaps which stepper rows are visible.
  - **Size steppers** (`[−] value [+]`, mirroring the radius stepper): Sphere →
    `radius`; Cylinder → `radius`, extent `aft`, extent `fore`; Box → `sx`, `sy`,
    `sz` (half-extents).
  - Apply (`shipPropertyViewerLightApply`) fires `set_light:<json>` with the active
    shape + its fields; Cancel closes.
  - Fires `overlay:1`/`overlay:0` like the radius modal so orbit is suppressed; ESC is
    owned by the panel's `handle_key_esc` (unchanged single-owner path).
  - Pre-fill from the right-clicked row's `light_region`.
- **Save bar / confirm modal:** unchanged — light edits flow through `pending_count`
  and the `pending` tally already rendered by the confirm modal.
- CSS: reuse `spv-modal*` / `spv-ctxmenu*`; add a shape-picker button row and
  multi-stepper layout.

## Phase 1 data flow

```
right-click impulse pod row (light=true)
  → context menu shows "Edit Light…"
  → modal pre-filled from row.light_region (Cylinder r0.25 [0,2])
  → pick shape, step size (mouse only)
  → Apply → 'set_light:{i:.., shape:"Box", sx:.., sy:.., sz:..}'
      → panel validates + stages _pending_light[i] = full spec
      → render_payload: row dirty, pending_count=1, popover light summary
      → host_loop passes pending_light_specs() into build_glow_region_overlay
      → orange wireframe updates live (box/cylinder/sphere — all real)
  → "Save changes (1)" → confirm lists "Center Impulse (1)"
  → Save → resolve_override_target(ship).write(leaf,
             [("Center Impulse", "__region__", 0, [<calls>])])
      → set_region rewrites region 0 → emit → atomic write
  → next ship build applies the new glow region
```

## Phase 1 testing

- **Writer (`set_region`, pure):** clean shape switch drops old size setters and
  writes the new shape's; index isolation; creates a block when absent; `emit`
  round-trips to a fixed point after a region edit.
- **Target:** a `__region__` 4-tuple persists a glow edit to a temp file; a mixed list
  (radius 3-tuple + light 4-tuple) applies both; radius-only path byte-identical.
- **Helper:** `glow_bearing_subsystem_ids` returns exactly the warp/impulse/sensor
  ids for a stub ship; None-safe.
- **Panel:** `set_light` stages a full spec and marks dirty; validation rejects
  `fore<=aft`/`r<=0`/`scale<=0`; `save` routes the `__region__` edit and clears;
  `pending_count`/tally count light + radius; close-without-save discards; overlay
  suppression unchanged.
- **Overlay:** a pending Cylinder overrides baked ops; a pending Box yields a box
  wire; other subsystems unchanged; `pending=None` == today.
- **Gate:** `scripts/check_tests.sh` green. **Live-verify** under `--developer` on
  Galaxy: right-click Center Impulse → Edit Light → step radius/extent → Apply (wire
  updates) → switch to Box, step sx/sy/sz (real orange box appears) → Save → confirm →
  inspect the regenerated `_galaxy` block → reload → glow persists.

---

## Risks / out of scope

- **From-scratch region on an unbaked sensor** (only 5 Federation ships bake sensor
  spheres). Handled: `light_region` defaults seed the modal; a Cylinder from scratch
  gets the default axis `(0,-1,0)`. Common case is editing an existing baked region.
- **Explicit position/axis in the file.** Full-region replace writes `Position` (and,
  for Cylinder, `Axis`) even when previously implicit. Intentional — keeps the region
  self-contained and matches the bake tools; the deterministic emit + git history
  absorb the few extra lines.
- **Fifth glow uniform.** `u_glow_region_e` adds one vec4 array per instance; well
  under the uniform budget (`MAX_GLOW_REGIONS = 12`). Capsule/sphere leave it zeroed
  → production path byte-identical.
- **Out of scope:** position/axis *editing*; region indices > 0; live-while-you-step
  preview (Apply-then-preview only); box **orientation** (body-axis-aligned per BC's
  schema); modded-ship target.

## Future work

- Live-while-you-step preview (stream staged specs on each stepper click).
- Position/axis editing and multi-region (index > 0) support.
