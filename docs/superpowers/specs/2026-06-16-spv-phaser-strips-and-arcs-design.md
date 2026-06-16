# Ship Property Viewer — phaser strips & firing arcs

**Status:** design approved 2026-06-16
**Related:** `docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md`,
`docs/instrumented_experiments/hardpoint_handling_research.md`,
`docs/superpowers/specs/2026-05-14-phaser-combat-design.md`

## Goal

Add two debug overlays to the developer-only Ship Property Viewer (SPV):

1. **Phaser emitter strips** — the curved lit-strip geometry each phaser bank
   fires from, drawn in **yellow at all times** while the SPV is open.
2. **Phaser firing arc** — the angular aim envelope of a single bank, drawn as a
   **cyan wireframe boundary** only when that bank's pin is selected.

These let a developer verify, against the rendered hologram, that hardpoint
strip geometry and firing arcs are positioned and scaled correctly.

## Decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| Arc representation | Wireframe boundary (hollow outline of the yaw×pitch envelope) | Unobtrusive; hull/strip stay visible inside |
| Strip scope | Emitter strip only (no mount cross / fwd-up arrows) | Only the real lit-strip geometry; minimal clutter |
| Arc radius | Bank `Length` (faithful), behind a tunable `ARC_RADIUS_SCALE = 1.0` | True to hardpoint data; one-line tune later if too small |
| Strip colour | Yellow `(1, 1, 0, 1)`, always on, all banks | Matches the BC lit-strip look |
| Arc colour | Cyan `(0, 1, 1, 1)`, selected bank only | Distinct from strips; reads over the dark hologram |
| Depth | Depth-test **off** (always visible, like the pins) | Faithful-radius arcs sit on the hull; occlusion would hide them |
| Render mechanism | Reuse the existing `PhaserPass` prism-beam machinery via a dedicated overlay beam buffer | Reuses a tested pass/shader; isolates the overlay from gameplay beams |

### Faithfulness caveat

At radius = `Length` the firing-arc wireframe sits essentially **on** the strip
(the strip is the arc's pitch = 0 slice), and on large ships `Length` can be
small relative to the hull, so the arc may render tiny. This is the faithful
choice; `ARC_RADIUS_SCALE` (default `1.0`) makes it a one-line tune without a
redesign.

## Architecture

```
ship (PhaserBank subsystems)
   │
   ▼
engine/ui/phaser_overlay.py            (new, pure Python, GL-free, tested)
   build_phaser_overlay(ship, selected_name)
     ├─ build_strip_beams(ship)        → yellow beams for ALL banks
     └─ build_arc_beams(bank)          → cyan wireframe for the SELECTED bank
   │  (list of PhaserBeamDescriptor dicts)
   ▼
engine/host_loop.py  (SPV viewer block, already runs while SPV open)
   r.set_spv_overlay_beams(beams)      (clear on open→closed edge)
   │
   ▼
engine/renderer.py  wrapper methods
   set_spv_overlay_beams / clear_spv_overlay_beams
   │
   ▼
native/src/host/host_bindings.cc
   g_spv_overlay_beams  +  set/clear bindings
   frame(): g_phaser_pass->render(g_spv_overlay_beams, …) inside viewer_mode
```

### Why a dedicated overlay buffer (not `g_phaser_beams`)

The gameplay `g_phaser_beams` global is owned by combat. The SPV overlay is a
debug artefact with different lifetime and depth rules. A separate
`g_spv_overlay_beams` keeps the two from contaminating each other and is the
reason the overlay can run depth-test-off without touching combat rendering.

### Render order (inside `viewer_mode`)

`frame()` currently, in `viewer_mode`, skips `render_space` and draws only the
hologram then the pins. New order:

1. Hologram (`g_hologram_pass`) — writes depth.
2. **SPV overlay beams** (`g_phaser_pass->render(g_spv_overlay_beams, …)`),
   depth-test **off**.
3. Subsystem pins (`g_subsystem_pin_pass`), depth-test off (always on top).

The existing `PhaserPass::render` enables depth-test internally; to draw the
overlay depth-off, pass a flag (preferred) or wrap the call with explicit GL
state and restore afterward. Implementation detail for the plan; the contract
is: **overlay beams are not occluded by the hologram hull.**

## Components

### 1. `engine/ui/phaser_overlay.py` (new — pure Python, GL-free, unit-testable)

Builds `PhaserBeamDescriptor` dicts (the format the renderer already consumes
via `set_phaser_beams`). Reuses the Rodrigues arc-sampling math from the
`edbf828` spike's `_build_hp_debug_beams`.

Public functions:

- `build_strip_beams(ship) -> list[dict]`
  Yellow beams for **every** `PhaserBank` on the ship. Per bank: a single arc of
  radius `Length` around the bank's world `Position`, swept across
  `ArcWidthAngles` in the (forward, right) plane around `Up`, sampled in
  `STRIP_SAMPLES` segments and joined by beam segments. This arc is the locus of
  all beam emit points (`ShipSubsystem._strip_emit_position` emits from
  `Position + Length × direction`, using only `Length`), so it *is* the lit
  emitter strip on the hull.

  **No inner rim / end-caps.** An earlier revision drew an inner rim at
  `Length − Width` plus radial end-caps when `Width > 0`. That was removed: the
  SDK `Width` is unused by the emit math and its meaning is unvalidated
  (`docs/instrumented_experiments/hardpoint_handling_research.md`), and on the
  Galaxy (`Width 1.35` vs `Length 1.69`) it drew spurious pie-wedges reaching
  into the saucer centre that correspond to no real emitter geometry.

- `build_arc_beams(bank) -> list[dict]`
  Cyan wireframe of the firing envelope at radius `Length × ARC_RADIUS_SCALE`
  around the bank's world `Position`. Four swept edges, each a polyline
  (`ARC_SAMPLES` segments) because the edges curve on the sphere:
  - pitch = `arc_height_hi`, yaw from lo→hi
  - pitch = `arc_height_lo`, yaw from lo→hi
  - yaw = `arc_width_lo`, pitch from lo→hi
  - yaw = `arc_width_hi`, pitch from lo→hi

  Direction for (yaw, pitch): start from world `forward`; rotate around world
  `Up` by `yaw` (Rodrigues); then rotate around the per-yaw `right` axis by
  `pitch`. Point = world `Position` + radius · direction.

- `build_phaser_overlay(ship, selected_name) -> list[dict]`
  `build_strip_beams(ship)` for all banks, plus `build_arc_beams(bank)` for the
  bank whose `GetName()` matches `selected_name` (a phaser bank). Returns just
  the strips when the selection is `None` or not a phaser bank.

Bank identification: `isinstance(sub, PhaserBank)`, or duck-typed (has
`GetArcWidthAngles` and `GetLength`) so test stubs work without the full type.

World transform: ship rotation (`GetWorldRotation`, column-vector convention)
applied to the bank's body-frame `Direction`/`Up`, world right derived as
`up × forward`; bank world position via `subsystem_world_position(bank, ship)`.

Beam descriptor fields (thin beams): `color`, small `width`, `emitter`,
`target`, `num_sides` (3–4), and the taper/tile fields the renderer expects
(taper effectively disabled). Module constants: `STRIP_SAMPLES`, `ARC_SAMPLES`,
`ARC_RADIUS_SCALE = 1.0`, `STRIP_COLOR`, `ARC_COLOR`, `BEAM_WIDTH`.

### 2. `engine/host_loop.py` — SPV viewer block

The block that already (when `_spv_open`) repoints the camera, hides the hull,
draws the hologram, and pushes pins also:

- Builds overlay beams from the player ship and the panel's selected pin name,
  and pushes them via `r.set_spv_overlay_beams(beams)`.
- On the open→closed edge (where it already calls `clear_subsystem_pins` /
  `clear_hologram_ship`), calls `r.clear_spv_overlay_beams()`.

The panel exposes the selected pin's name (e.g. `selected_descriptor()` →
the descriptor dict, or `None`) so the host can pass `selected_name` without
coupling the overlay builder to pin indices.

