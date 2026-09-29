# SPV Decal Editing — design

**Date:** 2026-09-28
**Status:** design agreed, spec written
**Branch:** `feat/spv-decal-editing` (from `main` at 75caa644)
**Builds on:** `docs/superpowers/specs/2026-09-28-hull-name-decals-design.md`

---

## 1. What this is

Hull decals (registry names today) become an **independent, per-ship-class
feature**, authored in the Ship Property Viewer (SPV). Any ship, stock or
mod, can carry decals: Klingon markings on a Bird of Prey, or a registry on
a mod hull that has none. Decals are no longer tied to the stock mesh fix.
The mesh fix goes back to being only what removes BC's baked-in name cut on
the five stock Federation hulls.

**Decided (Mark, 2026-09-28):**
- **Editor:** add, edit and delete placements, and preview registries.
- **Scope:** decals attach to **any** ship whose class declares them. The
  mesh-fix gate is removed entirely. Accepted consequence: a refit model
  copied over a stock Fed file can show our decal and BC's baked name
  together.
- **Live preview:** per-instance override, "approach A", through the real
  game shader.
- **Viewer layout:** decals get their own third side pane in the SPV, beside
  Subsystems and Model Parts.

## 2. Runtime model changes

### 2.1 Loader: no gate
- `AssetCache::load` attaches decals whenever they're requested, whether or
  not a mesh fix applied.
- Remove the gate, its warning, and the `effective_decals` split in
  `native/src/assets/src/cache.cc`. The cache key includes the requested
  decals.

### 2.2 Resolution beside the declared model path
- The class's `Masks/` folder is resolved from the ship script's
  **declared** model path: `GetShipStats()["FilenameHigh"]`, e.g.
  `data/Models/Ships/BirdOfPrey/BirdOfPrey.nif` → `data/Models/Ships/BirdOfPrey/Masks/`.
- Resolution goes through the game / mod / replacement overlay
  (`paths.game_asset`).
- This replaces today's `Path(nif_path).parent.relative_to(game_root())`,
  which skipped every mod-folder model.

### 2.3 Registry selection
The registry comes from the first of these that exists:
1. The stem of the last `ReplaceTexture(…, "ID")` queued for the ship (as today).
2. `decals.json`'s new optional **`default_registry`**.
3. None, which means no decals.

A `default_registry` naming a folder that doesn't exist → no decals, with
one warning.

### 2.4 A per-model decal list

`decals.json` keeps `"format": 1`. Adding optional keys is backward
compatible.

- Decals become a **per-model list of up to 4**. The native side moves from
  a per-material `Decal0` stage and projector to `Model::decals`: up to 4 ×
  (projector, normal, depth, mask texture index).
- **`shape` becomes optional:**
  - **without** it, a decal applies to every surface it projects onto,
    subject to the existing facing test (`dot(n_body, normal) > 0`) and
    depth slab;
  - **with** it, it's restricted to that shape's meshes. Implement it as a
    per-mesh 4-bit enable mask on the model.
  - The existing Ambassador `top` entry (which names `amb saucer:0`) keeps
    working unchanged.
- More than 4 placements declared → the first 4 are used, with one warning.
- **Shader (`opaque.frag`):** loop over up to 4 projectors, each with its
  own mask on **texture units 8–11**, through the clamp sampler object.
  Composite in order. Each decal follows the same rules as today:
  - premultiplied RGB overrides albedo;
  - it also overrides the RGB of the glow term, while the glow alpha
    (emissive map) is unchanged;
  - paint specular 0.8.

  Cost: 4 projector tests per pixel on decaled models, and texture reads
  only where a decal covers the pixel. No-decal models run the same
  uniform-branch cost as today.

### 2.4a Reusable masks, up to 16 placements (amended 2026-09-29, Mark, live)

