# Hull Name-Cut Fix — design

**Date:** 2026-09-28
**Status:** design agreed, spec under review
**Branch:** `feat/hull-name-cut-fix`
**Follow-up (separate spec):** hull names as model-space projected decals.

---

## 1. What this changes, and why

BC paints a Federation ship's registry ("U.S.S. DAUNTLESS NCC-71879") by cutting a
small **ID patch** out of the saucer mesh and giving it its own texture. At spawn,
`ReplaceTexture(new, "ID")` swaps that texture for a named one (`Dauntless.tga`,
`Enterprise.tga`, …). This lets a name cross the saucer's mirror line even though
the saucer texture is mirrored.

The cost is a visible seam: the patch uses a separate, lower-resolution texture
(the Sovereign's is 128² against the saucer's 256²), so the hull changes texture
at the cut, and glow and normal maps can't be matched across it.

This design **erases the cut at load time**. The patch is merged back into the
saucer shape and given UVs into the original saucer texture. The stock `.nif` in
the BC install is never modified. The correction ships as a small project-owned
fix file, applied after parsing.

**Accepted consequence:** on patched hulls, `ReplaceTexture("ID")` matches no
texture, so **stock Fed ships show no registry name** until the decal follow-up
lands. This was an explicit choice: ship the cleanup enabled by default and accept
nameless hulls in the meantime.

---

## 2. Measured findings this design rests on

All measured on the stock NIFs with a scratch probe linked against our own
`libnif` (2026-09-28).

### 2.1 The patch is a cut, not an overlay

Every stock Fed hull carries one ID shape whose border vertices coincide exactly
with saucer vertices. The **High and Medium** LODs both have one. **Low** LODs
have none.

| Ship | High patch | Medium patch |
|---|---|---|
| Galaxy | 25 v / 30 t, borders `Saucer Section:1` + bridge module | 9 v, borders 3 shapes |
| Nebula | 90 v / 30 t (flat-shaded) | 9 v, borders 2 shapes |
| Sovereign | 21 v / 24 t | 6 v |
| Akira | 6 v / 4 t | 7 v |
| Ambassador | 36 v / 12 t (flat-shaded) | 6 v |

### 2.2 The saucer UVs under the patch can be rebuilt

Fit against **only the texture region of the neighbour that the patch borders**
(vertices joined into regions by matching position *and* UV):

| Ship | Saucer mapping | Fit error |
|---|---|---|
| Galaxy | top-down, mirrored (\|x\|) | 7e-7 (exact) |
| Nebula | same texture as the Galaxy, mirrored | 8e-7 (exact) |
| Sovereign | main saucer region, mirrored | 7e-7 (exact) |
| Akira | top-down, **not mirrored** | 5e-7 (exact) |
| Ambassador | nearly flat, mirrored | 1.7e-2. Patch has no interior vertices, so most UVs copy directly from seam twins |

The Sovereign needs the region step. Its patch also borders a thin separate strip
of the same texture (the sloped band by the deck ring), and fitting across both
at once fails. Its inner edge stays a texture seam against that strip, as the rest
of the strip already is.

Hull detail **is painted under the patch** in the saucer texture. This has been
visually confirmed for the Galaxy (so the Nebula too) and the Sovereign. The
Akira and Ambassador overlays are unchecked.

The Sovereign's `Ent-E-dishtopbottomID_glow.tga` is an unmirrored resample of
`Ent-E-dishtopbottom_glow.tga`: at the same hull point the median difference is
3/255, with 81% of texels within 16. `Enterprise.tga` and `Sovereign.tga` differ
from it only in the lettering (about 5% of pixels, alpha identical).

### 2.3 Smoothing: mostly intact, except possibly the Sovereign

| Ship | Saucer-side seam vertex normals | Other seams |
|---|---|---|
| Galaxy | 13/13 identical | bridge module: real 63° crease |
| Nebula | identical | bridge module: real crease |
| Ambassador | faceted to match (whole saucer flat-shaded) | 60° crease to body |
| Akira | 6/10 identical; rest are real creases to the arms | — |
| Sovereign | **6/20 identical**, including the 70° strip edge | **may be genuinely broken** |

---

## 3. Architecture and data flow

```
nif::load(path) ──► apply_mesh_fix(file, fix) ──► build_model(file, ctx)
                         ▲
    fnv1a64(nif bytes) ──►  native/assets/mesh_fixes/<fnv1a64>.json  (absent ⇒ no-op)
```

