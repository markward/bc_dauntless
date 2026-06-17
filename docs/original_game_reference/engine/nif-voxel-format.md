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

## 4. Payload — container CONFIRMED, fill field DECODED

### Container layout (cleanroom-confirmed; all 84 files parse with zero slack)

After the 34-byte header, the payload is:

```
fillField        : byte[L]               # L implicit — recovered by two-ended closure
                                         # This IS the "occupancyBitmask" found by the
                                         # earlier anchoring analysis. It is the 7-bit fill
                                         # field described in §"The fill-field encoding"
                                         # above. The two names refer to the same bytes.
numVectors       : uint32
planes           : Vector4<f32>[numVectors]   # (n̂.x, n̂.y, n̂.z, d) — hull face planes
numBytes2        : uint32
bytes2           : byte[numBytes2]            # CSR-like offset-indexed table
trailer          : uint32[5]
```

`L` is **not stored**; it is recovered by the constraint that the vector run
ends exactly where `numBytes2` begins and the whole payload closes on the EOF
block (the decoder does this; it succeeds on all 84 files).

**Identity clarification:** The leading `fillField` bytes are precisely what
earlier analysis called the "occupancyBitmask". They are the 7-bit fill field
documented in §"The fill-field encoding" — 7 LSB-first bit-planes over the
(nx-1)×(ny-1)×(nz-1) interior-node lattice. `voxel::from_nif_voxel_data`
decodes this region and stores the 0–127 fill values in `VoxelVolume::occ`.
The `raw_voxel_payload` in `NiBinaryVoxelData` retains the full payload (fill
field + planes + bytes2 + trailer) for any consumer that needs the unparsed
sub-structures.

**Correction to an earlier guess:** the Vector4 records are **planes, not
positions**. Every record has a unit-magnitude xyz (n̂); the 4th float is a
signed plane distance `d` whose range exceeds the coordinate half-extents (so it
cannot be a coordinate). These are the hull's supporting/face planes used for
collision. Galaxy: 3002 planes; Shuttle: 526. There are no position vectors.

**`bytes2` is a CSR-like table:** it opens with a `uint32` array of
monotonically increasing offsets (Galaxy: 0, 56, 188, 328, 468, 664, …) — a
prefix-sum index into a following data region. Record stride/semantics are a
minor remaining item; not needed for occupancy.

**The niflib `byte[7][12]`=84 "Unknown Bytes 1" field does not exist** — that is
niflib's misparse of the variable-length fill field. This single error
is why niflib's `numVectors` read as garbage.

### The fill field — DECODED (see §"The fill-field encoding" above)

The leading `fillField` bytes (`L` bytes, recovered by two-ended closure) are
**not** a dense grid indexed at (nx,ny,nz) resolution, which explains why `L`
does not equal `ceil(nx·ny·nz/8)`. They encode the *interior-node* lattice at
`(nx-1,ny-1,nz-1)` resolution, using 7 LSB-first bit-planes (7·W bytes where
W = ceil(N/8), N = (nx-1)·(ny-1)·(nz-1)). Galaxy decoded: N = 11 340 nodes,
L = 7·1418 = 9926 bytes, matching the corpus measurement exactly.

`voxel::from_nif_voxel_data` fully decodes this region. Golden-verified on
Galaxy: dims (30,42,9), max 127, 2787 nonzero, 1584 solid (==127), node
flat-idx 37 = 88.

### Index / bit / axis order — CONFIRMED

**X-fastest, Y, Z** (`idx = x + (nx-1)*(y + (ny-1)*z)`), bits LSB-first within
each byte, planes LSB-first (plane 0 = bit 0). Confirmed by the Galaxy XY-slice
rendering the correct saucer+nacelle silhouette and by the golden node-37 spot
check.

---

## 5. Status of the open questions

| # | Question | Status |
|---|----------|--------|
| 1 | Payload field order | ✅ **CLOSED** — container confirmed (§4), all 84 files parse with zero slack |
| 2 | The Vector4 records | ✅ **CLOSED** — they are **planes** `(n̂, d)`, not positions/normals-only; hull face planes |
| 3 | `bytes2` tail | 🟡 **PARTIAL** — it's a CSR-like prefix-sum offset table; record stride/semantics are a minor non-blocking item (not needed for occupancy) |
| 4 | `NiBinaryVoxelExtraData.unknown_int` | ✅ **CLOSED** — vestigial reserved/bytes-remaining slot; write 0, ignore |
| 5 | Fill-field / "occupancy-bitmask" codec | ✅ **SOLVED** — 7 LSB-first bit-planes over (nx-1)·(ny-1)·(nz-1) interior-node lattice; decoded by `voxel::from_nif_voxel_data`; golden-verified on Galaxy (dims 30×42×9, max 127, 2787 nonzero, 1584 solid, occ[37]=88). Minor remaining items: exact 0–127 value transfer function (partial); `bytes2` per-record split (partial); small-dims padding nuance. None block occupancy use. |
| 6 | Bit/axis order | ✅ **CONFIRMED** — X-fastest, Y, Z; LSB-first in byte; planes LSB-first (plane 0 = bit 0). Confirmed by Galaxy XY-slice silhouette match + golden spot check. |

---

## 6. Contract for downstream tasks

**Safe and implemented:**
- Header: 3 `u16` dims, 1 `f32` cell size, 3 `f32` min, 3 `f32` max (34 bytes).
- Grid AABB = [min, max]; resolution = (nx,ny,nz); cell edge = cellsize;
  `(max-min)/cellsize == (nx,ny,nz)` is an assertable invariant.
- Coarse cell (i,j,k) center = `min + (i+0.5, j+0.5, k+0.5) * cellsize`.
- The **container** parse (fill-field length recovery, planes, bytes2, trailer) —
  the `ni_sdk/nibinaryvoxel_decode.py` algorithm parses all 84 files.
- **The fill field IS decoded** — `voxel::from_nif_voxel_data(vd)` reads the
  leading `fillField` bytes from `raw_voxel_payload` and returns a `VoxelVolume`
  whose `occ` holds 0–127 per interior node; `solid()` treats any nonzero as
  solid. This is the faithful BC voxel volume for stock ships. Golden-verified on
  Galaxy (see §"The fill-field encoding").

**Remaining non-blocking items (do not block occupancy use):**
- Exact 0–127 value transfer function (partial — values are correct; semantics
  of intermediate values 1–126 are not yet mapped to a physical quantity).
- `bytes2` per-record split — the CSR-like structure is identified but the
  per-record field layout is unresolved. Not needed for occupancy.
- Small-dims padding nuance — degenerate single-cell objects (nz-1 = 0 ⇒ N = 0)
  produce an empty fill grid, handled by `from_nif_voxel_data` returning an
  empty volume (tested by ShuttleDegenerateIsEmpty).
- **`planes` and `bytes2` sub-parsing** — retained opaquely in
  `raw_voxel_payload` for future consumers; not needed for the voxel volume.