The cap of 4 above counted the wrong thing. A ship commonly carries about 10
name placements (top, bottom, neck, both pylons, both nacelles, rim…), but
they reuse a handful of masks. What costs a texture unit is a distinct
**mask**, not a placement. This section supersedes the 4-cap above.

- **`mask` key, optional:** each placement may name the mask it uses:
  `"pylon_2": {"mask": "pylon", …}` → `<Registry>/pylon.png`. Without it,
  the placement's own name is the mask, so existing files are unchanged.
  `mask` follows the same filename-stem rules as a placement name.
- **Placements:** up to **16** per model (`kMaxDecals` = 16). Beyond 16 →
  the first 16 are used, with one warning.
- **Masks:** up to **4 distinct** mask textures per model, still on units
  8–11 (`kMaxDecalMasks` = 4). Masks are deduplicated by resolved path. A
  placement needing a 5th distinct mask is skipped, with one warning.
- Each projector carries a **mask slot index** (0–3). The per-mesh shape
  enable mask widens to 16 bits.
- **Shader:** loop over up to 16 projectors. Each samples its mask slot
  through the four named samplers; select the sampler by slot in a small
  switch, not by indexing a sampler array. Keep derivatives outside
  branches, and keep composite order and rules as in §2.4.
- **Override:** `set_instance_decals` takes up to 16 entries, with the same
  mask dedupe and the same 4-mask limit.
- **SPV:**
  - Add lists every PNG in the previewed registry every time, plus the
    default names, not only the unplaced ones.
  - The new placement is named automatically: the mask name if it's free,
    else `<mask>_2`, `<mask>_3`, …
  - The pane list shows each placement's mask when it differs from the name.
  - A 17th placement, or a 5th distinct mask, is refused inline.
- **Cost:** up to 16 projector tests per pixel on decaled models (a few
  multiply-adds each). Mask reads happen only where a projector covers the
  pixel. The uniform budget is about 21 floats per projector, ≈340 for 16,
  well under GL's 1024 minimum; the Windows check remains deferred.

### 2.5 Live per-instance override (approach A)
- **New host binding:** `set_instance_decals(iid, list | None)`.
  - A list **replaces** the instance's baked decal list for drawing: same
    entry shape as `load_model`'s decals, max 4.
  - `None` clears it.
- **Masks:** loaded through a host-side texture cache keyed by path (decoded
  with `decode_image`, premultiplied). The cache is released on host
  shutdown.
- The game never calls it. The SPV calls it while Decals mode is active, and
  clears it on leaving the mode or closing the SPV.

### 2.6 Save routing
Masks are PNGs that Mark authors externally. The SPV never writes images.

- **Stock class** (model not supplied by a mod) → the project replacements'
  `data/Models/Ships/<Class>/Masks/decals.json`.
- **Class whose model a mod supplies** → that mod's
  `data/Models/Ships/<Class>/Masks/decals.json`, following the SPV's
  existing mod-routing pattern in `engine/appc/override_routing.py`.

Writes are atomic (`.tmp` + `os.replace`), with the same formatting as
`tools/gen_mesh_fixes.decals_json`.

## 3. The SPV Decals pane

**Mode:** a new **Decals** pane, a third side pane styled like Subsystems
and Model Parts. While it's the active pane, the hull is shown **textured**
(the real opaque path; the hologram cannot show decals). The previous view
mode is restored on leaving.

**Pane header:**
- **Registry preview** dropdown: the registry folders found under `Masks/`,
  with the class default marked. Changing it swaps the masks in the live
  override immediately.
- **Add** and **Delete** (with a confirm step).

**Pane list:** the declared placements, each marked if the previewed
registry has no PNG for it.

**Add a placement:**
1. Click **Add** and type a name. The name is the mask filename:
   `bottom` → `<Registry>/bottom.png`. It must be a valid filename stem and
   unique; otherwise it's refused inline.
2. Click the hull. `cursor_ray` (from `engine/manual_aim.py`, the exact
   inverse of the SPV projection) plus `ray_trace_mesh` give the hit point
   and normal.
