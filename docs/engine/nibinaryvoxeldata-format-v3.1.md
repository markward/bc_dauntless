# NiBinaryVoxelData / NiBinaryVoxelExtraData — On-Disk Format (NetImmerse v3.1)

**Status:** reverse-engineered and validated against the full 84-file `*_vox.nif` corpus of
Star Trek: Bridge Commander (2001, NetImmerse). Container, header, fill field, plane palette,
and `bytes2` leaf records are confirmed against real data; the `bytes2` index-tree *writer*
needs a round-trip validation pass (noted in §9).

**Provenance / cleanroom note.** Field names for the two blocks derive from the open
niftools `nif.xml` schema (`NiBinaryVoxelData`, `NiBinaryVoxelExtraData`). That schema is
*incomplete and partly wrong* (it freezes the fill region as a fixed `byte[7][12]` and omits
the field semantics); everything below the header was recovered independently by byte
analysis + geometric correlation against the paired hull meshes. **No NDL/NetImmerse SDK
source was consulted.** Implement from this prose specification.

All integers little-endian. Floats are IEEE-754 32-bit. "GU" = game units (the model's
body-frame coordinates, same frame as the AABB).

---

## 1. File framing (v3.1)

A `*_vox.nif` contains exactly three blocks:

```
Header string:  "NetImmerse File Format, Version 3.1\n"
                "Numerical Design Limited, Chapel Hill, NC 27514\n"
                "Copyright (c) 1996-2000\nAll Rights Reserved\n"
u32  numBlocks  ( = 0x10 region / top-level object table per 3.1 framing )
... NiNode "Scene Root" ...               (root)
NiBinaryVoxelExtraData                    (extra-data block)
NiBinaryVoxelData                         (the voxel payload)
"End Of File"                             (length-prefixed sentinel block)
```

Each block is written as: `u32 typeStringLen; char[typeStringLen] typeString; u32 linkId;`
followed by the block body. `linkId` is an early-NIF 32-bit object id (a hash, not a
sequential index); references between blocks use these ids.

---

## 2. NiBinaryVoxelExtraData

Derived from `NiExtraData` (extra-data linked list).

