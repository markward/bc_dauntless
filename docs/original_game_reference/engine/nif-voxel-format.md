# NiBinaryVoxelData — recovered binary format (BC `*_vox.nif`)

Status: **DONE_WITH_CONCERNS.** The header (dimensions + bounds + cell size)
is **fully solved with high confidence** and corpus-validated across all 62
`*_vox.nif` files. The opaque voxel **payload encoding is characterized but
NOT decoded** — enough structure is recovered to plan Task 8, but the exact
unpacking procedure is unconfirmed and must be nailed down with the
point-dump / IoU validation (Tasks 8–10) before any decoder is trusted.

Investigation tool: `native/tools/voxel_inspect/` (`voxel_inspect <X_vox.nif> [X.nif]`).
All numbers below are this tool's actual output plus corpus scripts.

---

## 1. Block chain

Every `*_vox.nif` is a NetImmerse v3.1 file with exactly **3 blocks**:

1. `NiBinaryVoxelExtraData` (root) — `next_extra_data_link` (u32, always 0),
   `unknown_int` (u32, always 0 in samples), `data_link` (u32 → the data block).
2. `NiBinaryVoxelData` — the grid (see below).
3. `End Of File` sentinel.

These three always parse cleanly to EOF (verified by `voxel_inspect` and the
existing `scan_nifs` corpus run).

---

## 2. `NiBinaryVoxelData` header — SOLVED

On-disk layout immediately after the block type string + link id:

| Offset | Type        | Field         | Meaning (recovered)                              |
|--------|-------------|---------------|--------------------------------------------------|
| +0     | `u16`       | `short1` (nx) | grid resolution in cells along X                 |
| +2     | `u16`       | `short2` (ny) | grid resolution in cells along Y                 |
| +4     | `u16`       | `short3` (nz) | grid resolution in cells along Z                 |
| +6     | `f32`       | `float[0]`    | **cell size** in game units (uniform, isotropic) |
| +10    | `f32`×3     | `float[1..3]` | **min corner** (x,y,z) of grid AABB, body frame  |
| +22    | `f32`×3     | `float[4..6]` | **max corner** (x,y,z) of grid AABB, body frame  |
| +34    | bytes       | payload       | opaque voxel data, runs to the EOF sentinel      |

### The exact relationship (the invariant that proves the above)

For **all 62** `*_vox.nif` files in the corpus:

```
short_i  ==  round( (max[i] - min[i]) / cellsize )      for i in {x,y,z}
```

i.e. the three shorts are the grid's bounding box measured in whole cells, and
`cellsize` is the edge length of one cubic cell. `cellsize` is **per file**,
scaling with object size (values observed: 15, 25, 30, 50, 85, 100 GU;
distribution: 15→33 files, 30→17, 85→6, 100→3, 25→2, 50→1). The four task
sample files all happen to use cellsize = 15.

> **Note on units:** these are BC game units (1 GU = 175 m). A 15-GU cell is
> ~2.6 km on a side — coarse, consistent with a collision/volume proxy rather
> than a fine visual mesh.

### Galaxy — decoded header + hull-AABB cross-check

```
shorts  = (31, 43, 10)
cellsize= 15.0
min     = (-232.500, -322.500, -75.003)
max     = ( 232.500,  322.500,  74.997)
span    = ( 465.000,  645.000, 150.000)  -> /15 = (31, 43, 10)  == shorts  ✓
```

Hull AABB of `Galaxy.nif` (body frame, computed by `voxel_inspect` by walking
the NiNode tree and transforming every `NiTriShapeData` vertex):

```
hull min = (-232.064, -322.166, -70.501)
hull max = ( 232.064,  322.166,  70.495)
```

The voxel grid AABB **encloses the hull AABB** and is snapped outward to whole
15-GU cells on every axis (e.g. hull Z reaches ±70.5; the grid rounds out to
±75 = 5 cells each side). This is exactly what a solid voxelizer produces:
bound the mesh, round the box up to an integer cell count. **High confidence:
`float[1..3] = min`, `float[4..6] = max`, `float[0] = cellsize`.**