### 3. `engine/renderer.py` — wrapper methods

Add `set_spv_overlay_beams(beams)` and `clear_spv_overlay_beams()` wrappers.
Required because `hasattr`-guarded `r.<binding>` calls silently no-op without a
wrapper here (known gotcha from the damage-decals work).

### 4. C++ — `native/src/host/host_bindings.cc` (+ rebuild)

- `std::vector<renderer::PhaserBeamDescriptor> g_spv_overlay_beams;`
- `set_spv_overlay_beams(beams)` / `clear_spv_overlay_beams()` bindings,
  mirroring `set_phaser_beams`.
- Clear `g_spv_overlay_beams` in the shutdown/reset path alongside the other
  SPV globals.
- In `frame()`'s `viewer_mode` branch, render `g_spv_overlay_beams` through
  `g_phaser_pass` between the hologram and the pins, depth-test off.

Touches `host_bindings.cc` → needs a `dauntless` rebuild (compiled into both the
binary and `_dauntless_host`). Shader changes are not involved.

## Error handling

- Bank missing arc angles or `Length <= 0` → that bank contributes no strip /
  no arc; other banks unaffected.
- Selection not a phaser bank (or `None`) → strips only, no arc.
- Headless / no host / missing binding → `hasattr`-guarded push is a silent
  no-op; the pure-Python builder still runs and is testable.
- SPV closed → overlay cleared; production (non-`--developer`) render path is
  byte-identical because the panel is never constructed and the viewer block
  never runs.

## Testing

Unit tests on `engine/ui/phaser_overlay.py` (pure Python, no GL):

- **Strip on arc:** every strip outer-rim endpoint lies at distance `Length`
  from the bank world `Position` (within tolerance).
- **Strip is outer-arc only:** a bank with large `Width` still yields exactly
  `STRIP_SAMPLES` arc segments, all at radius `Length` (no inner rim / caps).
- **Strip sweep:** the rim spans `ArcWidthAngles` (first/last sample at the lo/hi
  yaw bounds).
- **No Width geometry:** `Width` adds no inner rim or caps; the strip is the
  outer arc regardless of `Width`.
- **Strip colour:** strip beams are `STRIP_COLOR` (yellow).
- **Arc edges:** arc wireframe has 4 edges; all vertices lie at radius
  `Length × ARC_RADIUS_SCALE`; the envelope is bounded by the yaw/pitch angles
  and centred on `forward`; colour is `ARC_COLOR` (cyan).
- **Bank identification:** only `PhaserBank`s (or arc-capable duck types)
  produce strips; non-weapon subsystems produce none.
- **Selection:** `build_phaser_overlay` emits an arc only for the bank whose
  name matches `selected_name`; `None`/non-phaser selection → strips only.

No automated GL/visual test (consistent with the rest of the renderer); visual
confirmation is manual: launch `./build/dauntless`, open the SPV, observe yellow
strips on all banks and a cyan arc when a phaser pin is selected.

## Out of scope

- Filled/translucent arc surfaces and radial-spoke arc styles (rejected in
  favour of the wireframe boundary).
- Mount-position crosses / forward-up arrows (the old calibration markers).
- Arc/strip overlays anywhere outside the SPV (gameplay scene unaffected).
- Tuning `ARC_RADIUS_SCALE` away from `1.0` (left faithful; tunable later).
