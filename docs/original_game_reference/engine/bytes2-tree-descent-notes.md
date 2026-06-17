# bytes2 head-tree descent — working notes (Task 2, BLOCKED)

Status: leaf tail + spec corrections CONFIRMED; the head-tree cell→leaf-record
descent is the open crux (cleanroom round 3). Captured from the Task 2 attempt.

# bytes2 descent findings (Galaxy_vox.nif)

Artifacts (binary dumps):
- /tmp/galaxy_bytes2.bin  : the raw bytes2 blob (94444 bytes)
- /tmp/galaxy_fill.bin    : int32 dx,dy,dz=(30,42,9) then dx*dy*dz bytes fill (0..127), X-fastest i+dx*(j+dy*k)
- /tmp/galaxy_planes.bin  : int32 n=3002 then n*(4 float) plane palette (nx,ny,nz,d)
- header: aabbMin=(-232.5,-322.5,-75.003) cell=15 nx,ny,nz=31,43,10 -> interior dnx,dny,dnz=30,42,9
- pos(i,j,k)=aabbMin+(i+1,j+1,k+1)*cell

## CONFIRMED
1. Z-CSR: first nz=10 u32 = [0,56,188,328,468,664,860,1072,1280,1416], byte offsets relative to
   base=40 (i.e. region [40+zc[s], 40+zc[s+1]) per slice). trailer[3]=40=4*nz. CONFIRMED.
2. **LEAF TAIL starts at byte 7750**, 14449 records of 6 bytes each (matches spec §11 count!).
   **planeIndex = FIELD 2 (the LAST u16, bytes [4:6]), NOT field 0.** Spec §7 byte order is WRONG.
   At 7750/field2: ALL values <3002, and all four anchor planes present:
     (want->recordIdx): 270->1095, 280->1140, 2247->10175, 417->1719.
   record r's planeIndex = u16 at 7750 + 6*r + 4.
3. HEAD = [0,7750). Sub-regions:
   - [0,40)    Z-CSR (10 u32)
   - [40,1456) Z-slice nodes. 9 nodes (dnz=9). Each begins with marker 0x0001000N at exactly
     40+zc[s]. marker low u16 = per-slice DEPTH (slice depths: 0,1,1,1,2,1,1,1,1). Node =
     {u32 marker, u32 lo, u32 hi, u32 csr[hi-lo+1]}. lo/hi are a mid-axis occupied range.
     Slice0(depth0): lo10,hi20,csr=[0,0,12,24,36,48,60,72,84,96,108] (step 12 = 2 records=12B).
     Larger slices have extra trailing words after csr (deeper levels).
   - [1456,7750) leaf-index region. Begins with its OWN node: marker0x10000, lo24,hi33,
     csr[10]=[0,3880,3892,...3976] (these csr are byte offsets relative to node-header-end=1508).
     Following each csr offset are record-index values ~11107..11550 (in 0..14449 range) MIXED
     with packed (lo,hi) u16 pairs, at apparently 6-byte (not 4-byte) stride in places.

## OPEN (the crux)
- Exact recursion: how Z-slice nodes [40,1456) compose with leaf-index region [1456,7750) to
  yield, per cell (i,j,k), the FIRST leaf record index. The leaf-index region uses record
  indices (~11340 range) and packed (lo,hi) X-spans, at mixed 4/6-byte alignment.
- Variable depth per slice (marker low u16) means recursion depth varies.

## GATE (must reproduce, planeIndex=field2@7750)
(13,4,0)->2247  (13,5,1)->417  (7,2,0)->270  (22,2,0)->280

## ROUND 3 FINDINGS (cleanroom)
- cell->plane is MANY-TO-ONE: planes are shared flat panels. A plane is referenced on
  average ~4.8x; only 253/3002 referenced exactly once. The gate's cell->recordIdx uses the
  FIRST occurrence of that (distinctive) plane. So a "cell" owns up to 3 edge-records, and a
  plane spans many cells.
- nextRefA/nextRefB (leaf fields 0/1) are ADJACENCY POINTERS to other leaf records (forward-
  mostly; refA zero 73%, refB zero 44%), NOT endpoints and NOT this record's id. They stitch
  the DC quad mesh. Max ~14699 > nRec 14449 (a few virtual/boundary edges).
- EDGE-SCAN SIDESTEP FAILS: nRec=14449 matches no grid quantity over the (30,42,9) fill
  (sign-change edges 2557; exposed faces 2920; either-endpoint-nonzero edges 9458;
  3*nonzeroNodes 8361). The leaves are the extracted surface's own edge list.
- RECORD ORDER IS NOT (k,j,i)-LEXICOGRAPHIC. Evidence from the gate (recordIdx, dominant
  normal): (7,2,0) -x ->1095 ; (22,2,0) +x ->1140 ; (13,5,1) +z ->1719 ; (13,4,0) -z ->10175.
  Within a row, ~3 records/cell with contiguous X (1095 vs 1140 = +45 over di=15). But
  same-slice j=2 (~1100) and j=4 (~10175) are 9000 apart, while the order tracks FACE
  DIRECTION: x-faces early (~1.1k), +z mid (~1.7k), -z late (~10.2k). => ordering looks
  FACE-OCTANT-MAJOR, then spatial. The head-tree descent must reconcile this with the
  per-slice CSR. This is why a naive Z->Y->X descent won't hit the gate.

## STRATEGIC NOTE
For a clean reimpl the head-tree descent may be UNNECESSARY:
  (A) render from leaves alone: planeIndex(Hermite) + nextRef adjacency + palette -> DC mesh.
  (B) RE-EXTRACT from fill: fill 0..127 (iso~63-64) for topology + nearest palette plane for
      sharp Hermite normals -> own dual contouring. Sidesteps tree AND leaf order; also the
      path needed to generate _vox for NEW models. Recommended.
The head tree is only required for byte-faithful reproduction of BC's spatial query path.
