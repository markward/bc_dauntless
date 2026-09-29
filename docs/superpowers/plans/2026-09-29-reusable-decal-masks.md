# Reusable Decal Masks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one mask be used by several placements (the name on the neck,
both pylons, the rim…), with up to 16 placements and up to 4 distinct masks
per model.

**Architecture:**
- Split "placement" (the projector) from "mask" (the texture).
- Native: `Model::decals` holds up to 16 projectors, each with a mask slot
  (0–3) into a deduplicated list of up to 4 mask textures on units 8–11.
- Python: an optional per-placement `"mask"` key, defaulting to the
  placement's name.
- The SPV Add action offers every PNG every time and auto-names the
  placement.

**Tech Stack:** C++20 / GLSL 410 (`native/`), Python 3 (`engine/`), CEF
JS (`native/assets/ui-cef/`), gtest + pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-spv-decal-editing-design.md`
§2.4a is the authority. It supersedes the 4-cap in §2.4.

## Global Constraints

**Limits and names:**
- `kMaxDecals` = 16 placements per model.
- `kMaxDecalMasks` = 4 distinct masks per model, on texture units 8–11
  through the existing named samplers `u_decal_mask0..3` and the existing
  clamp sampler object.
- Over the placement cap → the first 16 are used, with one warning.
- A placement needing a 5th distinct mask → that placement is skipped, with
  one warning.
- Masks are deduplicated by resolved absolute path.
- `"mask"` key: optional. Absent or empty → the placement name. It uses the
  same filename-stem validation as names.

**Shader:**
- Select the sampler by slot with a small `switch`/if-chain over the four
  named samplers; never index a sampler array.
- Derivatives stay outside branches; sampling uses `textureGrad`.
- Composite order and rules are unchanged: premultiplied RGB overrides
  albedo and glow RGB, glow alpha is kept, paint specular 0.8.
- The per-mesh shape enable mask is 16 bits.

**Compatibility:**
- The existing Ambassador `decals.json`, the committed `top` entry, renders
  byte-identically.
- The Zhukov render baseline in `native/tests/renderer/decal_render_test.cc`
  stays at 224 changed pixels.

**Project rules:**
- Python never spells `game` or `sdk` as a path segment, and never captures
  a path at import.
- Banned git: `git checkout -- <path>`, `git checkout .`, `git restore`,
  `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`.
  Stage explicit paths only.
- Never launch `./build/dauntless`. Build only with `cmake --build build -j`
  from the worktree root.
- `native/assets/replacements/data/Models/Ships/Ambassador/Masks/decals.json`
  currently holds Mark's UNCOMMITTED live saves (`bottom`, `pylon`). Never
  stage, modify or restore it. Tests must not depend on its placement count.

## Review Focus

1. Two placements sharing one mask → the mask is decoded and uploaded ONCE,
   and both draw.
2. Five distinct masks → the 5th placement is skipped with one warning;
   the others draw.
3. Placement 16 is honoured and 17 is dropped. The shape enable bits above
   bit 3 work: a shape-restricted decal at index 10 paints only its mesh.
4. The override (`set_instance_decals`) with 16 entries sharing masks
   matches the baked path pixel-for-pixel.
5. Tests in `tests/host/test_hull_decals_e2e.py` and
   `tests/host/test_spv_decals_e2e.py` that assumed exactly one Ambassador
   placement must assert `top` is present, not an exact count, so Mark's
   saves don't break them.

---

### Task 1: Native — 16 projectors, 4 deduplicated mask slots

**Files:**
- Modify: `native/src/assets/include/assets/model.h` (`kMaxDecals` 16, add
  `kMaxDecalMasks` 4; `ModelDecal` gains `int mask_slot`; `Model` gains a
  mask list of at most 4, as a texture index or equivalent; widen
  `Mesh::decal_mask()` to 16 bits)
- Modify: `native/src/assets/src/model_build.cc` (`apply_decals`: dedupe
  masks by path, assign slots, enforce both caps with warn-once)
- Modify: `native/src/assets/src/decal_override.cc` and
  `native/src/assets/include/assets/decal_override.h` (the same dedupe and
  caps for the override)
- Modify: `native/src/renderer/frame.cc` (`bind_hull_decal_list`: bind up to
  4 masks to units 8–11 once per `draw_model`; upload 16 projectors plus a
  `u_decal_slot[16]` int array)
- Modify: `native/src/renderer/shaders/opaque.frag` (loop 16; slot switch)
- Modify: `native/src/host/host_bindings.cc` (accept up to 16 entries in
  `load_model(decals=)` and `set_instance_decals`; the dedupe key still
  folds every entry's full geometry and mask path)
- Tests: `native/tests/assets/cpu/decal_build_test.cc`,
  `native/tests/renderer/decal_render_test.cc`, and the override tests next
  to them

- [ ] **Step 1: Write the failing tests**, one per Review Focus item 1–4:
  - Shared mask → one texture, two projectors with the same slot, both
    draw. In GL: a shared-mask pair changes pixels at both locations.
  - 5 distinct masks → 4 slots used, the 5th placement is absent, and
    exactly one warning.
  - 17 placements → 16 kept. A shape-restricted decal at index 10 paints
    only its mesh.
  - Override ≡ baked for a 16-entry shared-mask list.
  - Existing baselines unchanged: Zhukov 224 pixels, Ambassador `top`.
- [ ] **Step 2: Run the tests and watch them fail**:
  `cmake --build build -j && ctest --test-dir build -R "[Dd]ecal"`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests again; all pass.** Also run
  `uv run pytest tests/host -q -k decal`, since the host bindings changed.
- [ ] **Step 5: Commit:**
  `feat(decals): 16 placements sharing up to 4 deduplicated masks`

### Task 2: Python — optional `mask` key, caps, robust e2e

**Files:**
- Modify: `engine/appc/hull_decals.py` (`decals_for`: read the optional
  `"mask"`, resolve `<Registry>/<mask>.png`, cap 16 placements, count
  distinct masks and skip the 5th onwards with warn-once)
- Modify: `engine/ui/decal_editor.py` (`Placement.mask: str = ""`;
  `to_json_entry` writes `"mask"` only when it's non-empty and differs from
  the name; `from_json_entry` reads it; add
  `mask_of(p) -> str` = `p.mask or p.name`)
- Modify: `tests/host/test_hull_decals_e2e.py`,
  `tests/host/test_spv_decals_e2e.py` (Review Focus 5)
- Tests: `tests/unit/test_hull_decals.py`,
  `tests/unit/test_decal_editor.py`, `tests/unit/test_decals_writer.py`

- [ ] **Step 1: Write the failing tests:**
  - absent `mask` = name;
  - `"pylon_2": {"mask": "pylon"}` resolves to `pylon.png`;
  - an invalid mask stem is skipped with a warning;
  - 17 placements → 16;
  - a 5th distinct mask is skipped;
  - the JSON round-trip writes `mask` only when it differs;
  - a load-then-save of the committed Ambassador file (from `git show
    HEAD:`, copied to tmp) is still byte-identical.
- [ ] **Step 2: Watch them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run:**
  `uv run pytest tests/unit tests/host -q -k "decal"` and
  `uv run pytest tests/unit/test_path_indirection.py -q`.
- [ ] **Step 5: Commit:** `feat(decals): reusable masks via optional mask key`

### Task 3: SPV — Add offers every mask; auto-name; show the mask

**Files:**
- Modify: `engine/ui/spv_decals_pane.py`
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js`
- Tests: `tests/ui/test_spv_decals_pane.py`,
  `tests/ui/test_spv_decals_pane_cef.py`