| Field | Type | Observed | Meaning |
|---|---|---|---|
| `linkId` | u32 | (this block's id) | object id |
| `nextExtraData` | u32 (ref) | 0 / −1 | next extra-data block; none |
| `unknownInt` | u32 | 0 | vestigial reserved/bytes-remaining slot; **write 0** |
| `data` | u32 (ref) | → VoxelData id | link to the `NiBinaryVoxelData` block |

---

## 3. NiBinaryVoxelData — top-level layout

Body begins immediately after this block's `typeString` + `linkId`:

```
HEADER (34 bytes)
  u16 nx, ny, nz                       coarse cell dims
  f32 cellSize                         GU per cell
  f32 aabbMin[3]                       GU, body frame
  f32 aabbMax[3]                       GU; = hull AABB snapped OUT to whole cells

byte[L]   fillFieldSlab                §4   (L = 7 * ceil(N/8), N = (nx-1)(ny-1)(nz-1))
u32       numPlanes
Vector4[numPlanes]  planePalette       §5   (n̂.x, n̂.y, n̂.z, d)
u32       numBytes2
byte[numBytes2]     index              §6 (index tree) + §7 (leaf records)
u32       trailer[5]                   §8
```

**Header invariant** (verified 84/84): `round((aabbMax[a] − aabbMin[a]) / cellSize) == n[a]`
for each axis `a`. The grid AABB is the hull's mesh AABB expanded outward to whole `cellSize`
cells (frame-match confirmed: all hull margins < 1 cell).

`cellSize` is a per-model authored value tied to object class and LOD (§8a), observed values
1.0, 1.5, 2.0, 2.5, 4.5, 15, 25, 30, 50, 85, 100.

---

## 4. Fill field (the leading slab)

The hull **fill / occupancy scalar field**, 7 bits per sample, on the **interior-node
lattice** of size `(nx−1, ny−1, nz−1)`.

Let `N = (nx−1)(ny−1)(nz−1)` and `W = ceil(N / 8)`. Then **`L = 7 · W`** (holds for all 84
files; degenerate single-cell objects give `N=0…`, `W=1`, `L=7`, all zero).

The slab is **7 consecutive bit-planes**, each `W` bytes:

```
plane p occupies bytes [p*W, (p+1)*W)        for p = 0..6
node (i,j,k):  idx = i + (nx-1)*(j + (ny-1)*k)        # X-fastest, k outer
               byte = idx >> 3 ; bit = idx & 7        # LSB-first within a byte
               value = Σ_{p=0..6}  ((plane_p[byte] >> bit) & 1) << p     # 0..127
```

`value ∈ [0,127]`: **0 = empty, 127 = solid hull**, intermediate = partial fill at the
surface. (Validated visually: reshaping the Galaxy field to `(nz−1, ny−1, nx−1)` X-fastest and
thresholding at 127 renders the Galaxy-class silhouette — saucer, neck, two nacelles.)

The trailing `W*8 − N` bits are byte padding (zero).

---

## 5. Plane palette

A **deduplicated palette of unique surface planes** (every entry distinct in all files;
count grows only slowly with hull size — e.g. Galaxy 3002, Sovereign 3052, KessokHeavy 3426).

Each entry is a `Vector4` = a plane in **Hesse normal form**:

```
(n̂.x, n̂.y, n̂.z, d)    with |n̂| = 1,    plane = { p : n̂ · p = d }
```

* `n̂` — unit outward surface normal. Mostly **off-axis** (only ~6–10% axis-aligned) — this is
  what preserves hard hull facets.
* `d` — signed distance from the **body-frame origin**, in **GU** (not cells). Range tracks
  hull GU extent (Galaxy `d ∈ [−226, 347]`).

**To Hermite data for a QEF:** `normal = n̂`; a point on the plane = `d · n̂` (closest point to
origin), in GU. Convert a node `(i,j,k)` to GU with
`p = aabbMin + (i+1, j+1, k+1) · cellSize` (interior-node position).

---

## 6. `bytes2` — the cell→plane index (tree)

`bytes2` splits into a **head index tree** and a **tail leaf array** (§7). The head maps a
fill cell `(i,j,k)` to a range of leaf records.

### 6.1 Top level — per-Z-slice CSR
The first `nz` `u32` are byte offsets bounding the `nz−1` node-Z slices (X-fastest **k
outer**, same ordering as the fill field), i.e. a CSR over Z. (Confirmed: Galaxy
`[0,56,188,328,468,664,860,1072,1280,1416]`, `nz=10`.) `trailer[3] = 4·nz` equals this
array's byte size (84/84).

### 6.2 Recursive range-coded nodes
Below Z, the tree recurses **Z → Y → X** with nodes of the form:

```
node:
  u32 lo                       # first occupied index on this axis
  u32 hi                       # last  occupied index (+1) on this axis
  u32 csrOffset[hi-lo+1]       # child byte-offsets (CSR; empty children share an offset)
  u32 marker                   # 0x000N0000 : high u16 = tree level/depth (1 or 2),
                               #              low  u16 = per-node count/flag
```

`lo/hi` are **occupied index ranges** at that level — only non-empty rows/spans are stored,
which is why per-slice sizes swell amidships and shrink at bow/stern (your CSR observation).
The `0x000N0000` word is a **node terminator + level tag**, not data — confirming your
`0x00010000` reading; depth grows with hull size (Galaxy/CardFreighter = level 1,
KessokHeavy = level 2).

> The tree is keyed to the same `(nx−1, ny−1, nz−1)` interior-node lattice as the fill field.

---

## 7. Leaf records — **the cell→plane mapping** (confirmed)

The **tail of `bytes2`** is a flat array of **6-byte leaf records** (one per active surface
element / dual-contouring edge). The index tree (§6) resolves a cell to a contiguous run of
these.

```
leaf record (6 bytes):    # field order verified against Galaxy
  u16 nextRefA         # adjacency pointer to another leaf record (+0..+2); 0 = none
  u16 nextRefB         # adjacency pointer to another leaf record (+2..+4); 0 = none
  u16 planeIndex       # index into the plane palette (§5) — the Hermite plane  [+4..+6]
```

> **Leaf framing (verified, Galaxy):** the tail starts at `numBytes2 − 6·nRec = 94444 − 6·14449
> = 7750`; `planeIndex` is **field 2** (bytes +4..+6). End-anchoring is the correct derivation.
> All 14,449 `planeIndex` values are `< numPlanes`; the four gate anchors resolve.

**`nextRefA/B` are adjacency pointers, not endpoints or this record's id.** They reference
*other* leaf records (forward-pointing, mostly), with `nextRefA` zero 73% of the time and
`nextRefB` zero 44% — i.e. up-to-two outgoing links that stitch the dual-contouring surface
into quads. Their max (~14,699) slightly exceeds `nRec` (14,449), so the id space includes a
few virtual/boundary edges. **For the plane read you need only `planeIndex`.**

**Verification (Galaxy, 14,449 records):**
* `planeIndex` `< numPlanes` for **100%** of records (range [0, 3001]).
* Gate anchors resolve as `planeIndex` at `7750 + 6·k`: `(13,4,0)→2247`, `(13,5,1)→417`,
  `(7,2,0)→270`, `(22,2,0)→280`. Residual to palette by normal+`d` ≤ 0.02 GU.

> **The edge-scan sidestep does NOT work (tested).** The leaf count 14,449 matches *no* simple
> grid quantity over the `(nx−1,ny−1,nz−1)` fill: sign-change active edges = 2,557; exposed
> surface faces = 2,920; "either-endpoint-nonzero" edges = 9,458; `3·nonzeroNodes` = 8,361.
> So the leaves are the **extracted DC surface's own edge list**, whose cardinality depends on
> the surface topology — not a closed-form scan of the fill grid. Reproducing the order would
> mean replicating BC's *entire* extractor **and** its edge-emission order, which is more work
> than the head-tree descent (§6). Recommend against it. **The cell→leaf-record mapping
> therefore requires the §6 head-tree descent** (still open — see
> `bytes2-tree-descent-notes.md`).

---

## 8. Trailer `u32[5]`

All four non-zero values are multiples of 4 → **byte-sizes of the index-tree levels**:

| Field | Meaning | Evidence |
|---|---|---|
| `trailer[0..2]` | sizes of the deeper index level arrays (X / Y / leaf-index) | all ÷4 |
| `trailer[3]` | `= 4·nz` — size of the top per-Z-slice CSR | **84/84** |
| `trailer[4]` | `0` — reserved/terminator | always 0 |

They let the runtime seek directly to each level.

### 8a. Generation policy (cellSize & LOD)
* `cellSize` is **per-model, by object class/size** (small ships 15, Warbird 25, Cardassian
  bases 85–100, asteroids/probes 1.0–4.5).
* **full and Med LODs share the same `cellSize`** (→ identical dims and `L`; only plane
  count/content differ). **Low LOD is coarser** (~2× for ships: 15→30, 25→50; ~1.18× for the
  large bases: 85→100).
* The grid AABB = hull mesh AABB snapped outward to whole cells.

---

## 9. Read / write procedure (pseudocode)

### 9.1 Read
```
read header (34 B)
N = (nx-1)*(ny-1)*(nz-1);  W = ceil(N/8);  L = 7*W
read fillSlab = byte[L]                       # §4 unpack to value[i,j,k] in 0..127
read numPlanes;  read palette = Vector4[numPlanes]
read numBytes2;  read idx = byte[numBytes2]
read trailer = u32[5]

# plane lookup for a cell:
#   descend idx Z->Y->X (§6) using the per-axis lo/hi + CSR to a leaf-record run,
#   then for each 6-byte record take field0 = planeIndex -> palette[planeIndex] (§5,§7).
# extraction (§10) can instead iterate ALL leaf records (tail of idx) directly.
```

### 9.2 Write (regeneration)
```
choose cellSize (§8a);  grid AABB = snap(hullAABB, cellSize)
voxelize hull -> value[i,j,k] in 0..127 on the (nx-1,ny-1,nz-1) node lattice (§4)
emit header; emit fillSlab as 7 bit-planes (§4)
build plane palette: for each surface cell fit the local hull plane (n̂, d=n̂·p) (§5),
                     dedup -> palette
emit numPlanes, palette
build leaf records: per active surface element, (planeIndex, meshRefA, meshRefB) (§7)
build index tree: Z->Y->X range-coded CSR over occupied nodes, pointing to leaf runs (§6)
emit numBytes2, index(head tree + tail leaves), trailer (§8)
```

> **Validation still required (write path):** the §6 index-tree byte layout (child-offset base
> addressing, the exact level count vs. hull size, and the `meshRefA/B` id assignment) should
> be confirmed by a **round-trip test** — decode an original, re-encode, compare bytes — before
> trusting generated `_vox.nif` in the original runtime. The **read path and the leaf/plane
> mapping are settled** and sufficient for extraction today.

---

## 10. Intended extraction — dual contouring (sharp facets)

The format is purpose-built for **dual contouring**, which is why BC's breach cross-sections
show flat panels and crisp edges rather than rounded marching-cubes blobs:

1. Scalar field = the 7-bit fill (§4) on the interior-node lattice.
2. **Isovalue ≈ 63–64** (midpoint of 0…127). Surface = where fill crosses half.
3. For each cell straddling the isosurface, fetch its plane(s) from the palette via the leaf
   records (§7) → Hermite data `(point = d·n̂, normal = n̂)` in GU (§5).
4. **Solve a QEF per cell** from those planes → one vertex per cell at the intersection of the
   hull's flat panels → **sharp edges/corners**. Stitch quads via `meshRefA/B` (or re-derive).

Fill alone yields a watertight MC-style shell; the plane palette upgrades it to faithful
flat-panel hull geometry.

---

## 11. Worked example — Galaxy (`Galaxy_vox.nif`)

```
header:  nx,ny,nz = 31,43,10   cellSize = 15.0
         aabbMin = (-232.5, -322.5, -75.003)   aabbMax = (232.5, 322.5, 74.997)
fill:    N = 30*42*9 = 11340 ; W = ceil(11340/8) = 1418 ; L = 7*1418 = 9926 bytes
         -> 7-bit field, max 127, renders the Galaxy-class silhouette
planes:  numPlanes = 3002  (all unique;  d ∈ [-226, 347] GU;  ~10% axis-aligned)
bytes2:  numBytes2 = 94444
         head: Z-CSR [0,56,188,328,468,664,860,1072,1280,1416] (nz=10 entries)
               recursive Z->Y->X range-coded nodes, markers 0x00010000
         tail: 14449 leaf records of 6 B; field0 = planeIndex (100% < 3002)
               e.g. node (13,4,0) -> record planeIndex 2247 -> palette[2247] (-ẑ, |residual|≤0.02 GU)
trailer: (6244, 1508, 2256, 40, 0)   # 40 = 4*nz ; 0 reserved
```

---

## 12. Corrections to prior/public models

* niftools `byte[7][12]` "Unknown Bytes 1" — **wrong**; that region is the §4 fill field,
  length `7·W` (variable), not 84.
* The `Vector4[]` are **planes (n̂, d)**, *not* positions; 100% unit normals.
* The leaf record is **6 bytes** (not 12 — the 12 is index-level stride); **planeIndex
  is field 2** (last u16, bytes +4..+6), not field 0 — see the §7 correction.
* `numPlanes` is independent of `L`: a deduplicated palette, not per-voxel.
