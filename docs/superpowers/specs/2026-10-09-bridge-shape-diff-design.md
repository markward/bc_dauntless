# Bridge Shape Diff — design (living spike spec)

**Date:** 2026-10-09
**Status:** spike COMPLETE in practice — six DBridge rounds plus flipbook accepted live by Mark (2026-10-09/10); toolchain supports moves, UV edits, face add/remove, vertex deletion, new vertices, references, per-shape albedo + flipbook, apply-and-compare verification. Branch not yet merged to `main`. **Start with §11 (runbook + current state)**; §§1–10 are the design record and partly historical.
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
| Shape transforms | shape blocks themselves are identity, but the **composed world matrix** (shape × every ancestor `NiNode`) is non-identity for 92 of 145 shapes: 61 are a pure 180° rotation (mostly about X, a few about Y), 12 a pure 90° about Z, 6 a pure ≈30.5° about Z, and the rest compose rotations about more than one axis; scale is always 1 | Model↔local must invert the **full** `nif_block_world`, not just translation |
| Match groups | none | Nothing to keep consistent |
| Load path | `host_loop.realize_set` → `load_model(..., interior=True)` → `AssetCache::load` → `apply_mesh_fix` → `build_model` | Fixes already apply to sets; normal gen + T-junction repair run after the edit |
| Duplicate triangles | **7,628 of 8,580** DBridge triangles are exact duplicates (same vertex indices, same winding) | Blender keeps only one copy on import, so a move or UV edit affects both copies automatically (the diff records the original-vertex index, not the triangle); but any future triangle **removal** must remove every duplicate of that triangle, or the dropped copy keeps rendering |

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
(triangulation optional — n-gons are ear-clipped, iteration 3). Don't reorder
vertices (Sort Elements, or separating part of an object and joining it back):
the diff relies on Blender keeping survivors in order (§5.2) and refuses an
object whose order it can't explain.

---

## 5. Diff

### 5.1 base.obj → original NIF (identity)

Every face corner of `base.obj` is mapped back to BC model space (inverse axis
swap), then per object to an original vertex of that shape by (snapped
position, UV0 within 1e-5). **100 % of corners must match**, else the tool
refuses and names the first unmatched corner. Each base OBJ vertex thus owns
the set of original vertices it welds (its seam duplicates).

### 5.2 edit.obj → base.obj (correspondence)

~~Original plan (superseded by 2a below): by Blender vertex index, refusing
any deletion.~~

