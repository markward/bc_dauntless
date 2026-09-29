# SPV Decal Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make hull decals an independent per-class feature (any ship, up to 4 decals, no mesh-fix gate) and author them in a new Decals pane of the Ship Property Viewer, with live preview through the real shader.

**Architecture:**
- Native decals move from a per-material `Decal0` stage to a per-model list, `Model::decals` (≤4, optional shape restriction via a per-mesh enable mask), drawn by an `opaque.frag` loop over texture units 8–11.
- A per-instance override (`set_instance_decals`) lets the SPV preview edits without rebuilding the model.
- Python resolves `Masks/` beside the ship's declared model path, with a registry fallback to `default_registry`.
- A pure-maths editor module plus a decals writer back the SPV pane.

**Tech Stack:** C++20 (assets, renderer, host), GLSL 410, pybind11, Python 3.11 (stdlib + Pillow), CEF JS/CSS, GoogleTest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-spv-decal-editing-design.md`

## Global Constraints

- **Branch:** `feat/spv-decal-editing`, in worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/hull-name-cut-fix`. **Never commit to `main`.** Check `git branch --show-current` before every commit.
- **Banned git commands:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths only. Temporary mutations: back up with `cp`, restore with `cp`, then `diff`.
- **Never launch** `./build/dauntless`.
- **Build:** `cmake --build build -j` from the worktree root. Shader edits need `cmake -B build -S . -DPython3_EXECUTABLE=<worktree>/.venv/bin/python3` first.
- **C++ tests** run with `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"`. Asset-backed tests must PASS, not SKIP.
- **Paths rule:**
  - Python never spells `game` or `sdk` as a path segment, and never captures a path at import.
  - Resolve BC-relative files with `engine.paths.game_asset(rel)`.
- **No numpy.** Masks are PNG or TGA via `assets::decode_image`, premultiplied at load.
- **Max 4 decals per model.** The shader uses texture units 8–11 with the clamp sampler object. Units 0–7 are taken.
- **Look per decal** (unchanged from the hull-name-decals spec §2 as built):
  - premultiplied RGB overrides albedo AND the RGB of the glow term;
  - glow alpha (the emissive map) is unchanged;
  - paint specular `kDecalPaintSpecular` = 0.8.
- **Frame:** decal vectors are in the ship-body frame (`p_body`).
- **Errors never throw out of a ship load.** Each fault skips its own decal and logs once. A missing `decals.json` is silent.
- **Chirality:** an SPV-authored decal must satisfy `(u_axis × v_axis) · normal < 0`, i.e. it reads correctly from outside.
- **The committed Ambassador `Masks/decals.json` must keep rendering unchanged.** Its `top` names `amb saucer:0`.
- **Final gate:** `scripts/check_tests.sh`, in the foreground. It must print "OK — no new failures" with no "NO BC CONTENT ROOT" banner. The known intermittent flakes (`HullFieldClipTest.DegenerateNormalWithGradientOnStaysFinite`, `test_pursuers_avoid_each_other`) get re-run in isolation, then the gate is re-run with `--no-build`.

## Review Focus

1. **Top and bottom decals on one ship:** each must render only on its own side (facing test plus slab), never bleeding through the hull. Task 1 pins this with a two-decal GL test.
2. **Override lifetime:** the SPV override must never leak into gameplay after the SPV closes, or survive a mission swap. Tasks 2 and 6 pin this with clear-on-close tests.
3. **Mod-supplied class:** the save must go to the mod's folder, never the project replacements. Task 5 pins this with a routing test.
4. **A click-placed decal must read correctly** (not mirrored) on any hull orientation. Task 4 pins this with a chirality test across several normals.
5. **Legacy data:** the existing Ambassador `decals.json` (with `shape`, and no `default_registry`) renders identically after the refactor. Task 1 pins this with a regression GL test against the pre-refactor pixel count.

---

### Task 1: Native per-model decal list (≤4), no gate, shader loop

