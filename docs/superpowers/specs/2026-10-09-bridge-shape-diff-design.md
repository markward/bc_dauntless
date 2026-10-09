# Bridge Shape Diff — design (living spike spec)

**Date:** 2026-10-09
**Status:** design approved in chat; iteration 1 not started
**Branch:** `spike/bridge-shape-diff` (worktree `.claude/worktrees/bridge-shape-diff`)
**Living document:** updated after every accepted iteration (§9).

---

## 1. What this is, and why

A new mesh-fix operation, `shape_edits`, that lets Mark edit BC set geometry
(first target: DBridge) in Blender **without ever committing BC geometry**.

The repo stores only a **diff** against the player's own copy of the NIF:
references to original vertex/triangle indices, plus geometry Mark authored
(moved and new vertices). At load the diff is applied to the parsed
`nif::File`, keyed by the NIF's FNV-1a 64 content hash, exactly like the hull
name-cut fix (`docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md`).
A modded NIF has a different hash and loads unpatched.

**Why not replacement shapes.** The parked attempt (`spike/bridge-lighting-vfx`,
`replacements` op + `tools/bridge_meshgen/`) replaced whole shapes with
generated or hand-modelled lookalikes. Matching BC's shapes by hand was too hard,
and committing modified originals in full is ruled out by copyright. It also
dropped vertex colours, kept only UV0 and inverted only the node translation.
Reused from it: the OBJ reader, ear clipping and axis helpers.

**Targets on DBridge, in build order** (each proves more of the pipeline):

1. Close gaps/holes by **moving vertices only** — no topology change.
2. Reshape the ugly face above the turbolift archway (the `D walls 1` header
   meeting the turbolift top) — some triangles removed and added.
3. Extrude flat side-wall panels — new vertices, triangles and UVs.

---

## 2. Measured facts this rests on (2026-10-08, stock `Dbridge.NIF`)

Probe linked against our own `libnif` (scratch only).

| Fact | Value | Consequence |
|---|---|---|
| Blocks / shapes | 701 / 145 `NiTriShape`, ~9.5k verts, ~8.6k tris | One file, many shapes; a gap can sit between two shapes |
| Shape names | **all empty**; the readable name is on the parent `NiNode` (`D walls 1` → block 468) | Identity is the block index (the hash pins the layout); the parent name is a label only |
| Normals | none on any shape | Every edited shape still goes through interior normal generation |
| Vertex colours | **123 / 145** shapes | New vertices must carry a colour |
| UV sets | 128 shapes have 1, **17 have 2** | New vertices need a UV1 value although the renderer never draws it |
| Shape transforms | all identity; parent nodes translated (e.g. `wall side pnls 01` at (−22.2, 25.7, 62.2)), scale 1 | Model↔local must invert the **full** `nif_block_world`, not just translation |
| Match groups | none | Nothing to keep consistent |
| Load path | `host_loop.realize_set` → `load_model(..., interior=True)` → `AssetCache::load` → `apply_mesh_fix` → `build_model` | Fixes already apply to sets; normal gen + T-junction repair run after the edit |

---

## 3. Pipeline

```
bridge_shape_diff export  ─►  dbridge.obj + dbridge.mtl   (scratchpad)
                                   │  Blender: import (defaults)
                                   ├─► export unaltered ─► base.obj
                                   └─► edit, export    ─► edit.obj
bridge_shape_diff diff base.obj edit.obj ─► native/assets/mesh_fixes/<fnv1a64>.json  (committed)
engine: nif::load ─► apply_mesh_fix (merges, then shape_edits) ─► build_model (normal gen, T-junction repair)
```

One tool, `tools/bridge_shape_diff.py`, with `export`, `diff` and `preview`
subcommands. Geometry comes from `_dauntless_host.nif_shapes(path)`, extended to
also return per shape: `world` (column-major 4×4, data frame → model), `parent`
(parent `NiNode` name), `colors` (RGBA floats, or empty) and `uvs1` (UV set 1,
or empty). The source NIF resolves through `paths.game_root()` (stock only, as
§10.3 of the name-cut spec), never `game_asset`.

---

## 4. Export

- **Whole set, one OBJ**, model space, one `o` per shape, named
  `b<block:04d>_<parent name, spaces→_>` (e.g. `b0468_D_walls_1`).
- **Axes:** written as OBJ `(x, z, −y)` of BC model space, so Blender's
  **default** OBJ import/export settings (Forward −Z, Up Y) show BC's Z-up and
  round-trip with no transform beyond 6-decimal rounding.