- **Hook point:** `AssetCache::load` (`native/src/assets/src/cache.cc`), between
  `nif::load` and `detail::build_model`. This is the only call site that needs it.
  The hull-volume (`.dhv`) bake reads positions only, which the merge doesn't
  change. The set-camera, animation and officer loaders never load Fed hulls.
- **Lookup is by content hash** of the raw NIF bytes. A mod that reuses a stock
  mesh unchanged is fixed too. A mod that edits the mesh has a different hash and
  is left alone, with no separate guard needed. Stock meshes only.
- **Merge, applied to the parsed `nif::File`:**
  1. Append the patch's vertices (rebuilt UVs, normals, vertex colours if
     present) and triangles to the target shape's `NiTriShapeData`, transformed
     into the target's frame if the two shapes have different parents.
  2. Weld only the listed seam pairs, collapsing each into the target's vertex
     and remapping the appended triangles.
  3. Clear the target's `match_groups`, which the merge makes stale.
  4. Set the patch shape's hidden flag (`0x0001`). `build_model` already skips
     hidden shapes (`model_build.cc`), so no parent child list is edited and
     **node indices don't change**.
- **Cache key:** the fix file's hash is appended to the `AssetCache` key, like
  `replacements_key`, so patched and unpatched loads of one path never share an
  entry.
- **Knock-on effects the plan must verify:**
  - Mesh indices after the hidden patch shift down by one. Confirm that nothing
    persists or hard-codes a mesh index.
  - `apply_texture_replacements`' "no texture matching 'ID'" warning must print
    **once per model**, not on every spawn.

---

## 4. The fix file

`native/assets/mesh_fixes/<nif-fnv1a64>.json`, one per patched mesh:

```json
{
  "format": 1,
  "source": "data/Models/Ships/Galaxy/Galaxy.nif",
  "generator": "tools/gen_mesh_fixes.py",
  "merges": [{
    "patch":  {"block": 61, "name": "Ent-D Saucer Section:9"},
    "target": {"block": 14, "name": "Ent-D Saucer Section:1"},
    "method": "planar-mirrored",
    "max_fit_error": 7.1e-7,
    "uvs":    [[0.9834, 0.4765], "... one per patch vertex ..."],
    "weld":   [[0, 37], "... (patch vertex, target vertex) ..."],
    "normals": null
  }]
}
```

The block numbers and values above are illustrative; the generator produces the
real ones.

| Field | Meaning |
|---|---|
| `patch.block`, `target.block` | Block indices. Safe to use directly because the file hash pins the layout. |
| `patch.name`, `target.name` | Second check. A mismatch refuses the fix. |
| `uvs` | One `[u, v]` per patch vertex, in the patch's own vertex order. Literal numbers; nothing is recomputed at load. |
| `weld` | Seam pairs to collapse. Emitted only where position, rebuilt UV and normal are all identical, so creases are never welded. |
| `normals` | Optional per-vertex override for the patch. `null` unless a live check shows it's needed (candidate: the Sovereign). |
| `method`, `max_fit_error` | Provenance, for review and tests. Ignored by the loader. |

---

## 5. The generator — `tools/gen_mesh_fixes.py`

Run by hand; it writes the fix files that get committed.

- **Geometry source:** a new read-only binding, `_dauntless_host.nif_shapes(path)`,
  which returns each shape's block index, name, parent, texture names, vertices,
  normals, UVs and triangles, using the real C++ parser.
- **Maths:** plain Python least squares (at most 4 unknowns per axis). No new
  dependency; the project has Pillow and nothing else.
- **Per patch:**
  1. Find the shape using an `ID` texture.
  2. Group the neighbour's vertices into texture regions (joining vertices that
     match in position + UV).
  3. Pick the region with the most shared vertices.
  4. Try a mirrored, then unmirrored, top-down fit. Accept a fit only if its
     error is below 1e-4.
  5. Otherwise use `seam-copy`: copy seam twins' UVs and interpolate interior
     vertices from the border, weighted by inverse edge length.
- **Target choice:** the shape owning the chosen region. `--target <shape name>`
  overrides it, for Medium LODs that border several shapes.
- **Review output:** for each fix, a PNG of the target texture with the rebuilt
  patch drawn over it, written to a scratch directory (never `native/assets`).
  The texture is the one the engine would actually load, so the Akira uses
  `native/assets/replacements/.../AkiraSaucerTop_glow.tga`.
