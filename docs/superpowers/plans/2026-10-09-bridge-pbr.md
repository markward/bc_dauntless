# Bridge PBR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the player's bridge with physically based shading — linear-space Cook-Torrance GGX with per-pixel roughness / metalness / normal maps (layered: maps by albedo name → per-shape override → default), a box-projected reflection probe pair (green, yellow/red) captured at the captain's chair, and static picker-placed spot lights — while lit diffuse still never blooms.

**Architecture:** Assets gain `_rough` / `_metal` sibling discovery (normal maps reuse the existing `_normal` → Bump discovery) with a stock/mod lookup policy for interior loads. `bridge.frag` gains a PBR path (behind a dev A/B switch, default on) whose maths is pinned by a CPU twin header. A new `BridgeProbe` owns cubemap capture, GGX prefiltering and the BRDF LUT; `BridgePass` owns two probes, per-mesh material overrides and the spot-light list. Python evaluates the per-bridge document into overrides and spot lights, pushes them at bridge load (production) and on every editor change, and drives the green ↔ yellow/red probe cross-fade.

**Tech Stack:** C++20, GLSL 410 core, pybind11, Python 3, CEF (HTML/JS/CSS), gtest + pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` — §9 (9.1–9.6), §6.2 (spot light), §7 (the `material` / `emitter.light` sections). Builds on the foundation plan `docs/superpowers/plans/2026-10-09-bridge-editor-foundation.md` (live-verified).

## Design decisions this plan makes (not settled by the spec — flagged for Mark)

1. **Gamma.** The whole pipeline is gamma-space today (textures upload `GL_RGBA8`, no sRGB framebuffer, resolve never encodes). The bridge PBR path therefore decodes the albedo AND the received downlight with `pow(x, 2.2)`, lights in linear, and re-encodes the result with `pow(x, 1/2.2)` before writing the HDR target. Consequence: at the default material (metal 0, rough 1) the diffuse result equals today's `albedo × received` up to the `(1 − F)` Fresnel factor (≈ 0.96), so turning PBR on does not re-light the room — the §9.1 calibration then tunes from today's look, not from a dark linear one.
2. **Split ceiling.** `out = diffuse_ceiling(enc(D)) + max(enc(D + S) − enc(D), 0)` where D is linear diffuse and S linear specular. Lit diffuse can never reach bloom (§9.5); specular adds on top uncapped.
3. **Comm-set rooms** (another ship's room on the viewscreen RTT) keep today's shading: the probes hold the PLAYER's bridge, which would be the wrong room to reflect.
4. **Normal maps** use the existing `StageSlot::Bump`, which `_normal` siblings already fill for every model; no new slot.
5. **Spot light units.** The spec's falloff `(clamp(1 − (d/range)⁴))² / (d² + 1)` is in bridge units, so a useful intensity is in the thousands. The editor's default intensity is 2000; calibrate live.
6. **Profiles before emitters.** A light whose emitter names a profile uses that profile's CURRENT-alert-state `tint × level` as a steady colour (waves and fades arrive with the emitter plan); no profile ⇒ steady white, level 1 (§9.6).

## Global Constraints

- ⛔ Never run `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A` / `git add .`. Stage explicit paths. Temporary mutation: `cp f /tmp/bak` → edit → test → `cp /tmp/bak f` → `diff f /tmp/bak`.
- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/bridge-emitters`, branch `spike/bridge-emitters`. Build `cmake --build build -j`; after adding a source/test file `cmake -B build -S .` (the cache keeps Debug + the pinned Python). Never pass a different `CMAKE_BUILD_TYPE`; never run cmake from `native/`.
- GLSL 410 core. **Every sampler gets an explicit, unique texture unit in `set_frame_uniforms`, set on every use of the program** (a sampler left on unit 0, or two sampler TYPES sharing a unit, makes every draw `GL_INVALID_OPERATION` silently). Bridge-pass units: 0 base, **1 normal (Bump)**, 2 face_b, 3 AO, 4 AO depth, **5 roughness**, **6 metalness**, **7 probe green**, **8 probe yellow/red**, **9 BRDF LUT**.
- Shader errors appear only at RUNTIME: every shader change must be exercised by a GL frame test that draws through it.
- Material defaults: **metalness 0, roughness 1** (§9.2 C). Per channel, first hit wins: map → per-shape override → default. The NIF's own gloss/specular are NOT a source; the July spike's `_specular` multiplier is NOT ported.
- Maps by albedo filename: `<stem>_rough.tga`, `<stem>_metal.tga`, `<stem>_normal.tga` (stem with a trailing `_glow` stripped, like the existing `_normal` rule). **Interior loads only:** a STOCK albedo (resolved from the stock game dir) looks for siblings ONLY in the replacements overlay; a mod / replacements albedo looks ONLY beside itself. Non-interior (ship) loads keep today's behaviour byte-identically.
- Diffuse ceiling stays `kBridgeLighting.diffuse_max` (0.88) < `kBloomThreshold` (0.9); specular is uncapped.
- Probes: two — green and yellow/red (captured at yellow) — 256² RGBA16F, prefiltered over 6 mips (roughness 0, 0.2, 0.4, 0.6, 0.8, 1.0), box-projected against the bridge model's AABB, captured from the captain's-chair eye (`host_loop._BRIDGE_CAMERA_EYE`). Capture content = the bridge drawn diffuse-only in linear (no specular, no AO, no highlight), officers excluded, viewscreen black. Captured at bridge load and whenever overrides, spot lights or bridge lighting change — never per frame.
- Probe cross-fade green ↔ yellow/red over 0.5 s (§6.3 default `fade_s`), frozen under pause.
- Spot lights: max 32 (`kBridgeMaxSpots`); lights beyond are reported by name, never dropped silently; no shadows; AO never multiplies a spot.
- Without `--developer` the production bridge renders with PBR ON (this is the new look); the A/B switch and new debug views are developer-only. Without any per-bridge file the bridge gets PBR with defaults and no spots.
- Gate before calling the plan done: `scripts/check_tests.sh` exits 0, no new `tests/known_failures.txt` lines.

## Review Focus

1. **Turning PBR on re-lights the room.** At the default material the PBR output must match the legacy output within the `(1 − F)` factor. Pinned by Task 4's `DefaultMaterialMatchesLegacyWithinFresnel`.
2. **A shared stock texture picks up a mod's map, or a mod texture picks up our overlay map.** Pinned by Task 1's `InteriorStockAlbedoTakesSiblingsOnlyFromTheOverlay` and `InteriorModAlbedoTakesSiblingsOnlyBesideItself`.
3. **Sampler unit collisions / unbound cube samplers** turning every bridge draw into a silent GL error. Pinned by every Task 4–6 frame test asserting `glGetError() == GL_NO_ERROR` after `render`, including the comm-set and skinned paths (`CommSetAndOfficersDrawCleanWithPbrOn`).
4. **Specular lets lit diffuse bloom.** A bright metal floor reflecting a dim room must stay below the threshold; only reflections of bright things may cross it. Pinned by Task 4's `DiffuseNeverReachesBloomEvenWithPbr` and Task 6's `ReflectionOfABrightSourceMayExceedTheThreshold`.
5. **Editor edits not visible until relaunch.** A slider change must push overrides and re-capture the probes the same frame. Pinned by Task 9's `test_material_edit_pushes_overrides_and_requests_capture`.

---

## File Structure

**Assets (C++)**
- Modify `native/src/assets/include/assets/material.h` — `StageSlot::Roughness`, `StageSlot::Metalness` (appended before `Count`).
- Modify `native/src/assets/src/model_build.cc` / `model_build.h` — `_rough` / `_metal` sibling discovery; `ModelBuildContext::sibling_overlay_dirs` + `sibling_policy_interior`.
- Modify `native/src/assets/src/material_build.cc` / `material_build.h` — bind the new siblings.
- Modify `native/src/assets/src/cache.cc` + `native/src/assets/include/assets/cache.h` — pass the overlay dirs through; fold them into the cache key.

**Renderer (C++)**
- Create `native/src/renderer/include/renderer/bridge_pbr.h` — CPU twin of every PBR formula (header-only, `inline`).
- Create `native/src/renderer/include/renderer/bridge_probe.h`, `native/src/renderer/bridge_probe.cc` — capture, prefilter, BRDF LUT.
- Create shaders `native/src/renderer/shaders/probe_prefilter.{vert,frag}`, `native/src/renderer/shaders/brdf_lut.{vert,frag}` (registered where `bridge.frag` is embedded).
- Modify `native/src/renderer/shaders/bridge.frag`, `native/src/renderer/include/renderer/bridge_pass.h`, `native/src/renderer/bridge_pass.cc`, `native/src/renderer/include/renderer/bridge_lighting_tuning.h`, `native/src/renderer/include/renderer/cubemap_target.h` / `cubemap_target.cc` (per-mip face binding).
- Modify `native/src/host/host_bindings.cc` — bindings listed per task.

**Python**
- Create `engine/bridge_editor/materials.py` — document → per-mesh overrides.
- Create `engine/bridge_editor/lights.py` — document → spot list.
- Create `engine/bridge_editor/runtime.py` — load + push for a bridge instance (production path).
- Modify `engine/bridge_lighting.py` — `ProbeBlend`.
- Modify `engine/host_io.py`, `engine/renderer.py`, `engine/host_loop.py`, `engine/ui/bridge_emitters_panel.py`, `engine/ui/developer_options_panel.py`, `native/assets/ui-cef/js/bridge_emitters.js`, `native/assets/ui-cef/js/developer_options.js`.

**Tests** — listed per task.

---

### Task 1: Roughness / metalness sibling maps and the interior lookup policy

**Files:**
- Modify: `native/src/assets/include/assets/material.h:34-37`
- Modify: `native/src/assets/src/model_build.h` (`ModelBuildContext`), `native/src/assets/src/model_build.cc` (`load_all_textures` :148-290; `sibling_normal_filename` :767-780)
- Modify: `native/src/assets/src/material_build.h:25-56`, `native/src/assets/src/material_build.cc:83-181`
- Modify: `native/src/assets/include/assets/cache.h`, `native/src/assets/src/cache.cc` (load overload chain; cache key)
- Test: `native/tests/assets/cpu/model_build_test.cc`, `native/tests/assets/cpu/cache_test.cc`

**Interfaces:**
- Produces: `assets::Material::StageSlot::Roughness`, `StageSlot::Metalness` (values 9 and 10; `Count` becomes 11); `std::string assets::detail::sibling_map_filename(std::string_view fname, std::string_view suffix)` (strips a trailing `_glow` from the stem, appends `suffix` before the extension); `ModelBuildContext::sibling_overlay_dirs` (`std::vector<std::filesystem::path>`) and `ModelBuildContext::interior_sibling_policy` (`bool`); `AssetCache::load(..., bool interior, const std::vector<fs::path>& sibling_overlay_dirs)` overload.
- Policy (only when `interior_sibling_policy` is true): let `albedo` be the resolved albedo path. If `albedo.parent_path()` is one of the LAST entry of `texture_search_paths` (the stock dir — `game_asset_dirs` always ends with it) ⇒ probe `_rough`/`_metal`/`_normal` ONLY in `sibling_overlay_dirs`; otherwise ⇒ probe ONLY in `{albedo.parent_path()}`. When false (every ship load) ⇒ today's behaviour: probe all `texture_search_paths`.

- [ ] **Step 1: Write the failing tests**

In `model_build_test.cc` (the fixture already has `write_tga(name)` writing into its temp dir and `make_ctx()`; read the `SyntheticHullWithNormalSiblingGetsBumpFromDisk` test at :719 and reuse its helpers):

```cpp
TEST(ModelBuildFilenames, SiblingMapAppendsSuffixAndStripsGlow) {
    using assets::detail::sibling_map_filename;
    EXPECT_EQ(sibling_map_filename("Map 3.tga", "_rough"), "Map 3_rough.tga");
    EXPECT_EQ(sibling_map_filename("wall_glow.TGA", "_metal"), "wall_metal.TGA");
    EXPECT_EQ(sibling_map_filename("noext", "_rough"), "noext_rough");
}

TEST_F(ModelBuildTest, RoughAndMetalSiblingsBindTheirStages) {
    write_tga("hull_ID.tga");
    write_tga("hull_ID_rough.tga");
    write_tga("hull_ID_metal.tga");
    auto f = file_with_textured_shape();
    auto model = assets::detail::build_model(f, make_ctx());
    using S = assets::Material::StageSlot;
    const auto& m = model.materials[0];
    EXPECT_GE(m.stages[static_cast<size_t>(S::Roughness)].texture_index, 0);
    EXPECT_GE(m.stages[static_cast<size_t>(S::Metalness)].texture_index, 0);
}

TEST_F(ModelBuildTest, NoSiblingsLeavesRoughAndMetalEmpty) {
    write_tga("hull_ID.tga");
    auto f = file_with_textured_shape();
    auto model = assets::detail::build_model(f, make_ctx());
    using S = assets::Material::StageSlot;
    EXPECT_EQ(model.materials[0].stages[static_cast<size_t>(S::Roughness)].texture_index, -1);
    EXPECT_EQ(model.materials[0].stages[static_cast<size_t>(S::Metalness)].texture_index, -1);
}
```

A policy test needs two directories. Add, using the fixture's temp dir `dir_` (rename to the fixture's real member if different):