The schema in `extra_data.cc` currently *names* these `unknown_7_floats`; they
should be relabelled `cell_size` + `aabb_min[3]` + `aabb_max[3]` in Task 7.

---

## 3. The four sample files (evidence table)

| File      | dims (nx,ny,nz) | cells   | payload (B) | cells·1B ratio | ceil(cells/8) | payload/(cells/8) |
|-----------|-----------------|---------|-------------|----------------|---------------|-------------------|
| Galaxy    | 31×43×10        | 13 330  | 152 430     | 11.44          | 1 667         | 91.4              |
| Sovereign | 16×47×6         |  4 512  | 127 790     | 28.32          |   564         | 226.6             |
| Shuttle   | 2×2×1           |      4  |  17 683     | 4420.75        |     1         | 17683.0           |
| DryDock   | 62×95×35        | 206 150 | 529 004     | 2.57           | 25 769        | 20.5              |

**The payload is one to several orders of magnitude larger than the cell
count.** The Shuttle case is decisive: a 2×2×1 = 4-cell coarse grid carries a
17.6 KB payload. So the payload is **not** keyed to the (nx,ny,nz) lattice —
the shorts describe a *coarse* bounding box, while the payload stores a much
finer / richer volume (per-voxel geometry, not a single occupancy bit per
coarse cell). The payload/cells ratio also **shrinks** as the grid grows
(DryDock 2.57 vs Shuttle 4420), i.e. there is a large per-object component plus
a per-finer-voxel component that amortizes. This is consistent with BC
rendering breached "guts" as dense multicolored voxel splats: the payload most
likely stores **occupancy + per-voxel attributes (color and/or normal)** at a
subdivision finer than the coarse 15-GU lattice.

---

## 4. Payload encoding — CHARACTERIZED, NOT DECODED

### What is observable (facts)

- **Full byte entropy.** All 256 byte values occur in every sample. ~26–31%
  of bytes are `0x00`; `0xff` is rare (<1%). Not a sparse single-symbol stream.
- **Leading bit-run region.** Every file, a few dozen bytes into the payload,
  has a run of bytes that form a smoothly *shifting* bit pattern, e.g.
  Sovereign: `1c 00  0e 00  07 80  03 c0  01 e0  00 70  00 38  00 08` and
  Galaxy: `…1e  00 00 c0 0f  00 00 f0 03  00 00 fc 00  00 00 3f 00…`.
  Read as bits, these are a set bit-mask widening then narrowing — the classic
  signature of a **bit-packed occupancy slab of a convex hull cross-section**.
  DryDock's equivalent region is sparse single bits (`08`, `40`, `10 00 08`),
  consistent with a hollow/large structure. **There is a bit-packed occupancy
  component**, but it does not start at payload offset 0 and is not the whole
  payload.
- **Float vectors present.** Shuttle's payload (offset ~11 onward) is a long
  run of IEEE-754 floats. Many are unit-magnitude (|v| = 1.000 — normals);
  interleaved with larger vectors whose components fall inside the grid AABB
  (positions). So the payload also carries **floating-point per-voxel geometry
  (normals and/or positions)**, not just bits.
- **Structured tail.** The last region is regular records mixing `u32` and
  `u16` fields with recurring high-byte indices in the ~0x39xx range
  (~14 700), close to but not equal to the Galaxy cell count (13 330). These
  read like an index/value table, but the stride is **not** a clean 6/8 bytes
  and did not resolve to a self-consistent record array from four samples.
- **No clean niflib match.** The auto-gen niflib schema
  (3 u16 + 7 f32 + 7×12 bytes + numVectors + Vector4[] + numBytes2 + byte[] +
  5 u32) does **not** parse cleanly: the would-be `num_unknown_vectors` u32 at
  the post-7×12 offset is garbage (e.g. 70 498 116 for Shuttle), and no
  trailing-count interpretation closed the buffer. Treat that schema as a
  *hint that float-vector + byte sections exist*, not as the layout.