- **Welded by position per shape** (snap 1/1024 model units, the normal
  generator's grid): one `v` per unique position, so Mark edits connected
  surfaces. UV seams survive as distinct `vt` per corner.
- **Colours** as `v x y z r g b` (Blender imports them as a colour attribute).
- **`.mtl`** with one material per texture, `map_Kd` pointing at the install's
  own texture file in place — nothing is copied.
- Hidden shapes are exported too (so block indices stay one-to-one) but tagged
  in the object name suffix `_hidden`.

**Rules for Mark in Blender:** don't join, split or rename objects; new geometry
goes inside an existing object; export both OBJs with the same settings
(triangulation optional — n-gons are ear-clipped).

---

## 5. Diff

### 5.1 base.obj → original NIF (identity)

Every face corner of `base.obj` is mapped back to BC model space (inverse axis
swap), then per object to an original vertex of that shape by (snapped
position, UV0 within 1e-5). **100 % of corners must match**, else the tool
refuses and names the first unmatched corner. Each base OBJ vertex thus owns
the set of original vertices it welds (its seam duplicates).

### 5.2 edit.obj → base.obj (correspondence)

Per object, by **Blender vertex index**: Blender keeps the index of every vertex
that is not deleted, and appends new ones. The tool checks the invariant
(vertex count ≥ base count; every base face whose vertices all survive is either
present or explicitly gone) and **stops with a clear message** if vertices were
deleted (which compacts indices). Topology matching is added only if an
iteration actually needs deletions.

### 5.3 Classification, per shape

| Change | Recorded as |
|---|---|
| base vertex whose position changed | `move`: every original vertex it welds → new position (shape-local, inverted in float64, stored f32) |
| corner UV changed on a kept vertex | `uv`: original vertex → new UV0 |
| vertex appended in Blender | `add vertex`: position, UV0, colour from the OBJ (if the shape has colours; else none). UV1 copied from the nearest kept vertex. A new vertex with several distinct corner UVs becomes one added vertex per UV |
| original triangle with no matching edit face | `remove triangle` (original index) |
| edit face not matching an original triangle | `add triangle` (indices into the final vertex array) |

An original triangle "matches" an edit face when its three original vertices
map to the face's three corners with the same winding.

`diff --expect move-only` (iteration 1) fails if anything other than `move`
appears. The tool prints a per-shape summary (moved / uv / added verts /
removed tris / added tris).

---

## 6. The fix file

Same file as today: `native/assets/mesh_fixes/<fnv1a64>.json`. `merges` becomes
optional; a file needs at least one of `merges` / `shape_edits`.

```json
{
  "format": 1,
  "source": "data/Models/Sets/DBridge/Dbridge.NIF",
  "generator": "tools/bridge_shape_diff.py",
  "shape_edits": "<base64 of the binary payload>"
}
```

**Not human-readable by design** (Mark's ask): the edits are one packed binary
blob, base64-encoded. No compression — no new dependency on either side.

### 6.1 Payload layout (little-endian)

```
char[4]  magic "BSD1"
u16      shape_count
per shape:
  u32    block                (NiTriShape block-array index)
  u16    orig_vertex_count    (must equal the shape's NiTriShapeData)
  u16    orig_triangle_count  (ditto)
  u16    n_move, n_uv, n_add_vertex, n_remove_triangle, n_add_triangle
  n_move        × { u16 vertex; f32 x, y, z }           shape-local
  n_uv          × { u16 vertex; f32 u, v }              UV set 0
  n_add_vertex  × { f32 x, y, z; f32 u0, v0; f32 u1, v1; f32 r, g, b, a }
  n_remove_tri  × { u16 triangle }                      original index
  n_add_tri     × { u16 a, b, c }                       final vertex indices
```

Added vertices take indices `orig_vertex_count + i`. The final triangle list is
the surviving original triangles **in original order**, then the added ones.
UV1 / colour fields are ignored when the shape has no second UV set / colours.
Vertices are never removed (an orphan is harmless).

### 6.2 Copyright posture

The payload holds no original position, UV, colour or triangle — only indices
into them, plus geometry Mark authored. It is useless without the original. The
OBJs (which do contain BC geometry) live only in the session scratchpad.
*(Not legal advice.)*

---

## 7. Loader

`apply_shape_edits` in `native/src/assets/src/mesh_fix.cc`, called by
`apply_mesh_fix` after merges, under the same all-or-nothing contract: validate
everything first, mutate only if all passes. Refuses (warn once, load the
original) when:

- the payload's base64/magic/length is malformed;
- a block is out of range, not a `NiTriShape`, or its data is unresolved;
- `orig_vertex_count` / `orig_triangle_count` differ from the NIF;
- any vertex or triangle index is out of range, or a triangle is removed twice;
- the final vertex or triangle count exceeds 65 535;
- an added triangle is degenerate (repeated index or zero area);
- the shape has authored normals (none on DBridge — out of scope);
- a data block is also used by a merge.

After applying: recompute the shape's bound centre/radius; clear match groups.

---

## 8. Testing

| Test | Kind | Asserts |
|---|---|---|
| Apply on a synthetic `nif::File` | gtest | moves, uv edits, added verts (with/without colours, 1 or 2 UV sets), removed + added tris, order |
| Each refusal in §7 | gtest | file unchanged in memory, error returned |
| Real `Dbridge.NIF` + committed fix | gtest, asset-backed (`content_root.h`) | applies with `""`; hash matches file stem |
| Export → simulated Blender round-trip → diff | pytest, synthetic meshes | identity map is exact; moves/adds/removes recovered; reorder/deletion is refused |
| Payload encode | pytest + gtest | Python encoder and C++ decoder agree on a golden blob |
| Drift guard | existing pytest | skips files whose `generator` isn't `tools/gen_mesh_fixes.py` (shape-edit inputs are never committed, so they can't be regenerated) |

**Inspection:** `bridge_shape_diff preview` writes the patched set as an OBJ to
the scratchpad; in game, Developer Options → Lighting → Bridge Debug View
(triangle id / mesh id / normals).

---

## 9. Iteration log

| # | Goal | Status | Notes |
|---|---|---|---|
| 1 | Move-only gap closing: export, diff, loader end to end | not started | |
| 2 | Turbolift header reshape: triangle remove/add | — | |
| 3 | Extruded side panels: new verts/tris/UVs | — | Open: side-face texturing. Lean: collapse the new faces' UVs onto the panel border (stretch edge texels, no new texture); alternative: a project-owned trim texture |