- [ ] **Step 1: Write the failing tests:**
  - Add's pick list contains every registry PNG stem plus the default names
    (top/bottom/port/starboard/bow/stern), even when they're already placed.
  - Picking `pylon` twice produces placements `pylon` and `pylon_2`, the
    second with `mask="pylon"`.
  - The override entries for both use `pylon.png`, or the placeholder if
    it's missing.
  - `has_mask` and the aspect lookups use `mask_of(p)`.
  - The list payload carries `mask` for each placement; the JS shows
    `pylon_2 (pylon)`.
  - A 17th Add, or an Add that would need a 5th distinct mask, is refused
    inline with an error hint.
  - The Scale/Width aspect uses the placement's mask PNG.
- [ ] **Step 2: Watch them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run:**
  `uv run pytest tests/ui tests/unit tests/host -q -k "decal or spv or ship_property"`
  and `uv run pytest tests/unit/test_path_indirection.py -q`.
- [ ] **Step 5: Commit:**
  `feat(spv): reuse a mask across placements; auto-named placements`

### Task 4: Docs and gate

- [ ] Update the `CLAUDE.md` "Hull name decals" row: "Per-model list, ≤16
  placements sharing ≤4 masks (units 8–11), optional `mask` key". Stay
  within the `tests/docs` budget.
- [ ] Run `scripts/check_tests.sh` in the foreground. Report its summary
  verbatim.
- [ ] Commit: `docs: reusable decal masks`.