- **Scope:** a fixed list of the 10 stock meshes (5 hulls × High and Medium).
  Anything without an ID shape is refused.

---

## 6. Error handling

A bad fix never breaks a spawn. Every failure warns once and loads the
**unpatched** mesh. A fix is refused whole, never half-applied, when:

- the JSON doesn't parse, or `format` is unknown;
- a block index is out of range, or its name doesn't match;
- `len(uvs)` ≠ the patch's vertex count, or `normals` is present with the wrong
  length;
- a weld index is out of range;
- the merged vertex count would exceed 65,535 (16-bit indices).

---

## 7. Testing

| Test | Kind | Asserts |
|---|---|---|
| Merge on a synthetic `nif::File` | gtest | vertices/triangles appended; only listed pairs welded; patch hidden; `match_groups` cleared |
| Each refusal case in §6 | gtest | file left byte-identical in memory, one warning |
| No fix file present | gtest | `build_model` output identical to today |
| Cache key | gtest | patched and unpatched loads of one path are distinct entries |
| Real `Galaxy.nif` + committed fix | gtest, asset-backed (`content_root.h`, baselined skip) | no visible mesh uses an `ID` texture; saucer vertex count = old + patch − welds; welded seam vertices have identical normals |
| Fitting and region grouping | pytest | a known synthetic mirrored / unmirrored projection comes back exact; seam-copy on a synthetic patch |
| Drift guard | pytest, asset-backed | rerunning the generator reproduces every committed fix file byte-for-byte |

Gate: `scripts/check_tests.sh` before merge.

**Live check (Mark):** each of the 5 hulls at High and Medium LOD. The seam
should be gone and there should be no lighting line across the saucer. The
Sovereign's result decides whether it gets a `normals` override. Until that's
done, status is "merged, not live-verified".

---

## 8. Out of scope

- **Names.** Re-adding registries as model-space projected decals is the
  follow-up spec.
- Mod ships and non-Fed hulls.
- Low LODs (no ID patch).
- Changing the hull-volume bake, damage voxels or any texture file.

## 9. Open items for the plan

- Resolved: FNV-1a 64 (the tree's existing content hash, used by the `.dhv`
  cache) and nlohmann/json via FetchContent (no JSON parser existed).
- Where fix files resolve from at runtime: the project asset root
  (`set_project_asset_root`), never the BC install.
- Medium-LOD target choices (Galaxy Med borders 3 shapes): decided per mesh from
  the review PNGs.
- Visual check of the Akira and Ambassador overlays before their fix files are
  committed.
- CLAUDE.md reference-table row.

---

## 10. As built (deviations from §§2–7)

Implementation surfaced several decisions §§2–7 didn't anticipate. This
section is authoritative where it conflicts with the sections above; §§1–9
are left as the original design record. Sourced from the SDD ledger
(`.superpowers/sdd/2026-09-28-hull-name-cut-fix/progress.md`), Rulings 3–8
and the 2026-09-28 Mark-decisions entry.

### 10.1 Scope is High LOD only — 5 fixes, not 10

