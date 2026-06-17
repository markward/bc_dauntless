# Cleanroom request #2: the `planes` palette + `bytes2` index (NiBinaryVoxelData)

**Goal:** recover how BC's `NiBinaryVoxelData` ties its **surface planes** to its
**fill cells**, so we can reconstruct the hull surface with a **dual-contouring-style
extraction** (sharp hull facets/edges), not a rounded marching-cubes blob. Faithful
battle-damage cross-sections need the hard corners — a ship hull is all flat panels
and crisp edges — so the rounding marching cubes does over our coarse grid won't cut it.

**Status going in:** the container + header + 7-bit fill field are fully decoded
(see `nif-voxel-format.md`). The two pieces still opaque are the `Vector4` **plane
records** and the **`bytes2`** table. We now have strong structural leads on both.

## What dual contouring needs (the consumption model)
Per surface cell, it wants **Hermite data**: for each surface crossing, a point + a
normal. A plane `(n̂, d)` is exactly that in implicit form. So we need: **given a fill
cell `(x,y,z)`, which plane(s) describe its surface?** That mapping is what `bytes2`
almost certainly encodes.

## Lead 1 — `bytes2` opens with a per-Z-slice CSR offset array (strong, cross-ship)
The first `uint32`s of `bytes2` are a monotonic offset array of length **`(nz−1)+1`** —
one entry per interior Z-slice plus a terminator — then a `0x00010000` marker and the
per-slice data:

| Ship | nz−1 | leading offsets | count = (nz−1)+1? |
|---|---|---|---|
| Galaxy | 9 | 0,56,188,328,468,664,860,1072,1280,1416 | 10 ✓ |
| Sovereign | 5 | 0,60,196,392,656,888 | 6 ✓ |
| KessokHeavy | 13 | 0,192,596,1088,1492,1844,2220,2604,2956,3232,3384,3428,… | ~14 ✓ |
| Shuttle | 0 (degenerate) | n/a | n/a |

Per-slice byte sizes grow toward the middle slices and shrink at the ends — consistent
with a hull cross-section widening then narrowing. So `bytes2` is a **hierarchical
index keyed first by Z-slice**, presumably drilling to per-row and/or per-cell →
plane-index lists.

**Questions:**
1. Confirm the top level is a per-Z-slice CSR. What is the **per-slice region's**
   internal format — a nested per-row CSR? per-cell records? How does it ultimately
   yield, for a given fill cell `(x,y,z)`, its plane index/indices?
2. What is the recurring **`0x00010000` (65536)** value — a section marker, a
   sub-count, or a pair of `u16`s misread as `u32`?
3. Is the index keyed by the **interior-node `(nx−1,ny−1,nz−1)` lattice** (same as the
   fill field) or by some other cell set?

## Lead 2 — `planes` is a deduplicated palette, not per-voxel (strong)
`numPlanes` barely changes with ship size — Galaxy 3002, Sovereign 3052, KessokHeavy
3426 — even though KessokHeavy has ~4× the solid nodes (11906 vs 2787). So the planes
are a **bounded palette of unique facet orientations**, and `bytes2` indexes into it.

**Questions:**
4. Confirm `planes` is a deduplicated palette (unique `(n̂, d)` orientations) rather
   than one-per-surface-element. Is there an implicit ordering/grouping?
5. For a plane `(n̂, d)`: what is **`d` measured from** (grid origin `aabb_min`? body
   origin? cell units or game units?), and what is the convention to turn
   `(n̂, d)` + a cell into the **point+normal** a QEF solver consumes?

## The prize
6. **The intended extraction algorithm:** how did BC combine the **fill field (0–127)**
   + the **plane palette** + the **`bytes2` index** to produce the rendered hull/breach
   surface? Even a sketch of "for each cell: threshold the fill, look up its planes via
   bytes2, place the vertex at the plane intersection" would let us reproduce it.
7. **0–127 fill value semantics** for the isosurface: what value is "the surface"
   (a fixed isovalue? a coverage fraction?) — needed for the threshold dual contouring
   contours at.
8. **`trailer` `uint32[5]`** — still unidentified (Galaxy `(6244,1508,2256,40,0)`,
   t4 always 0).

## We can provide
The updated decoder `ni_sdk/nibinaryvoxel_decode.py` returns `fillGrid`, `planes`,
`bytes2`, `trailer`. On request we can dump, for any ship: the full per-slice byte
regions of `bytes2`, the plane list, plane-component histograms, and cross-reference
counts (numPlanes vs solid-nodes vs per-slice sizes) — say what would help.

---

## Cross-reference for the leaf-layout pass (Galaxy)

Known-normal surface nodes matched to the palette by BOTH normal and `d`
(`d ≈ n̂·pos`, `pos = aabbMin + (i+1,j+1,k+1)·cellSize`, ISO=64). These are the
cell↔plane ground-truth pairs to pin the 12-byte leaf field order:

| node (i,j,k) | GU pos | normal | palette idx | n̂ | d | residual |
|---|---|---|---|---|---|---|
| (13,4,0) | (−22.5,−247.5,−60) | −ẑ | **2247** | (0.186,0.121,−0.975) | 24.28 | **0.02 GU** |
| (13,5,1) | (−22.5,−232.5,−45) | +ẑ | 417 | (−0.159,−0.207,0.965) | 9.29 | 0.92 GU |
| (22,2,0) | (112.5,−277.5,−60) | +x̂ | 280 | (0.975,0.220,0.029) | 51.09 | 4.34 GU |
| (7,2,0) | (−112.5,−277.5,−60) | −x̂ | 270 | (−0.975,0.220,0.029) | 51.09 | 4.34 GU |

Palette axis-plane counts (|n̂·axis|>0.98): z=746, x=194, y=132 — hull-consistent
(deck/saucer faces dominate). numPlanes(Galaxy)=3002, all unique.

The `(13,4,0) → palette[2247]` pair (0.02 GU residual) is the cleanest anchor: find
plane index 2247 in that cell's leaf record to identify the plane-index field.