**Files:**
- Modify: `native/src/assets/include/assets/model.h`
- Modify: `native/src/assets/include/assets/material.h` (remove `Material::decal` and the `Decal0` usage)
- Modify: `native/src/assets/src/model_build.cc` (`apply_decals`)
- Modify: `native/src/assets/src/cache.cc` (remove the mesh-fix gate)
- Modify: `native/src/renderer/frame.cc`
- Modify: `native/src/renderer/shaders/opaque.frag`
- Modify tests: `native/tests/assets/cpu/decal_build_test.cc`, `native/tests/renderer/decal_render_test.cc`, and any cache test asserting the gate

**Interfaces:**
- Produces:
  ```cpp
  // model.h
  struct ModelDecal {
      glm::mat4 body_to_mask{1.0f};
      glm::vec3 normal{0, 0, 1};
      float     depth = 0.0f;
      int       texture_index = -1;   // into Model::textures (premultiplied mask)
  };
  // in Model:
  std::vector<ModelDecal> decals;      // size <= 4
  // per mesh (in Mesh or a parallel Model vector; implementer's choice, document it):
  std::uint8_t decal_mask = 0x0F;      // bit i => decal i applies to this mesh
  // DecalRequest gains nothing; `shape` empty => all meshes.
  inline constexpr int kMaxDecals = 4;
  ```
  Frame binding: units 8+i ← decal i's mask, `u_decal_count` (int), `u_decal_proj[4]`, `u_decal_normal[4]`, `u_decal_depth[4]`, `u_decal_enabled_mask` (int, this mesh's mask ANDed with the list size).
- Consumes: the existing `DecalRequest`, `decal_body_to_mask`, `decal_projector_is_degenerate`, and premultiply at load.

- [ ] **Step 1: Failing tests.**
  - **C++ build tests:**
    - (a) two requests (`top` with `shape` set, `bottom` without) → `model.decals.size() == 2`; the `top` bit is set only on the saucer shape's meshes, and the `bottom` bit on all meshes;
    - (b) five requests → 4 kept, one warning;
    - (c) no mesh fix configured → decals STILL attached (the gate is gone). Delete or replace the old `DecalMeshFixGate` expectations accordingly.
  - **GL tests:**
    - (d) the **legacy regression**: the committed Ambassador `top` placement plus the real `Zhukov/top.png` must change more than 150 pixels. The pre-refactor figure is 224; record the new one. Also keep the existing red-coverage, orientation and glow tests green.
    - (e) the **two-decal** test on the Ambassador: a red opaque decal from above (normal +z) and a blue opaque decal from below (normal −z) with overlapping u/v footprints. The top-down render shows red and no blue; a bottom-up render shows blue and no red.

- [ ] **Step 2: Run and watch them fail.** Build, then run the new filters.

- [ ] **Step 3: Implement.**
  - `apply_decals` fills `Model::decals` in request order: skip invalid entries (existing warnings), cap at 4 with one warning, and set the per-mesh masks from `shape` (empty = all).
  - Remove `Material::decal` and the Decal0 stage writes.
  - In `cache.cc`, remove the fix-applied gate and its warning; the key includes the requested decals.
  - In `frame.cc`: per mesh, bind decal masks on units 8..8+n−1 (black fallback plus sampler 0 for the unused ones) and set the uniform arrays plus `u_decal_enabled_mask`. `u_ship_world_inv` is set whenever any decal is enabled. Unbind samplers 8–11 after the loop.
  - In `opaque.frag`, loop `i < u_decal_count`, skipping when bit i is clear. For each decal, apply the same inside test, the `textureGrad` with the gradients taken **outside** the loop (the scuff pattern), and the albedo, glow-RGB and paint-spec composites, in order. `sampler2D u_decal_mask[4]` with a constant-index loop (unrolled) is fine on GLSL 410. If indexing a sampler array by the loop index is rejected, use four named samplers and an unrolled body.

- [ ] **Step 4: Build (reconfigure for the shader) and run** the assets and renderer decal tests, then the full `renderer_tests` and `assets_tests`.

- [ ] **Step 5: Commit:** `feat(decals): per-model decal list (<=4), optional shape, no mesh-fix gate`.

---

### Task 2: Per-instance decal override (`set_instance_decals`)