```cpp
// Interior policy (spec §9.2): a STOCK albedo takes siblings only from the
// overlay; a mod albedo only from beside itself.
TEST_F(ModelBuildTest, InteriorStockAlbedoTakesSiblingsOnlyFromTheOverlay) {
    namespace fs = std::filesystem;
    const fs::path stock = dir_ / "stock", mod = dir_ / "mod", overlay = dir_ / "overlay";
    for (const auto& d : {stock, mod, overlay}) fs::create_directories(d);
    write_tga_at(stock / "hull_ID.tga");
    write_tga_at(mod / "hull_ID_rough.tga");      // a mod's map for a STOCK albedo: must be ignored
    write_tga_at(overlay / "hull_ID_metal.tga");  // our overlay map: must be used
    auto ctx = make_ctx();
    ctx.texture_search_paths = {mod, stock};      // stock dir is LAST, as game_asset_dirs orders it
    ctx.sibling_overlay_dirs = {overlay};
    ctx.interior_sibling_policy = true;
    auto model = assets::detail::build_model(file_with_textured_shape(), ctx);
    using S = assets::Material::StageSlot;
    EXPECT_EQ(model.materials[0].stages[static_cast<size_t>(S::Roughness)].texture_index, -1);
    EXPECT_GE(model.materials[0].stages[static_cast<size_t>(S::Metalness)].texture_index, 0);
}

TEST_F(ModelBuildTest, InteriorModAlbedoTakesSiblingsOnlyBesideItself) {
    namespace fs = std::filesystem;
    const fs::path stock = dir_ / "stock", mod = dir_ / "mod", overlay = dir_ / "overlay";
    for (const auto& d : {stock, mod, overlay}) fs::create_directories(d);
    write_tga_at(mod / "hull_ID.tga");            // the mod overrides the albedo
    write_tga_at(overlay / "hull_ID_rough.tga");  // our stock-only map: must be ignored
    write_tga_at(mod / "hull_ID_metal.tga");      // the mod's own map: used
    auto ctx = make_ctx();
    ctx.texture_search_paths = {mod, stock};
    ctx.sibling_overlay_dirs = {overlay};
    ctx.interior_sibling_policy = true;
    auto model = assets::detail::build_model(file_with_textured_shape(), ctx);
    using S = assets::Material::StageSlot;
    EXPECT_EQ(model.materials[0].stages[static_cast<size_t>(S::Roughness)].texture_index, -1);
    EXPECT_GE(model.materials[0].stages[static_cast<size_t>(S::Metalness)].texture_index, 0);
}

TEST_F(ModelBuildTest, ShipLoadsKeepProbingEverySearchPath) {
    namespace fs = std::filesystem;
    const fs::path stock = dir_ / "stock", mod = dir_ / "mod";
    for (const auto& d : {stock, mod}) fs::create_directories(d);
    write_tga_at(stock / "hull_ID.tga");
    write_tga_at(mod / "hull_ID_normal.tga");
    auto ctx = make_ctx();
    ctx.texture_search_paths = {mod, stock};      // policy off (default): today's behaviour
    auto model = assets::detail::build_model(file_with_textured_shape(), ctx);
    using S = assets::Material::StageSlot;
    EXPECT_GE(model.materials[0].stages[static_cast<size_t>(S::Bump)].texture_index, 0);
}
```

If the fixture has only `write_tga(name)`, add `write_tga_at(const std::filesystem::path&)` beside it (same body, explicit path). Make `file_with_textured_shape()` reference the texture by basename `hull_ID.tga` (it already does for the existing sibling test — check).

In `cache_test.cc`, after `InteriorLoadCarriesTheNifContentHash`:

```cpp
TEST(AssetCacheTest, OverlayDirsAreAPartOfTheInteriorCacheKey) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    if (!fs::exists(dbridge_path())) GTEST_SKIP() << "DBridge not installed";
    assets::AssetCache cache(stub_config());
    auto a = cache.load(dbridge_path(), {dbridge_tex_path()}, {}, {}, 1.0f, false, true, {});
    auto b = cache.load(dbridge_path(), {dbridge_tex_path()}, {}, {}, 1.0f, false, true,
                        {fs::temp_directory_path()});
    EXPECT_NE(a.get(), b.get());
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmake -B build -S . && cmake --build build -j 2>&1 | tail -5`
Expected: compile FAIL — `no member named 'Roughness'`, `no member named 'sibling_overlay_dirs'`, `sibling_map_filename` undeclared.

- [ ] **Step 3: Implement**

- `material.h`: `Base = 0, Dark, Detail, Gloss, Glow, Bump, Decal0, Decal1, Decal2, Roughness, Metalness, Count`. Comment: "Roughness/Metalness: `<stem>_rough` / `<stem>_metal` siblings, read only by the bridge PBR path (spec 2026-10-08-bridge-emitters §9.2)."
- `model_build.cc`: replace the body of `sibling_normal_filename` with a call to a new generic `sibling_map_filename(fname, "_normal")` (declare `sibling_map_filename` in `model_build.h` inside `assets::detail`). In `load_all_textures`, generalise the `_normal` sibling probe into a loop over `{ {"_normal", &out.sibling_normal_for_image, /*reconstruct_z=*/true}, {"_rough", &out.sibling_rough_for_image, false}, {"_metal", &out.sibling_metal_for_image, false} }` keeping the `_normal` path's semantics exactly (missing = silent, corrupt = logged + skipped, never the checkerboard; `reconstruct_normal_map_z` only for `_normal`). The probe directories:

```cpp
// Interior sibling policy (spec 2026-10-08-bridge-emitters §9.2/§9.3).
std::vector<std::filesystem::path> sibling_dirs_for(
    const ModelBuildContext& ctx, const std::filesystem::path& resolved_albedo) {
    if (!ctx.interior_sibling_policy) return ctx.texture_search_paths;
    const auto parent = resolved_albedo.parent_path();
    const bool stock = !ctx.texture_search_paths.empty() &&
        std::filesystem::equivalent(parent, ctx.texture_search_paths.back());
    if (stock) return ctx.sibling_overlay_dirs;
    return {parent};
}
```

  (`std::filesystem::equivalent` throws if a path does not exist — wrap it in a `std::error_code` overload.) An empty dir list means no sibling probe at all.
- `TextureLoadResult` / `MaterialInputs` gain `sibling_rough_for_image` and `sibling_metal_for_image` (same type as `sibling_normal_for_image`); `apply_texture_property` binds them to `StageSlot::Roughness` / `Metalness` exactly where the sibling normal binds to Bump (:171-179), `apply_mode = 2`. `build_material` wires them like the normal map (:263-277).
- `ModelBuildContext` gains `std::vector<std::filesystem::path> sibling_overlay_dirs;` and `bool interior_sibling_policy = false;`.
- `cache.h/.cc`: add the overload with `const std::vector<fs::path>& sibling_overlay_dirs` after `interior`; the existing 7-arg overload forwards `{}`. Set `ctx.interior_sibling_policy = interior; ctx.sibling_overlay_dirs = sibling_overlay_dirs;`. Append to the cache key, only when non-empty: `"|overlay:" + join(dirs, ";")`.

- [ ] **Step 4: Run tests**

