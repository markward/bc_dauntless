# NiBinaryVoxelData — recovered binary format (BC `*_vox.nif`)

Status: **FULLY SOLVED** (cleanroom, verified against real geometry). Header,
container, the 7-bit fill field, and the cell index→(x,y,z) mapping are all
confirmed; the standalone decoder `ni_sdk/nibinaryvoxel_decode.py` decodes all
84 `*_vox.nif` end-to-end (zero slack to EOF) and returns `fillGrid[k][j][i]`
(0–127). Remaining items are minor/non-blocking (exact 0–127 value transfer
function; `bytes2` per-record split; a small-dims padding nuance — see §4). See
also `nif-voxel-corpus-table.csv` and `nif-voxel-format-cleanroom-brief.md`.

### The fill-field encoding (the former "codec", now solved)

```
fillField : byte[L]   where  N = (nx-1)·(ny-1)·(nz-1)   # interior-node lattice
                             W = ceil(N / 8)
                             L = 7 · W                  # 7 bit-planes, W bytes each
node (i,j,k):  idx = i + (nx-1)·(j + (ny-1)·k)          # X-fastest
               value v = Σ_{p=0..6} bit(plane_p, idx) << p      # LSB-plane first, 0..127
               bit(plane_p, idx) = (fillField[p·W + idx/8] >> (idx%8)) & 1   # LSB-first in byte
```
`v` ∈ 0..127 is the hull fill/coverage at that interior node (0 empty … 127
solid) — the quantity the runtime carves for battle damage. **Golden check
(Galaxy):** grid (30,42,9), N=11340, max=127, 2787 nonzero, 1584 solid(==127),
node flat-idx 37 = 88. Degenerate single-cell objects have `nz-1=0` ⇒ N=0 ⇒
empty fill grid (valid). Axis/bit order confirmed by the Galaxy XY-slice
rendering the correct saucer+nacelle silhouette.

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

## 4. Payload — container CONFIRMED, bitmask codec remaining

### Container layout (cleanroom-confirmed; all 84 files parse with zero slack)

After the 34-byte header, the payload is:

```
occupancyBitmask : byte[L]               # L implicit — recovered by two-ended closure
numVectors       : uint32
planes           : Vector4<f32>[numVectors]   # (n̂.x, n̂.y, n̂.z, d) — hull face planes
numBytes2        : uint32
bytes2           : byte[numBytes2]            # CSR-like offset-indexed table
trailer          : uint32[5]
```

`L` is **not stored**; it is recovered by the constraint that the vector run
ends exactly where `numBytes2` begins and the whole payload closes on the EOF
block (the decoder does this; it succeeds on all 84 files).

**Correction to an earlier guess:** the Vector4 records are **planes, not
positions**. Every record has a unit-magnitude xyz (n̂); the 4th float is a
signed plane distance `d` whose range exceeds the coordinate half-extents (so it
cannot be a coordinate). These are the hull's supporting/face planes used for
collision. Galaxy: 3002 planes; Shuttle: 526. There are no position vectors.

**`bytes2` is a CSR-like table:** it opens with a `uint32` array of
monotonically increasing offsets (Galaxy: 0, 56, 188, 328, 468, 664, …) — a
prefix-sum index into a following data region. Record stride/semantics still
need the corpus to pin.

**The niflib `byte[7][12]`=84 "Unknown Bytes 1" field does not exist** — that is
niflib's misparse of the variable-length `occupancyBitmask`. This single error
is why niflib's `numVectors` read as garbage.

### The remaining unknown — the occupancy-bitmask codec

`occupancyBitmask` is bit-packed but **variable-length and compressed**, not a
dense fixed-resolution grid:

- Galaxy `L = 9926` bytes, 14 702 set bits; Shuttle `L = 7` bytes, **0** set
  bits (a thin shuttle has no interior-solid cells — its slab is all-empty).
- `L` is **not** `ceil(nx·ny·nz/8)` (that is 1667 for Galaxy, not 9926) and not
  any padded fine-grid product: `9926 = 2·7·709`, 709 prime — no `fx·fy·fz` nor
  row-padded factorization. An autocorrelation peak at stride 15 bytes plus the
  un-factorable length point to a **per-slice convex-span or RLE encoding**, not
  a dense grid. This is the last real unknown; the 84-file corpus table
  (`nif-voxel-corpus-table.csv`) is the input for fitting it.

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

### Index / bit / axis order — HYPOTHESIS (confirm after codec is cracked)

Standard NetImmerse convention is **X-fastest, then Y, then Z** (`i = x +
nx*(y + ny*z)`), bits LSB-first within each byte. Consistent with the
shifting-bit-run direction, **but unconfirmed** — because the slab is
compressed, axis/bit order can only be confirmed once the codec is decoded and a
slice is rendered against the hull cross-section (Task 9 point-dump).

---

## 5. Status of the open questions

| # | Question | Status |
|---|----------|--------|
| 1 | Payload field order | ✅ **CLOSED** — container confirmed (§4), all 84 files parse with zero slack |
| 2 | The Vector4 records | ✅ **CLOSED** — they are **planes** `(n̂, d)`, not positions/normals-only; hull face planes |
| 3 | `bytes2` tail | 🟡 **PARTIAL** — it's a CSR-like prefix-sum offset table; record stride/semantics need the corpus |
| 4 | `NiBinaryVoxelExtraData.unknown_int` | ✅ **CLOSED** — vestigial reserved/bytes-remaining slot; write 0, ignore |
| 5 | Occupancy-bitmask codec | ❌ **OPEN** — variable-length, compressed (per-slice convex-span or RLE); the one real remaining unknown |
| 6 | Bit/axis order | ❌ **OPEN** — X-fastest LSB-first hypothesis; confirm via Task 9 point-dump once the codec is decoded |

### What closes the remaining unknowns

The cleanroom needs corpus data, now produced: **`nif-voxel-corpus-table.csv`**
— all 84 files with `(dims, cellSize, aabb-diagonal, L, popcount, numPlanes,
numBytes2, trailer)`. The cellSize spread is now rich (1.0, 1.5, 2.0, 2.5, 4.5,
15, 25, 30, 50, 85, 100), versus the single value (15) the first four samples
had. With L and dims across 84 files the cleanroom can fit the bitmask
resolution/codec rule and the cellSize-selection (generation) policy.

---

## 6. Contract for downstream tasks

**Safe to implement now (high confidence):**
- Header: 3 `u16` dims, 1 `f32` cell size, 3 `f32` min, 3 `f32` max (34 bytes).
- Grid AABB = [min, max]; resolution = (nx,ny,nz); cell edge = cellsize;
  `(max-min)/cellsize == (nx,ny,nz)` is an assertable invariant.
- Coarse cell (i,j,k) center = `min + (i+0.5, j+0.5, k+0.5) * cellsize`.
- The **container** parse (bitmask length recovery, planes, bytes2, trailer) —
  the `ni_sdk/nibinaryvoxel_decode.py` algorithm parses all 84 files.

**NOT safe yet (blocked on the codec):**
- Interpreting the `occupancyBitmask` bytes as a solid grid — the compression
  codec is unresolved. Until it's cracked, the decoded occupancy (and hence the
  faithful BC volume) is unavailable; our own voxelizer (Tasks 1–5) is the
  volume source in the meantime.
