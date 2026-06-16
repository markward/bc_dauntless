# Voxel Hull-Damage Foundation — Design

**Date:** 2026-06-16
**Status:** Design approved, ready for implementation plan
**Scope:** Spec #1 of 2. This spec covers the **voxel foundation** — decode, voxelize, validate. The runtime damage renderer (carve, remesh, shading, debris) is a **follow-on spec** built on this foundation.

## Motivation

Bridge Commander physically removes hull geometry during combat: chunks and holes that change a ship's silhouette, exposing a chunky interior fill (observed directly in stock-game screenshots of a destroyed Galaxy — decomposed in "Visual target reference" below). This is *not* a texture overlay — the original engine voxelizes each hull into a solid volume and carves it.

Every ship ships a `<ship>_vox.nif` (e.g. `Galaxy_vox.nif`, ~150 KB) containing `NiBinaryVoxelExtraData` → `NiBinaryVoxelData` — a solid voxel grid. Critically, **BC generates these volumes at runtime for ships that lack them** (the modding community's long-standing understanding), so the shipped files are cached outputs of BC's own voxelizer. To run BC mods (the project's compatibility goal) we must voxelize unknown hulls ourselves, not merely read shipped files.

Prior tessellation/displacement experiments produced soft "dents," never the sharp breaches BC shows. BC's authentic look is **voxel-chunky**, so reusing its voxel volume — and going modern only on the *rendering* of that volume — is both more faithful and more achievable than smooth-mesh deformation.

## Faithful vs. modern — where the line sits

- **Faithful = the data and carve semantics.** Same per-ship voxel volume, same data-driven carve the original `AddDamage` fed.
- **Modern = how we turn the carved volume into pixels.** BC splatted raw voxel cells (the colorful chunky speckle is the 2001 limitation). The follow-on renderer replaces that with SDF + sharp-feature surface extraction + modern shading.

This foundation spec produces the **faithful volume**. The renderer spec spends the modern budget.

## Goal

Any ship NIF → a correct **solid voxel volume**, by two independent paths that validate each other:

1. **Decode** a shipped `<ship>_vox.nif` into the volume.
2. **Voxelize** the ship's hull mesh into the volume.

When both paths agree on the Galaxy, we have recovered BC's voxelization and can trust the voxelizer for ships (mods) that ship no vox file.

## Non-goals (this spec)

- Runtime carving, SDF remeshing, interior/rim shading, debris — all **renderer spec**.
- **Encoding** to BC's byte format. We never write `<ship>_vox.nif`; option 1 (volume-only, our representation) was chosen. We do not expect anyone to port our volumes back to original STBC.
- SDF representation. The foundation stores **binary occupancy** (matches BC's grid; makes the validation diff exact). SDF derivation is a renderer-spec consumer concern.

## Components

### 1. `VoxelVolume` (the shared output type)

A value type produced by both decode and voxelize, consumed by the renderer spec:

- `dims`: grid resolution `(nx, ny, nz)`
- `bounds`: world-space origin + cell size (the mapping from voxel index to hull body-frame position)
- axis/origin convention (recovered from decode; documented explicitly)
- `occupancy`: packed bit-grid, 1 = solid, indexed `[x + nx*(y + ny*z)]` (exact order confirmed against decode)

Binary, not SDF — BC's grid is binary, and the validation diff must be bit-exact.

### 2. Decoder (`NiBinaryVoxelData` → `VoxelVolume`)

Extends `native/src/nif/src/blocks/extra_data.cc`, replacing the opaque `raw_voxel_payload` capture with a real decode. Working hypotheses (confirm against `Galaxy_vox.nif`):

- 3 leading `uint16` → grid dims `(nx, ny, nz)`
- 7 `float` → bounds (origin + extent/cell size; exact packing TBD)
- payload → RLE/bit-packed occupancy

niflib's auto-generated schema is documented as *not* matching real BC v3.x files, so the encoding is reverse-engineered empirically. The decode-vs-voxelize diff (§4) is the lever that cracks it: a known output file constrains the format.

### 3. Voxelizer (hull NIF → `VoxelVolume`)

1. Walk the NIF node tree, gather every `NiTriShapeData` (`vertices` + `triangles`, `block.h:165`) with its accumulated world transform → one triangle soup in hull body frame.
2. Choose grid resolution by **BC's recovered rule** (from §2) — not an arbitrary resolution. Hole granularity is a function of voxel resolution; matching BC's is what makes breaches read as authentic, and it gives stock and mod ships a consistent look from one rule.
3. **Solid-voxelize** via **flood-fill-from-outside-then-invert**: flood exterior-empty from the bounding-box corners; everything unreached = solid. This robustly fills the interior (the "guts" we want) and tolerates small surface leaks, where ray-stab parity would fail on BC's non-watertight hulls. Leak behavior (windows, hangar mouths) is tuned against the oracle.

### 4. Validation (the gate)

Voxelize the Galaxy hull, decode `Galaxy_vox.nif`, diff the grids.

- **Metric:** per-voxel agreement / IoU on the solid set.
- Iterate voxelizer rules (resolution, fill, axis/origin) until agreement is high.
- This is the deliverable's pass/fail and the proof we recovered BC's algorithm.

### 5. Code layout

- **Decoder:** extend `native/src/nif/src/blocks/extra_data.cc`.
- **`VoxelVolume` + voxelizer:** new module `native/src/voxel/` (neither pure NIF parsing nor scenegraph).
- **Debug viz + Python binding:** dump a volume as points so decode and voxelizer output can be eyeballed during RE. (Respect the build single-source-of-truth and `host_bindings.cc` → `dauntless` rebuild rules.)

### 6. Testing

- Decoder: against a captured `Galaxy_vox.nif` fixture — golden dims/bounds, spot-checked voxels.
- Voxelizer: determinism; a known watertight cube → exact expected fill.
- Integration: Galaxy IoU threshold (decode vs. voxelize).

## Risks

- **Undocumented payload encoding** — may resist decoding. Mitigation: the decode-vs-voxelize diff constrains it from both ends.
- **BC's leak-handling heuristic** — non-watertight solid-fill may need several iterations to match the oracle.
- **Resolution rule** — if BC scales resolution per-ship rather than fixed, the rule must be recovered exactly so mod ships match.

---

## Visual target reference (for the follow-on renderer spec)

Close analysis of the reference screenshot (destroyed Galaxy) decomposes the damage into distinct ingredients. This is **not** implemented in the foundation; it defines the renderer spec's targets. None of it changes the foundation (the same solid volume serves all of it).

**Observed ingredients:**

1. **Major breach** — reads as *two adjacent lobes* (a chunk broke in pieces); silhouette genuinely gone; visible inward depth; **irregular, blocky (voxel-stepped) boundary**.
2. **Interior fill = colorful chunky speckle** — dense granular field of *multicolored* per-cell specks (reds, magentas, cyans, greens, yellows, whites). Confirms raw-voxel-splat with arbitrary per-cell color — reads as "data," not "ship interior."
3. **Charred ragged rim** — blackened, jagged edge framing the bright interior.
4. **Multi-scale breaches** — a few large + many small torn gouges (saucer, dorsal/neck).
5. **Second, warm damage flavor** — starboard nacelle/pylon shows red/orange streaks + reddish glow. Distinct **emissive** treatment vs. the cold multicolored breaches.
6. **Global destroyed-state darkening** — whole hull unlit; aztec readable underneath (separate concern).

**Reproduce — and exceed:**

| Element | BC (2001) | Our reproduction | "Better" opportunity |
|---|---|---|---|
| Hole + silhouette + depth | voxel carve, blocky rim | voxel carve + dual-contour remesh → real geometry | sharper *or* cleaner torn edges, controllable |
| Interior fill | random multicolored voxel splat | sample the volume for the cavity | **biggest win:** believable interior (decks, ribs, conduits, sparks) with a **"Classic colored-voxel" toggle** to reproduce the original exactly |
| Charred ragged rim | blackened voxel edge | extruded torn-metal rim geometry at the breach boundary | bent/peeled plating, thickness, scorch gradient |
| Multi-scale breaches | size ∝ damage | carve radius ∝ hit strength | finer small-hit detail |
| Warm emissive damage | red streaks/glow | emissive hot-edge + glowing exposed conduits, HDR bloom (Modern VFX HDR toggle) | molten cooling-over-time embers (cf. shipped decal embers) on breach rims |
| Scorch around breaches | — | **reuse shipped decal system** as a scorch ring per breach | already built; wire it |
| Destroyed darkening | global dim | destroyed-state shading | separate concern |

**Two damage flavors, not one:** cold **structural breach** (carve + interior + torn rim) and warm **emissive damage** (glowing exposed/molten areas). The renderer spec must handle both. The scorch ring is free (existing decals). The interior fill is the main faithful-vs-better decision — proposed default: render a real interior with a "Classic colored-voxel" toggle under Modern VFX, so we exceed by default but reproduce the original exactly on demand.
