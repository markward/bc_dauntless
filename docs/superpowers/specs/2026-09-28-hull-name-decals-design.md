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

## 3. Files and authoring

Per ship class, beside its NIF, under `data/Models/Ships/<Class>/Masks/`.
These are resolved through the normal game / mod / project-replacement
overlay (`paths.game_asset`), so a mod can ship its own. The stock
Ambassador's live in the project replacements tree:
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
   width. Mask orientation follows the ID texture's s/t axes.
5. **To ship-body space.** Map the mask rectangle's corners through the
   inverse of the plane fit to get `origin`, `u_axis` and `v_axis`.
   `normal` is the plane normal, oriented outward (same side as the patch's
   vertex normals). `depth` = 2.0 model units unless the plan's measurement
   says otherwise.

Every registry of the class reuses this placement.

## 4. Runtime flow

1. **Python** (`engine/appc/registry_texture.py` and `engine/host_loop.py`):
   - The `("ID", path)` queue is unchanged.
   - When a ship's instance is built (the `replacements_for` call sites), a
     new `decals_for(ship, nif_path)` returns
     `[(shape, origin, u_axis, v_axis, normal, depth, mask_abs_path), …]`.
   - To build that list, it takes the **last** queued `"ID"` path's stem as
     the registry, reads `decals.json` and resolves the masks through
     `paths.game_asset` (checking that each exists).
   - The list is passed to `renderer.load_model(..., decals=…)`.
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
| degenerate projector (`u_axis`/`v_axis` parallel or zero) | that decal skipped, one warning |

## 6. Testing

- **Python:**
  - stem → folder resolution, including a mod overlay;
  - "last ID path wins";
  - `decals.json` parse and each §5 skip;
  - the generator's fit on a synthetic patch with known s/t (the corners come back exact);
  - on the real Ambassador, the generated rectangle's centre lies inside the old patch's footprint and its `normal` points outward.
- **C++:**
  - `build_model` with a decal sets `Decal0` and the projector on the named shape's materials only;
  - separate cache entries per registry;
  - each bad input is skipped without throwing;
  - the projector matrix maps `origin`, `origin+u_axis` and `origin+v_axis` to (0,0), (1,0), (0,1).
- **Renderer (headless GL, `FrameTest`-style):** a model with a decal renders
  - the mask colour inside the rectangle;
  - the base colour outside it;
  - a higher specular response under the mask than beside it.
- **Live (Mark):**
  - QuickBattle Ambassador (Zhukov): the name sits where BC drew it, glossy, with windows glowing through;
  - `E3M1`'s USS Excalibur: the second registry through the same placement.

## 7. Out of scope

- The other four Fed hulls: they have no masks yet.
- Bottom, nacelle and pylon placements: the masks exist; they need `decals.json` entries later.
- A Ship Property Viewer placement tool.
- Distance culling or fading: only High LOD is loaded, and the cost is one masked sample.
- The glTF / KTX2 asset pipeline.
