# Hull Breach Renderer — 2b (Dual-Contouring Breach Interior) — Design

**Date:** 2026-06-17
**Status:** SHIPPED via **Path C** (see REFRAME 2 below). In-game confirmed on the Galaxy: scoop aligns with the hole, no whole-hull erosion, no poke-out, genuine see-through breach-through, triplanar `Damage.tga` reads on the carved wall. The dual-contouring approach (Path A/B below) was abandoned for rendering; the `voxel::dual_contour` library remains (tested) but is unused by the render path.
**Scope:** Spec 2b of the hull-damage renderer. One feature: replace 2a's see-through breaches + flat colored-cube splat with a real **dual-contouring interior surface** built from BC's voxel data — sharp hull-facet cross-sections, no see-through. Builds on the merged 2a and the now fully-decoded vox format.

## Motivation

2a opened see-through holes but left two problems: (1) a breach reveals straight through the single-sided ship to stars (no interior surface), and (2) the interior is a flat candy-rainbow cube splat. The fix is the **runtime voxel remesh** this whole approach was named for, now unblocked: BC's `*_vox.nif` is fully decoded, including the **0–127 scalar fill field**, the **deduplicated plane palette** (Hesse-form `(n̂,d)` surface orientations), and the **`bytes2` index tree** mapping each fill cell to its palette plane. That is exactly the Hermite data dual contouring needs to reconstruct **sharp hull facets** — the authentic look (BC was smooth-with-hard-corners, not blocky). Reference: `docs/engine/nibinaryvoxeldata-format-v3.1.md`.

## REFRAME 2 (in-game verification, 2026-06-17): render the INSIDE of the volume, not the outside — Path C

The dual-contouring approach below (Path B) extracted the **outer boundary surface of the carved volume** and tried to make *that* stand in for the hull. In-game this was wrong on two counts, confirmed by Mark:

1. **The coarse voxel fill is fatter than the hull.** Voxelizing a smooth mesh at 15-GU cells inflates the solid region by up to a cell, so the DC surface always sits ~1 cell *outside* the real hull. No nudge/inflation/clip can reconcile a fattened proxy with the hull mesh — the cavity poked out past the hull, and clipping the hull *by* the fill eroded thin features.
2. **BC never rendered the volume's outer surface.** It cut a hole and rendered the **inside of the volume exposed within the damage radius** — a recessed scooped cross-section seen *through* the hole.

**Path C (the corrected, faithful model).** The **damage radius (sphere) is the single primitive**; the **fill is a material mask**, not a surface to extract:

