# Hull Name Decals — design

**Date:** 2026-09-28
**Status:** design agreed, spec written
**Branch:** `feat/hull-name-decals` (forked from `feat/hull-name-cut-fix`)
**Builds on:** `docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md`

---

## 1. What this is

`feat/hull-name-cut-fix` merges each stock Fed hull's "ID" name patch back
into its saucer. As a result, `ReplaceTexture(".../Zhukov.tga", "ID")` matches
nothing and the hulls render nameless. This feature brings names back as
**model-space projected decals**: a PNG mask per registry, placed by a
per-class JSON, drawn by the opaque shader over the hull's own texture.

**Scope of this first cut (Mark, 2026-09-28):** the **Ambassador only**, and
the **top-saucer** placement only. Masks for its other placements (bottom,
nacelle, pylon) exist but aren't declared yet. The other four stock Fed
hulls stay nameless until their masks are drawn.

## 2. Look

Where the mask's alpha covers the hull:

| Channel | Behaviour |
|---|---|
| Albedo | **replaced**: `base.rgb = mix(base.rgb, mask.rgb, mask.a)` |
| Glow / window map | **unchanged**: a lit window under a letter still glows |
| Material emissive | unchanged formula; it's modulated by the (now mask-coloured) base, as today |
| Normal map | unchanged |
| Specular | **paint sheen**: `+ mask.a × kDecalPaintSpecular (0.8) × paint_spec_acc`, computed even when the material has no specular map, using the material's own specular power |

Paint is glossy and the hull is matte: the name catches the light as the ship
turns.

**Implementation note:** mask RGB is **premultiplied by alpha at load**, and
the albedo composite is `base.rgb·(1−a) + mask.rgb_premultiplied`. That's the
same result as the straight-alpha `mix` for opaque texels. Without it,
bilinear and mip filtering would pull the black RGB of transparent texels
into the letter edges as a dark halo.

## 3. Files and authoring