3. **Orientation:** "up" defaults to the ship's forward axis projected onto
   the surface plane (falling back to ship-up if forward is parallel to the
   normal). The basis is built so the decal reads correctly from outside:
   `(u_axis × v_axis) · normal < 0`, the generator's chirality rule.
4. **Initial size:** width is 25% of the ship's radius. Height comes from
   the mask aspect: the PNG if it exists, else 2:1. Depth starts at 5% of
   the width.

If a click misses the hull, no placement is made and a hint is shown.

**Edit the selected placement** (the existing gizmo suite, adapted):

| Tool | Behaviour |
|---|---|
| Move | Arrows along the decal's own u/v axes; **click-to-reposition** re-seats it at a new hull hit with the new normal |
| Rotate | A ring about the normal (roll) |
| Scale | Uniform, with the aspect locked to the mask |
| Numbers | In the tool's own top-right panel, never the sidebar (Mark, live): Move shows the centre X/Y/Z, Rotate the Roll, Scale the Width (aspect-locked) and Depth. No Copy/Paste/Mirror/Uniform for a decal |

**No mask yet:** a built-in **checkerboard placeholder** is used for the
preview, so a placement can be positioned and sized before its artwork
exists.

**Undo and save:**
- Edits are staged, and each gesture is snapshotted onto the SPV's shared
  undo stack.
- **Save** writes `decals.json` per §2.6, shows the existing toast and
  clears the staged state.
- The live override stays until you leave the mode. On the ship's next
  load, the baked list matches.
- Unsaved edits on leaving → the SPV's existing unsaved-edits prompt.

## 4. Errors

In-game loads never fail because of decals. Each fault skips only its own
decal and logs once. The rows from the hull-name-decals spec §5 still apply,
except the removed "no mesh fix" row. New rows:

| Fault | Result |
|---|---|
| more than 4 placements | first 4 used, one warning |
| `default_registry` folder missing | no decals for that ship, one warning |
| SPV: click misses the hull | no placement made; a hint in the pane |
| SPV: invalid or duplicate placement name | refused inline |
| SPV: save target not writable | existing SPV error toast; staged edits kept |
| SPV: existing `decals.json` corrupt / not an object | save refused, file untouched, error toast; staged edits kept |
| SPV: a placement entry is unreadable | listed as "(unreadable)", delete-only; written back unchanged on Save |

## 5. Testing

- **C++:**
  - a `Model::decals` list of up to 4;
  - top and bottom on one model, both drawn and separated by the facing
    test;
  - the shape-restricted path;
  - the more-than-4 cap;
  - the override replaces the baked list for one instance only, and clears;
  - GL tests: two decals on one ship; the override changes the rendered
    image without a model rebuild; the existing Ambassador `top` renders as
    before.
- **Python:**
  - registry fallback order (script → `default_registry` → none);
  - `Masks/` resolved beside the declared `FilenameHigh`, for stock and mod
    models;
  - save routing (stock → project replacements, mod → the mod's folder);
  - pure SPV maths: surface frame from a hit, the chirality rule, aspect
    lock, roll, move along u/v, click-to-reposition;
  - undo snapshots;
  - validation of the name and the more-than-4 case.
- **Migration:** the committed Ambassador `decals.json` loads and renders
  unchanged. `tools/gen_mesh_fixes.py --decals` output stays readable.
- **Live (Mark):**
  - author a Bird of Prey decal from scratch using the checkerboard;
  - add an Ambassador `bottom`;
  - switch between Zhukov and Excalibur;
  - save, restart, and confirm in-game.

## 6. Out of scope

- Painting or editing mask images in the SPV (artwork stays in Gimp or
  Photoshop).
- More than 4 decals per model.
- Decals on articulated shapes (no rest-frame correction; unchanged from
  the hull-name-decals spec §7).
- Guarding the refit-over-stock double name (accepted in §1).