- **Hull hole** — pure damage-sphere fragment clip in `opaque.frag`: discard a hull fragment iff it is inside *any* active carve sphere. (This is exactly the 2a sphere clip, which worked. No fill sampling in the hull clip.)
- **Interior scoop** — for each active carve sphere render its **inner (far) wall**, masking each fragment by the **original (uncarved) fill**: keep the fragment iff `fill(p_body) ≥ iso` (solid material there), else `discard`. The in-material arc of the sphere is the exposed bowl; where the sphere passes back out of solid (far side of a thin hull, or the half that's out in space) the mask discards → genuine see-through breach. Render **back faces** (cull front) so the wall is recessed and **cannot poke out**; depth-test against the already-drawn hull so the scoop shows *only* through the hole. Triplanar `Damage.tga`, muted (reuse the 2a/`breach.frag` shading).
- **Alignment is by construction** — the same sphere defines the hole *and* the scoop extent, so they cannot mismatch. The fill no longer needs to coincide with the hull (it's only a "is there ship material here?" mask).
- **Progressive deepening** — repeated/overlapping hits at a spot merge in the carve field → larger/deeper scoops → the indentation pushes further back, eventually punching through. (Matches the intended damage model.)

**What this removes:** the DC mesh from the render path (dual-contouring code stays, tested, just unused by the breach pass), the *carved*-fill 3D texture and its carve-version cache (the mask is the **static original fill**, built once per hull), and the fill-based hull clip.

**v1 surface = smooth spherical scoop.** Reproducing BC's grittier chunky/voxel-faced interior is a fast follow-on if the smooth bowl reads too clean in-game; start smooth to get alignment + masking right first.

## Approach (superseded by REFRAME 2 — kept for history)

Dual contouring on the interior-node lattice:
- **Scalar field** = the 7-bit fill (0–127); **isovalue ≈ 63–64** is the surface.
- For each cell straddling the isosurface, fetch its palette plane(s) via the `bytes2` tree → Hermite data (`point = d·n̂`, `normal = n̂`); solve a per-cell **QEF** → one vertex snapped to the intersection of the hull's flat panels (sharp edges/corners); stitch quads across crossing edges.
- **Carve** subtracts a smooth falloff from a per-instance copy of the fill (smooth cut), then we re-extract the affected region.
- The extracted **interior surface** renders through the 2a fragment-clip holes, interior-shaded (muted), depth-tested so it shows only through breaches. It **replaces** 2a's colored-cube splat.
- The original NIF hull (exterior, fragment-clipped) is unchanged — we only build the interior cavity, so no loss of hull detail.

## REFRAME (cleanroom round 3): no head-tree needed — Path B

The `bytes2` head-tree descent (cell→authored-plane index) turned out hard (records are **face-octant-major**, not lexicographic) AND **unnecessary**. The cleanroom confirmed two self-contained routes that skip it; we take **Path B: re-extract our own dual-contouring surface from the decoded fill + plane palette.** Per surface cell, the Hermite plane comes from the **nearest palette plane(s) by point-to-plane distance** (`|n̂·p − d|` minimal — the discriminating metric; the earlier *gradient-normal* matching failed only the byte-exact anchor gate, which we no longer target). This (a) gives sharp flat-panel cross-sections, (b) needs no tree and no leaf order, and (c) is the **same code that generates `_vox` for mod ships** (decode-existing and generate-new share one extractor). The head-tree descent is now a deferred *nice-to-have* (byte-faithful reads of the 84 originals only).

## Components

### 1. ~~`bytes2` tree reader~~ → Nearest-palette-plane matching (Path B)
No tree parse. The plane palette (decoded, §5) + the fill scalar field are enough. For each surface cell, select the palette plane(s) the cell's surface point lies on (`|n̂·p − d|` minimal), giving the sharp Hermite normal(s) for the QEF. Validation is the Galaxy IoU + eyeball, **not** byte-exact anchors.

### 2. Source surface data (extends `SourceVolumeCache`)
Per model, alongside the fill volume: the **plane palette** and a **cell→plane resolver** (the tree reader). Decoded once per model, shared (immutable).

### 3. Dual-contouring extractor (NEW, the core)
`extract(scalar fill, cell→plane resolver, isovalue) → mesh (positions, normals, indices)`. Standard DC: per straddling cell, gather the cell's plane constraints, solve the QEF (with a safe fallback to the mass-point when the system is degenerate/under-constrained), emit one vertex; for each sign-changing edge shared by 4 cells, emit a quad. Normals from `n̂`. Pure, CPU, unit-testable.

### 4. Carved scalar field (extends 2a carve)
Per-instance mutable copy of the fill; a hit subtracts a smooth radial falloff inside the carve sphere (clamped at 0), giving a smooth cut surface. (2a stored carve spheres only; 2b needs the carved scalar volume.) Re-extract the dirty region after a carve.

### 5. Breach interior render (replaces 2a breach pass)
Render the extracted interior mesh through the clipped holes: depth-test ON, lit by the DC facet normals, so it reads as a solid breached cross-section and is visible only through breaches. The 2a colored-cube splat is removed.

**Texturing — triplanar `Damage.tga`.** The DC mesh is generated geometry with **no UVs**, so it's textured by **triplanar projection** (project down the 3 body-space axes, blend by the facet normal). Content is BC's own **`game/data/Textures/Effects/Damage.tga`** (the texture the original used for damaged-interior shading) — muted (folding in the tone-down). The DC facet normals make the projection read as clean panels with blended edges. (A subtle emissive ember accent at deep/recent cuts is a later option; a fully-procedural material is the fallback if `Damage.tga` reads poorly.)

### 6. Tone-down (folded in)
Reduce breach size/frequency (the 2a `hull_carve.py` knobs) and use the muted interior shading above — addresses the "too strong" + candy-color feedback as part of this work, not a separate effort.

## Validation (plan ordering, not a sub-spec)
The extractor is the novel risk, so the plan **builds and validates it first** on static (uncarved) data before wiring carve/render: extract the uncarved Galaxy surface and confirm it reproduces the hull (IoU vs the hull-mesh voxelization + a debug OBJ dump to eyeball sharp facets). Only then: carve, re-extract, render. This is the same "prove the core before integrating" discipline used for the decoder — sequenced inside one plan.

## Testing
- **Pure (gtest):** `bytes2` tree reader against the cross-reference anchors (cell (13,4,0) → palette[2247], etc.); QEF solver on synthetic plane sets (a known corner → the corner vertex); the extractor on a synthetic fill+planes (a cube/wedge → expected sharp mesh).
- **Real-data (gtest, GL-skip):** extract uncarved Galaxy → IoU vs hull voxelization above a threshold; debug OBJ dump.
- **Manual (in-game, Mark drives):** breach a Galaxy → solid sharp-faceted interior cross-section, no see-through; muted palette; toned-down size.

## Risks
- **QEF degeneracy** (cells with too few/parallel planes) → fallback to mass-point/clamped vertex; bound the vertex to its cell.
- **Coarse grid** → DC + sharp planes should hold facets, but a breach a few cells wide may still be low-detail; judge in the manual check (upsampling is a later option).
- **Re-extract cost on carve** → extract only the dirty brick around the carve, not the whole ship.

## Non-goals (2b)
- **`bytes2` *writer* / `_vox.nif` regeneration** for mod ships — the read/extraction path is enough for stock ships; the writer needs a round-trip diff and is deferred (mod ships keep the 2a voxelizer fallback for now).
- **Debris / cooling embers** — 2c.
- **A classic-cube vs modern toggle** — dropped; DC is the interior. (2a's cube splat is removed, not toggled.)
- Any change to the stock render path when the Hull-breaches toggle is off.