Per ship class, beside its NIF, under `data/Models/Ships/<Class>/Masks/`.
These are resolved through the normal game / mod / project-replacement
overlay (`paths.game_asset`), which is a precedence chain, not an
additive union: **project replacements outrank mods** for any path both
supply, so a mod cannot override the stock Ambassador's own
`Masks/Zhukov/top.png` or `decals.json`. A mod CAN still add value on top
of a stock-folder class: it may ship a new registry folder
(`Masks/<NewRegistry>/top.png`) for a placement `decals.json` already
declares, and that resolves normally since the project tree has no
same-path file to shadow it with. What a mod CANNOT do is put decals on
its own NIF: this whole feature is gated on the mesh-fix cache key, which
is keyed by the **stock NIF's content hash** (`native/assets/mesh_fixes/
<hash>.json`) — a mod-folder NIF (different bytes, a different file
entirely) never matches a committed fix, the fix never "applies", and
`AssetCache::load` (`native/src/assets/src/cache.cc`) skips decals
whenever no fix applied, warning once. The stock Ambassador's masks live
in the project replacements tree:
`native/assets/replacements/data/Models/Ships/Ambassador/Masks/`.

```
Masks/
  decals.json            which decals exist on this class, and where
  Zhukov/top.png         artwork, one folder per registry
  Excalibur/top.png
  (bottom/nacelle/pylon.png present, unused until declared)
  templates/*.svg        Mark's authoring templates; not read by the engine
```

### 3.1 `decals.json`

```json
{
  "format": 1,
  "decals": {
    "top": {
      "shape":  "amb saucer:0",
      "origin": [x, y, z],
      "u_axis": [x, y, z],
      "v_axis": [x, y, z],
      "normal": [x, y, z],
      "depth":  d
    }
  }
}
```

- All vectors are in the **ship-body frame**, the frame `opaque.frag`'s
  `p_body` lives in: model space with every NIF node transform applied, and
  the instance's world placement and scale removed.
- `origin`, `u_axis` and `v_axis` span the mask rectangle:
  - mask (0,0) = `origin`;
  - (1,0) = `origin + u_axis`;
  - (0,1) = `origin + v_axis`.

  Mask v runs down the image, row 0 at the top.
- `normal` is the direction the decal faces, pointing outward from the hull
  surface. Only surfaces whose normal has `dot(n, normal) > 0` receive it.
- `depth` is the slab half-thickness along `normal` around the rectangle's
  plane. It stops the projection reaching the far side of the saucer.
- `shape` is the NIF shape name whose material carries the decal. On the
  Ambassador that's the merged saucer (`amb saucer:0`).
- The **declared keys** of `decals` are the placements. Each is looked up as
  `<Registry>/<placement>.png`.

### 3.2 Registry selection

A BC script calls `ReplaceTexture("Data/Models/Ships/Ambassador/Zhukov.tga", "ID")`.
- The registry is the **file stem**: `Zhukov`.
- The mask folder is `<model's own folder>/Masks/Zhukov/`, where the model's
  folder is the parent of the NIF being loaded.
- For each declared placement `p`, the artwork is `Masks/Zhukov/<p>.png`.

The Ambassador class default (`DEFAULT_REGISTRY_BY_CLASS`, from
`MissionLib`) is Zhukov. `E3M1` spawns "USS Excalibur" with `Excalibur.tga`.

### 3.3 The first `decals.json`

It's written by `tools/gen_mesh_fixes.py` and hand-editable afterwards. For
each hull with masks (the Ambassador), for the `top` placement:

1. **Where BC's name lived.** Fit the ID patch's original ID-texture UVs to
   its ship-body positions: an affine map `p → (s, t)` on the patch's
   best-fit plane (the Ambassador fits to ~1e-3).
2. **Where BC's lettering sat.** Diff the stock default-registry texture
   (`Zhukov.tga`) against the blank ID texture
   (`AmbassadorSaucerID_glow.tga`). The bounding box of the changed pixels
   is BC's lettering box in ID-texture space.
3. **Where Mark's lettering sits.** Take the alpha bounding box of
   `Zhukov/top.png`.
4. **Fit.** Place the mask so its lettering-box centre lands on BC's
   lettering-box centre, with **uniform** scale matching BC's lettering
   width.

   **Orientation is derived, not assumed.** BC's `Zhukov.tga` stores the
   lettering rotated 180° relative to the mask as authored. The generator
   scores the mask in the four aspect-preserving orientations (identity,
   rotated 180°, flipped in u, flipped in v) by the overlap (IoU) of its
   lettering with BC's lettering, both resampled into BC's lettering box,
   and uses the best. Isolated stray differing texels (fewer than 2 differing
   8-neighbours) are dropped from BC's lettering first.
5. **To ship-body space.** Map the mask rectangle's corners through the
   inverse of the plane fit to get `origin`, `u_axis` and `v_axis`.
   `normal` is the plane normal, oriented outward (same side as the patch's
   vertex normals). `depth` = 2.0 model units unless the plan's measurement
   says otherwise.

Every registry of the class reuses this placement.

## 4. Runtime flow

1. **Python** (`engine/appc/hull_decals.py` and `engine/host_loop.py`):
   - `engine/appc/registry_texture.py` is **unchanged**: the `("ID", path)`
     queue and `replacements_for(ship)` are exactly what they were before
     this feature.
   - The actual new entry point is
     `hull_decals.decals_for(nif_rel_dir, registry) ->
     [(shape, origin, u_axis, v_axis, normal, depth, mask_abs_path), …]` --
     it takes the NIF's own BC-relative folder and an already-resolved
     registry name, not a ship or a nif_path.
   - `host_loop._ship_decals(nif_path, reps)` is the glue between the two:
     it derives `nif_rel_dir` from `nif_path` (relative to `game_root()`,
     `[]` if that fails -- a mod-overlay NIF outside the BC tree), takes the
     **last** queued `"ID"` path's stem as the registry via
     `hull_decals.registry_stem(reps)`, and calls `decals_for`. Both of its
     call sites (`realize_set_objects` and
     `_reconcile_runtime_instances`) pass the result to
     `renderer.load_model(..., decals=…)`.
   - `decals_for` itself reads `decals.json` and resolves each declared
     placement's mask through `paths.game_asset` (checking that it exists).
2. **Host binding** (`load_model_impl`):
   - It accepts the decal list, and the host dedupe key includes it.
3. **Asset cache and build:**
   - `AssetCache::load` gets a `std::vector<DecalRequest>` whose key joins
     the cache key (like `replacements_key`).
   - `build_model` does the following for each request:
     1. decodes the mask with `assets::decode_image`;
     2. uploads it with mipmaps;
     3. sets `Material::stages[Decal0].texture_index` on every material of
        the named shape;
     4. stores the projector on that material: a `mat4` from ship-body to
        mask `(u, v, w)`, plus the normal.
4. **Draw** (`frame.cc`): for a material with a Decal0 stage:
   - it binds the mask on **texture unit 8**;
   - it sets `u_decal_mask_enabled`, `u_decal_proj`, `u_decal_normal` and
     `u_decal_depth`;
   - otherwise it sets `u_decal_mask_enabled = 0`.
5. **Shader** (`opaque.frag`):
   - compute `q = u_decal_proj · p_body`;
   - `inside = q.u, q.v ∈ [0,1] && |q.w| ≤ depth && dot(n_body, u_decal_normal) > 0`;
   - sample with `textureGrad`, the gradients taken from `dFdx`/`dFdy` of
     `p_body` **outside** any branch (the scuff-decal pattern);
   - albedo and paint specular as in §2.

   `paint_spec_acc` reuses the directional- and dynamic-light specular maths
   with the material's `u_specular_power`, evaluated only when
   `u_decal_mask_enabled != 0`.

`ReplaceTexture("ID")` keeps working on **unpatched** models that still have
an ID texture (mod ships). On patched hulls it matches nothing; the
warn-once from the cut-fix branch applies.

## 5. Errors

Nothing in this feature can stop a ship from loading. Each fault skips only
what it affects and logs once:

| Fault | Result |
|---|---|
| `decals.json` missing | no decals (silent: most classes have none) |
| `decals.json` malformed, or `format` ≠ 1 | no decals, one warning |
| declared placement with no `<Registry>/<p>.png` | that decal skipped, one line |
| mask fails to decode | that decal skipped, one warning |
| `shape` names no shape in the model | that decal skipped, one warning |
| degenerate projector: **zero** `normal`, or `normal` **in-plane** with `u_axis`/`v_axis` (as well as `u_axis`/`v_axis` themselves parallel or zero) | that decal skipped, one warning |
| a second decal targets a shape another decal already claimed | that decal skipped, one warning ("first decal wins") |
| a malformed placement entry (missing/non-numeric field, including a JSON integer too large for `float()`) | that placement skipped, one warning |
| mask decodes with no alpha channel (RGB8/R8) | still attached (treated as fully opaque), one warning |
| no mesh fix applied to this load (no `mesh_fix_dir` configured, no fix file matched, or a matched fix was refused) | **all** decals for this load skipped, one warning per NIF path -- BC's own un-merged "ID" patch geometry is still present and would otherwise paint a second name |

## 6. Testing

This section lists what is actually covered, by file, not an aspirational
plan -- two gaps called out explicitly below are real and unclosed.

- **Python** (`tests/unit/test_hull_decals.py`,
  `tests/host/test_hull_decals_e2e.py`,
  `tests/host/test_hull_decals_realize.py`,
  `tests/host/test_load_model_decals.py`,
  `tests/tools/test_gen_decals.py`):
  - `registry_stem`: file-stem extraction, "last ID path wins", no-`"ID"`-entry;
  - `decals_for`: the happy path, `decals.json` parse and every §5 skip
    (missing file, malformed JSON, wrong `format`, a placement with no PNG,
    degenerate projector -- zero cross, zero normal, in-plane normal --, and
    a malformed vector/depth field including an over-long JSON integer);
  - `host_loop._ship_decals`: swallows an unexpected exception from
    `decals_for` itself (warn-once, `[]`), and -- at the real seam, through
    `realize_set_objects` with a capturing fake renderer -- resolves the
    real Ambassador's Zhukov `top` decal end to end;
  - `_ship_load_key` differs by decal list, dedupes identical ones;
  - the host binding (`_dauntless_host.load_model`): distinct handles per
    registry, dedupe on repeat, `decals=None` stays a distinct variant, and
    a malformed decal tuple from Python is skipped rather than raising;
  - the generator (`tools/gen_mesh_fixes.py`): `fit_plane_st`'s exact
    inversion on a synthetic patch, `build_decal`'s centring/scaling and
    its derived-not-assumed orientation (parametrized over all 4 Ruling D
    orientations against an asymmetric bracket), the chirality guard
    raising on a forced-mirrored fixture, and `_run_decals`' overwrite
    warning.
  - **Gap: no automated mod-overlay resolution test.** Every Python test
    above drives `paths.game_asset` either for real (against the project
    replacements tree) or via a monkeypatch that bypasses overlay
    precedence entirely -- nothing proves a mod-supplied `Masks/` file
    actually wins or loses against the project-replacement tree the way §3
    describes. Unverified by test; live-only.
- **C++** (`native/tests/assets/cpu/decal_build_test.cc`):
  - `build_model` with a decal sets `Decal0` and the projector on the named
    shape's materials only, and each bad input (unknown shape, degenerate
    projector, missing mask file, a second decal on an already-claimed
    shape) is skipped without throwing;
  - the projector matrix (`decal_body_to_mask`) maps `origin`,
    `origin+u_axis` and `origin+v_axis` to (0,0), (1,0), (0,1), including a
    mirrored-basis case;
  - the mask is premultiplied before upload, and a mask with no alpha
    channel still attaches (treated as opaque) but warns once;
  - separate cache entries per registry (`DecalCache`);
  - the mesh-fix gate (`DecalMeshFixGate`): attaches on the real Ambassador
    with the committed fix, does NOT attach with no `mesh_fix_dir`
    configured (one warning asserted), does NOT attach when a matched fix
    is refused;
  - `DecalFrame`: the authored frame in `decals.json` agrees with the
    renderer's actual draw-time frame for the same real vertex.
- **Renderer** (`native/tests/renderer/decal_render_test.cc`, headless GL):
  a model with a decal renders the mask colour inside the projected
  rectangle (vs. under 10 red-dominant pixels on the plain hull, over 200
  with the decal) and the mask's row 0 lands at the top of the screen, not
  the bottom.
  - **Gap: no automated specular test.** Nothing in this suite renders and
    measures the `kDecalPaintSpecular` response under vs. beside the mask
    -- that check (§2's "a higher specular response under the mask") is
    live-only, verified by Mark, not by a headless GL assertion.
- **Live (Mark):**
  - QuickBattle Ambassador (Zhukov): the name sits where BC drew it,
    glossy, with windows glowing through -- this is also where the §2
    specular claim gets its only verification;
  - `E3M1`'s USS Excalibur: the second registry through the same placement.

## 7. Out of scope

- The other four Fed hulls: they have no masks yet.
- Bottom, nacelle and pylon placements: the masks exist; they need `decals.json` entries later.
- A Ship Property Viewer placement tool.
- Distance culling or fading: only High LOD is loaded, and the cost is one masked sample.
- The glTF / KTX2 asset pipeline.
- Decals on articulated shapes: the projector uses `p_body` with no `u_node_rest_fix` correction, so a decal on a moving part would slide with it. Fine for the Fed saucers this covers; a follow-up if an articulated placement is ever authored.