§5 scoped the generator to "10 stock meshes (5 hulls × High and Medium)".
Mark's dry-run decision narrowed this: **the engine never loads Medium or Low
meshes** (confirmed against the loader), so a Medium-LOD fix file would never
be looked up at runtime. Scope is the **5 High-LOD meshes only** — one fix
file per hull: Galaxy, Nebula, Sovereign, Akira, Ambassador. `tools/
gen_mesh_fixes.py`'s `STOCK_MESHES` and the committed `native/assets/
mesh_fixes/*.json` both hold exactly 5 entries; `TARGET_OVERRIDES` is empty
(no committed fix needed one).

### 10.2 Akira is included, with a stock-texture caveat

Mark's decision also settled the Akira, left open by §2.2 ("Akira and
Ambassador overlays are unchecked"): included. Mark's local replacement
texture for the Akira saucer is clean under the patch, but **the stock**
`AkiraSaucerTopID_glow.tga` **sits over `NCC-63471`** — a different ship's
registry baked into the base texture. The fix still erases the seam; a
player running unmodified stock content will see that baked-in registry
until the decal follow-up (§8) re-adds the correct one.

### 10.3 Stock NIFs resolve via `game_root()`, not `game_asset()`

Ruling 5: the generator, the drift-guard test, and the C++ gate test all
resolve source NIFs as `paths.game_root() / rel` (Python) /
`test_support::game_root() / rel` (C++) — **never** `paths.game_asset(rel)`.
`game_asset` prefers a mod/replacement override when one exists, which would
compute a fix against content different from what's committed and drift the
hash. Fixes are stock-only by design (§3: "Stock meshes only"), so this is
deliberate, not an oversight of the general paths rule. Cost if wrong: none
observed for the 5 stock ships; a future case-sensitive filesystem would need
a case-insensitive lookup for `Nebula.NIF` (the file is capitalized
differently than the other four `.nif` files, and macOS/Windows are already
case-insensitive).

### 10.4 Multi-merge role refusal (not cumulative-offset support)

§6 lists the all-or-nothing refusal rules; fix-round-1 review of Task 2 found
a gap not in that list: two merges in the same fix that both touch one
`NiTriShapeData` block (as a target used twice, a patch used twice, or one
merge's patch being another's target) would corrupt the second merge's index
remap, because `validate_merge` plans against the *pre-merge* vertex count.
Ruling 3 chose the cheap fix over threading a cumulative append offset
through repeated use: **`apply_mesh_fix` refuses the whole fix if any
`NiTriShapeData` block appears in more than one role across its merges.**
Every stock fix is a single merge, so this costs nothing today — a future
mesh needing two patches merged into one target would need the fuller
(cumulative-offset) implementation. Implemented as the `data_block_owner`
check in `mesh_fix.cc`; covered by `MeshFixApply.RefusesWhenTwoMergesShareTargetData`.

### 10.5 `normals` overrides are patch-local, not target-local

Ruling 4: `MeshFixMerge::normals`, where present, is one override vector per
patch vertex, **in the patch's own local frame** — rotated into the target
shape's frame the same way the patch's own `NiTriShapeData` normals are
(`n_to_target`, §3's step 1). This was the natural reading given the
generator authors overrides from patch-local data, and every committed fix
emits `null` (no override was needed on any of the 5 — see §2.3's "Sovereign
may be genuinely broken" note, which turned out not to require one). A
hand-authored override in a target-local frame would land rotated; none
exist.

### 10.6 Twin-count ranking, then fit quality

§5 step 3 said "pick the region with the most shared vertices." Ruling 7(a)
made this explicit as a two-key sort: **rank candidate target regions by
twinned-patch-vertex count first**, breaking ties only by fit success. A
"twin" is a patch vertex whose position and UV both coincide with a
candidate region's vertex (`_LOCAL_FIT_TOL` = 5e-3 GU, shared with welding).
This is `build_fix`'s candidate sort key
`(num_twinned, fit_ok, region_count)` in `tools/gen_mesh_fixes.py`.

### 10.7 The `local-fit` method

§5 step 4 only described a global mirrored/unmirrored top-down fit, accepted
below `1e-4`. The Ambassador's saucer mapping is only *nearly* planar
(~1.7e-2 error globally — §2.2) and the `seam-copy` fallback (§5 step 5)
collapsed its 16 body-only vertices to degenerate slivers, so Ruling 7(b)
added a third method, tried after the global fit fails:

1. **Window:** every chosen-region vertex within `_LOCAL_FIT_RADIUS_FRAC`
   (0.05) × the patch's own world-bbox diagonal of **any** patch vertex — a
   distance *ring* around the patch, not an expanded bounding box (a plain
   bbox expansion was tried first and rejected; see `fix(tools): local-fit
   window is a distance ring, not a bbox expansion`).
2. **Fit:** least-squares plane fit restricted to that window, tried
   mirrored then unmirrored, `xy` then `xyz`. Accepted if `max_fit_error <=
   _LOCAL_FIT_TOL` (5e-3 GU).
3. **Snap:** every patch vertex with an exact twin in the chosen region is
   then snapped to that twin's own UV, so the shared seam is always exact
   even though the fitted interior is only approximate.

Ruling 8 fixed the window radius by measurement on the Ambassador: `d < 10`
GU (≈ 0.05 × 206, the patch's diagonal) gives 34 twinned vertices and a
mirrored-xyz fit error of 2.0e-3; `d < 50` gives 7.1e-3; the whole region
gives 1.7e-2 (the mapping drifts away from the patch at that range). The
Ambassador's committed fix uses `local-planar-mirrored` at `max_fit_error =
4.37e-3` (\~4.4e-3) — inside the window's tolerance, worse than the other
four ships' near-exact global fits, but the only one of the 5 that needed
this method. UV error from the fit stays inside the patch interior; the seam
itself is snap-exact by construction.

Even a fit that passes its tolerance is only constrained AT the vertices it
was fitted against — nothing stops it extrapolating past them for a patch
vertex further out than the region reaches. `AmbassadorSaucer_glow.tga`
packs unrelated content on the other side of the saucer region's own UV
footprint (a texture half-split at u≈0.5), and the Ambassador's local fit put
one hub-end centreline vertex at u=0.48952, just outside — below — the
chosen region's own u range, sampling that unrelated content and drawing a
thin dark radial line on the live-verified hull. `build_fix` now clamps
every patch vertex's UV into `[min, max]` of the chosen region's own
vertices (computed before the float32 round, after any fit method), fixing
that vertex to u=0.49947 — the region's true minimum, not the ~0.5 this
paragraph's diagnosis eyeballed. Snapped twins already lie inside the range,
so the clamp is a no-op for them and for all 4 exact-fit ships.

### 10.8 The 5 committed fixes

| Ship | Patch → target | Method | `max_fit_error` | Welds |
|---|---|---|---|---|
| Galaxy | `Ent-D Saucer Section:9` → `Ent-D Saucer Section:1` | `planar-mirrored` | 1.86e-7 | 13 |
| Nebula | `Nebula Hull:11` → `Nebula Hull:7` | `planar-mirrored` | 2.23e-7 | 0 |
| Sovereign | `top o dish:5` → `top o dish:1` | `planar-mirrored` | 4.24e-7 | 6 |
| Akira | `Akira - Saucer:3` → `Akira - Saucer:1` | `planar-xyz` | 8.72e-8 | 6 |
| Ambassador | `amb saucer:3` → `amb saucer:0` | `local-planar-mirrored` | 4.37e-3 | 6 |

The Nebula's 0 welds is deliberate, not a miss: the Python weld-normal gate
(`0.9999` dot product) is tighter than the C++ apply-time gate (`0.999`,
`mesh_fix.cc`'s "weld normals differ" rule), and the Nebula's seam-vertex
normal dots measure 0.9993–0.9997 — inside the C++ tolerance but outside the
generator's, so no weld pair is emitted for it. The seam UVs are still
continuous either way (rebuilt UVs match the neighbour's exactly at every
seam vertex; welding only affects whether the *vertex* itself is shared or
duplicated). Loosening the Python gate (e.g. to `0.9995`) is safe either way
and was left for a live check to decide (deferred, not yet done).

### 10.9 Tests as actually written (§7 update)

The asset-backed real-mesh tests in `native/tests/assets/cpu/cache_test.cc`
diverge from §7's table in one respect: §7 specified an exact arithmetic
assertion ("saucer vertex count = old + patch − welds"). As built,
`AssetCacheMeshFix.RealGalaxyLosesItsIdPatch` instead asserts:

- `fixed->meshes.size() + 1 == plain->meshes.size()` (the patch shape is
  hidden and skipped by `build_model`),
- `fixed->materials.size() + 1 == plain->materials.size()` (the patch's own
  material disappears with it),
- `verts(fixed) < verts(plain)` (a strict *decrease*, not an exact count) —
  welding removes duplicate seam vertices, but pinning the precise arithmetic
  in a gtest would recouple the test to the exact weld count, which is a
  property of the fix data, not of `apply_mesh_fix`'s contract.

The final review wave (this section's own source) added a second,
fix-file-driven test, `AssetCacheMeshFix.EveryCommittedFixApplies`, closing
the gap that only the Galaxy fix had ever been exercised against real
content. For every `*.json` under `native/assets/mesh_fixes/`, it: reads the
fix file's `source` field, resolves it under `test_support::game_root()`
(§10.3), asserts the filename stem equals `fnv1a64_hex` of the real NIF's
bytes, asserts `apply_mesh_fix` returns `""` against a fresh `nif::load` of
that file, and — through two `AssetCache`s (one plain, one configured with
`mesh_fix_dir` pointing at the committed directory) — asserts the fixed
model has exactly one fewer mesh than the plain one. It also pins the
committed-fix count at exactly 5 (§10.1). The drift guard
(`tests/tools/test_mesh_fixes_drift.py::test_committed_fixes_match_generator_output`)
covers §7's last row unchanged: rerunning the generator over `STOCK_MESHES`
must reproduce every committed fix file byte-for-byte.