Run: `cmake --build build -j && ctest --test-dir build -R "ModelBuild|AssetCacheTest" --output-on-failure`
Expected: all PASS (the existing `_normal` / `_specular` tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add native/src/assets/include/assets/material.h native/src/assets/src/model_build.h native/src/assets/src/model_build.cc native/src/assets/src/material_build.h native/src/assets/src/material_build.cc native/src/assets/include/assets/cache.h native/src/assets/src/cache.cc native/tests/assets/cpu/model_build_test.cc native/tests/assets/cpu/cache_test.cc
git commit -m "feat(assets): _rough/_metal sibling maps and the interior stock/mod sibling policy"
```

---

### Task 2: Load the bridge with the overlay; report maps in model identity

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`load_model` :2946-2951 args; `model_identity` :6326-6375)
- Modify: `engine/renderer.py:188` (`load_model`), `engine/host_io.py` (`model_identity` decoding)
- Modify: `engine/host_loop.py:8016-8047` (bridge load)
- Test: `tests/unit/test_bridge_load_overlay_dirs.py` (create), `tests/host/test_bridge_editor_bindings.py`

**Interfaces:**
- Consumes: Task 1's `AssetCache::load(..., interior, sibling_overlay_dirs)`.
- Produces: `renderer.load_model(..., interior=False, sibling_overlay_dirs=None)`; `host_loop._bridge_overlay_dirs(tex_rel: str) -> list[str]` (replacements dirs for that relative texture dir — `mods.replacements().dirs_for(tex_rel)` as strings); `model_identity` per mesh gains `"maps": {"roughness": bool, "metalness": bool, "normal": bool}`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_bridge_load_overlay_dirs.py`:

```python
"""Bridge PBR: the bridge is loaded with the replacements overlay as its
sibling-map directory (spec 2026-10-08-bridge-emitters §9.2)."""
from engine import host_loop


def test_overlay_dirs_are_the_replacements_dirs_for_the_texture_rel(monkeypatch):
    class Rep:
        def dirs_for(self, rel):
            assert rel == "data/Models/Sets/DBridge/High"
            return ["/proj/native/assets/replacements/data/Models/Sets/DBridge/High"]

    monkeypatch.setattr(host_loop._mods, "replacements", lambda: Rep())
    assert host_loop._bridge_overlay_dirs("data/Models/Sets/DBridge/High") == [
        "/proj/native/assets/replacements/data/Models/Sets/DBridge/High"]


def test_no_overlay_files_means_no_overlay_dirs(monkeypatch):
    class Rep:
        def dirs_for(self, rel):
            return []

    monkeypatch.setattr(host_loop._mods, "replacements", lambda: Rep())
    assert host_loop._bridge_overlay_dirs("x") == []
```

(If `host_loop` imports the mods module under a different alias, use that alias; if it does not import it, add `from engine import mods as _mods` at module level — never capture a PATH at import, only the module.)

Append to `tests/host/test_bridge_editor_bindings.py`:

```python
def test_model_identity_meshes_report_maps(monkeypatch):
    from engine import host_io

    class FakeHost:
        @staticmethod
        def instance_translation(iid):
            return None

        @staticmethod
        def model_identity(iid):
            return {"source": b"/x.nif", "content_hash": "ab", "meshes": [
                {"mesh": 0, "block": 3, "name": b"floor", "node_chain": [],
                 "material": 0, "textures": [b"floor.tga"],
                 "maps": {"roughness": True, "metalness": False, "normal": False}}]}

    monkeypatch.setattr(host_io, "_h", FakeHost)
    mesh = host_io.model_identity(0)["meshes"][0]
    assert mesh["maps"] == {"roughness": True, "metalness": False, "normal": False}
```

(Match the real decoding: if `host_io.model_identity` rebuilds each mesh dict field by field, it must carry `maps` through unchanged.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_bridge_load_overlay_dirs.py tests/host/test_bridge_editor_bindings.py -v`
Expected: FAIL — `_bridge_overlay_dirs` missing; `maps` missing from the decoded mesh.

- [ ] **Step 3: Implement**

- `host_bindings.cc` `load_model`: add `py::arg("sibling_overlay_dirs") = std::vector<std::string>{}` and pass it (as `fs::path`s) to the Task 1 overload; it is also folded into the `g_loaded_models` dedupe key exactly as `interior` is (`rep_key`).
- `model_identity`: per mesh, from its material (`assets::material_or_default(*model, mesh.material_index())`):

```cpp
                  py::dict maps;
                  const auto& mat = assets::material_or_default(*model, mesh.material_index());
                  using S = assets::Material::StageSlot;
                  maps["roughness"] = mat.stages[static_cast<size_t>(S::Roughness)].texture_index >= 0;
                  maps["metalness"] = mat.stages[static_cast<size_t>(S::Metalness)].texture_index >= 0;
                  maps["normal"]    = mat.stages[static_cast<size_t>(S::Bump)].texture_index >= 0;
                  d["maps"] = std::move(maps);
```

- `engine/renderer.py` `load_model(..., interior=False, sibling_overlay_dirs=None)` forwards `list(sibling_overlay_dirs or [])`.
- `engine/host_io.py` `model_identity`: copy `maps` through (default `{"roughness": False, "metalness": False, "normal": False}` when absent — an old binary).
- `engine/host_loop.py`: add

```python
def _bridge_overlay_dirs(tex_rel) -> list:
    """The replacements-overlay dirs holding project-authored PBR maps for a
    stock bridge's textures (spec 2026-10-08-bridge-emitters §9.2). Resolved
    at use; [] when the overlay has nothing there."""
    return [str(d) for d in _mods.replacements().dirs_for(tex_rel)]
```

  and at the bridge load (`if is_bridge: handle = r.load_model(nif_abs, tex_abs, interior=True)`), pass `sibling_overlay_dirs=_bridge_overlay_dirs(<the same rel used to build tex_abs>)` — the `env` rel when `env` is set, else `_pp.dirname(nif) + "/High"`. Hold that rel in a local so both calls use one value.

- [ ] **Step 4: Run tests**

Run: `cmake --build build -j && uv run pytest tests/unit/test_bridge_load_overlay_dirs.py tests/host/test_bridge_editor_bindings.py tests/unit/test_host_io_binding_manifest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py engine/host_io.py engine/host_loop.py tests/unit/test_bridge_load_overlay_dirs.py tests/host/test_bridge_editor_bindings.py
git commit -m "feat(bridge-pbr): bridge loads with the overlay as its map dir; identity reports maps"
```

---

### Task 3: The PBR maths, pinned on the CPU

**Files:**
- Create: `native/src/renderer/include/renderer/bridge_pbr.h`
- Modify: `native/src/renderer/include/renderer/bridge_lighting_tuning.h` (PBR constants)
- Test: `native/tests/renderer/bridge_pbr_test.cc` (create; add to `native/tests/renderer/CMakeLists.txt` after `bridge_lighting_test.cc`)

**Interfaces:**
- Produces (namespace `renderer::pbr`, all `inline`, `glm::vec3` / `float`): `decode(glm::vec3)` = `pow(c, 2.2)`; `encode(glm::vec3)` = `pow(max(c,0), 1/2.2)`; `D_ggx(float n_dot_h, float rough)`; `G_smith(float n_dot_v, float n_dot_l, float rough)`; `F_schlick(float cos_t, glm::vec3 f0)`; `f0_for(glm::vec3 albedo_lin, float metal)` = `mix(0.04, albedo, metal)`; `spot_falloff(float d, float range)` = `(clamp(1 − (d/range)⁴, 0, 1))² / (d² + 1)`; `spot_cone(float cos_angle, float cos_outer, float cos_inner)` = `smoothstep(cos_outer, cos_inner, cos_angle)²`; `combine(glm::vec3 diffuse_lin, glm::vec3 spec_lin, float diffuse_max)` = `diffuse_ceiling(encode(D), max) + max(encode(D+S) − encode(D), 0)`; `specular_occlusion(float n_dot_v, float ao, float rough)` = `clamp(pow(n_dot_v + ao, exp2(−16·rough − 1)) − 1 + ao, 0, 1)`; `box_project(glm::vec3 pos, glm::vec3 dir, glm::vec3 box_min, glm::vec3 box_max, glm::vec3 probe_pos)` returning the parallax-corrected lookup direction; `prefilter_mip(float rough)` = `rough * (kBridgeProbeMips − 1)`. `bridge_lighting_tuning.h` gains `inline constexpr int kBridgeProbeFace = 256; inline constexpr int kBridgeProbeMips = 6; inline constexpr int kBridgeBrdfLutSize = 128; inline constexpr int kBridgeMaxSpots = 32; inline constexpr float kBridgeDefaultSpotIntensity = 2000.0f;`.

- [ ] **Step 1: Write the failing test**

```cpp
// native/tests/renderer/bridge_pbr_test.cc
//
// CPU twin of bridge.frag's PBR path (spec 2026-10-08-bridge-emitters §9):
// every formula the shader uses is pinned here, so a shader edit that drifts
// from these is a review finding, and the frame tests can assert against
// these values.
#include <gtest/gtest.h>
#include <renderer/bridge_pbr.h>
#include <renderer/bridge_lighting_tuning.h>
#include <renderer/bloom_pass.h>

using namespace renderer;

TEST(BridgePbr, EncodeDecodeRoundTrip) {
    const glm::vec3 c{0.1f, 0.5f, 0.9f};
    const glm::vec3 r = pbr::encode(pbr::decode(c));
    EXPECT_NEAR(r.x, c.x, 1e-5f); EXPECT_NEAR(r.y, c.y, 1e-5f); EXPECT_NEAR(r.z, c.z, 1e-5f);
}

TEST(BridgePbr, GgxNdfPeaksAtNormalAndNarrowsWhenSmooth) {
    EXPECT_GT(pbr::D_ggx(1.0f, 0.2f), pbr::D_ggx(1.0f, 0.8f));
    EXPECT_GT(pbr::D_ggx(1.0f, 0.2f), pbr::D_ggx(0.9f, 0.2f));
}

TEST(BridgePbr, FresnelIsF0HeadOnAndOneAtGrazing) {
    const glm::vec3 f0{0.04f};
    EXPECT_NEAR(pbr::F_schlick(1.0f, f0).x, 0.04f, 1e-6f);
    EXPECT_NEAR(pbr::F_schlick(0.0f, f0).x, 1.0f, 1e-6f);
}

TEST(BridgePbr, MetalTakesItsF0FromTheAlbedo) {
    const glm::vec3 a{0.9f, 0.5f, 0.1f};
    EXPECT_EQ(pbr::f0_for(a, 1.0f), a);
    EXPECT_EQ(pbr::f0_for(a, 0.0f), glm::vec3(0.04f));
}

TEST(BridgePbr, SpotFalloffIsWindowedInverseSquare) {
    EXPECT_FLOAT_EQ(pbr::spot_falloff(0.0f, 100.0f), 1.0f);
    EXPECT_FLOAT_EQ(pbr::spot_falloff(100.0f, 100.0f), 0.0f);
    EXPECT_FLOAT_EQ(pbr::spot_falloff(150.0f, 100.0f), 0.0f);
    EXPECT_GT(pbr::spot_falloff(10.0f, 100.0f), pbr::spot_falloff(20.0f, 100.0f));
}

TEST(BridgePbr, SpotConeIsOneInsideZeroOutside) {
    const float ci = std::cos(glm::radians(30.0f)), co = std::cos(glm::radians(60.0f));
    EXPECT_FLOAT_EQ(pbr::spot_cone(1.0f, co, ci), 1.0f);
    EXPECT_FLOAT_EQ(pbr::spot_cone(std::cos(glm::radians(70.0f)), co, ci), 0.0f);
    const float mid = pbr::spot_cone(std::cos(glm::radians(45.0f)), co, ci);
    EXPECT_GT(mid, 0.0f); EXPECT_LT(mid, 1.0f);
}

TEST(BridgePbr, DiffuseNeverReachesBloomEvenWithPbr) {
    for (float d = 0.0f; d < 50.0f; d += 0.25f) {
        const glm::vec3 out = pbr::combine(glm::vec3(d), glm::vec3(0.0f), kBridgeLighting.diffuse_max);
        EXPECT_LT(std::max(out.x, std::max(out.y, out.z)), kBloomThreshold) << d;
    }
}

TEST(BridgePbr, SpecularAddsOnTopUncapped) {
    const glm::vec3 base = pbr::combine(glm::vec3(0.5f), glm::vec3(0.0f), kBridgeLighting.diffuse_max);
    const glm::vec3 lit = pbr::combine(glm::vec3(0.5f), glm::vec3(4.0f), kBridgeLighting.diffuse_max);
    EXPECT_GT(lit.x, base.x);
    EXPECT_GT(lit.x, kBloomThreshold);
}

TEST(BridgePbr, SpecularOcclusionIsOneWhenOpenAndFallsInCreases) {
    EXPECT_NEAR(pbr::specular_occlusion(1.0f, 1.0f, 0.5f), 1.0f, 1e-5f);
    EXPECT_LT(pbr::specular_occlusion(0.5f, 0.2f, 0.5f), 0.5f);
}

TEST(BridgePbr, BoxProjectionPointsAtTheWallThePixelSees) {
    // Probe at the origin, box ±100. A pixel at x=+90 looking +x hits the
    // wall at x=+100: the corrected direction from the probe is ~+x.
    const glm::vec3 d = pbr::box_project({90, 0, 0}, {1, 0, 0}, {-100, -100, -100},
                                         {100, 100, 100}, {0, 0, 0});
    EXPECT_NEAR(d.x, 1.0f, 1e-4f);
    // A pixel at y=+90 looking +x hits (100, 90, 0): from the probe that is
    // up-and-right, not +x — the parallax correction this exists for.
    const glm::vec3 e = pbr::box_project({0, 90, 0}, {1, 0, 0}, {-100, -100, -100},
                                         {100, 100, 100}, {0, 0, 0});
    EXPECT_GT(e.y, 0.5f);
}

TEST(BridgePbr, PrefilterMipSpansTheChain) {
    EXPECT_FLOAT_EQ(pbr::prefilter_mip(0.0f), 0.0f);
    EXPECT_FLOAT_EQ(pbr::prefilter_mip(1.0f), float(kBridgeProbeMips - 1));
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j 2>&1 | tail -5`
Expected: compile FAIL — `renderer/bridge_pbr.h` not found.

- [ ] **Step 3: Implement**

`bridge_lighting_tuning.h`: add the five constants above (with a comment block citing spec §9 and Global Constraints).

`bridge_pbr.h`:

```cpp
// native/src/renderer/include/renderer/bridge_pbr.h
//
// CPU twin of the bridge PBR path in shaders/bridge.frag (spec
// docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md §9). Every
// function here has a GLSL counterpart of the same name in bridge.frag; keep
// them in step — bridge_pbr_test.cc pins these, and the frame tests assert
// the shader against them.
#pragma once
#include <algorithm>
#include <cmath>
#include <glm/glm.hpp>
#include <renderer/bridge_lighting_tuning.h>

namespace renderer::pbr {

inline constexpr float kGamma = 2.2f;
inline constexpr float kPi = 3.14159265358979f;

// The pipeline is gamma-space end to end (textures upload GL_RGBA8, resolve
// never encodes): the bridge decodes to light, then re-encodes.
inline glm::vec3 decode(glm::vec3 c) { return glm::pow(glm::max(c, glm::vec3(0.0f)), glm::vec3(kGamma)); }
inline glm::vec3 encode(glm::vec3 c) { return glm::pow(glm::max(c, glm::vec3(0.0f)), glm::vec3(1.0f / kGamma)); }

inline float D_ggx(float n_dot_h, float rough) {
    const float a = rough * rough, a2 = a * a;
    const float d = n_dot_h * n_dot_h * (a2 - 1.0f) + 1.0f;
    return a2 / std::max(kPi * d * d, 1e-7f);
}
inline float G_schlick_ggx(float n_dot_x, float k) { return n_dot_x / (n_dot_x * (1.0f - k) + k); }
inline float G_smith(float n_dot_v, float n_dot_l, float rough) {
    const float k = (rough + 1.0f) * (rough + 1.0f) / 8.0f;
    return G_schlick_ggx(n_dot_v, k) * G_schlick_ggx(n_dot_l, k);
}
inline glm::vec3 F_schlick(float cos_t, glm::vec3 f0) {
    const float m = std::pow(std::clamp(1.0f - cos_t, 0.0f, 1.0f), 5.0f);
    return f0 + (glm::vec3(1.0f) - f0) * m;
}
inline glm::vec3 f0_for(glm::vec3 albedo_lin, float metal) {
    return glm::mix(glm::vec3(0.04f), albedo_lin, metal);
}
inline float spot_falloff(float d, float range) {
    const float r = d / std::max(range, 1e-4f);
    const float w = std::clamp(1.0f - r * r * r * r, 0.0f, 1.0f);
    return w * w / (d * d + 1.0f);
}
inline float spot_cone(float cos_angle, float cos_outer, float cos_inner) {
    const float t = std::clamp((cos_angle - cos_outer) / std::max(cos_inner - cos_outer, 1e-5f), 0.0f, 1.0f);
    const float s = t * t * (3.0f - 2.0f * t);
    return s * s;
}
inline glm::vec3 combine(glm::vec3 diffuse_lin, glm::vec3 spec_lin, float diffuse_max) {
    const glm::vec3 d = encode(diffuse_lin);
    const glm::vec3 ds = encode(diffuse_lin + spec_lin);
    return diffuse_ceiling(d, diffuse_max) + glm::max(ds - d, glm::vec3(0.0f));
}
inline float specular_occlusion(float n_dot_v, float ao, float rough) {
    return std::clamp(std::pow(n_dot_v + ao, std::exp2(-16.0f * rough - 1.0f)) - 1.0f + ao, 0.0f, 1.0f);
}
inline glm::vec3 box_project(glm::vec3 pos, glm::vec3 dir, glm::vec3 bmin, glm::vec3 bmax, glm::vec3 probe) {
    const glm::vec3 inv = 1.0f / dir;
    const glm::vec3 t1 = (bmax - pos) * inv, t2 = (bmin - pos) * inv;
    const glm::vec3 tf = glm::max(t1, t2);
    const float t = std::min(tf.x, std::min(tf.y, tf.z));
    return glm::normalize(pos + dir * t - probe);
}
inline float prefilter_mip(float rough) { return std::clamp(rough, 0.0f, 1.0f) * float(kBridgeProbeMips - 1); }

}  // namespace renderer::pbr
```

(`diffuse_ceiling(glm::vec3, float)` already lives in `bridge_lighting_tuning.h`. Division by a zero `dir` component yields ±inf in `inv`, which the max/min handle — the test's axis-aligned case exercises it.)

- [ ] **Step 4: Run test**

Run: `cmake --build build -j && ctest --test-dir build -R "BridgePbr|DiffuseCeiling" --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/bridge_pbr.h native/src/renderer/include/renderer/bridge_lighting_tuning.h native/tests/renderer/bridge_pbr_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(bridge-pbr): CPU twin of the PBR maths"
```

---

### Task 4: PBR shading in bridge.frag — materials, normal maps, overrides, A/B switch

**Files:**
- Modify: `native/src/renderer/shaders/bridge.frag`, `native/src/renderer/shaders/bridge.vert` (no change unless needed), `native/src/renderer/include/renderer/bridge_pass.h`, `native/src/renderer/bridge_pass.cc`
- Modify: `native/src/host/host_bindings.cc` — `set_bridge_material_overrides`, `set_bridge_pbr_enabled`, debug-view clamp 0..10
- Modify: `engine/host_io.py` — wrappers
- Test: `native/tests/renderer/bridge_pbr_frame_test.cc` (create, add to CMake), `tests/host/test_bridge_editor_bindings.py`

**Interfaces:**
- Consumes: Task 1 stages; Task 3 `renderer::pbr::*` names (the GLSL mirrors them).
- Produces:
  - `struct renderer::BridgeMaterialOverride { int mesh; float roughness; float metalness; };` (`< 0` = "no override" for a channel).
  - `void BridgePass::set_material_overrides(unsigned long long model_handle, std::vector<BridgeMaterialOverride>)`; `void BridgePass::clear_material_overrides()`.
  - `void BridgePass::set_pbr_enabled(bool)` (default `true`); `bool BridgePass::pbr_enabled() const`.
  - `BridgeDebugView` gains `Roughness = 6, Metalness = 7, SpecularOnly = 8, ProbeMirror = 9, MapNormals = 10`.
  - Bindings: `set_bridge_material_overrides(instance_id, [(mesh, roughness, metalness)])` — NOT developer-gated (saved data applies in production); `None`/stale id clears; never raises. `set_bridge_pbr_enabled(bool)` — developer-gated no-op without `--developer`.
  - host_io: `set_bridge_material_overrides(instance_id, overrides)` and `set_bridge_pbr_enabled(on)`, both no-op headless.
  - Shader uniforms (per draw): `int u_pbr` (1 on main bridge / officers, 0 for comm sets or when disabled), `int u_has_rough_map`, `int u_has_metal_map`, `int u_has_normal_map`, `float u_rough_override` (`< 0` = none), `float u_metal_override`; samplers `u_normal_map` (1), `u_rough_map` (5), `u_metal_map` (6).

- [ ] **Step 1: Write the failing frame tests**

`native/tests/renderer/bridge_pbr_frame_test.cc` — copy `bridge_highlight_test.cc`'s fixture, but give `append_quad`'s vertices planar UVs (`uv = position.xy / 100` for the floor, `position.yz / 100` for the wall) so normal mapping has a tangent frame; add one test `NormalMapOnAUvLessMeshIsHarmless` that renders the original UV-less corner with a Bump map and asserts a finite result equal to the no-map render (the shader's degenerate-frame fallback), (window, pipeline, pass with AO off, `make_corner`, `corner_camera`, `lookup_fn`, RGBA16F target, 9×9 `render_floor` mean). Add a helper that gives the corner a solid-colour base texture (copy the `red_1x1()` / `black_1x1()` helper pattern from the renderer tests: a 1×1 RGBA8 texture uploaded with `assets::upload_texture` or the helper's existing code, set as `stages[Base]`), and a helper `set_map(StageSlot, glm::vec4 rgba)` that does the same for Roughness / Metalness / Bump. Then:

```cpp
TEST_F(BridgePbrFrame, DefaultMaterialMatchesLegacyWithinFresnel) {
    set_base({0.6f, 0.5f, 0.4f, 1.0f});
    pass->set_pbr_enabled(false);
    const glm::vec3 legacy = render_floor();
    pass->set_pbr_enabled(true);
    const glm::vec3 pbr = render_floor();
    // (1 - F) at F0 = 0.04 and the camera's ~55° view: within 6% per channel.
    for (int i = 0; i < 3; ++i) {
        EXPECT_NEAR(pbr[i], legacy[i], 0.06f * legacy[i] + 1e-3f) << i;
    }
}

TEST_F(BridgePbrFrame, MetalnessMapDarkensTheDiffuse) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    const glm::vec3 dielectric = render_floor();
    set_map(assets::Material::StageSlot::Metalness, {1, 1, 1, 1});
    const glm::vec3 metal = render_floor();   // no probe yet: a metal has ~no diffuse
    EXPECT_LT(metal.r, dielectric.r * 0.5f);
}

TEST_F(BridgePbrFrame, OverrideAppliesWhenThereIsNoMap) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    const glm::vec3 base = render_floor();
    pass->set_material_overrides(handle(), {{0, -1.0f, 1.0f}});   // metal 1 by override
    EXPECT_LT(render_floor().r, base.r * 0.5f);
    pass->clear_material_overrides();
    EXPECT_NEAR(render_floor().r, base.r, 1e-4f);
}

TEST_F(BridgePbrFrame, MapBeatsOverride) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    set_map(assets::Material::StageSlot::Metalness, {0, 0, 0, 1});   // map says dielectric
    const glm::vec3 by_map = render_floor();
    pass->set_material_overrides(handle(), {{0, -1.0f, 1.0f}});        // override says metal
    EXPECT_NEAR(render_floor().r, by_map.r, 1e-4f);
}

