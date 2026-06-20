# Map-Driven Starsphere — Design

**Status:** design approved, pending implementation plan
**Branch:** continues from `feat/procedural-starfield` (reuses its shader/pass)
**Related:**
- [`docs/sector-cartography.md`](../../sector-cartography.md) — the sector model this consumes
- [`2026-06-20-procedural-starfield-design.md`](2026-06-20-procedural-starfield-design.md) — the procedural shader/pass this reuses

## 1. Summary

Render the in-game sky as a **view of the 3D sector model** rather than as each
system's hand-authored backdrop spheres. One persistent galaxy model drives the
sky from every vantage: at Vesuvi the Vesuvi nebula envelops you; from a
neighbouring system it appears as a sized patch in Vesuvi's true direction;
distant features shrink to faint smudges. The cartography map and the sky become
the **same spatial model**.

This swaps the **front of the procedural pipeline** (where backdrop descriptors
come from) and **reuses the procedural shader, pass, and descriptor contract**
built in the procedural-starfield phase.

## 2. Goals & non-goals

**Goals**
- The sky is a spatially-consistent, persistent view of the sector model.
- A system's own nebula (incl. gameplay `MetaNebula`, e.g. Vesuvi) is finally
  visible in its own sky — enveloping when you're at it.
- Whole-galaxy coverage: every modelled feature projects, distance-scaled.
- Reuse the procedural shader/pass/appearance work unchanged.
- Stock-BC faithful fallback preserved (toggle off).

**Non-goals (explicitly out of scope)**
- **Ship-position parallax / realistic-scale space** — the sky is per-system
  **camera-anchored** (rotates with view, does not translate as the ship moves
  within the local combat scene). Continuous ship-parallax is the deferred
  Phase 3 (`docs/sector-cartography.md` §7).
- Gameplay, mission behaviour, object placement, local combat scenes — untouched.
- A third "authored-procedural" sky mode — retired (see §3).

## 3. Design decisions (resolved during brainstorming)