**Files:**
- Modify: `native/src/host/host_bindings.cc` (new binding; host-side mask texture cache released in `shutdown()`)
- Modify: `native/src/renderer/frame.cc`, plus whatever carries per-instance draw state (look at how the renderer passes per-instance data such as hull carve or node overrides into `draw_model`, and follow that)
- Modify: `engine/renderer.py` (a `set_instance_decals(iid, decals)` wrapper), and `engine/host_io.py` if that façade exposes renderer calls to the UI
- Test: `native/tests/renderer/decal_render_test.cc` (an override test through the frame path the host uses), `tests/host/test_instance_decal_override.py`

**Interfaces:**
- Produces: `_dauntless_host.set_instance_decals(iid: int, decals: list | None) -> None`. Each entry has the same 7-tuple shape as `load_model` decals: `(shape_or_empty, origin, u_axis, v_axis, normal, depth, mask_path)`. The shape is honoured by name against the instance's model meshes.
  - A list **replaces** the instance's baked `Model::decals` for drawing. `None` clears it.
  - Malformed entries are skipped with one warning; it never throws.
  - Masks are loaded once per path into a host texture cache (`decode_image`, premultiplied, mipmapped).
- Consumes: Task 1's `ModelDecal` and the frame uniforms.

- [ ] **Step 1: Failing tests.**
  - **GL:** the plain Ambassador with no baked decals, plus an override of a red decal over the saucer → red pixels appear. Clearing it with `None` → none. A second instance of the same model is unaffected.
  - **Python host test:** calling the binding with a malformed entry doesn't raise, and `None` clears.
- [ ] **Step 2: Watch them fail.**
- [ ] **Step 3: Implement.** Instance overrides are stored in the scenegraph or host state, keyed by iid. They're cleared when the instance is destroyed, and all of them are cleared by `init()` and `shutdown()` (the host's reset invariant).
- [ ] **Step 4: Build and run** the tests plus the full `renderer_tests`, then `uv run pytest tests/host -q`.
- [ ] **Step 5: Commit:** `feat(host): set_instance_decals live override for the SPV`.

---

### Task 3: Python resolution from the declared model path, and `default_registry`

**Files:**
- Modify: `engine/appc/hull_decals.py`, `engine/host_loop.py` (`_ship_decals`)
- Test: `tests/unit/test_hull_decals.py`, `tests/host/test_hull_decals_realize.py`

**Interfaces:**
- Produces:
  ```python
  def declared_model_dir(ship) -> str | None   # dirname of GetShipStats()["FilenameHigh"], posix, BC-relative
  def resolve_registry(replacements, decals_doc: dict | None) -> str | None
      # last ("ID", path) stem, else decals_doc.get("default_registry"), else None
  def decals_for(nif_rel_dir: str, registry: str | None) -> list[DecalSpec]   # unchanged signature
  ```
  - `decals_for` now also:
    - honours a missing `shape` (it passes `""` in the spec tuple);
    - caps at 4 with one warning;
    - warns once when `default_registry` names a folder with none of the declared masks.
  - `_ship_decals(ship, nif_path, reps)`, which now takes the ship, uses `declared_model_dir(ship)` instead of `relative_to(game_root())`. Update both host_loop call sites.
- Consumes: Tasks 1 and 2 accept an empty shape.

- [ ] **Step 1: Failing tests.**
  - A mod-style ship whose NIF resolves outside `game_root()` still gets decals, via a monkeypatched `paths.game_asset` pointing `data/Models/Ships/BirdOfPrey/Masks/...` at a temp tree.
  - A ship with no ID registry and a `default_registry` of "Klingon" resolves the `Klingon/` masks.
  - Script registry wins over default.
  - More than 4 → 4.
  - An empty `shape` is passed through.
  - The existing Ambassador realize test still passes.