**As built 2a (superseded by iteration 3 below):** deletions are accepted. Equal vertex counts
still correspond by index. With **fewer** edit vertices, Blender has deleted
some and renumbered the survivors **preserving their relative order**, so the
tool walks the edit vertices in order and, for each, advances through the base
vertices until one sits at the same position (L∞ ≤ `POS_TOL`); the skipped
base vertices are the deleted ones. An edit vertex that finds no match (a
survivor also moved, or vertices were added as well) is refused ("can't align
vertices after deletion"). **More** edit vertices are refused ("new vertices
are iteration 3"). Every face comparison below runs in base indices, through
this correspondence.

**Current rule (as built iteration 3, revised in fix round 1, 2026-10-09) --
`match.correspond`.**

1. **Fast path:** equal counts and every vertex at its own index unmoved →
   identity (the iteration-1 behaviour, and the common case).
2. **Anchors, in any order.** An edit vertex and a base vertex whose
   positions coincide (L∞ ≤ `POS_TOL`) **one-to-one in both directions** are
   paired regardless of order. Separate/join can hand survivors back in a
   different order (b0395 cove_graphic came back with its two columns
   swapped), and a unique position settles them. A new vertex placed exactly
   on a deleted original is anchored to it too -- the output is identical
   either way.
3. **Leftovers** (moved survivors, new and deleted vertices, non-unique
   position claims) go through the **order-preserving** (monotone) matching
   that maximises agreement. Every (edit, base) pair gets an integer score,
   independent of the rest of the matching: **4** same position, **+2 per
   edit neighbour** sitting where one of the base vertex's neighbours sits,
   **+1** when the pair already scores and a corner UV of one equals a corner
   UV of the other (only a tie-breaker), and **+4 proximity** when the two
   are each other's strictly nearest candidate (no bonus on a tie). The
   proximity term is what lets a survivor that moved a little beat a new
   vertex that merely shares more neighbours with the original (b0688: the
   new bottom midpoint shares two neighbours with the moved top-left corner,
   which shares one with its own moved self -- 4 vs 2+4). The heaviest
   monotone chain is found exactly (Fenwick tree over base index), with the
   number of distinct optima.
4. **Non-unique optimum:** keep only the pairs every optimum shares (a pair
   whose removal lowers the optimum); the rest stay unpaired. A contested
   pair that is a **position claim** (the edit vertex sits on the base
   vertex) is refused ("ambiguous correspondence"): nothing else can say
   which of two coincident originals survived.
5. **Winding check:** an edit face that lands, under the pairing, on a base
   face wound the other way is told apart by geometry (fix round 2). If it
   still **faces the same way** (Newell normals agree), a corner sits on the
   other side of its opposite edge: the original was deleted and a new
   vertex took its neighbours (b0395, new vertices below a deleted middle
   row) -- its non-anchored pairings are undone and its faces re-derived as
   added. If it **faces the other way**, it is a real flip of a surviving
   face (a normal flipped in Blender, e.g. on a moved corner): the pairing
   stays and the flipped kept face is refused as before -- never shipped as
   a back-face. **Qualified (parked minor, Task 15 ledger):** this holds for
   the face under test, not its neighbours. Undoing a same-facing pairing
   un-pairs its corner, and every face touching that corner is re-derived
   as added -- so a GENUINE flip on a *neighbouring* face of an un-paired
   corner can pass as an added back-face (needs a folded mesh plus a
   deliberate flip; not seen on Mark's data). Enforcing it means checking
   every face touching an about-to-be-unpaired corner.
6. **Face propagation** (an unmatched vertex completing a base face, same
   winding, unique candidate) and **equal gaps** (a run facing as many
   unmatched base vertices, accepted only if every touching face maps onto a
   base face with the same winding) as before; order windows count only the
   non-anchored matches.
7. An original left unpaired at the position of a non-anchored pair's edit
   vertex is refused (two coincident originals, one survived: unsettled).
   The old "unmatched edit vertex on an unmatched base vertex" refusal is
   **gone** -- survivor vs new-on-that-original give identical output.

Every unpaired edit vertex is new, every unpaired base vertex deleted. A
pairing the score gets wrong still yields the edited geometry -- every face
is re-derived through the matching -- and the **verify step (§5.4) now
proves that** for each fix, instead of the argument this section used to
rest on. Scratch fuzz (400 random delete/move/add trials on DBridge objects,
against ground truth): no survivor paired with the wrong original, no
refusal; 61 new↔deleted pairings and 4 survivors left unpaired, all of
which re-derive the same faces.

### 5.3 Classification, per shape

| Change | Recorded as |
|---|---|
| base vertex whose position changed | `move`: every original vertex it welds → new position (shape-local, inverted in float64, stored f32) |
| corner UV changed on a kept vertex | `uv`: original vertex → new UV0 |
| vertex appended in Blender | `add vertex`: position (reference or literal), UV0 (reference or literal), `attr_src` -- the target shape's original nearest in model space (ties → lowest index) whose colour and UV1.. it copies. A new vertex with several distinct corner UVs becomes one added vertex per UV (iteration 3; the OBJ colour is ignored -- it was BC data) |
| original triangle with no matching edit face | `remove triangle` (original index) |
| edit face not matching an original triangle | `add triangle` (indices into the final vertex array) |

An original triangle "matches" an edit face when its three original vertices
map to the face's three corners with the same winding.

**Iteration 1, as built:** `diff` records `move` and `uv` together (a single
edit can move vertices and re-map UVs at once); it refuses anything that
needs topology (`add vertex`, `remove triangle`, `add triangle`) and a UV
edit that would need a vertex split -- one original vertex whose corners
disagree on the new UV (both iteration 2+). The tool prints a per-shape
summary (`block N: M vertices moved, K UVs changed`).

**Iteration 2a, as built (2026-10-09):** faces are compared by **vertex set**
(base indices). Present in both → today's move/UV handling (a set whose
winding differs is refused: "changed winding"). A base set with no edit face
is a **removed face**: every NIF triangle whose three vertices lie in three
distinct corners' weld groups is removed -- duplicates, reversed twins and
twins on a UV-seam copy alike -- because `write_obj` exports exactly those
triangles onto that face and Blender collapses them into one (§2's duplicate
row). This deliberately does **not** filter by corner UV (the brief's rule):
a collapsed twin with different UVs would otherwise survive and keep the
deleted face rendering. A removed face that resolves to no NIF triangle is
refused. Removals are de-duplicated and sorted. An edit set that isn't a base
set is an **added face**: it must be a triangle (n-gons are refused,
"triangulate before export" -- the codebase has no ear-clipper) and each
corner must be an **existing original** at that position whose **final** UV
(NIF UV0 with this same diff's `uv` edits applied) equals the corner's UV
(1e-5; several → the lowest index), else it is refused as iteration 3 ("needs
a new vertex/UV"); a corner showing the *old* UV of an original this diff
re-maps is refused as needing two different UVs (a vertex split). A
removed/added face touching an OBJ vertex whose identity group overlaps
another OBJ vertex's (two vertices within `POS_TOL` straddling a weld
boundary; none on stock DBridge) is refused -- the NIF triangles can't be
picked out unambiguously. It is emitted in the edit face's
winding; a repeated index or zero area (`|cross| ≤ 1e-10` on final shape-local
positions -- `mesh_fix.cc`'s own rule) is refused at diff time. A deleted
base vertex contributes nothing; orphaned original vertices are left in
place, never emitted. Summary line:
`block N: M vertices moved, K UVs changed, R triangles removed, A added`.

**Iteration 2b, as built (2026-10-09) -- per-shape albedo.** `read_objects`
also records, per face, the material in effect (`usemtl`) resolved through
the `.mtl` named by `mtllib` (read beside the OBJ; missing file -> no texture
info) to its `map_Kd` file **basename** -- compared case-insensitively, never
by material name (Blender renames to `.001`; the directory differs between
source trees). Per object: if every edit face uses one and the same albedo
basename and it differs from the base object's, a texture op
`{block, albedo}` is recorded, alongside any moves/UVs/topology on the same
object. Faces split across two or more albedos (or an albedo and none) are
refused ("per-face material split isn't supported -- one texture per
object"); an object with no `map_Kd` records nothing. The file must be a
`.tga` (the NIF loader decodes TGA only) and must exist -- case-insensitive
name match -- in the **replacements overlay dir mirroring the NIF's texture
dir** (`mods.replacements_root()/<nif dir>/High`) or the **stock** one
(`paths.game_root()/<nif dir>/High`); else the object is refused, naming the
file and both dirs. Mod dirs are deliberately not searched: the fix applies
with or without a mod. Summary line gains `, texture -> <name>`; a block
with only a texture op prints `block N: texture -> <name>`. **Albedo only:**
emissive / glow maps are deliberately out of scope (the PBR plan decides
`_glow` vs `_emissive`). Because the loader applies BC's filename
conventions to any image (`*_glow` → Base + Glow, `*_spec[ular]` → Gloss
only, `*_norm[al]` → Bump only; case-insensitive on the extension-less stem),
an albedo with one of those suffixes is **refused** ("would bind as glow; an
albedo op takes a plain diffuse") -- by the diff and again by the loader.
An OBJ whose `mtllib` names a file that isn't there is a **file-level** error
(aborts even with `--partial`): a missing base `.mtl` would otherwise make
every textured object look retextured. An OBJ with no `mtllib` line carries
no texture info and records no texture ops. A **base** object whose faces
span two albedos is refused (base.obj must be the unaltered export).

**Flipbook (Task 16, 2026-10-09).** When a recorded albedo's basename is
`<stem>_0.<ext>` (case-insensitive) and the same two dirs, by the same
case-insensitive existence rule, hold `<stem>_1.<ext>`, `<stem>_2.<ext>`, ...
the contiguous run (stopping at the first gap; at most 256) of N >= 2 frames
is recorded with the texture op as `flipbook: {frames, fps}`. Frame 0 is the
albedo as the `.mtl` names it (the loader requires `albedo == frames[0]`);
frames 1.. are the names found on disk. A run of one, a name not ending in
`_0`, or `_00` record a plain albedo op. `fps` is `--flipbook-fps` (CLI,
default 5 -- Mark's ruling for the LCARS strip; `build_fix(...,
flipbook_fps=5.0)`), refused unless finite and > 0. Summary line:
`texture -> running_0.tga (flipbook 12 frames @ 5 fps)`. The verifier
(§5.4) is unchanged: `nif_shapes` reports a flipbook shape's texture as its
frame 0 (below), which is what the albedo check compares.

**Iteration 3, as built (2026-10-09).**

- **References (§6.2).** A position within `POS_TOL` of an ORIGINAL vertex
  of ANY shape (model space) is stored as a reference to it -- the target
  shape's own originals first, then the lowest block, then the lowest index.
  This applies to moves (a vertex snapped onto another to close a gap
  becomes `move → ref`), added vertices and split vertices. A UV0 equal
  (1e-5) to the UV0 of the position's reference vertex is a reference to
  that same vertex; else to the lowest target-shape original **at that
  position** with that UV0; else (**an extension of the brief**, same value,
  keeps BC's number out of the payload) to the lowest target-shape original
  anywhere with that UV0; else a literal.
- **New vertices** (§5.2's unmatched edit vertices) used by added faces
  become added vertices, one per distinct corner UV. A loose new vertex on
  no face records nothing. A corner with no UV is refused.
- **Split vertices (new in iteration 3).** An added face corner on a
  *survivor* whose UV matches no original's final UV -- which 2a refused as
  "needs a new vertex/UV", and the "old UV of a re-mapped original" case 2a
  refused as a vertex split -- becomes an added vertex at the survivor's
  final position (a reference when unmoved) with the corner's UV and
  `attr_src` from the nearest original. A UV conflict on a **kept** face is
  still refused as before (re-pointing NIF triangles is out of scope).
  *(Lifted in iteration 6 -- see §11.6: a kept face that would split an
  original is removed and re-added through this same path.)*
- **N-gons.** Added faces with more than 3 corners are ear-clipped
  (`tools/shape_diff/triangulate.py`, ported from the parked spike) on the
  corners' edit positions in the polygon's dominant plane, keeping its
  winding. Unlike the spike it never falls back to a fan: a polygon with no
  ear, no area, or ears that don't tile its area (self-intersecting) is
  refused. The zero-area check then runs per triangle as before.
- **`--exclude BLOCK`** (repeatable; `exclude=` on `build_fix` / `match.diff`)
  leaves the block out before any diffing -- even an object that would be
  refused -- and prints `excluded: blocks N, M`. Excluding a block with no
  object in the export is a file-level refusal (a typo would otherwise be
  silent).
- Summary line: `block N: M vertices moved[ (R by reference)], K UVs
  changed, R triangles removed, A added, V vertices added[ (R by
  reference)]` -- "by reference" counts positions that ARE an original
  (snapped, kind 1); the rest are an original plus a delta (kind 2, §6.1).
- **Dead records dropped (fix round 1).** A move or UV edit on an original
  that no surviving or added triangle uses renders nothing and is not
  written (e.g. a moved survivor whose every face was re-added with new UVs
  as split vertices -- b0688's top corners).
- **A removal never lands without its replacement (fix round 1).** An
  object left out of the fix (skipped by `--partial`, or `--exclude`d) whose
  edit puts a new or moved vertex where a triangle REMOVED by an included
  block had a corner was that removal's replacement (b0395 re-making b0392's
  faces). Such blocks are left out too -- under `--partial` listed as
  `skipped` with "depends on skipped/excluded <object>", repeatedly until
  nothing changes; without `--partial` a dependency on an excluded block is
  refused ("exclude it too").

**`--partial`:** by default a single unsupported object (one that needs
topology, or a vertex-split UV conflict) aborts the whole diff -- nothing is
written. `diff BASE EDIT --partial [--write]` instead diffs every object
all-or-nothing *per object*: objects whose change is a plain move/UV edit are
recorded as normal, and every object whose `diff_shape` call refused is
**skipped and reported** (`skipped (not yet supported):` followed by
`  <object>: <reason>` lines) rather than aborting the run. `--write` with
`--partial` writes the fix built from the recorded (supported) edits only; a
skipped object leaves no trace in the fix file, and is unaffected by any
earlier fix for the same object committed in a prior round. File-level
problems (renamed/missing objects, two objects mapping to one block, an
import that isn't a clean shape export, a block that isn't in the NIF) still
abort the whole run in `--partial` mode exactly as without it -- those mean
the export itself is broken, not that one object's edit is unsupported.

### 5.4 Verify (fix round 1)

`build_fix` (dry run and `--write` alike) applies the fix it built through
the loader's own code -- `_dauntless_host.nif_shapes(path, fix_json)` runs
`parse_mesh_fix` + `apply_mesh_fix` in memory (a refusal raises with the
loader's reason) -- and checks (`tools/shape_diff/verify.py`):

- every block **not** in the fix is identical to stock;
- per edited object, the applied triangles equal edit.obj's faces (n-gons
  through the same `ear_clip`): corners compared as model-space position
  snapped to the 1/1024 weld grid and UV0 to 1e-5, rotation-canonical,
  degenerate triangles dropped, grouped by position set because Blender
  shows one face per set (NIF duplicates, reversed and seam twins collapse):
  every edit triangle must be one of its set's applied triangles, and the
  sets must agree both ways; a corner one grid/UV step off still matches
  (rounding across a cell boundary);
- each texture op binds its albedo;
- (fix round 2) wherever the fix ADDS a triangle (the loader appends them
  last), that position set holds exactly the added triangles: an original
  left on the same three positions -- a reversed or seam twin of the face
  Mark replaced -- is refused. Sets the fix doesn't add to keep the
  stock-collapse tolerance above.

Any difference refuses the run before anything is written, naming the
object and the first differing triangle; success prints `verified N
objects`. A warning lists survivors paired without position agreement per
block -- only pairs that produce a move record, and never an index-identity
pair in a block with no deletions (a plain move). Verification needs the host module; the CLI
refuses without it (never skipped silently), and only unit tests opt out
with `verify=False`.

---

## 6. The fix file

Same file as today: `native/assets/mesh_fixes/<fnv1a64>.json`.
The tool writes payload **BSD2** since iteration 3; the loader still reads
BSD1 (the fix committed in rounds 1c–4b is BSD1 until it is regenerated). `merges` becomes
optional; a file needs at least one of `merges` / `shape_edits` / `textures`.
Still `format` 1.

```json
{
  "format": 1,
  "source": "data/Models/Sets/DBridge/Dbridge.NIF",
  "generator": "tools/bridge_shape_diff.py",
  "shape_edits": "<base64 of the binary payload>",
  "textures": [{"block": 29, "albedo": "g_imp_connops.tga"}]
}
```

`textures` (2b, optional, sorted by block, written only when non-empty) gives
one NiTriShape its own albedo: a **bare** `.tga` filename resolved through the
model's texture search dirs exactly like a stock NiImage. The host's bridge
search list is `paths.game_asset_dirs(env)`, which already puts the
replacements overlay dir first (pinned by
`tests/host/test_realize_set.py::test_realize_set_bridge_texture_dirs_include_the_replacements_overlay`),
so a file that exists only in the overlay is found. `shape_edits` is omitted
when the diff holds texture ops but no geometry.

A `textures` entry may carry `"flipbook": {"frames": ["running_0.tga", ...,
"running_11.tga"], "fps": 5.0}` (Task 16): the shape's albedo then loops
through `frames` at `fps`. Frames follow the `albedo` name rules, 2..256 of
them, `frames[0] == albedo`; `fps` finite and > 0. A texture filename is a
name, not BC data, so it doesn't change §6.2.

**Not human-readable by design** (Mark's ask): the edits are one packed binary
blob, base64-encoded. No compression — no new dependency on either side.

### 6.1 Payload layout (little-endian)

**BSD2 (written since iteration 3).** Same header and per-shape counts as
BSD1 below; the move, uv and add-vertex records change so positions/UVs can
be references:

```
position := u8 kind; kind 0: f32 x, y, z         (literal, shape-local; read only)
                     kind 1: u32 src_block, u16 src_vertex   (reference)
                     kind 2: u32 src_block, u16 src_vertex, f32 dx, dy, dz
                             (reference + TARGET-shape-local delta)
uv0      := u8 kind; kind 0: f32 u, v             (literal)
                     kind 1: u32 src_block, u16 src_vertex   (reference)
n_move        × { u16 vertex; position }
n_uv          × { u16 vertex; uv0 }
n_add_vertex  × { position; uv0; u16 attr_src }
n_remove_tri  × { u16 triangle }                 (unchanged)
n_add_tri     × { u16 a, b, c }                  (unchanged)
```

A position reference is that ORIGINAL vertex's position carried
src-shape-local → model → target-shape-local through `nif_block_world`
(double precision; an exact copy when src is the target shape), plus the
kind-2 delta. **Since fix round 1 the encoder never writes kind 0**: a
position that coincides with an original is kind 1; every other move is
kind 2 off the moved vertex's own original, and every other added vertex is
kind 2 off the target shape's nearest original (its `attr_src`). The
decoder still reads kind 0. A uv
reference is that original's UV0. `attr_src` is an ORIGINAL vertex index of
the TARGET shape whose colour and UV sets 1.. the new vertex copies
(replacing BSD1's literal uv1/colour -- those were BC data). Any other kind
byte is refused at decode, and a uv kind 2 likewise. Golden: one blob with
every kind the encoder writes (positions 1 and 2, uvs 0 and 1), pinned
byte-identical in `tests/tools/test_shape_diff.py` (`GOLDEN_B64`, built by
hand with `struct`, not by the encoder) and
`native/tests/assets/cpu/mesh_fix_parse_test.cc` (`kGoldenBsd2B64`); a
second C++-only blob (`kBsd2Kind0B64`) keeps kind-0 positions decoding.

**BSD1 (read only):**

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

**Iteration 3 closes two gaps.** (1) A vertex Mark **snaps** onto an original
vertex (gap closing), or a new vertex placed on one, used to be stored as a
literal -- i.e. BC's coordinate. BSD2 stores it as a **reference** (§5.3's
iteration-3 rule), so the payload stays index-only even for snapped and
coincident vertices; likewise a UV equal to an original's. (2) Added
vertices no longer carry colour/UV1 values: they copy them from an original
named by `attr_src`. What remains literal is only what Mark authored: a
UV that coincides with no original's.

**Fix round 1 (controller's posture decision):** positions are never
literal. A position that is no original's is written as an original plus
the offset Mark authored (kind 2) -- the moved vertex's own original for a
move, the nearest original for a new vertex -- so no absolute coordinate,
BC's or otherwise, is in the payload; a delta is meaningless without the
original it is added to.

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
- a data block is also used by a merge;
- (BSD2) a kind-2 delta is non-finite; a reference's block is out of range, not a `NiTriShape`, or its
  data is unresolved/inconsistent; its vertex is not below that shape's
  ORIGINAL vertex count (a vertex that only exists after this same fix
  adds it is refused); a uv reference's shape has no UV set 0; `attr_src`
  is not below the target's original vertex count; a literal is non-finite.

**References read the unmodified file.** Every edit is validated and its
references resolved to concrete values *before* any merge, edit or texture
op mutates anything, so a reference into a shape the same fix edits still
reads that shape's ORIGINAL data (pinned by
`MeshFixShapeEditRef.RefIntoAShapeTheSameFixEditsReadsTheOriginalPosition`).

After applying: recompute the shape's bound centre/radius; clear match groups.

**Texture ops (2b).** Validated with the same contract, before any mutation:
block in range and a `NiTriShape`; `albedo` non-empty, a bare filename (no
`/` or `\`), extension `.tga` (case-insensitive); each block at most once in
`textures` (a texture op may share its block with a shape edit -- texture
and geometry are independent); no reserved suffix (`_glow`, `_specular`,
`_spec`, `_normal`, `_norm` on the stem, mirroring `model_build.cc`); and the
block is not a merge's (hidden) patch. Applied last: append an external `NiImage`
(`file_name` = albedo, other fields at the parser's defaults) and an
`NiTextureProperty` (flags 0, as every stock DBridge one) pointing at it, with
fresh link ids (`max(block_ids) + 1, + 2`), and push the property's link onto
the shape's **own** `property_links`. `gather_material_inputs` visits a
shape's own links before any ancestor's, so it wins over the inherited
texture while its siblings keep theirs -- no renderer change was needed.
`File::root` is re-pointed at block 0 after the append (it is a raw pointer
into `blocks`). Tests: `native/tests/assets/cpu/mesh_fix_texture_test.cc`
(synthetic sibling isolation; every refusal leaves the file unchanged; real
`Dbridge.NIF`: block 29 samples the swap while 59 keeps `Map 22.tga`, and all
four round-2b targets 29/45/59/479 take a swap -- none is overridden by an
ancestor `NiMultiTextureProperty`).

**Flipbook texture ops (Task 16).** Extra validation, same all-or-nothing
contract: 2..256 frames, each a valid albedo name (bare, `.tga`, no reserved
suffix), `frames[0] == albedo`, `fps` finite and > 0. Applied as BC's **only
stock flip controller** is authored (`EBridge.nif`: `NiTextureProperty` 549
-> `NiFlipController` 550, 8 LCARS frames; no stock ship has one -- the
Sovereign example in `model_build.cc` is a mod): a `NiTextureProperty`
(flags 0, **`image_link` 0**, `controller_link` -> the controller), a
`NiFlipController` (`flags` 0x0009 = active, cycle type loop; `frequency` 1,
`phase` 0, `start_time` 0, `delta` = 1/fps, `stop_time` = N x delta, as the
stock N x delta; `texture_slot` 0; no next controller; the v3.1 target field
`unknown_integer` = the property's link id, as stock), then one external
`NiImage` per frame (parser defaults, as stock). Fresh ids in append order
`max(block_ids) + 1 ..`; the property is linked onto the shape. `model_build`
already turns that into `Model::texture_animations` + `Material::
animation_index`, drawing source 0 as the static Base when `image_link` is
0, and every Base-binding pass (bridge included) samples
`animated_base_texture` -- no renderer change. The host's `nif_shapes`
binding (which the verifier reads) now mirrors that source-0 substitution;
before Task 16 it fell through to the ancestor's texture for such a
property. Tests: `native/tests/assets/cpu/mesh_fix_flipbook_test.cc`
(parse; frame k at t = k/fps and the wrap at N/fps; sibling untouched;
every refusal leaves the file unchanged; spliced fields; the stock EBridge
controller has exactly the mirrored shape; real `Dbridge.NIF` b0688
animates `Map 7` / `Map 8`).

---

## 8. Testing

| Test | Kind | Asserts |
|---|---|---|
| Apply on a synthetic `nif::File` | gtest | moves, uv edits, added verts (with/without colours, 1 or 2 UV sets), removed + added tris, order |
| Each refusal in §7 | gtest | file unchanged in memory, error returned |
| Real `Dbridge.NIF` + committed fix | gtest, asset-backed (`content_root.h`) | applies with `""`; hash matches file stem |
| Export → simulated Blender round-trip → diff | pytest, synthetic meshes | identity map is exact; moves/adds/removes recovered; references, new vertices, splits, ear clipping, correspondence (deletion + move + add, translated island, reorder and tie refused), `--exclude` |
| BSD2 references on real `Dbridge.NIF` | gtest + pytest, asset-backed | a cross-frame reference (block 11 → rotated block 24) lands on the referenced vertex's model position; a new vertex snapped onto block 24 is diffed as a reference |
| Payload encode | pytest + gtest | Python encoder and C++ decoder agree on a golden blob |
| Drift guard | existing pytest | skips files whose `generator` isn't `tools/gen_mesh_fixes.py` (shape-edit inputs are never committed, so they can't be regenerated) |

**Inspection:** `bridge_shape_diff preview` writes the patched set as an OBJ to
the scratchpad; in game, Developer Options → Lighting → Bridge Debug View
(triangle id / mesh id / normals).

---

## 9. Iteration log

| # | Goal | Status | Notes |
|---|---|---|---|
| 1 | Move-only gap closing: export, diff, loader end to end | accepted 2026-10-09 (live, via 1c) | |
| 1b | UV re-map of console seats (b0224/b0255) | tool support built; Mark's first edit turned out to hold no UV changes — unused so far | `diff` now records `uv` alongside `move`; the loader (`apply_shape_edits`) already applied `uv` records before this task -- only the Python side refused them |
| 1c | First live step: moves on b0468 (13 NIF verts) / b0652 (28) / b0663 (28) | accepted by Mark in game 2026-10-09; fix `dbcdbd4a43dc5a56.json` committed | Console sliver b0170/b0175 needs triangle add/remove (next) |
| 2a | Triangle add/remove on existing vertices (console sliver b0170/b0175) | accepted by Mark in game 2026-10-09: b0175 loses NIF tris 4+5 (the squashed sliver, stored twice), b0170 gains (22, 9, 32) on existing originals/UVs; committed in fix `dbcdbd4a43dc5a56.json` with 1c's moves | Removal takes every NIF copy of the face (duplicates, reversed and seam twins); added triangles must sit on existing originals with existing UVs; vertex deletion aligned by order (§5.2) |
| 2b | Per-shape albedo texture op (console top panels b0029/b0059 → g_imp_connops, wall inset slots b0045/b0479 → g_imp_redbars) | accepted by Mark in game 2026-10-09 (round 4b): textures + UVs on b0029/b0059 (g_imp_connops), b0045/b0479 (g_imp_redbars), b0063 (Map 22b), b0189/b0236/b0415 (Map 22c); back wall b0017 UV re-map on replaced Map 7 | `textures` field in the fix file (§6, §7); diff records it by `map_Kd` basename, one per object, file must exist in the overlay or stock dir (§5.3). Emissive/glow deliberately out of scope |
| 2 | Turbolift header reshape: triangle remove/add | superseded — the capability shipped as 2a/3; the header itself was not reworked as a separate round | |
| 3 | Extruded side panels: new verts/tris/UVs | superseded — new vertices shipped as row "3 — new vertices + refs"; side panels not yet extruded | Open: side-face texturing. Lean: collapse the new faces' UVs onto the panel border (stretch edge texels, no new texture); alternative: a project-owned trim texture |
| 3 — new vertices + refs (cove b0392/b0395, LCARS b0688/b0697, b0471) | New vertices, BSD2 references (snapped moves become refs), robust correspondence, n-gon ear clipping, `--exclude`; b0392's removals land with b0395's rework | accepted by Mark in game 2026-10-09 (round 5): verified 21 objects; cove b0392+b0395, black panel b0471 (Map 22a), LCARS b0688 (running_0, static until flipbook) + b0697 (g_imp_redbars), seat panels b0121/b0124 (Map 22a); payload has no absolute coordinates | §5.2/§5.3 iteration-3 rules, §6.1 BSD2. Expect previously committed blocks unchanged except snapped moves turning into references. The `running_0..11` flipbook on b0688 is row 4 |
| 4 — flipbook (LCARS b0688 running_0..11 @ 5 fps) | Animated albedo: a numbered frame run becomes a looping `NiFlipController` | accepted by Mark in game 2026-10-09: b0688 cycles running_0..11 at 5 fps on game time (stock EBridge flip-controller shape) | `textures[].flipbook` (§6, §7); detection §5.3; fps 5, continuous loop (Mark 2026-10-09) |
| 5 — roof rebuild (Mark's 'modified and enhanced' round) | Roof structure b0475 remodelled (352 moved, 239 new verts, 136 tris out / 444 in, own Map 28), new 32-gon roof centre b0051 on replaced Map 1, roof light ribs b0076/81/84/87/90 moved, seat backs b0244/b0267 and b0326 rebuilt | accepted by Mark in game 2026-10-09; verified 31 objects | Generated from a scratch copy with b0475_roof_structure.001 renamed to b0051_roof_center_hole (Mark renamed it in the .blend; his next export must reproduce this fix). Open: vertex colour of off-position survivors comes from the paired/nearest original — not verified (OBJ has no colours) |
| 6 — consoles, ribs, seat panels | Console bases b0331/b0352 re-unwrapped and rebuilt, roof ribs b0076/81/84/87/90 moved, seat panels b0121/124 onto Map 22d, consoles b0175/203/491/506 onto Map 4a | committed on Mark's go-ahead 2026-10-10; verified 41 objects, nothing skipped | Needed two tool changes: same-UV copies at one corner are told apart by their source NIF triangle (b0331 vertex 2 was a false split), and a genuine seam through an original vertex now SPLITS it (§11.6) instead of refusing. Generated from Mark's re-export after renaming b0337/b0358 `.001` back to b0331/b0352 and moving one stray Map 28 face to Map 17 |
| 7 — UV re-maps + roof rib b0087 | UV-only re-maps on b0149/157/161/165/179/207 (new to the fix); roof rib b0087 reworked (36 moved, 7 new verts, 28 tris out / 14 in); b0471 re-encoded, same op counts | accepted by Mark in game 2026-10-14; verified 47 objects, nothing skipped | Generated from `Dbridge/Dbridge_modified_and_enhanced_rexport.obj` (Mark's working files now live under `~/Documents/dauntless-blender/Dbridge/`) with no tool changes and no new textures |
| 8 — ceiling rebuild, wall insets, consoles | New ceiling b0081 (all-new geometry on reworked Map 13); roof b0475 rebuilt on Map 3; roof ribs b0084/b0090 deleted; white light panels on spare shapes (roof panels on b0087, rear-wall panel split from b0102 on b0076, both Map 13); walls b0468 on Map 3; wall insets b0652/b0663 rebuilt (left mirrored from right); helm consoles joined into their bases (right into b0331, left into b0352; helm displays b0340/343/361/364 emptied); console seats b0224/b0255, side panels b0488/b0503, com sides b0024/b0056 UV re-maps | accepted by Mark in game 2026-10-17; verified 64 objects, nothing skipped | Needed two tool changes: `--delete BLOCK` empties a shape whose object was deleted (explicit -- a missing object is indistinguishable from a join), and coincident consecutive corners from an unwelded mirror seam are collapsed before ear clipping (§11.6). Generated from a scratch copy of `Dbridge/Dbridge_CEILING_replaced.obj` with `b0475_roof_structure.001`→b0087, `b0102_wall_rear_panel_04.001`→b0076, `b0343_Material_console_helm_4`→b0331 renamed and the empty `path1.002` dropped; flags `--delete 84 --delete 90 --delete 340 --delete 343 --delete 361 --delete 364`. Lighting: b0090's orphaned panel light removed, b0076 linked to `roof (Map 13)`. A subdivided b0468 was tried and reverted: the dark soffit band is the baseline downlight (`down_bottom` 0.25 on down-facing surfaces, confirmed in Light Only view), not geometry -- open, to be lit per-bridge |

---

## 10. As built (iteration 1)

> **Historical.** Written after iteration 1; several limits below ("new vertices are refused", "topology is refused") were lifted later. §11 is current.

- **No separate preview step.** §8's `preview` subcommand was dropped: Blender's
  own `edit.obj` export already *is* the preview (reopen it, or diff and inspect
  the fix). `bridge_shape_diff.py` ships only `export` and `diff`.
- `diff` records **moves and UV0 edits** (and, since 2a, removed faces and
  added triangles on existing vertices -- §5.3); new vertices are refused
  as iteration 3. A corner UV change is paired with its original
  vertex by matching the NIF's own UV0 for that vertex (seam duplicates at
  the same position can disagree on UV; the corner's UV, not just its
  position, says which original it is) and recorded as a `uv` edit --
  except when one original vertex's corners disagree on the new value,
  which needs a vertex split and is refused as iteration 2. This matters
  because Blender's Vertex/Edge Slide defaults to "Correct UVs", which
  silently drags UVs along with a gap-closing move: that case is now
  recorded correctly rather than refused.
- Textures resolve through **ancestor `NiNode`s**, not just the shape's own
  property links — DBridge's `NiTextureProperty` sits on the parent, not the
  shape (§2's "Shape names" row). The walk mirrors the renderer's own
  (`model_build.cc:gather_material_inputs`): nearest ancestor with any texture
  wins, and a shape that already has its own texture is never touched by it.
- **Workflow notes for Mark:**
  - Import the exported OBJ into an **empty** scene — delete Blender's default
    Cube/Camera/Light first, or `diff` refuses with "not a shape export".
  - Export `base.obj` **before** entering Edit Mode, and `edit.obj` after.
  - Keep the `.blend` and `base.obj` somewhere **durable outside the repo**
    — the session scratchpad is wiped between sessions.
  - **Iteration-2 hazard:** `diff` always compares `edit.obj` against the
    *unpatched* NIF (via `base.obj`), and `--write` replaces the whole fix
    file rather than merging into it. A later editing session must therefore
    reopen the **same `.blend`** that holds every earlier move — diffing a
    fresh export against a fresh edit would silently drop prior edits from
    the committed fix.
- **Incremental workflow (Mark approved 2026-10-09):** one `.blend`, edited a
  little at a time. `base.obj` is exported once, right after import, and kept
  fixed for the whole series; each round Mark edits a few more objects in the
  same `.blend` and re-exports `edit.obj` over the previous one. Because
  `base.obj` never changes, each `diff base.obj edit.obj --write` regenerates
  the **whole** fix file from scratch against the NIF — cumulatively, not as
  a delta — so every earlier move/UV edit still present in the `.blend` is
  recorded again alongside the new ones. `--partial` is what makes this safe
  to run mid-series: objects the tool can't diff yet (anything needing
  topology, today) are skipped and listed instead of blocking the whole
  round's `--write`.

---

## 11. Runbook and current state (2026-10-10) — READ THIS FIRST

### 11.1 What exists

| Piece | Where |
|---|---|
| CLI | `tools/bridge_shape_diff.py` (`export`, `diff [--partial] [--exclude B]... [--delete B]... [--flipbook-fps F] [--write]`) |
| Library | `tools/shape_diff/` — `obj_io` (OBJ/MTL read/write), `match` (identity, correspondence, classification), `payload` (BSD1/BSD2 encoder), `frames`, `triangulate` (ear clip), `verify` (apply-and-compare) |
| Loader | `native/src/assets/src/mesh_fix.cc` — `shape_edits` (BSD2 decode/validate/apply, refs resolved against the UNMODIFIED file), `textures` (per-shape albedo splice + optional `flipbook` NiFlipController shaped like stock EBridge block 550) |
| Binding | `_dauntless_host.nif_shapes(path, fix_json=None)` — world matrix, parent, colours, UV1, inherited textures; applies a fix in memory when given one (used by the verifier) |
| The DBridge fix | `native/assets/mesh_fixes/dbcdbd4a43dc5a56.json` (generator `tools/bridge_shape_diff.py`; the drift test skips it; `AssetCacheMeshFix.EveryCommittedFixApplies` guards it) |
| Project textures | `native/assets/replacements/data/Models/Sets/DBridge/High/` — tracked via the narrow `.gitignore` exception `!native/assets/replacements/data/Models/Sets/**/*.tga` (`*.tga` stays ignored elsewhere) |
| Emissive maps | not part of the diff: `<albedo stem>_emissive{,_y,_r}.tga` siblings, bridge PBR spec §9.7 |

### 11.2 Mark's working files (outside the repo — BC geometry never enters git)

`~/Documents/dauntless-blender/`:
- `Dbridge_unmodified_rexport.obj/.mtl` — **the fixed base**. Exported from Blender right after importing the tool's export, never re-exported. Every diff runs against it.
- `Dbridge_modified_and_enhanced_rexport.obj/.mtl` — the current edit (round 6). Earlier rounds used `Dbridge_modified_rexport.obj`; the name is whatever Mark exports, pass it explicitly.
- `fixed-3.blend` — the live `.blend` holding EVERY accepted edit. Future rounds must continue in it (see 11.4).
- `Dbridge.obj/.mtl` — the tool's original export (input to Blender).

### 11.3 One round

```
cd <worktree>
uv run python -m tools.bridge_shape_diff diff ~/Documents/dauntless-blender/Dbridge_unmodified_rexport.obj ~/Documents/dauntless-blender/<edit>.obj --partial
```
1. Read the dry run: per-block summary, `verified N objects`, `skipped` list, warnings. Investigate every `skipped`/`refused` before writing (see 11.5).
2. `--write` regenerates the WHOLE fix cumulatively from base → edit (it never merges). It refuses to overwrite a fix owned by another generator, and refuses to write if verification fails.
3. Mark checks in game (`./build/dauntless --developer` from the worktree; no rebuild needed for fix/texture changes — they are read at load).
4. Only after Mark accepts: commit the fix + any new textures together, and add a §9 row.

### 11.4 Rules for the Blender side

- Import into an EMPTY scene. Don't join, split or rename objects. If Blender produces a `.001` object (join/separate), rename it back to the `bNNNN_...` shape it replaces before exporting — otherwise `diff` stops at the object-set check. (Rounds 5 and 6 needed this: `cove_black.001`→`b0395_Material_cove_graphic`, `Lcar_02.001`→`b0697_...`, `roof_structure.001`→`b0051_roof_center_hole`.)
- New albedo: set the material's Base Color to a `.tga` in the overlay folder (only the FILENAME matters). Never a reserved suffix (`_glow`, `_spec(ular)`, `_norm(al)`, `_emissive*`). A `<stem>_0.tga` with `_1`, `_2`… beside it becomes a flipbook (default 5 fps, game time, loops).
- One albedo per object (per-face material splits are refused). Keep the `.mtl` beside the `.obj` — a missing named `mtllib` aborts the diff.
- Flipping a face's winding is refused (it would ship as a back-face).

### 11.5 Reading refusals

| Message | Meaning / action |
|---|---|
| `objects differ between base and edit` | a join/split/rename — rename the `.001` back (11.4). If objects are only MISSING and the message suggests `--delete N`, check they were deleted on purpose (their vertices appear in no other object), then pass those flags |
| `ambiguous correspondence` | the tool can't tell which originals survived — it refuses rather than guess; `--exclude` that block to land the rest |
| `depends on skipped/excluded bNNNN` | a block's triangle removals need another block's replacement; they land together or not at all |
| `texture '…' not found` | the `.mtl` names a file not in the overlay/stock dir (often an old name or a main-checkout path) |
| `would bind as glow/gloss/bump` | albedo uses a reserved suffix — point Base Color at the plain diffuse |
| verifier mismatch | the produced fix does not reproduce `edit.obj` through the real loader — a tool bug; do not write |

### 11.6 Known limitations (parked, with rulings)

- **Deleted objects (2026-10-14).** Deleting a whole object in Blender is
  explicit: `--delete BLOCK` stands an empty object in for it and every
  triangle the export carries is removed (a NIF triangle that is zero-area once
  welded never reaches the OBJ and stays, rendering nothing). Without the flag
  the export still refuses -- a missing object is indistinguishable by name
  from an accidental join. First use: ceiling rebuild, ribs b0084 + b0087.
- **Unwelded mirror seams (2026-10-14).** Consecutive face corners at the SAME
  position (Blender's `-0.0`/`0.0` copies on an unmerged x=0 seam) are
  collapsed before ear clipping; a face that collapses below three corners is
  dropped (no area). Non-consecutive coincident corners (a polygon touching
  itself) are still refused. The duplicate vertices themselves are kept, so
  generated normals may show a crease on the seam -- Merge by Distance in
  Blender removes it.

- **Vertex splits (iteration 6).** An original vertex whose kept faces disagree on
  its new UV (a seam BC never cut) keeps the UV most of its corners show (tie:
  the lowest face key); every face showing another UV there is removed (all NIF
  copies) and re-added, that corner becoming an added vertex placed by reference
  to the original. Several originals at one position sharing ONE UV (BC's
  side/end/top copies) are told apart by the NIF triangle each face came from,
  not by UV -- they are not splits.

- **Vertex colour / UV1 of new or re-paired vertices** comes from the paired or nearest original (`attr_src`). Not verified — Mark's OBJs carry no colours. If remodelled areas (e.g. roof b0475) show colour patches, that's the cause.
- **Flip cascade:** unpairing a corner for the genuine-deletion case (§5.2 step 5) can carry a deliberate flip on a NEIGHBOURING face through as an added back-face. Needs a folded mesh plus deliberate flips; not seen in data.
- **Dependency guard is one-way:** `--exclude 392` lets b0395's additions land over b0392's unchanged faces (overlap, not a hole).
- **Survivor snapped onto an earlier DELETED vertex** can mis-align (refusal or identical geometry only).
- **Literal UVs** are authored values (allowed); positions are never absolute (refs or deltas).
- **Emissive** on a flipbook shape is static (frame 0's stem).

### 11.7 Before merging `spike/bridge-shape-diff` into `main`

- The **main checkout** has UNTRACKED older copies in `native/assets/replacements/data/Models/Sets/DBridge/High/` (e.g. `g_imp_connops01.tga`, `g_imp_redbars_glow.tga`, `Map *.tga`) that collide with tracked files on this branch — move them aside first or git refuses the merge.
- Run `scripts/check_tests.sh` on the merged result.
