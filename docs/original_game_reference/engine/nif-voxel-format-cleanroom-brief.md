# Cleanroom request: `NiBinaryVoxelData` on-disk format (NetImmerse v3.1)

**What we need:** a written **specification** of how `NiBinaryVoxelData` (and its
companion `NiBinaryVoxelExtraData`) are **serialized to disk** in NetImmerse
File Format **Version 3.1**, complete enough that an engineer with no SDK access
can write an independent reader/writer from your description alone.

**Cleanroom constraint (important):** Please describe the format as a
**specification** — field-by-field layout tables, encoding rules, and read/write
procedure in neutral pseudocode. **Do not paste verbatim SDK source code.** We
will implement from your spec independently. Citing the SDK class name and
version your spec is derived from (for provenance) is welcome; copied code is not.

---

## Context (minimal)

We are building a clean, independent reimplementation of the engine behind a
2001 game that used NetImmerse. Its model files are NetImmerse v3.1 NIFs
(header string: `NetImmerse File Format, Version 3.1` / `Numerical Design
Limited, Chapel Hill, NC 27514 / Copyright (c) 1996-2000`). Alongside each ship
model `X.nif` the game ships `X_vox.nif`, a voxelization of that hull used for
collision and for rendering battle-damage "guts." We need to decode these
volumes (and, separately, regenerate them for new models that lack one — the
original runtime generated them on demand).

Each `*_vox.nif` contains exactly three blocks:
1. `NiBinaryVoxelExtraData` (root)
2. `NiBinaryVoxelData`
3. `End Of File` sentinel

---

## What we have already recovered (please confirm or correct)

### `NiBinaryVoxelExtraData`
After the block-type string + link id, three `uint32`:
`next_extra_data_link` (always 0 in samples), `unknown_int` (always 0),
`data_link` (→ the `NiBinaryVoxelData` block). **Q: what is `unknown_int`?**

### `NiBinaryVoxelData` header — believed SOLVED
Immediately after the block-type string + link id:

| Offset | Type     | Field      | Our interpretation                       |
|--------|----------|------------|-------------------------------------------|
| +0     | `u16`    | nx         | grid resolution (cells) in X              |
| +2     | `u16`    | ny         | grid resolution (cells) in Y              |
| +4     | `u16`    | nz         | grid resolution (cells) in Z              |
| +6     | `f32`    | cellSize   | cubic cell edge length (world units)      |
| +10    | `f32`×3  | aabbMin    | grid bounding-box min corner (x,y,z)      |
| +22    | `f32`×3  | aabbMax    | grid bounding-box max corner (x,y,z)      |
| +34    | bytes    | payload    | opaque voxel data, runs to EOF sentinel   |

Validated across **all 62** sample files: `round((aabbMax[i]-aabbMin[i]) /
cellSize) == n[i]` for each axis. Example (largest capital ship):
`dims=(31,43,10), cellSize=15.0, min=(-232.5,-322.5,-75.003),
max=(232.5,322.5,74.997)` → span `(465,645,150)/15 = (31,43,10)` ✓, and the box
encloses the hull mesh AABB snapped outward to whole cells. `cellSize` is
**per-file** (observed 15/25/30/50/85/100), scaling with object size.

**Please confirm this header layout, OR correct it** (especially: are there
fields we've folded into "payload" that are really named header fields — e.g. a
secondary/finer resolution, a flags word, or counts?).

---

## What we could NOT decode — the payload (the real ask)

The payload is **1–3 orders of magnitude larger** than the coarse cell count, so
it is clearly **not** one occupancy bit per `(nx,ny,nz)` cell:

| File      | dims      | coarse cells | payload bytes | payload ÷ (cells/8) |
|-----------|-----------|--------------|---------------|----------------------|
| Galaxy    | 31×43×10  | 13 330       | 152 430       | 91×                  |
| Sovereign | 16×47×6   | 4 512        | 127 790       | 227×                 |
| Shuttle   | 2×2×1     | 4            | 17 683        | 17 683×              |
| DryDock   | 62×95×35  | 206 150      | 529 004       | 21×                  |

Observed structure inside the payload (from hex/entropy analysis):
- **A leading bit-run region** whose bytes form a smoothly widening-then-
  narrowing set-bit mask — looks like a **bit-packed occupancy slab of a convex
  cross-section**. It does not start at payload offset 0 and is not the whole
  payload.
- **IEEE-754 float vectors**, many of unit magnitude (**normals?**), interleaved
  with vectors whose components lie inside the grid AABB (**positions?**).
- **A structured tail** of mixed `u32`/`u16` records with recurring indices in a
  range near (but not equal to) the cell count — reads like a **sparse
  index/value table**.
- ~26–31% of bytes are `0x00`; all 256 byte values occur; `0xff` is rare.
- The publicly-circulated auto-generated schema (3×`u16` + 7×`f32` + 7×12 opaque
  bytes + `numVectors:u32` + `Vector4[]` + `numBytes2:u32` + `byte[]` + 5×`u32`)
  **does not parse**: the `numVectors` `u32` reads as garbage at the expected
  offset. Treat it as a hint that float-vector and byte sections exist, not as
  the layout.

### Specific questions
1. **Exact serialization order** of `NiBinaryVoxelData` for NIF **v3.1** — the
   full ordered field list with types, from the first header byte to the end of
   the block. (A `Load`/`Read`-equivalent field walk, described in prose/pseudocode.)
2. **Finer resolution:** the coarse `(nx,ny,nz)` is far too small to explain the
   payload size. Is each coarse cell **subdivided** (e.g. fixed 8³/16³ bricks),
   or is there an **independent fine grid resolution** stored in the payload? If
   so, where and how is it encoded? *(This is our single biggest unknown — the
   payload size cannot be predicted from the header without it.)*
3. **Occupancy encoding:** bit-packed or RLE? At what resolution? **Bit order**
   within a byte (LSB- or MSB-first) and **axis traversal order** (is the linear
   index `x + nx*(y + ny*z)`, i.e. X-fastest, or some other order)?
4. **Float-vector records:** are these per-occupied-voxel **normals**,
   **positions**, both, or something else? What is the per-record layout/stride,
   and how many are there / how is the count determined?
5. **The 7×12 "unknown bytes"** that the auto-gen schema places right after the
   7 floats — what are they (e.g. an orientation matrix, padding, sub-grid
   descriptors)?
6. **The index/value tail table:** what does it map (sparse voxel → attribute?
   color palette indices? surface records?), and what is its record stride?
7. **Generation rule:** what algorithm and resolution policy did the SDK/tooling
   use to **produce** a `NiBinaryVoxelData` from a triangle mesh (so we can
   regenerate volumes for models lacking a `_vox` file)? In particular, how is
   `cellSize` chosen, and how is the finer subdivision chosen?
8. **Version notes:** did this block's layout change across NIF versions? Please
   anchor the spec to **v3.1** and flag anything version-specific.

---

## What we'd like back

1. **Byte-layout tables** for `NiBinaryVoxelExtraData` and `NiBinaryVoxelData`
   at NIF v3.1, every field in order with type and meaning.
2. **The payload unpacking procedure** as numbered steps / neutral pseudocode —
   enough to decode occupancy (and, ideally, normals/attributes) deterministically.
3. **Index & bit ordering** stated explicitly.
4. **The voxelization/generation rule** (resolution policy + fill method), if available.
5. A **worked example** decoding our Galaxy header values above, so we can verify
   our reader against your spec.

We can provide on request: the sample `*_vox.nif` files, full hex dumps of any
payload, the per-file evidence table for all 62 files, and our header-decoder's
output.