TEST_F(BridgePbrFrame, NormalMapChangesTheShading) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    const glm::vec3 flat = render_floor();
    // A tangent-space normal tilted hard sideways: the up-facing downlight
    // term drops.
    set_map(assets::Material::StageSlot::Bump, {1.0f, 0.5f, 0.5f, 1.0f});
    EXPECT_LT(render_floor().r, flat.r - 0.02f);
}

TEST_F(BridgePbrFrame, DiffuseNeverReachesBloomEvenWithPbr) {
    set_base({1, 1, 1, 1});
    renderer::Lighting bright;
    bright.ambient = glm::vec3(8.0f);
    const glm::vec3 c = render_floor_with(bright);
    EXPECT_LT(std::max(c.r, std::max(c.g, c.b)), renderer::kBloomThreshold);
}

TEST_F(BridgePbrFrame, CommSetAndOfficersDrawCleanWithPbrOn) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    render_as_comm_set();                     // comm set path: legacy shading, no GL error
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgePbrFrame, DebugViewsDrawWithoutGlErrors) {
    for (int v = 6; v <= 10; ++v) {
        pass->set_debug_view(static_cast<renderer::BridgeDebugView>(v));
        render_floor();
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR)) << v;
    }
    pass->set_debug_view(renderer::BridgeDebugView::Off);
}
```

`render_floor_with(Lighting)` and `render_as_comm_set()` are the fixture's `render_floor` with the lighting / `comm_set_id` (non-zero, instance tagged `set_comm_set_id`) parameterised — write them once in the fixture.

Host test (append to `tests/host/test_bridge_editor_bindings.py`):

```python
@pytest.mark.parametrize("name", ["set_bridge_material_overrides", "set_bridge_pbr_enabled"])
def test_pbr_binding_exists(host_module, name):
    assert hasattr(host_module, name)


def test_material_overrides_with_a_stale_id_never_raise(host_module):
    host_module.set_bridge_material_overrides(host_module.InstanceId(), [(0, 0.5, -1.0)])
    host_module.set_bridge_material_overrides(None, [])


