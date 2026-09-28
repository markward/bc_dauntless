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