| Fork | Decision |
|---|---|
| Vantage model | **Per-system, camera-anchored.** Vantage = the current system's position in the sector model; sky doesn't parallax with local ship movement. |
| Mode structure | **Two modes.** Toggle ON → map-driven sky; OFF → byte-identical stock BC. The authored-backdrop *procedural sourcing* is retired; its **shader is reused**. |
| Coverage | **Whole galaxy, distance-scaled.** Every modelled feature projects; near ones large, distant ones faint. |
| Near-field | A nebula whose distance < its radius (the system's own) **envelops the full sphere**; otherwise it's a directional patch. |

## 4. Architecture & data flow

Almost entirely a **Python** change; the C++ shader/pass are reused (one small
shader addition for the near-field case).

When the procedural toggle is **ON**:

1. **Sector model (baked data).** Productionize the PoC extractor
   (`poc/extract_map.py`) into a build step emitting a committed
   `sector_model.json`: systems (`id → position`), nebulae (`position, radius,
   colour, proc_kind`), star-clouds/galaxies (`position, size, colour`). One
   model, read by both the 2D map and the sky.
2. **Vantage lookup.** From the active `pSet`'s region module
   (`"Systems.Vesuvi.Vesuvi6"` → system `vesuvi`, synthetic systems like
   `tauceti` mapped) → the system's 3D position = the vantage.
3. **Projection aggregator** (new; replaces authored-backdrop sourcing). For the
   vantage, walk every model entity → a backdrop descriptor (`world_rotation`
   from the projected direction, `span` from apparent size, recorded
   `colour`/`proc_kind`). Always also emit one full-sphere base-starfield
   descriptor.
4. **`set_backdrops` → shader/pass** — unchanged; renders the projected
   descriptors as today.

When the toggle is **OFF**: the existing `aggregate_for_renderer` texture path
runs (stock BC), untouched.

**Frame convention:** sector-model axes *are* world axes (identity). Positions
are inferred/artistic and each local set has an arbitrary orientation, so there
is no canonical frame to reconcile — directions are correct *relative to the
persistent model*, which is the point.

## 5. Projection math

For each entity, from the vantage `v`. "Extent" below means the entity's
`radius` (nebulae) or `size` (star-clouds) — both feed the apparent-size and
near-field math identically.

- **Direction:** `d = normalize(pos − v)`; build `world_rotation` as an
  orthonormal basis with forward = `d` (AlignToVectors-style).
- **Apparent size:** angular radius `θ = atan(extent / distance)`, mapped to
  `span` via a global scale constant. Near → large; far → small.
- **Distance falloff:** brightness/alpha decreases with distance; a far cutoff
  fades the most distant features toward faint smudges/points, giving depth
  without a wall of fog.
- **Colour / kind:** taken from the model (`proc_kind`, recorded colour) so
  nebulae render as nebulae (with nurseries), star-clouds as Milky-Way dust.

**Near-field / enveloping.** When `distance < extent` (the system's own nebula
sits at the vantage), `extent/distance` blows up and the nebula switches to a
**full-sphere enveloping render** (like the star sphere — no angular discard,
fills the dome), density ramping up the deeper in you are. This is the **one
C++ shader addition**: a full-sphere nebula branch (the far-patch math already
exists). At Vesuvi the Vesuvi nebula surrounds you; from a neighbour it's a
sized patch in Vesuvi's direction — one model, two read-outs.

**Base starfield:** one always-emitted full-sphere `proc_kind = 0` descriptor
(the real distant stars, with the existing density-drift variety); projected
features layer on top.

## 6. Modes, faithfulness, persistence

- Reuse `procedural_sky_set_enabled`: **ON → map-driven, OFF → stock BC**
  (byte-identical, faithful path untouched).
- The host loop selects the backdrop source by the toggle: projection aggregator
  when on, `aggregate_for_renderer` texture path when off.
- Persistence is automatic: one `sector_model.json` read from every system, so a
  feature occupies the same world position everywhere.

## 7. Components (isolated units)

| Unit | Location | Responsibility | Depends on |
|---|---|---|---|
| Sector-model bake | `tools/bake_sector_model.py` (from `poc/extract_map.py`) | SDK → `sector_model.json` | SDK, Pillow (bake-time) |
| Sector model | committed `engine/appc/sector_model.json` | persistent galaxy positions/sizes/colours | — |
| Vantage lookup | `engine/appc/sky_projection.py` | set region module → system id (synthetic-aware) → position | sector model |
| Projection aggregator | `engine/appc/sky_projection.py` | `(vantage, model) → descriptors` (pure) | sector model |
| Host-loop wiring | `engine/host_loop.py` | choose source by toggle | toggle |
| Enveloping shader branch | `native/src/renderer/shaders/backdrop.frag` | near-field full-sphere nebula | embedded at build |

**Reminder:** shader edits require a `cmake -B build -S .` reconfigure before
`cmake --build` (embedding headers regenerate at configure time).

## 8. Data contracts

**`sector_model.json`:**
```jsonc
{
  "systems":    [{ "id": "vesuvi", "position": [x,y,z] }],
  "nebulae":    [{ "position": [x,y,z], "radius": r, "color": [r,g,b], "proc_kind": "nebula" }],
  "starclouds": [{ "position": [x,y,z], "size": s,   "color": [r,g,b] }]
}
```
(colours 0–1 floats; positions in sector units.)

**Backdrop descriptor:** unchanged shape from the procedural-starfield phase
(`kind, world_rotation, h_span/v_span, color, coverage, seed, proc_kind`, plus
the existing texture fields, unused on the procedural path). The projection
aggregator builds `world_rotation` from the entity direction.

## 9. Testing

- **Deterministic (Python):** bake output shape; vantage lookup (known
  set→position, synthetic mapping, unknown→graceful fallback); projection
  aggregator (direction/span correct for a hand-built model + vantage; near-field
  flag when `distance < radius`; far falloff; determinism).
- **Visual (FrameTest, C++):** enveloping nebula fills the sphere in the
  near-field; a far nebula renders as a sized patch in its direction; toggle-off
  is byte-identical stock BC.

## 10. Edge cases & error handling

- Unknown / unmapped system → **fall back to stock backdrops** for that set
  (never blank the sky).
- System with nothing modelled nearby → just the base starfield.
- Toggle off → stock BC, byte-identical (regression guard).
- Near-field continuity: the patch→envelope transition must not pop (ramp across
  `distance ≈ radius`).
- Performance: ~15–20 features + base starfield = a tiny descriptor list; cheap.

## 11. Cleanup

The procedural fields added to `aggregate_for_renderer` in the procedural-starfield
phase (`proc_kind`/`color`/`coverage`/`seed`) become **unused** once the
projection aggregator supplies descriptors — note as vestigial; remove in this
phase if trivial, otherwise leave for a later tidy.

## 12. Future (out of scope)

- **Phase 3:** ship-position parallax / unified realistic scale + dynamic warp
  (floating-origin precision, mission rescaling).
- Rigorous nebula placement (bearing triangulation) feeding the sector model.
- Suns/planets projected from the model (this phase: nebulae/clouds/stars).