### What the encoding probably is (HYPOTHESIS — unconfirmed)

A two-part body: **(a)** a bit-packed occupancy slab over a finer grid (the
shifting-bit-run region), followed by **(b)** per-occupied-voxel attribute data
(floats = normal/position, plus the indexed tail table). The coarse
(nx,ny,nz) shorts + AABB give the *outer* box; the occupancy bits define the
finer solid fill; the float/index sections color it. **This is a hypothesis;
the precise field order, the finer subdivision factor, the bit/axis order, and
the record stride are all UNCONFIRMED.** Do not implement a decoder against
this section as if it were spec.

### Index / bit / axis order — HYPOTHESIS only

Standard NetImmerse/voxel convention would be **X-fastest, then Y, then Z**
(linear index `i = x + nx*(y + ny*z)`), bits packed LSB-first within each byte.
The shifting-bit-run direction in the leading region is consistent with
X-fastest packing, **but this is not confirmed.** It must be validated in
Task 8/9 by dumping decoded occupied points back into body frame and checking
they land inside the hull AABB and reproduce the hull silhouette (IoU).

---

## 5. Open questions / unconfirmed (be honest before building Tasks 7–8)

1. **Exact payload field order.** Where does the occupancy slab end and the
   attribute data begin? Is there an explicit count, or is it implied by the
   occupancy bit total? **Unknown.**
2. **Finer subdivision factor.** The coarse grid is (nx,ny,nz) at `cellsize`,
   but the payload is far larger. Is each coarse cell subdivided (e.g. 2³, 4³),
   or is there an independent fine grid resolution stored somewhere in the
   leading bytes we currently treat as opaque? **Unknown** — this is the single
   most important gap; the payload size cannot be predicted from the header
   without it.
3. **What the float vectors are.** Normals, positions, or both, and their
   exact per-voxel record layout. The unit-magnitude entries are almost
   certainly normals; the rest are spatial but unverified. **Unconfirmed.**
4. **The tail index/value table.** Stride and meaning of the `u32`/`u16`
   records (the ~0x39xx indices). **Unconfirmed.**
5. **Bit and axis order.** X-fastest LSB-first is the working assumption only.
   **Must be confirmed by point-dump.**
6. **`NiBinaryVoxelExtraData.unknown_int`.** Always 0 in samples; purpose
   unknown (harmless).

### What additional evidence would close these

- A **known-trivial shape** vox file (a unit cube / single filled cell) would
  expose the occupancy-section length and the per-voxel record stride directly.
  Worth generating one if BC's runtime voxelizer can be coaxed, or hand-crafting
  the simplest real file (Shuttle is the smallest at 2×2×1 coarse cells / 17.6 KB
  and is the best existing probe target for Task 8).
- The **point-dump + IoU validation** (Tasks 9–10): decode under the hypothesis,
  project occupied voxels to body frame, and measure overlap with the hull mesh.
  High IoU confirms dims/bounds/axis-order simultaneously and is the real gate
  on the payload interpretation.

---

## 6. Contract for Tasks 7–8 (what you can safely build on)

**Safe to implement now (high confidence):**
- Read 3 `u16` dims, 1 `f32` cell size, 3 `f32` min, 3 `f32` max.
- Grid AABB = [min, max]; resolution = (nx,ny,nz); cell edge = cellsize;
  `(max-min)/cellsize == (nx,ny,nz)` is an assertable invariant.
- Body-frame world position of coarse cell (i,j,k) center =
  `min + (i+0.5, j+0.5, k+0.5) * cellsize`.

**NOT safe to implement yet (must pass Task 9/10 validation first):**
- Any interpretation of `raw_voxel_payload` (occupancy, color, normals).
  Keep it as opaque bytes until the point-dump confirms the unpacking.