- [ ] **Step 2: Watch them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_hull_decals.py tests/host/test_hull_decals_realize.py tests/host/test_hull_decals_e2e.py tests/unit/test_path_indirection.py -q`.
- [ ] **Step 5: Commit:** `feat(decals): resolve Masks beside the declared model path; default_registry`.

---

### Task 4: Decal editor maths (pure module)

**Files:**
- Create: `engine/ui/decal_editor.py`
- Test: `tests/unit/test_decal_editor.py`

**Interfaces:**
- Produces (pure functions, no GL or CEF). All vectors are ship-body 3-tuples:
  ```python
  @dataclass
  class Placement:            # mirrors a decals.json entry
      name: str; origin: Vec3; u_axis: Vec3; v_axis: Vec3; normal: Vec3; depth: float; shape: str = ""
  def place_at_hit(name, hit_point, hit_normal, ship_forward, ship_up, ship_radius, mask_aspect) -> Placement
      # width = 0.25*ship_radius; height = width/mask_aspect; depth = 0.05*width;
      # up = ship_forward projected onto the plane (fallback ship_up if near-parallel);
      # centred on the hit; satisfies chirality (u x v)·n < 0
  def reposition(p, hit_point, hit_normal) -> Placement     # re-seat centre + normal, keep size and roll relative to the projected up
  def move_uv(p, du, dv) -> Placement                       # along the decal's own u/v (units)
  def roll(p, radians) -> Placement                         # rotate u/v about the normal, keep the centre
  def scale(p, factor) -> Placement                         # uniform about the centre, aspect preserved
  def set_width(p, width, mask_aspect) -> Placement         # numbers panel
  def centre(p) -> Vec3; def width(p) -> float; def roll_angle(p, ship_forward) -> float
  def chirality_ok(p) -> bool
  def to_json_entry(p) -> dict; def from_json_entry(name, d) -> Placement
  def valid_name(name, existing) -> str | None              # error text or None
  ```
- [ ] **Step 1: Failing tests:**
  - `place_at_hit` on normals +z, −z, +x, and a tilted normal: centre = hit, `chirality_ok`, `|u|/|v|` = aspect, u ⟂ normal;
  - the forward-parallel fallback;
  - `reposition` keeps width and aspect;
  - `move_uv`, `roll` and `scale` round-trips;
  - JSON round-trip;
  - `valid_name` rejects `""`, `"a/b"`, `".."` and duplicates.
- [ ] **Step 2: Watch them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests.
- [ ] **Step 5: Commit:** `feat(spv): pure decal editor maths`.

---

### Task 5: `decals.json` writer and save routing

**Files:**
- Create: `engine/appc/decals_writer.py`
- Test: `tests/unit/test_decals_writer.py`

**Interfaces:**
- Produces:
  ```python
  def decals_target_path(nif_rel_dir: str) -> Path
      # the mod's <mod>/data/Models/Ships/<Class>/Masks/decals.json if a mod supplies the class's model
      # (engine.mods lookup of the model file), else <project replacements>/…/Masks/decals.json
  def write_decals(path: Path, placements: list, default_registry: str | None) -> None
      # atomic .tmp + os.replace; format 1; key order: format, default_registry (only if set), decals;
      # entry key order as the generator writes; floats via to_f32 formatting consistent with tools/gen_mesh_fixes.decals_json
  ```
  It preserves any unknown top-level keys already in the file.
- [ ] **Step 1: Failing tests:**
  - stock routing → the project replacements path (monkeypatch `paths.project_asset_root`);
  - mod routing → the mod path (monkeypatch the mods index);
  - atomic write;
  - round-trip with Task 3's reader;
  - unknown keys preserved;
  - `default_registry` omitted when None.
- [ ] **Step 2: Watch them fail.**
- [ ] **Step 3: Implement.** Look at `engine/appc/override_routing.py` and `engine/mods.py` first, and follow their patterns.
- [ ] **Step 4: Run** the tests plus `tests/unit/test_path_indirection.py`.
- [ ] **Step 5: Commit:** `feat(decals): decals.json writer with stock/mod routing`.

---

### Task 6: SPV Decals pane

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py` (state, input, payload, save)
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js`, `native/assets/ui-cef/css/ship_property_viewer.css` (the third pane)
- Modify: `engine/host_loop.py` (wiring the renderer override calls and the iid, following the existing `iid_getter` and emitter-refresh wiring)
- Test: `tests/ui/test_spv_decals_pane.py` (or next to the existing SPV panel tests; find them)

**Interfaces:**
- Consumes: Task 2 `set_instance_decals`, Task 3 `declared_model_dir`/`resolve_registry`/`decals_for`, Task 4 `decal_editor`, Task 5 `decals_target_path`/`write_decals`, `engine.manual_aim.cursor_ray`, `engine.host_io.ray_trace_mesh`.
- Produces: a third side pane "Decals", styled like Subsystems and Model Parts. The payload key is `decals`:
  ```
  {
    "registries": [...],
    "registry": str,
    "default_registry": str | None,
    "placements": [{"name", "has_mask"}],
    "selected": str | None,
    "adding": bool,
    "error": str | None
  }
  ```
  JS events: `ship-property-viewer/decal-registry`, `/decal-add`, `/decal-delete`, `/decal-select`, plus the existing gizmo/save/undo events.

**Behaviour** (spec §3):
- While the Decals pane is active, the textured hull mode (`show_hull_texture`) is forced on, and the previous mode is restored on leaving.
- The SPV pushes `set_instance_decals(iid, working_list)` whenever the working list or registry changes. It clears it (`None`) when the pane is left, the SPV closes, or the mission swaps.
- A placement without a mask for the previewed registry uses a built-in checkerboard PNG. Commit it as a project asset: `native/assets/textures/decal_placeholder.png`, a 64×32, 8-px checker with 50% alpha.
- **Add:** a name prompt, validated by `valid_name`; then the next hull click → `cursor_ray` + `ray_trace_mesh` on the SPV iid → `place_at_hit`. A miss sets the pane error hint.
- **Gizmos:**
  - Move: arrows along the decal's u/v, driving `move_uv`, plus a "Reposition" toggle for click-to-reseat;
  - Rotate: a ring about the normal, driving `roll`;
  - Scale: uniform, driving `scale`.

  Reuse the existing gizmo pass and pick helpers.
- **Numbers panel:** centre, width, roll, depth.
- **Undo:** snapshot the working list per gesture onto the SPV's shared undo stack.
- **Save:** `write_decals(decals_target_path(dir), …)`, the existing toast, clear staged state.
- **Unsaved edits** on leaving or closing → the existing unsaved prompt.

- [ ] **Step 1: Failing tests** (the panel logic with a fake renderer/host_io recording calls):
  - entering the pane forces textured mode and pushes an override; leaving restores the mode and clears the override;
  - add plus a click hit → a placement in the working list, with chirality ok and the override updated;
  - a miss → an error hint and no placement;
  - duplicate/invalid names refused;
  - a registry switch changes the mask paths in the override;
  - a missing mask → the placeholder path;
  - delete removes a placement;
  - undo restores;
  - save calls `write_decals` with the right path (stock and mod cases);
  - SPV close clears the override;
  - a mission swap clears the override.
- [ ] **Step 2: Watch them fail.**
- [ ] **Step 3: Implement** the Python first, then the JS/CSS pane, mirroring the Model Parts pane's structure in `ship_property_viewer.js` (`renderSPVModelParts`).
- [ ] **Step 4: Run** the new tests, then `uv run pytest tests/ui tests/unit -q -k "spv or ship_property or decal"`.
- [ ] **Step 5: Commit:** `feat(spv): Decals pane — add, edit, delete, registry preview, live override, save`.

---

### Task 7: End to end, docs and gate

**Files:**
- Test: `tests/host/test_spv_decals_e2e.py`
- Modify: `CLAUDE.md` (the "Hull name decals" row: no gate, per-model list ≤4, `default_registry`, SPV authoring), and spec cross-links if needed

- [ ] **Step 1: E2E test.** Through the real host:
  1. load the Ambassador with its committed decals;
  2. drive the SPV panel (headless) to add a `bottom` placement via a synthetic hit;
  3. save to a temp replacements root (monkeypatch `paths.project_asset_root`);
  4. re-resolve with `decals_for`: two placements come back, and `load_model` accepts them.
- [ ] **Step 2: CLAUDE.md row update,** staying within the doc budget test (`tests/docs`).
- [ ] **Step 3: Full gate** `scripts/check_tests.sh`, in the foreground.
- [ ] **Step 4: Commit:** `test(spv): decal authoring end to end; docs`.

## After the plan

Mark's live check:
- author a Bird of Prey decal from scratch using the checkerboard;
- add an Ambassador `bottom`;
- switch between Zhukov and Excalibur;
- save, restart, and confirm in-game.