def test_host_io_pbr_wrappers_degrade_headless(monkeypatch):
    from engine import host_io
    monkeypatch.setattr(host_io, "_h", None)
    host_io.set_bridge_material_overrides(0, [(0, 0.5, -1.0)])
    host_io.set_bridge_pbr_enabled(False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmake -B build -S . && cmake --build build -j 2>&1 | tail -5`
Expected: compile FAIL — `set_pbr_enabled` / `set_material_overrides` not members.

- [ ] **Step 3: Implement the pass side**

- `bridge_pass.h`: the struct, setters, `BridgeDebugView` values; private `bool pbr_enabled_ = true; unsigned long long overrides_model_ = 0; std::unordered_map<int, std::pair<float,float>> overrides_;`.
- `bridge_pass.cc` `set_frame_uniforms`: add `s.set_int("u_normal_map", 1); s.set_int("u_rough_map", 5); s.set_int("u_metal_map", 6);` (and Task 6 adds 7, 8, 9). `u_pbr` = `pbr_enabled_ && pass == scenegraph::Pass::Bridge` (comm set ⇒ 0).
- `draw_mesh` gains trailing params `int pbr, float rough_override, float metal_override`. It binds, every draw: Bump stage texture or the white fallback on unit 1 with `u_has_normal_map`; Roughness on 5 with `u_has_rough_map`; Metalness on 6 with `u_has_metal_map` (white fallback when absent — never leave a unit unbound); sets `u_pbr`, `u_rough_override`, `u_metal_override`. Use `assets::material_or_default` for the material (never the copying ternary).
- Sub-pass A computes the override for `(mh, mesh index)` from `overrides_` when `mh == overrides_model_`, else `(-1, -1)`. Sub-pass B (officers) passes `pbr` with no overrides.
- At the end of `render`, unbind units 1, 5, 6 (same pattern as the AO units).

- [ ] **Step 4: Implement the shader**

In `bridge.frag` add the uniforms above and GLSL twins of Task 3's functions with the same names (`decode`, `encode`, `D_ggx`, `G_smith`, `F_schlick`, `f0_for`, `diffuse_ceiling` already exists, `combine`, `specular_occlusion`). Add:

```glsl
// Tangent frame from screen-space derivatives (no mesh tangents) — the July
// spike's pbr_perturb_normal.
vec3 perturb_normal(vec3 N, vec2 uv, vec3 map_n) {
    vec3 dp1 = dFdx(v_world), dp2 = dFdy(v_world);
    vec2 duv1 = dFdx(uv), duv2 = dFdy(uv);
    vec3 dp2perp = cross(dp2, N), dp1perp = cross(N, dp1);
    vec3 T = dp2perp * duv1.x + dp1perp * duv2.x;
    vec3 B = dp2perp * duv1.y + dp1perp * duv2.y;
    float m = max(dot(T, T), dot(B, B));
    if (m < 1e-12) return N;          // no UV gradient (UV-less mesh): no tangent frame
    float invmax = inversesqrt(m);
    return normalize(mat3(T * invmax, B * invmax, N) * map_n);
}

float channel(int has_map, sampler2D map, float override_v, float dflt) {
    if (has_map != 0) return texture(map, v_uv).r;
    return override_v >= 0.0 ? override_v : dflt;
}
```

In `main()`, after the existing debug views 1/3/4/5 and before the legacy lighting, branch:

```glsl
    if (u_pbr != 0) {
        vec3 N = n;
        if (u_has_normal_map != 0)
            N = perturb_normal(n, base_uv, texture(u_normal_map, base_uv).xyz * 2.0 - 1.0);
        float rough = clamp(channel(u_has_rough_map, u_rough_map, u_rough_override, 1.0), 0.04, 1.0);
        float metal = clamp(channel(u_has_metal_map, u_metal_map, u_metal_override, 0.0), 0.0, 1.0);
        if (u_debug_view == 6) { FragColor = vec4(vec3(rough), 1.0); return; }
        if (u_debug_view == 7) { FragColor = vec4(vec3(metal), 1.0); return; }
        if (u_debug_view == 10) { FragColor = vec4(N * 0.5 + 0.5, 1.0); return; }
        vec3 albedo = (u_debug_view == 2) ? vec3(1.0) : decode(base.rgb);
        vec3 V = normalize(u_eye - v_world);
        float NdotV = max(dot(N, V), 1e-4);
        vec3 F0 = f0_for(albedo, metal);
        vec3 Fv = F_schlick(NdotV, F0);
        float h = clamp(dot(N, u_up) * 0.5 + 0.5, 0.0, 1.0);
        // The downlight (AO included) is authored in display space: decode
        // the WHOLE legacy received term, so AO reads exactly as it does today.
        vec3 received = decode(u_ambient * mix(u_down_bottom, u_down_top, h) * ao);
        vec3 diffuse = albedo * (1.0 - metal) * (vec3(1.0) - Fv) * received;
        vec3 spec = vec3(0.0);               // Task 6 adds the probe; Task 7 the spots
        if (u_debug_view == 8) { FragColor = vec4(encode(spec), 1.0); return; }
        vec3 col = combine(diffuse, spec, u_diffuse_max) * u_viewscreen_brightness;
        col = mix(col, vec3(1.0), clamp(u_viewscreen_flash, 0.0, 1.0));
        FragColor = vec4(apply_highlight(col), 1.0);
        return;
    }
```

Keep the legacy path unchanged below it (it is the A/B "off" side). Debug view 9 (probe mirror) is added by Task 6; until then view 9 falls through to the lit result.

- [ ] **Step 5: Implement the bindings**

```cpp
    // Bridge PBR per-shape material overrides (spec 2026-10-08-bridge-emitters
    // §9.2 source B). Production data: NOT developer-gated. None / stale clears.
    m.def("set_bridge_material_overrides",
          [](py::object instance_id, std::vector<std::tuple<int, float, float>> overrides) {
              if (!g_bridge_pass) return;
              if (instance_id.is_none()) { g_bridge_pass->clear_material_overrides(); return; }
              auto* inst = g_world.get(instance_id.cast<scenegraph::InstanceId>());
              if (inst == nullptr) { g_bridge_pass->clear_material_overrides(); return; }
              std::vector<renderer::BridgeMaterialOverride> v;
              for (const auto& [mesh, r, mt] : overrides) v.push_back({mesh, r, mt});
              g_bridge_pass->set_material_overrides(inst->model_handle, std::move(v));
          },
          py::arg("instance_id"), py::arg("overrides"),
          "Per-mesh roughness/metalness overrides for the bridge (mesh, rough, metal; "
          "< 0 = none). None or a stale id clears. Never raises.");

    m.def("set_bridge_pbr_enabled",
          [](bool on) {
              if (!dauntless::is_developer_mode() || !g_bridge_pass) return;
              g_bridge_pass->set_pbr_enabled(on);
          },
          py::arg("on"), "Developer-only A/B: bridge PBR on/off (default on).");
```

Extend `set_bridge_debug_view`'s clamp to `0..10`. Overrides must also be cleared where the bridge pass state resets on mission swap (`reset_frame_state` or the bridge-pass reset beside `g_bridge_highlight`). host_io wrappers follow the `set_bridge_highlight` pattern (getattr-guarded; update `_OPTIONAL_BINDINGS` and `tests/unit/test_host_io_binding_manifest.py` if the manifest test requires it).

- [ ] **Step 6: Run tests**

Run: `cmake --build build -j && ctest --test-dir build -R "BridgePbr|BridgeHighlight|BridgeAo|BridgeLighting|BridgePass|SkinnedBridge" --output-on-failure && uv run pytest tests/host/test_bridge_editor_bindings.py tests/unit/test_host_io_binding_manifest.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/shaders/bridge.frag native/src/renderer/include/renderer/bridge_pass.h native/src/renderer/bridge_pass.cc native/src/host/host_bindings.cc engine/host_io.py native/tests/renderer/bridge_pbr_frame_test.cc native/tests/renderer/CMakeLists.txt tests/host/test_bridge_editor_bindings.py tests/unit/test_host_io_binding_manifest.py
git commit -m "feat(bridge-pbr): linear GGX shading with layered material channels and normal maps"
```

---

### Task 5: Probe infrastructure — per-mip cubemap faces, GGX prefilter, BRDF LUT

**Files:**
- Modify: `native/src/renderer/include/renderer/cubemap_target.h`, `native/src/renderer/cubemap_target.cc`
- Create: `native/src/renderer/include/renderer/bridge_probe.h`, `native/src/renderer/bridge_probe.cc`
- Create: `native/src/renderer/shaders/probe_prefilter.vert`, `probe_prefilter.frag`, `brdf_lut.vert`, `brdf_lut.frag`; register them where the build embeds `bridge.frag` (grep CMake / the shader-embedding script for `bridge.frag` and add the four beside it); add the source files to the renderer library's CMake list
- Test: `native/tests/renderer/bridge_probe_test.cc` (create, add to CMake)

**Interfaces:**
- Consumes: Task 3 constants `kBridgeProbeFace`, `kBridgeProbeMips`, `kBridgeBrdfLutSize`.
- Produces:
  - `CubemapTarget::allocate(int face_size, int mip_levels)` (allocates every mip with `glTexImage2D` per face per level; the existing `allocate(int)` = `allocate(n, 1)` keeps the backdrop byte-identical); `CubemapTarget::bind_face(int face, int mip = 0) const` (sets the viewport to the mip's size).
  - `class renderer::BridgeProbe` with:
    - `bool ensure()` — lazily creates GL objects; false without a context;
    - `template <class DrawFace> void capture(glm::vec3 origin, DrawFace draw_face)` — `draw_face(const scenegraph::Camera&)` is called once per face with a 90° camera at `origin`, rendering into the raw cube (`kBridgeProbeFace`, 1 mip); then `prefilter()` runs;
    - `void prefilter()` — fills the output cube's `kBridgeProbeMips` mips, mip k = GGX importance-sampled convolution at roughness `k / (mips−1)` (mip 0 = a copy);
    - `GLuint texture() const` (the prefiltered cube), `bool valid() const`;
    - `static GLuint brdf_lut()` — lazily generated once per context, `kBridgeBrdfLutSize²` `GL_RG16F`, x = NdotV, y = roughness, rg = (A, B) of the split-sum.
  - Face orientation table: copy `BackdropPass::bake`'s exactly (`backdrop_pass.cc:157-199`), so sampling conventions match the sky cubemap.

- [ ] **Step 1: Write the failing tests**

`bridge_probe_test.cc` with a GL fixture (window as in `bridge_ao_test.cc`, skip without a context):

```cpp
TEST_F(BridgeProbeGl, CaptureFillsEachFaceWithWhatThatFaceSees) {
    renderer::BridgeProbe probe;
    ASSERT_TRUE(probe.ensure());
    // Each face clears to a colour keyed by its index: proves face order and
    // that every face was rendered.
    int face = 0;
    probe.capture(glm::vec3(0.0f), [&](const scenegraph::Camera&) {
        const float v = 0.1f * float(face + 1);
        glClearColor(v, v, v, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        ++face;
    });
    EXPECT_EQ(face, 6);
    EXPECT_TRUE(probe.valid());
    // Mip 0 of the PREFILTERED cube is a copy: +X face (index 0) reads 0.1.
    EXPECT_NEAR(read_cube_texel(probe.texture(), /*face=*/0, /*mip=*/0), 0.1f, 0.01f);
    EXPECT_NEAR(read_cube_texel(probe.texture(), /*face=*/5, /*mip=*/0), 0.6f, 0.01f);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeGl, RougherMipsBlendNeighbouringFaces) {
    renderer::BridgeProbe probe;
    ASSERT_TRUE(probe.ensure());
    int face = 0;
    probe.capture(glm::vec3(0.0f), [&](const scenegraph::Camera&) {
        const float v = (face == 0) ? 1.0f : 0.0f;   // only +X is lit
        glClearColor(v, v, v, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        ++face;
    });
    const float sharp = read_cube_texel(probe.texture(), 2, 0);   // +Y face, mip 0: black
    const float rough = read_cube_texel(probe.texture(), 2, renderer::kBridgeProbeMips - 1);
    EXPECT_NEAR(sharp, 0.0f, 0.01f);
    EXPECT_GT(rough, 0.02f);                                      // +X light bled in
}

TEST_F(BridgeProbeGl, BrdfLutMatchesTheKnownSplitSumCorners) {
    const GLuint lut = renderer::BridgeProbe::brdf_lut();
    ASSERT_NE(lut, 0u);
    // Head-on, smooth: A ≈ 1, B ≈ 0. Grazing, rough: A + B small.
    const glm::vec2 smooth_head_on = read_lut(lut, /*n_dot_v=*/0.99f, /*rough=*/0.05f);
    EXPECT_GT(smooth_head_on.x, 0.9f);
    EXPECT_LT(smooth_head_on.y, 0.05f);
    const glm::vec2 rough_grazing = read_lut(lut, 0.05f, 0.95f);
    EXPECT_LT(rough_grazing.x + rough_grazing.y, 0.5f);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeGl, CaptureRestoresTheCallersFramebufferAndViewport) {
    renderer::HdrTarget t;
    t.resize(64, 48);
    t.bind();
    glViewport(0, 0, 64, 48);
    renderer::BridgeProbe probe;
    ASSERT_TRUE(probe.ensure());
    probe.capture(glm::vec3(0.0f), [](const scenegraph::Camera&) {});
    GLint fbo = 0, vp[4] = {};
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fbo);
    glGetIntegerv(GL_VIEWPORT, vp);
    EXPECT_EQ(static_cast<GLuint>(fbo), t.fbo());
    EXPECT_EQ(vp[2], 64);
    EXPECT_EQ(vp[3], 48);
}
```

`read_cube_texel(tex, face, mip)` reads the centre texel's red channel with `glGetTexImage(GL_TEXTURE_CUBE_MAP_POSITIVE_X + face, mip, GL_RGBA, GL_FLOAT, ...)`; `read_lut(lut, x, y)` reads the RG texel at that normalised coordinate with `glGetTexImage(GL_TEXTURE_2D, 0, GL_RG, GL_FLOAT, ...)`. Write both in the test file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmake -B build -S . && cmake --build build -j 2>&1 | tail -5`
Expected: compile FAIL — `renderer/bridge_probe.h` not found.

- [ ] **Step 3: Implement**

`cubemap_target`: the `(face_size, mip_levels)` allocate (per level `glTexImage2D` for all 6 faces, `GL_TEXTURE_MAX_LEVEL = mip_levels − 1`); `bind_face(face, mip)` attaches `(face, mip)` and sets `glViewport(0,0,max(1,size>>mip),...)`.

`bridge_probe.cc`:
- `ensure()`: allocate `raw_` (`kBridgeProbeFace`, 1 mip) and `out_` (`kBridgeProbeFace`, `kBridgeProbeMips`) `CubemapTarget`s; compile the prefilter program; make a unit cube VAO.
- `capture(origin, draw)`: save FBO + viewport; `glEnable(GL_TEXTURE_CUBE_MAP_SEAMLESS)`; for each face i: `raw_.bind_face(i)`; build `scenegraph::Camera` with `eye = origin`, `target = origin + dir[i]`, `up = up[i]`, `fov 90°`, `aspect 1`, `near 0.5`, `far 2000`; `draw(cam)`. Then `prefilter()`; restore FBO + viewport.
- `prefilter()`: for each mip k and face i: `out_.bind_face(i, k)`; draw the face with `probe_prefilter` sampling `raw_` on unit 0 at `u_roughness = k/(mips−1)`; mip 0 uses roughness 0 (a straight copy).
- `probe_prefilter.frag`: the standard GGX importance-sampled prefilter (Karis), 256 Hammersley samples, `N = V = R = normalize(local direction)`, sampling `textureLod(u_env, L, mip_from_pdf)` to avoid fireflies (mip of the raw cube is 0 only, so plain `texture`). Write it out in full; GLSL 410.
- `brdf_lut.frag`: the standard split-sum integration (Karis) over 512 Hammersley samples with `G_smith` using `k = a²/2` (IBL remap), output `vec2(A, B)`; render once into a `kBridgeBrdfLutSize²` `GL_RG16F` texture.
- All GL objects released in the destructor; `brdf_lut()` holds a function-local static.

- [ ] **Step 4: Run tests**

Run: `cmake --build build -j && ctest --test-dir build -R "BridgeProbe|Backdrop|Cubemap" --output-on-failure`
Expected: PASS (backdrop tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/cubemap_target.h native/src/renderer/cubemap_target.cc native/src/renderer/include/renderer/bridge_probe.h native/src/renderer/bridge_probe.cc native/src/renderer/shaders/probe_prefilter.vert native/src/renderer/shaders/probe_prefilter.frag native/src/renderer/shaders/brdf_lut.vert native/src/renderer/shaders/brdf_lut.frag native/src/renderer/CMakeLists.txt native/tests/renderer/bridge_probe_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(bridge-pbr): reflection probe capture, GGX prefilter and BRDF LUT"
```

(Stage the actual CMake / shader-embedding files you changed — check `git status --short` and add them by path.)

---

### Task 6: Bridge probes in the pass — capture mode, box-projected reflections, the green ↔ yellow/red mix

**Files:**
- Modify: `native/src/renderer/shaders/bridge.frag`, `native/src/renderer/include/renderer/bridge_pass.h`, `native/src/renderer/bridge_pass.cc`
- Modify: `native/src/host/host_bindings.cc` — `set_bridge_probe_origin`, `set_bridge_probe_scales`, `set_bridge_probe_mix`, `request_bridge_probe_capture`
- Modify: `engine/host_io.py` — wrappers
- Test: `native/tests/renderer/bridge_pbr_frame_test.cc` (extend), `tests/host/test_bridge_editor_bindings.py`

**Interfaces:**
- Consumes: Task 5 `BridgeProbe`; Task 3 `pbr::box_project`, `pbr::specular_occlusion`, `pbr::prefilter_mip`.
- Produces:
  - `BridgePass::set_probe_origin(glm::vec3)`, `set_probe_scales(float green, float yellow_red)` (ambient multipliers each probe is captured with), `set_probe_mix(float)` (0 = green, 1 = yellow/red), `request_probe_capture()` (marks dirty; capture happens inside the next main-bridge `render`, before AO).
  - Capture draws: the main bridge sub-pass A only (officers excluded), `u_capture = 1` (diffuse-only, linear OUTPUT — no encode, no ceiling, no AO, no highlight, viewscreen black), once per probe with `lighting.ambient × scale`.
  - Box = the bridge model's AABB from its CPU mesh data (all meshes through node worlds), computed once per model handle and cached.
  - Shader: samplers `u_probe_a` (7, samplerCube), `u_probe_b` (8, samplerCube), `u_brdf_lut` (9, sampler2D); uniforms `int u_has_probe`, `float u_probe_mix`, `vec3 u_probe_pos`, `vec3 u_box_min`, `vec3 u_box_max`, `int u_capture`.
  - Specular term: `R = reflect(-V, N)`; `Rb = box_project(v_world, R, box_min, box_max, probe_pos)`; `pre = mix(textureLod(u_probe_a, Rb, mip), textureLod(u_probe_b, Rb, mip), u_probe_mix)` with `mip = prefilter_mip(rough)`; `ab = texture(u_brdf_lut, vec2(NdotV, rough)).rg`; `spec = pre * (F0 * ab.x + ab.y) * specular_occlusion(NdotV, ao, rough)`. Debug view 9 = `encode(textureLod(u_probe_a, R, 0))` (mirror sphere).
  - Bindings (NOT developer-gated — production): `set_bridge_probe_origin((x,y,z))`, `set_bridge_probe_scales(green, yellow_red)`, `set_bridge_probe_mix(t)`, `request_bridge_probe_capture()`; all no-ops before init.

- [ ] **Step 1: Write the failing frame tests** (extend `bridge_pbr_frame_test.cc`)

Build a second model for these tests: the corner's floor + wall, with the WALL a separate mesh textured bright red and the floor neutral grey (so a reflection is identifiable by hue). Then:

```cpp
TEST_F(BridgePbrFrame, ASmoothMetalFloorReflectsTheRedWall) {
    use_red_wall_corner();
    set_floor_override(/*rough=*/0.05f, /*metal=*/1.0f);
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->set_probe_scales(1.0f, 1.0f);
    pass->request_probe_capture();
    const glm::vec3 c = render_floor();
    EXPECT_GT(c.r, c.g * 1.5f);                 // the floor shows red
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgePbrFrame, RoughFloorReflectsLessDistinctly) {
    use_red_wall_corner();
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->request_probe_capture();
    set_floor_override(0.05f, 1.0f);
    const glm::vec3 smooth = render_floor();
    set_floor_override(1.0f, 1.0f);
    const glm::vec3 rough = render_floor();
    EXPECT_GT(smooth.r - smooth.g, rough.r - rough.g);
}

TEST_F(BridgePbrFrame, ProbeMixCrossFadesBetweenTheTwoProbes) {
    use_red_wall_corner();
    set_floor_override(0.05f, 1.0f);
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->set_probe_scales(2.0f, 0.5f);          // green probe 4x brighter
    pass->request_probe_capture();
    pass->set_probe_mix(0.0f);
    const float green = render_floor().r;
    pass->set_probe_mix(1.0f);
    const float yr = render_floor().r;
    pass->set_probe_mix(0.5f);
    const float mid = render_floor().r;
    EXPECT_GT(green, yr);
    EXPECT_LT(mid, green); EXPECT_GT(mid, yr);
}

TEST_F(BridgePbrFrame, ReflectionOfABrightSourceMayExceedTheThreshold) {
    use_red_wall_corner();
    set_floor_override(0.05f, 1.0f);
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->set_probe_scales(40.0f, 40.0f);        // the captured room is very bright
    pass->request_probe_capture();
    const glm::vec3 c = render_floor();
    EXPECT_GT(std::max(c.r, std::max(c.g, c.b)), renderer::kBloomThreshold);
}

TEST_F(BridgePbrFrame, NoCaptureMeansNoSpecularAndNoGlError) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    set_floor_override(0.05f, 1.0f);
    render_floor();                              // u_has_probe = 0
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}
```

(`set_floor_override` calls `pass->set_material_overrides(handle(), {{floor_mesh, rough, metal}})`; `use_red_wall_corner` swaps the fixture's model for the two-mesh variant and remembers `floor_mesh`.)

Host tests:

```python
@pytest.mark.parametrize("name", ["set_bridge_probe_origin", "set_bridge_probe_scales",
                                  "set_bridge_probe_mix", "request_bridge_probe_capture"])
def test_probe_binding_exists(host_module, name):
    assert hasattr(host_module, name)


def test_probe_bindings_are_safe_before_init(host_module):
    host_module.set_bridge_probe_origin((0.0, 87.0, 50.0))
    host_module.set_bridge_probe_scales(1.5, 1.0)
    host_module.set_bridge_probe_mix(0.25)
    host_module.request_bridge_probe_capture()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: compile FAIL — `set_probe_origin` not a member.

- [ ] **Step 3: Implement**

- `BridgePass` owns `BridgeProbe probe_green_, probe_yr_`, `glm::vec3 probe_origin_`, `float scale_green_ = 1, scale_yr_ = 1, probe_mix_ = 0`, `bool probe_dirty_ = false`, and a cached `{handle, box_min, box_max}`.
- In `render`, for `main_bridge` and `probe_dirty_` and `probe_green_.ensure()`: for each probe, `capture(probe_origin_, [&](const Camera& face_cam) { render_capture(world, face_cam, pipeline, lookup, scaled_lighting); })`, where `render_capture` runs sub-pass A only with `u_capture = 1`, depth on, cull off, into the bound face. Then `probe_dirty_ = false`. Capture BEFORE the AO pre-pass.
- `set_frame_uniforms`: units 7/8/9 always set; bind the probe cubes and LUT when valid (`u_has_probe = 1`), else bind nothing to 7/8/9 BUT keep `u_has_probe = 0` so the shader never samples them (a cube sampler with no cube bound must not be sampled). Unbind 7/8/9 at the end of `render`.
- Shader `u_capture != 0` path: linear `albedo × (1 − metal) × decode(u_ambient × mix(u_down_bottom, u_down_top, h))` (no AO) written UNENCODED (the probe holds linear radiance); `u_unlit` meshes write black; return before specular/ceiling/highlight.
- Shader PBR path: add the specular term above in place of `vec3 spec = vec3(0.0)`, guarded by `u_has_probe`.
- Probe state resets with the other bridge state on mission swap; a new bridge model (handle change) marks the probes dirty automatically.
- Bindings as listed, writing `g_bridge_pass` when it exists and also stashing the values in globals that `init` re-applies (the `g_bridge_highlight` pattern).

- [ ] **Step 4: Run tests**

Run: `cmake --build build -j && ctest --test-dir build -R "BridgePbr|BridgeProbe|BridgeHighlight|BridgeAo|BridgeLighting|BridgePass|SkinnedBridge" --output-on-failure && uv run pytest tests/host/test_bridge_editor_bindings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/bridge.frag native/src/renderer/include/renderer/bridge_pass.h native/src/renderer/bridge_pass.cc native/src/host/host_bindings.cc engine/host_io.py native/tests/renderer/bridge_pbr_frame_test.cc tests/host/test_bridge_editor_bindings.py tests/unit/test_host_io_binding_manifest.py
git commit -m "feat(bridge-pbr): box-projected reflection probes, green and yellow/red"
```

---

### Task 7: Static spot lights in the pass

**Files:**
- Modify: `native/src/renderer/shaders/bridge.frag`, `native/src/renderer/include/renderer/bridge_pass.h`, `native/src/renderer/bridge_pass.cc`, `native/src/host/host_bindings.cc`, `engine/host_io.py`
- Test: `native/tests/renderer/bridge_pbr_frame_test.cc` (extend), `tests/host/test_bridge_editor_bindings.py`

**Interfaces:**
- Consumes: Task 3 `pbr::spot_falloff`, `pbr::spot_cone`, `kBridgeMaxSpots`.
- Produces: `struct renderer::BridgeSpot { glm::vec3 position; glm::vec3 direction; float cos_inner; float cos_outer; float range; glm::vec3 radiance; };` (`radiance` = linear colour × intensity); `std::size_t BridgePass::set_spots(std::vector<BridgeSpot>)` — keeps the first `kBridgeMaxSpots`, returns how many were dropped; binding `set_bridge_spots([(pos3, dir3, inner_deg, outer_deg, range, (r,g,b), intensity)]) -> int` (dropped count; NOT developer-gated; converts degrees to cosines, normalises direction, colour × intensity → radiance) — and setting spots marks the probes dirty. Shader: `const int MAX_SPOTS = 32; uniform int u_spot_count; uniform vec3 u_spot_pos[32], u_spot_dir[32], u_spot_radiance[32]; uniform vec4 u_spot_params[32]; // x cos_inner, y cos_outer, z range`. host_io `set_bridge_spots(spots) -> int` (0 headless).

- [ ] **Step 1: Write the failing tests**

```cpp
TEST_F(BridgePbrFrame, SpotLightsTheFloorInsideItsCone) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    const glm::vec3 dark = render_floor();
    pass->set_spots({{{70.0f, 0.0f, 60.0f}, {0.0f, 0.0f, -1.0f},
                      std::cos(glm::radians(20.0f)), std::cos(glm::radians(30.0f)),
                      200.0f, glm::vec3(1.0f) * 2000.0f}});
    EXPECT_GT(render_floor().r, dark.r + 0.05f);
}

TEST_F(BridgePbrFrame, SpotDoesNotLightOutsideItsCone) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    const glm::vec3 dark = render_floor();
    // Pointing away along +y: the floor point at x=70 is outside the cone.
    pass->set_spots({{{70.0f, 0.0f, 60.0f}, {0.0f, 1.0f, 0.0f},
                      std::cos(glm::radians(10.0f)), std::cos(glm::radians(15.0f)),
                      200.0f, glm::vec3(1.0f) * 2000.0f}});
    EXPECT_NEAR(render_floor().r, dark.r, 1e-3f);
}

TEST_F(BridgePbrFrame, SpotsBeyondTheCapAreDroppedAndCounted) {
    std::vector<renderer::BridgeSpot> many(renderer::kBridgeMaxSpots + 3,
        renderer::BridgeSpot{{0, 0, 50}, {0, 0, -1}, 0.9f, 0.8f, 100.0f, glm::vec3(1.0f)});
    EXPECT_EQ(pass->set_spots(many), 3u);
    render_floor();
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgePbrFrame, ASpotNeverMakesLitDiffuseBloom) {
    set_base({1, 1, 1, 1});
    set_floor_override(1.0f, 0.0f);   // fully rough dielectric: almost all diffuse
    pass->set_spots({{{70.0f, 0.0f, 20.0f}, {0.0f, 0.0f, -1.0f}, 0.95f, 0.9f, 200.0f,
                      glm::vec3(1.0f) * 1.0e6f}});
    const glm::vec3 c = render_floor();
    // Diffuse is capped; only the (small, rough) specular may add above it.
    EXPECT_LT(c.r, kBridgeLighting.diffuse_max + 0.25f);
}
```

Host test:

```python
def test_set_bridge_spots_returns_dropped_count(host_module):
    spot = ((0.0, 0.0, 50.0), (0.0, 0.0, -1.0), 30.0, 60.0, 120.0, (1.0, 1.0, 1.0), 2000.0)
    assert host_module.set_bridge_spots([spot]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: compile FAIL — `BridgeSpot` undeclared.

- [ ] **Step 3: Implement**

- Pass: store spots; upload arrays once per `render` in `set_frame_uniforms` (`set_vec3_array` / `set_vec4_array` as `frame.cc:645-668` does for dynamic lights); `u_spot_count` = 0 on comm sets and in capture mode? — NO: capture mode INCLUDES spots' diffuse (the probe must see the room lit by them; §9.6 static lights are steady). Comm sets: 0.
- Shader, inside the PBR path after the probe term:

```glsl
    for (int i = 0; i < u_spot_count; ++i) {
        vec3 Lv = u_spot_pos[i] - v_world;
        float d = length(Lv);
        vec3 L = Lv / max(d, 1e-4);
        float NdotL = max(dot(N, L), 0.0);
        if (NdotL <= 0.0) continue;
        float att = spot_falloff(d, u_spot_params[i].z)
                  * spot_cone(dot(-L, u_spot_dir[i]), u_spot_params[i].y, u_spot_params[i].x);
        if (att <= 0.0) continue;
        vec3 H = normalize(L + V);
        float NdotH = max(dot(N, H), 0.0);
        vec3 F = F_schlick(max(dot(V, H), 0.0), F0);
        vec3 radiance = u_spot_radiance[i] * att * NdotL;
        diffuse += (vec3(1.0) - F) * (1.0 - metal) * albedo / 3.14159265 * radiance;
        spec += D_ggx(NdotH, rough) * G_smith(NdotV, NdotL, rough) * F
              / max(4.0 * NdotV * NdotL, 1e-4) * radiance;
    }
```

  Add the GLSL twins `spot_falloff` / `spot_cone` with Task 3's exact formulas. In capture mode the same loop adds only the diffuse half. Spots are not multiplied by AO.
- Binding: build `BridgeSpot`s; `set_spots` returns dropped; call `request_probe_capture()`.

- [ ] **Step 4: Run tests**

Run: `cmake --build build -j && ctest --test-dir build -R "BridgePbr|BridgePbrFrame" --output-on-failure && uv run pytest tests/host/test_bridge_editor_bindings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/bridge.frag native/src/renderer/include/renderer/bridge_pass.h native/src/renderer/bridge_pass.cc native/src/host/host_bindings.cc engine/host_io.py native/tests/renderer/bridge_pbr_frame_test.cc tests/host/test_bridge_editor_bindings.py tests/unit/test_host_io_binding_manifest.py
git commit -m "feat(bridge-pbr): static spot lights with windowed inverse-square falloff"
```

---

### Task 8: Python runtime — document → overrides and spots, probe blend, bridge-load push

**Files:**
- Create: `engine/bridge_editor/materials.py`, `engine/bridge_editor/lights.py`, `engine/bridge_editor/runtime.py`
- Modify: `engine/bridge_lighting.py` (`ProbeBlend`), `engine/host_loop.py` (bridge load push; per-frame probe mix; probe origin + scales)
- Test: `tests/unit/test_bridge_materials.py`, `tests/unit/test_bridge_lights.py`, `tests/unit/test_bridge_runtime.py`, `tests/unit/test_bridge_lighting.py` (extend or create — check the existing name first with `ls tests/unit | grep bridge_lighting`)

**Interfaces:**
- Consumes: `lighting_doc.load / match_shapes`; `host_io.model_identity`, `set_bridge_material_overrides`, `set_bridge_spots`, `set_bridge_probe_origin`, `set_bridge_probe_scales`, `set_bridge_probe_mix`, `request_bridge_probe_capture`; `bridge_lighting.ambient_scale_for_alert`.
- Produces:
  - `materials.overrides(doc, matched: dict[key, mesh]) -> list[tuple[int, float, float]]` — one `(mesh, rough, metal)` per matched shape with a `material` section, `-1.0` for an absent channel; sorted by mesh.
  - `lights.spots(doc, matched, alert_level: int) -> tuple[list[tuple], list[str]]` — `(pos, dir, inner_deg, outer_deg, range, (r,g,b), intensity)` per matched shape whose emitter has a `light`; colour = the named profile's state for `alert_level` (`0` green, `1` yellow, `2` red) `tint × level`, or white × 1 when there is no profile; a state that is missing ⇒ that light is OFF (skipped); defaults `inner_deg 30, outer_deg 60, range 200, intensity kDefaultIntensity = 2000.0`. Second element: warnings — the shape keys beyond 32, `"<key>: dropped (more than 32 bridge lights)"`.
  - `runtime.BridgeRuntime` with `attach(iid) -> None` (load doc via the instance's content hash, match, push overrides + spots, origin, scales, request capture; stores the doc), `push(doc) -> list[str]` (re-push from an edited doc; returns warnings), `on_alert(level) -> None` (re-push spots when the alert state changes; the probes keep their capture), `detach()` (clear overrides + spots). Never raises: a missing identity / hash ⇒ clears and returns.
  - `bridge_lighting.ProbeBlend(fade_s=0.5)` with `update(alert_level, dt) -> float` (mix target 0 for green, 1 for yellow/red; moves toward it at `1/fade_s` per second; starts AT the first target, no fade on the first call).
  - `bridge_lighting.probe_scales() -> tuple[float, float]` = `(ambient_scale_for_alert(0), ambient_scale_for_alert(1))`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_bridge_materials.py`:

```python
from engine.bridge_editor import lighting_doc as ld, materials


def test_overrides_from_matched_shapes():
    d = ld.empty_doc("x")
    ld.shape_entry(d, 3, "floor")["material"] = {"roughness": 0.3}
    ld.shape_entry(d, 7, "rail")["material"] = {"metalness": 1.0}
    ld.shape_entry(d, 9, "plain")
    assert materials.overrides(d, {"3:floor": 4, "7:rail": 1, "9:plain": 2}) == [
        (1, -1.0, 1.0), (4, 0.3, -1.0)]


def test_unmatched_shapes_are_ignored():
    d = ld.empty_doc("x")
    ld.shape_entry(d, 3, "floor")["material"] = {"roughness": 0.3}
    assert materials.overrides(d, {}) == []
```

`tests/unit/test_bridge_lights.py`:

```python
from engine.bridge_editor import lighting_doc as ld, lights


def _doc():
    d = ld.empty_doc("x")
    d["profiles"]["red_bar"] = {
        "green": {"tint": [1, 0.2, 0.1], "level": 0},
        "red": {"tint": [1, 0.1, 0.05], "level": 4},
    }
    e = ld.shape_entry(d, 5, "bar")
    e["emitter"] = {"profile": "red_bar",
                    "light": {"position": [1, 2, 3], "direction": [0, 0, -1]}}
    w = ld.shape_entry(d, 6, "lamp")
    w["emitter"] = {"light": {"position": [0, 0, 9], "direction": [0, 0, -1],
                              "inner_deg": 10, "outer_deg": 20, "range": 50, "intensity": 900}}
    return d


def test_no_profile_is_steady_white():
    spots, warnings = lights.spots(_doc(), {"6:lamp": 0}, alert_level=0)
    assert spots == [((0, 0, 9), (0, 0, -1), 10, 20, 50, (1.0, 1.0, 1.0), 900)]
    assert warnings == []


def test_profile_state_for_the_alert_gives_the_colour():
    spots, _ = lights.spots(_doc(), {"5:bar": 1}, alert_level=2)
    (pos, dirn, inner, outer, rng, colour, intensity), = spots
    assert colour == (4.0, 0.4, 0.2)
    assert (inner, outer, rng, intensity) == (30, 60, 200, lights.DEFAULT_INTENSITY)


def test_missing_state_turns_the_light_off():
    spots, _ = lights.spots(_doc(), {"5:bar": 1}, alert_level=1)   # no yellow state
    assert spots == []


def test_more_than_32_are_reported_by_name():
    d = ld.empty_doc("x")
    matched = {}
    for i in range(34):
        ld.shape_entry(d, i, f"s{i}")["emitter"] = {
            "light": {"position": [0, 0, 0], "direction": [0, 0, -1]}}
        matched[f"{i}:s{i}"] = i
    spots, warnings = lights.spots(d, matched, alert_level=0)
    assert len(spots) == 32
    assert len(warnings) == 2 and "dropped" in warnings[0]
```

`tests/unit/test_bridge_runtime.py`:

```python
import pytest

from engine.bridge_editor import lighting_doc as ld, lighting_writer as lw, runtime

HASH = "0123456789abcdef"
INFO = {"source": "/x.nif", "content_hash": HASH, "meshes": [
    {"mesh": 0, "block": 3, "name": "floor", "node_chain": [], "material": 0,
     "textures": [], "maps": {"roughness": False, "metalness": False, "normal": False}}]}


class FakeIO:
    def __init__(self, info=INFO):
        self.info = info
        self.calls = []

    def model_identity(self, iid):
        return self.info

    def __getattr__(self, name):
        def rec(*a):
            self.calls.append((name,) + a)
            return 0
        return rec


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setattr(ld.paths, "game_asset_dirs", lambda rel: [tmp_path / "stock" / rel])
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: tmp_path)
    return tmp_path


def names(io):
    return [c[0] for c in io.calls]


def test_attach_pushes_overrides_spots_origin_scales_and_capture(proj):
    d = ld.empty_doc("x")
    ld.shape_entry(d, 3, "floor")["material"] = {"roughness": 0.25}
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0.0, 87.0, 50.0), alert=lambda: 0)
    rt.attach("iid")
    assert ("set_bridge_material_overrides", "iid", [(0, 0.25, -1.0)]) in io.calls
    assert ("set_bridge_spots", []) in io.calls
    assert ("set_bridge_probe_origin", (0.0, 87.0, 50.0)) in io.calls
    assert names(io)[-1] == "request_bridge_probe_capture"


def test_attach_without_a_hash_clears_and_does_not_raise(proj):
    io = FakeIO(info={"source": "", "content_hash": "", "meshes": []})
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    assert ("set_bridge_material_overrides", None, []) in io.calls


def test_a_broken_file_is_ignored_not_raised(proj):
    (proj / "bridge_lighting").mkdir()
    (proj / "bridge_lighting" / f"{HASH}.json").write_text("{broken")
    io = FakeIO()
    runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0).attach("iid")
    assert ("set_bridge_material_overrides", "iid", []) in io.calls


def test_alert_change_repushes_spots_only(proj):
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    io.calls.clear()
    rt.on_alert(2)
    assert names(io) == ["set_bridge_spots"]
```

ProbeBlend tests (in the bridge-lighting test file):

```python
from engine import bridge_lighting as bl


def test_probe_blend_starts_at_its_target_and_fades():
    b = bl.ProbeBlend(fade_s=0.5)
    assert b.update(0, 0.016) == 0.0
    assert b.update(2, 0.25) == pytest.approx(0.5)
    assert b.update(2, 0.5) == 1.0
    assert b.update(1, 1.0) == 1.0          # yellow and red share a probe


def test_probe_blend_first_call_has_no_fade():
    assert bl.ProbeBlend().update(2, 0.016) == 1.0


def test_probe_blend_holds_with_zero_dt():
    b = bl.ProbeBlend()
    b.update(0, 0.0)
    assert b.update(2, 0.0) == 0.0


def test_probe_scales_are_the_green_and_yellow_ambient():
    assert bl.probe_scales() == (bl.ambient_scale_for_alert(0), bl.ambient_scale_for_alert(1))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_bridge_materials.py tests/unit/test_bridge_lights.py tests/unit/test_bridge_runtime.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement**

`engine/bridge_editor/materials.py`:

```python
"""Per-bridge document -> per-mesh material overrides (spec
2026-10-08-bridge-emitters §9.2 source B). -1.0 = no override for a channel."""


def overrides(doc, matched):
    out = []
    for key, mesh in matched.items():
        mat = doc["shapes"].get(key, {}).get("material")
        if not mat:
            continue
        out.append((int(mesh), float(mat.get("roughness", -1.0)),
                    float(mat.get("metalness", -1.0))))
    return sorted(out)
```

`engine/bridge_editor/lights.py`:

```python
"""Per-bridge document -> static spot lights (spec 2026-10-08-bridge-emitters
§6.2, §9.6). Before the emitter plan, a profile contributes its CURRENT alert
state's tint x level as a steady colour (waves and fades come later); no
profile = steady white, level 1; a profile with no state for this alert = off."""

MAX_SPOTS = 32               # kBridgeMaxSpots
DEFAULT_INTENSITY = 2000.0   # kBridgeDefaultSpotIntensity; calibrate live
_STATE = {0: "green", 1: "yellow", 2: "red"}


def _colour(doc, emitter, alert_level):
    name = emitter.get("profile")
    if name is None:
        return (1.0, 1.0, 1.0)
    state = doc["profiles"].get(name, {}).get(_STATE.get(int(alert_level), "green"))
    if state is None:
        return None
    t, lv = state["tint"], float(state["level"])
    return (t[0] * lv, t[1] * lv, t[2] * lv)


def spots(doc, matched, alert_level):
    out, warnings = [], []
    for key in sorted(matched, key=lambda k: matched[k]):
        emitter = doc["shapes"].get(key, {}).get("emitter") or {}
        light = emitter.get("light")
        if light is None:
            continue
        colour = _colour(doc, emitter, alert_level)
        if colour is None:
            continue
        if len(out) >= MAX_SPOTS:
            warnings.append(f"{key}: dropped (more than {MAX_SPOTS} bridge lights)")
            continue
        out.append((tuple(light["position"]), tuple(light["direction"]),
                    light.get("inner_deg", 30), light.get("outer_deg", 60),
                    light.get("range", 200), colour,
                    light.get("intensity", DEFAULT_INTENSITY)))
    return out, warnings
```

`engine/bridge_editor/runtime.py`:

```python
"""Applies a bridge's per-bridge lighting document to the renderer — the
PRODUCTION path (spec 2026-10-08-bridge-emitters §7, §9): at bridge load, on
editor edits, and on alert changes. Never raises into the host loop."""
from engine import bridge_lighting, dev_mode, host_io
from engine.bridge_editor import lighting_doc as ld
from engine.bridge_editor import lights, materials


class BridgeRuntime:
    def __init__(self, io=host_io, eye=None, alert=None):
        self._io = io
        self._eye = eye
        self._alert = alert
        self._iid = None
        self._doc = None
        self._matched = {}

    def attach(self, iid):
        self._iid, self._doc, self._matched = iid, None, {}
        try:
            info = self._io.model_identity(iid) or {}
            h = info.get("content_hash", "")
            if not h:
                self.detach()
                return
            loaded = ld.load(h, info.get("source", ""))
            self._doc = loaded.doc
            self._matched, _ = ld.match_shapes(self._doc, info.get("meshes", []))
            self._io.set_bridge_probe_origin(tuple(self._eye()))
            self._io.set_bridge_probe_scales(*bridge_lighting.probe_scales())
            self.push(self._doc)
        except Exception as e:  # noqa: BLE001 - never let bridge data kill the frame
            dev_mode.log_swallowed("bridge runtime attach", e)

    def push(self, doc, matched=None):
        if self._iid is None:
            return []
        self._doc = doc
        if matched is not None:
            self._matched = matched
        self._io.set_bridge_material_overrides(self._iid, materials.overrides(doc, self._matched))
        spot_list, warnings = lights.spots(doc, self._matched, self._alert())
        self._io.set_bridge_spots(spot_list)
        self._io.request_bridge_probe_capture()
        return warnings

    def on_alert(self, level):
        if self._iid is None or self._doc is None:
            return
        spot_list, _ = lights.spots(self._doc, self._matched, level)
        self._io.set_bridge_spots(spot_list)

    def detach(self):
        self._io.set_bridge_material_overrides(None, [])
        self._io.set_bridge_spots([])
```

Ruling built into `on_alert`: re-pushing spots changes the lighting, but `set_bridge_spots` in C++ marks the probes dirty, so the reflections follow — and the test asserts Python makes exactly one call (the capture is the binding's job). In `attach`, a broken file gives `loaded.doc` = an empty doc, so the push clears overrides (the third test).

`engine/bridge_lighting.py`:

```python
class ProbeBlend:
    """Green <-> yellow/red reflection-probe mix (spec 2026-10-08-bridge-emitters
    §9.4): 0 = green, 1 = yellow/red, moving at 1/fade_s per second. The first
    update lands on its target. Feed it the paused-aware player dt."""

    def __init__(self, fade_s=0.5):
        self._fade_s = max(float(fade_s), 1e-6)
        self._mix = None

    def update(self, alert_level, dt):
        target = 0.0 if int(alert_level) == 0 else 1.0
        if self._mix is None:
            self._mix = target
            return self._mix
        step = max(float(dt), 0.0) / self._fade_s
        if self._mix < target:
            self._mix = min(target, self._mix + step)
        else:
            self._mix = max(target, self._mix - step)
        return self._mix


def probe_scales():
    """Ambient scales the green and the yellow/red probes are captured with."""
    return ambient_scale_for_alert(0), ambient_scale_for_alert(1)
```

`engine/host_loop.py`:
- Construct `bridge_runtime = BridgeRuntime(eye=lambda: _BRIDGE_CAMERA_EYE, alert=<the player's alert level getter, 0 when no player>)` near the other bridge state (resolve `_BRIDGE_CAMERA_EYE` at call time — it is reassigned at mission load).
- Right after `controller.bridge_instance = iid` (:8046) call `bridge_runtime.attach(iid)`; where `controller.bridge_instance` is cleared (:7968) call `bridge_runtime.detach()`.
- Per frame, next to `r.set_bridge_ambient_scale(...)` (:12269): read the alert level once; `host_io.set_bridge_probe_mix(probe_blend.update(level, _player_dt))`; if the level differs from last frame's, `bridge_runtime.on_alert(level)`.
- Give the Bridge Emitters panel access to `bridge_runtime` (Task 9 consumes it): pass it into `_register_bridge_emitters` as a new `runtime` argument.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_bridge_materials.py tests/unit/test_bridge_lights.py tests/unit/test_bridge_runtime.py tests/unit/test_bridge_lighting*.py tests/unit/test_host_loop_bridge_emitters_registration.py tests/unit/test_path_indirection.py -v`
Expected: PASS (update the registration test's call for the new `runtime` argument).

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/materials.py engine/bridge_editor/lights.py engine/bridge_editor/runtime.py engine/bridge_lighting.py engine/host_loop.py tests/unit/test_bridge_materials.py tests/unit/test_bridge_lights.py tests/unit/test_bridge_runtime.py tests/unit/test_host_loop_bridge_emitters_registration.py
git commit -m "feat(bridge-pbr): bridge runtime applies materials, spots and probes at load and on alert"
```

(Add the bridge-lighting test file by its real path.)

---

### Task 9: Editor — live material push, the "map" source, and the Light section

**Files:**
- Modify: `engine/ui/bridge_emitters_panel.py`, `native/assets/ui-cef/js/bridge_emitters.js`, `engine/host_loop.py` (pass `runtime` into the panel)
- Test: `tests/unit/test_bridge_emitters_panel.py`, `tests/ui/test_bridge_emitters_js.*` (extend the existing node-run JS test the foundation added — find it with `ls tests/ui | grep -i bridge`)

**Interfaces:**
- Consumes: Task 8 `BridgeRuntime.push(doc, matched) -> warnings`; Task 2 `maps` in `model_identity`; the panel's last pick hit point (store `self._last_hit = (point, normal)` from the pick trace).
- Produces:
  - `BridgeEmittersPanel(..., runtime=None)`; after EVERY document change (material edit/clear, light add/remove/edit, undo, revert) the panel calls `runtime.push(self._doc, matched)` with `matched` from `ld.match_shapes`.
  - `_material_state()` reports `"source": "map"` (value shown as the default, slider disabled) when `selected` mesh `maps[ch]` is true.
  - Actions: `light-add` (adds `emitter.light` at `self._last_hit` point, direction = the hit normal, `inner_deg 30, outer_deg 60, range 200, intensity 2000`); `light-remove`; `light-aim` (direction = the fly camera's forward); `light-place` (position = last hit); `light:<inner_deg|outer_deg|range|intensity>:<float>` (clamped: angles 0–90 with inner ≤ outer, range > 0, intensity ≥ 0).
  - Payload `selected.light`: `null` or `{position, direction, inner_deg, outer_deg, range, intensity}`; `status` includes push warnings.

- [ ] **Step 1: Write the failing tests** (extend `tests/unit/test_bridge_emitters_panel.py`; reuse its `env`, `click`, `payload`, `FakeIO`, `INFO`)

Give `INFO`'s meshes `maps` (`mesh 1` → `{"roughness": True, "metalness": False, "normal": False}`), and add:

```python
class FakeRuntime:
    def __init__(self):
        self.pushes = []

    def push(self, doc, matched=None):
        self.pushes.append((json.dumps(doc, sort_keys=True), dict(matched or {})))
        return []


@pytest.fixture
def env_rt(env):
    p, io, h, t, tmp = env
    rt = FakeRuntime()
    p._runtime = rt
    return p, io, h, t, tmp, rt


def test_material_edit_pushes_overrides_and_requests_capture(env_rt):
    p, io, h, t, tmp, rt = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material:metalness:0.8")
    doc, matched = rt.pushes[-1]
    assert '"metalness": 0.8' in doc
    assert matched.get("7:redalertpanel") == 1


def test_map_wins_and_is_reported(env_rt):
    p, io, h, *_ = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    mat = payload(p)["selected"]["material"]
    assert mat["roughness"]["source"] == "map"
    assert mat["metalness"]["source"] == "default"


def test_light_add_places_at_the_hit_facing_the_normal(env_rt):
    p, io, h, *_ = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add")
    light = payload(p)["selected"]["light"]
    assert light["position"] == [0, 10, 50]       # FakeIO's hit point
    assert light["direction"] == [0, -1, 0]       # FakeIO's hit normal
    assert (light["inner_deg"], light["outer_deg"], light["range"], light["intensity"]) == (30, 60, 200, 2000)


def test_light_aim_uses_the_fly_camera_forward(env_rt):
    p, io, h, *_ = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add")
    p.dispatch_event("light-aim")
    d = payload(p)["selected"]["light"]["direction"]
    assert abs(d[1] - 1.0) < 1e-6                 # POSE looks along +Y


def test_light_fields_clamp_and_keep_inner_le_outer(env_rt):
    p, io, h, *_ = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add")
    p.dispatch_event("light:inner_deg:80")        # above outer 60 -> outer follows
    light = payload(p)["selected"]["light"]
    assert light["inner_deg"] == 80 and light["outer_deg"] == 80
    p.dispatch_event("light:range:-5")
    assert payload(p)["selected"]["light"]["range"] > 0


def test_light_remove_and_undo_both_push(env_rt):
    p, io, h, t, tmp, rt = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add")
    n = len(rt.pushes)
    p.dispatch_event("light-remove")
    assert payload(p)["selected"]["light"] is None
    p.dispatch_event("undo")
    assert payload(p)["selected"]["light"] is not None
    assert len(rt.pushes) == n + 2


def test_saved_lights_validate(env_rt):
    p, io, h, t, tmp, rt = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add")
    p.dispatch_event("save")
    saved = json.loads((tmp / "bridge_lighting" / f"{HASH}.json").read_text())
    assert saved["shapes"]["7:redalertpanel"]["emitter"]["light"]["range"] == 200
```

(If the foundation's `FakeIO.ray_trace_mesh_pick` hit point/normal differ from `(0,10,50)` / `(0,-1,0)`, use its real values. The panel must keep the hit from the CLICK trace, not the hover trace.)

JS test: extend the existing node test to assert `setBridgeEmitters` renders a "Light" section with Add/Remove/Place/Aim buttons and number fields when `selected.light` is set, an "Add light" button when it is `null`, and that a `source: "map"` row renders its slider `disabled`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_bridge_emitters_panel.py -v`
Expected: FAIL — no `light-add` handling, no pushes, no `map` source.

- [ ] **Step 3: Implement**

- Panel constructor gains `runtime=None`; `_after_change()` = `if self._runtime and self._info: self._runtime.push(self._doc, ld.match_shapes(self._doc, self._info["meshes"])[0])`, appending returned warnings to `_status`. Call it at the end of every doc-changing action, after undo, and after `_attach`/revert (so reopening shows the saved state rendered).
- `_click` keeps `self._last_hit = (point, normal)` from the CLICK's trace result (extend `pick_mesh` to return the hit, or trace again in `_click` — keep `pick_mesh`'s existing signature and add `picking.pick_hit(...)` returning the full 5-tuple; test it in `tests/unit/test_bridge_picking.py`).
- Light actions as specified, each snapshotting for undo first, writing `shape_entry(...)["emitter"]["light"]`, removing an empty `emitter` on remove.
- `_material_state()` checks the selected mesh's `maps` first.
- JS: a "Light" section under Material: when `selected.light` is null, an "Add light" button; else Place here / Aim where I'm looking / Remove buttons and four number fields (`inner°`, `outer°`, `range`, `intensity`) committing on `change` via `dauntlessEvent('bridge-emitters/light:<field>:' + this.value)`; disable the slider of a `map`-sourced channel. Keep `_beEsc` on every string.
- `host_loop._register_bridge_emitters(..., runtime)` passes it through.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_bridge_emitters_panel.py tests/unit/test_bridge_picking.py tests/unit/test_host_loop_bridge_emitters_registration.py tests/ui -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/bridge_emitters_panel.py engine/bridge_editor/picking.py native/assets/ui-cef/js/bridge_emitters.js engine/host_loop.py tests/unit/test_bridge_emitters_panel.py tests/unit/test_bridge_picking.py
git commit -m "feat(bridge-pbr): editor pushes materials live, shows map sources, places spot lights"
```

(Add the JS test file by its real path.)

---

### Task 10: Developer Options — PBR A/B switch and the new debug views

**Files:**
- Modify: `engine/ui/developer_options_panel.py`, `native/assets/ui-cef/js/developer_options.js`
- Test: `tests/unit/test_developer_options_panel.py`

**Interfaces:**
- Consumes: `host_io.set_bridge_pbr_enabled(on)`; the existing debug-view row and `set_bridge_debug_view`.
- Produces: Lighting tab row "Bridge PBR" (toggle, default ON, not persisted) → `host_io.set_bridge_pbr_enabled`; the "Bridge Debug View" row's cycle list gains `Roughness`, `Metalness`, `Specular only`, `Probe (mirror)`, `Map normals` as values 6–10.

- [ ] **Step 1: Write the failing tests**

Read the existing Lighting-tab debug-view test in `tests/unit/test_developer_options_panel.py` and mirror it:

```python
def test_bridge_pbr_toggle_defaults_on_and_calls_the_binding(dev_panel, monkeypatch):
    calls = []
    monkeypatch.setattr("engine.host_io.set_bridge_pbr_enabled", lambda on: calls.append(on))
    assert dev_panel.state()["lighting"]["bridge_pbr"] is True
    dev_panel.dispatch_event("toggle:bridge_pbr")
    assert calls == [False]


def test_bridge_debug_view_cycles_through_the_pbr_views(dev_panel):
    names = dev_panel.bridge_debug_view_names()
    assert names[6:11] == ["Roughness", "Metalness", "Specular only", "Probe (mirror)", "Map normals"]
```

(Use the panel's real fixture name, state accessor, action names and names-list accessor — adapt the test to them; the assertions' content is the requirement.)

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_developer_options_panel.py -v` — FAIL.

- [ ] **Step 3: Implement** the row and list entries following the existing Lighting-tab code exactly.

- [ ] **Step 4: Run** the same command plus `tests/ui -q` — PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/developer_options_panel.py native/assets/ui-cef/js/developer_options.js tests/unit/test_developer_options_panel.py
git commit -m "feat(bridge-pbr): Developer Options PBR A/B switch and PBR debug views"
```

---

### Task 11: Gate, docs and the live calibration check

**Files:**
- Modify: `CLAUDE.md` (the "Bridge editor" row from the foundation: extend it, or add a "Bridge PBR" row after it), `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` (§10 log), `engine/ui/bridge_emitters_panel.py` (module docstring: the override IS rendered now)

- [ ] **Step 1: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0, "OK — no new failures". Fix any regression test-first; never edit `tests/known_failures.txt`.

- [ ] **Step 2: CLAUDE.md row**

```markdown
| Bridge PBR — linear GGX, layered materials, reflection probes, spot lights | `native/src/renderer/{bridge_pass,bridge_probe}.cc`, `renderer/bridge_pbr.h`, `shaders/bridge.frag`, `engine/bridge_editor/{materials,lights,runtime}.py`, `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` §9 | The bridge decodes albedo AND the downlight with pow 2.2, lights in linear GGX, re-encodes before the shared (gamma-space) post chain — so the default material (metal 0, rough 1) matches the old look. Output = `ceiling(enc(D)) + max(enc(D+S) − enc(D), 0)`: lit diffuse never blooms, specular may. Channels: `<stem>_rough/_metal/_normal` maps (interior loads: stock albedo → ONLY our replacements overlay; mod albedo → ONLY beside itself) → per-shape override → default. Two probes (green, yellow/red) 256², 6 prefiltered mips, box-projected, captured at `_BRIDGE_CAMERA_EYE` at load and on any material/spot change; cross-fade 0.5 s. ≤32 spot lights, no shadows, no AO. Bridge units: 0 base, 1 normal, 2 face_b, 3 AO, 4 AO depth, 5 rough, 6 metal, 7/8 probes, 9 BRDF LUT. Comm sets keep legacy shading. `BridgeRuntime` applies saved data in PRODUCTION. Dev: Developer Options → Lighting → Bridge PBR (A/B), debug views 6–10. |
```

- [ ] **Step 3: Spec log row**

Append to §10: `| P1 | 2026-10-09 | Bridge PBR built (plan 2026-10-09-bridge-pbr): linear GGX, layered material channels, normal/rough/metal maps, two box-projected probes, spot lights, live editor push | pending Mark's live calibration | 9 |`

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md engine/ui/bridge_emitters_panel.py
git commit -m "docs: bridge PBR — reference row and spec log"
```

- [ ] **Step 5: Live calibration (ASK MARK BEFORE LAUNCHING)**

Give Mark:

```bash
cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/bridge-emitters
./build/dauntless --developer
```

Checklist (DBridge and EBridge):
1. With PBR on, the bridge looks like the baseline (Developer Options → Lighting → Bridge PBR toggles A/B; the difference at default materials is small).
2. Bridge Emitters…: select the floor, set metalness 1 / roughness 0.1 → the floor reflects the room; roughness up → the reflection blurs.
3. Debug views Roughness / Metalness / Specular only / Probe (mirror) / Map normals render.
4. Add a light on a fixture, Aim where I'm looking → a pool of light on the floor; the floor does not bloom; a glossy surface's highlight may.
5. Save, close, quit, relaunch WITHOUT `--developer` → the saved materials and lights are there.
6. Green → red alert: the reflections cross-fade (subtle until emitters exist).
Then tune `down_top` / `down_bottom` / green ambient (§9.1) with Mark and record his verdict in the spec log.
