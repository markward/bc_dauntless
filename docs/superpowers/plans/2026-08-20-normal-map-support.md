# Normal-Map Support for Ship Hulls — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load a `<basename>_normal.tga` sibling texture beside a ship's diffuse and light the hull with the perturbed normal, with no NIF, script, or vertex-format change.

**Architecture:** Discovery mirrors the existing `_specular` sibling shim in `model_build.cc` and binds into the already-declared-but-unused `Material::StageSlot::Bump`. The tangent frame is reconstructed per-pixel in `opaque.frag` from screen-space derivatives (Mikkelsen's method) — BC NIFs carry no tangents and none are added. The perturbed normal feeds diffuse, specular, and dynamic lights but deliberately **not** the shadow bias or the Fresnel rim.

**Tech Stack:** C++20, OpenGL 3.3 core GLSL, stb_image (TGA), GoogleTest, pybind11, CMake.

**Spec:** `docs/superpowers/specs/2026-08-20-normal-map-support-design.md`

## Global Constraints

- **Byte-identical fallback.** A material with no Bump texture must take the pre-existing shading path. `u_normal_enabled == 0` early-outs to the geometric normal. This is the fidelity guarantee — stock BC ships zero `_normal` files.
- **Never bind a checkerboard as a normal map.** The base-texture failure path substitutes a magenta checkerboard so geometry always renders. A bump texture that fails to load must instead be **skipped**, leaving `Bump.texture_index == -1`. A checkerboard normal map is violent garbage lighting, not a legible error.
- **No NaN may escape the shader.** A non-finite normal poisons every downstream term and surfaces as black squares through the HDR bloom chain. Every division in the tangent-frame reconstruction is guarded, falling back to the geometric normal.
- **Green channel is the OpenGL convention (+Y up).** A global `u_normal_flip_g` handles DirectX-convention maps. No per-file heuristics, no filename magic.
- **Texture unit 4** is the bump slot in the opaque pass (0 base, 1 glow, 2 specular, 3 damage decal, 5 shadow).
- **Do not refactor the existing `_glow` / `_specular` helpers.** They stay in their anonymous namespace exactly as they are. The new predicates are added alongside.
- **Shared checkout.** Stage with explicit pathspecs only. Never `git add -A`, `git add .`, `git checkout --`, `git restore`, `git stash`, `git clean`, or `git reset --hard`.
- **Shader edits need a CMake reconfigure**: `cmake -B build -S .` before `cmake --build build -j`, because `.vert`/`.frag` files are baked at configure time.
- **Test gate**: `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`). Never judge a failure "pre-existing" by eye.

**Test asset already in the tree:** `game/data/Models/Ships/Warbird/High/WarBirdBottomWing_normal.tga` — 1024×1024, RLE true-colour (`imgtype=10`), 32bpp. Its diffuse sibling `WarBirdBottomWing.tga` is 256×256 24bpp, and `WarBirdBottomWing_specular.tga` already exists, so the sibling-probe path is proven on this exact texture.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `native/src/assets/src/model_build.h` | Declare the two filename helpers so they are unit-testable | 1 |
| `native/src/assets/src/model_build.cc` | Filename predicates; sibling discovery in `load_all_textures`; wire into `MaterialInputs` | 1, 3 |
| `native/tests/assets/cpu/model_build_test.cc` | Filename-rule unit tests; end-to-end discovery test on the real Warbird | 1, 3 |
| `native/src/assets/src/material_build.h` | Two new `MaterialInputs` members | 2 |
| `native/src/assets/src/material_build.cc` | Route normal textures to `StageSlot::Bump` | 2 |
| `native/tests/assets/cpu/material_build_test.cc` | Bump-binding unit tests | 2 |
| `native/src/renderer/shaders/opaque.frag` | Derivative tangent frame + perturbed shading normal | 4 |
| `native/src/renderer/frame.cc` | `dauntless_normal_map` toggle namespace; bind unit 4 + uniforms | 4 |
| `native/tests/renderer/frame_test.cc` | Toggle round-trip; strength-0 equals disabled; strength-1 differs | 4 |
| `native/src/host/host_bindings.cc` | Expose the three setters to Python | 5 |
| `engine/renderer.py` | Façade wrappers + binding-name whitelist entries | 5 |
| `engine/ui/developer_options_panel.py` | Lighting-tab rows: enable toggle, green flip, strength cycle | 5 |
| `native/assets/ui-cef/js/developer_options.js` | Render those rows | 5 |
| `tests/unit/test_developer_options_panel.py` | Panel row behaviour | 5 |

---

## Task 1: Filename predicates

**Files:**
- Modify: `native/src/assets/src/model_build.h`
- Modify: `native/src/assets/src/model_build.cc` (add beside `sibling_specular_filename`, currently ending at `:118`)
- Test: `native/tests/assets/cpu/model_build_test.cc`

**Interfaces:**
- Consumes: nothing.
- Produces: `bool assets::detail::filename_is_normal(std::string_view)` and `std::string assets::detail::sibling_normal_filename(std::string_view)`.

**Why these two are declared in the header** when `filename_is_glow` / `filename_is_specular` are file-local: those are untested today, and the filename rules are exactly the part worth pinning down with cheap unit tests. Declaring the new pair in `assets::detail` makes that possible without disturbing the existing three.

- [ ] **Step 1: Write the failing tests**

Append to `native/tests/assets/cpu/model_build_test.cc` (the file already includes `"model_build.h"` and `<gtest/gtest.h>`):

```cpp
TEST(ModelBuildFilenames, NormalPredicateMatchesLongAndShortForms) {
    using assets::detail::filename_is_normal;
    EXPECT_TRUE (filename_is_normal("Hull_normal.tga"));
    EXPECT_TRUE (filename_is_normal("Hull_norm.tga"));
    EXPECT_TRUE (filename_is_normal("HULL_NORMAL.TGA"));   // case-insensitive
    EXPECT_TRUE (filename_is_normal("WarBirdBottomWing_normal.tga"));
    EXPECT_FALSE(filename_is_normal("Hull.tga"));
    EXPECT_FALSE(filename_is_normal("Hull_specular.tga"));
    EXPECT_FALSE(filename_is_normal("Hull_glow.tga"));
    EXPECT_FALSE(filename_is_normal("normal.tga"))
        << "a bare 'normal' stem has no _normal suffix and must not match";
}

TEST(ModelBuildFilenames, SiblingNormalAppendsAndStripsGlow) {
    using assets::detail::sibling_normal_filename;
    EXPECT_EQ(sibling_normal_filename("Hull.tga"), "Hull_normal.tga");
    EXPECT_EQ(sibling_normal_filename("WarBirdBottomWing.tga"),
              "WarBirdBottomWing_normal.tga");
    // A _glow map and its hull diffuse must resolve to the SAME normal map,
    // exactly as sibling_specular_filename does for spec masks.
    EXPECT_EQ(sibling_normal_filename("CardGalor01_glow.tga"),
              "CardGalor01_normal.tga");
    EXPECT_EQ(sibling_normal_filename("CardGalor01_GLOW.tga"),
              "CardGalor01_normal.tga");
}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cmake -B build -S . && cmake --build build -j --target assets_tests
```

Expected: **compile error** — `filename_is_normal` / `sibling_normal_filename` are not members of `assets::detail`.

- [ ] **Step 3: Declare the helpers in the header**

In `native/src/assets/src/model_build.h`, add `#include <string>` and `#include <string_view>` to the include block, then add these declarations inside `namespace assets::detail`, immediately above `Model build_model(...)`:

```cpp
/// True if `fname`'s extension-less basename ends in "_normal" or "_norm"
/// (case-insensitive). BC authored no normal maps at all, so both forms are
/// ours; the long form is primary. Declared here (unlike the file-local
/// _glow / _specular predicates) so the filename rules are unit-testable.
bool filename_is_normal(std::string_view fname);

/// Given "Hull.tga" or "Hull_glow.tga", produce the sibling normal-map
/// filename "Hull_normal.tga". Strips a trailing "_glow" (case-insensitive)
/// from the stem before appending, so a hull's diffuse and its glow map
/// resolve to the SAME normal map — matching sibling_specular_filename.
std::string sibling_normal_filename(std::string_view fname);
```

- [ ] **Step 4: Implement them**

In `native/src/assets/src/model_build.cc`, **outside** the anonymous namespace but inside `namespace assets::detail` (put them immediately after the anonymous namespace's closing `}  // namespace`, before the first `assets::detail` free function):

```cpp
bool filename_is_normal(std::string_view fname) {
    auto dot = fname.find_last_of('.');
    auto stem = (dot == std::string_view::npos) ? fname : fname.substr(0, dot);
    auto lower_ends_with = [](std::string_view s, std::string_view suffix) {
        if (s.size() < suffix.size()) return false;
        for (std::size_t i = 0; i < suffix.size(); ++i) {
            char c = s[s.size() - suffix.size() + i];
            c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
            if (c != suffix[i]) return false;
        }
        return true;
    };
    return lower_ends_with(stem, "_normal") || lower_ends_with(stem, "_norm");
}

std::string sibling_normal_filename(std::string_view fname) {
    auto dot = fname.find_last_of('.');
    std::string stem(dot == std::string_view::npos ? fname : fname.substr(0, dot));
    std::string ext (dot == std::string_view::npos ? std::string{}
                                                   : std::string(fname.substr(dot)));
    // Strip trailing "_glow" (case-insensitive, length 5).
    if (stem.size() >= 5) {
        std::string tail = stem.substr(stem.size() - 5);
        std::transform(tail.begin(), tail.end(), tail.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (tail == "_glow") stem.resize(stem.size() - 5);
    }
    return stem + "_normal" + ext;
}
```

`<algorithm>`, `<cctype>`, `<string>`, and `<string_view>` are already included by this file for the existing predicates; add any that the compiler reports missing.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cmake --build build -j --target assets_tests && ./build/native/tests/assets/assets_tests --gtest_filter='ModelBuildFilenames.*'
```

Expected: 2 tests, both PASS. (If the binary path differs, find it with `find build -name assets_tests -type f`.)

- [ ] **Step 6: Commit**

```bash
git add native/src/assets/src/model_build.h native/src/assets/src/model_build.cc native/tests/assets/cpu/model_build_test.cc
git commit -m "feat(assets): _normal filename predicates for normal-map sibling discovery"
```

---

## Task 2: Bind normal textures to the Bump stage

**Files:**
- Modify: `native/src/assets/src/material_build.h`
- Modify: `native/src/assets/src/material_build.cc:68-140`
- Test: `native/tests/assets/cpu/material_build_test.cc`

**Interfaces:**
- Consumes: nothing from Task 1 (this task is pure CPU material logic; the maps are injected directly by the tests).
- Produces: `MaterialInputs::normal_image_links` (`const std::unordered_set<std::uint32_t>*`) and `MaterialInputs::sibling_normal_for_image` (`const std::unordered_map<std::uint32_t, int>*`), both consumed by Task 3. After this task, `build_material` populates `Material::StageSlot::Bump`.

- [ ] **Step 1: Write the failing tests**

Append to `native/tests/assets/cpu/material_build_test.cc`:

```cpp
TEST(MaterialBuild, NormalImageBindsToBumpSlotOnly) {
    // A directly-referenced _normal image is a standalone map: like
    // _specular and unlike _glow, it must NOT dual-bind to Base.
    nif::NiTextureProperty tex;
    tex.image_link = 55;

    std::unordered_map<std::uint32_t, int> img_to_tex = {{55, 9}};
    std::unordered_set<std::uint32_t> normal_links = {55};

    auto in = basic_inputs();
    in.texture = &tex;
    in.image_to_texture = &img_to_tex;
    in.normal_image_links = &normal_links;

    auto m = assets::detail::build_material(in);
    using S = assets::Material::StageSlot;
    EXPECT_EQ(m.stages[static_cast<std::size_t>(S::Bump)].texture_index, 9);
    EXPECT_LT(m.stages[static_cast<std::size_t>(S::Base)].texture_index, 0)
        << "_normal images must not dual-bind to Base";
}

TEST(MaterialBuild, SiblingNormalBindsToBumpAlongsideBase) {
    // The hull texture keeps Base; the probed sibling fills Bump.
    nif::NiTextureProperty tex;
    tex.image_link = 70;

    std::unordered_map<std::uint32_t, int> img_to_tex = {{70, 2}};
    std::unordered_map<std::uint32_t, int> sibling_normal = {{70, 11}};

    auto in = basic_inputs();
    in.texture = &tex;
    in.image_to_texture = &img_to_tex;
    in.sibling_normal_for_image = &sibling_normal;

    auto m = assets::detail::build_material(in);
    using S = assets::Material::StageSlot;
    EXPECT_EQ(m.stages[static_cast<std::size_t>(S::Base)].texture_index, 2);
    EXPECT_EQ(m.stages[static_cast<std::size_t>(S::Bump)].texture_index, 11);
}

TEST(MaterialBuild, NoNormalSiblingLeavesBumpUnpopulated) {
    // The overwhelmingly common case: no _normal on disk. Bump stays -1 so
    // frame.cc writes u_normal_enabled = 0 and the hull shades as it always has.
    nif::NiTextureProperty tex;
    tex.image_link = 80;

    std::unordered_map<std::uint32_t, int> img_to_tex = {{80, 4}};
    std::unordered_map<std::uint32_t, int> sibling_normal = {{79, 12}};  // different image

    auto in = basic_inputs();
    in.texture = &tex;
    in.image_to_texture = &img_to_tex;
    in.sibling_normal_for_image = &sibling_normal;

    auto m = assets::detail::build_material(in);
    using S = assets::Material::StageSlot;
    EXPECT_EQ(m.stages[static_cast<std::size_t>(S::Base)].texture_index, 4);
    EXPECT_LT(m.stages[static_cast<std::size_t>(S::Bump)].texture_index, 0);
}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cmake --build build -j --target assets_tests
```

Expected: **compile error** — `MaterialInputs` has no member `normal_image_links` / `sibling_normal_for_image`.

- [ ] **Step 3: Add the two `MaterialInputs` members**

In `native/src/assets/src/material_build.h`, inside `struct MaterialInputs`, immediately after the `sibling_specular_for_image` member:

```cpp
    /// Link IDs of NiImages whose filename matches the `_normal` / `_norm`
    /// suffix convention. Routed to StageSlot::Bump. Like specular and
    /// unlike glow, these are standalone maps and do NOT dual-bind to Base.
    const std::unordered_set<std::uint32_t>* normal_image_links = nullptr;

    /// NIF link_id of a non-`_normal` NiImage -> Model::textures index of a
    /// sibling `*_normal.tga` the asset loader probed for and found on disk.
    /// Bound to StageSlot::Bump in addition to the hull texture's normal
    /// Base/Glow binding. The slot's contract is "a texture in this
    /// material's bump stage", not "a file found on disk" — a generated map
    /// can be attached through the same field.
    const std::unordered_map<std::uint32_t, int>* sibling_normal_for_image = nullptr;
```

- [ ] **Step 4: Route them in `apply_texture_property`**

In `native/src/assets/src/material_build.cc`, extend the `apply_texture_property` parameter list (currently ending `const std::unordered_map<std::uint32_t, int>* sibling_specular_for_image`) with:

```cpp
    ,
    const std::unordered_set<std::uint32_t>* normal_image_links,
    const std::unordered_map<std::uint32_t, int>* sibling_normal_for_image
```

Immediately **after** the existing `if (is_specular) { ... return; }` block, add the standalone-map early return:

```cpp
    const bool is_normal = normal_image_links &&
        normal_image_links->find(effective_image_link) != normal_image_links->end();
    if (is_normal) {
        auto& bump = m.stages[static_cast<std::size_t>(Material::StageSlot::Bump)];
        bump.texture_index = tex_idx;
        bump.apply_mode    = 2;  // APPLY_MODULATE
        return;
    }
```

At the **end** of the function, after the existing `sibling_specular_for_image` block:

```cpp
    // Sibling shim, mirroring the _specular block above: if the asset loader
    // probed for a `_normal` texture next to this image and found one, bind it
    // to the Bump slot. The hull texture stays in Base / Glow.
    if (sibling_normal_for_image) {
        auto it = sibling_normal_for_image->find(effective_image_link);
        if (it != sibling_normal_for_image->end()) {
            auto& bump = m.stages[static_cast<std::size_t>(Material::StageSlot::Bump)];
            bump.texture_index = it->second;
            bump.apply_mode    = 2;
        }
    }
```

Then update the call site inside `build_material` (near `material_build.cc:220`, where `in.sibling_specular_for_image` is passed) to forward the two new fields as the final arguments:

```cpp
        in.sibling_specular_for_image,
        in.normal_image_links,
        in.sibling_normal_for_image);
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cmake --build build -j --target assets_tests && ./build/native/tests/assets/assets_tests --gtest_filter='MaterialBuild.*'
```

Expected: all `MaterialBuild` tests PASS, including the three new ones and the pre-existing specular/glow tests (which must be unaffected).

- [ ] **Step 6: Commit**

```bash
git add native/src/assets/src/material_build.h native/src/assets/src/material_build.cc native/tests/assets/cpu/material_build_test.cc
git commit -m "feat(assets): route normal maps to Material::StageSlot::Bump"
```

---

## Task 3: Sibling discovery in the texture loader

**Files:**
- Modify: `native/src/assets/src/model_build.cc:121-131` (`TextureLoadResult`), `:196-232` (`load_all_textures`), `:337-346` (`MaterialInputs` population), `:634-636` (call site)
- Test: `native/tests/assets/cpu/model_build_test.cc`

**Interfaces:**
- Consumes: `assets::detail::filename_is_normal`, `assets::detail::sibling_normal_filename` (Task 1); `MaterialInputs::normal_image_links`, `MaterialInputs::sibling_normal_for_image` (Task 2).
- Produces: after this task, `build_model` on a NIF whose diffuse has a `_normal.tga` sibling yields a `Material` with `stages[Bump].texture_index >= 0`.

- [ ] **Step 1: Write the failing test**

Append to `native/tests/assets/cpu/model_build_test.cc`. This is an end-to-end test against the real Warbird and the real `_normal` asset in the tree:

```cpp
TEST(ModelBuildNormalDiscovery, WarbirdBottomWingGetsBumpFromSiblingOnDisk) {
    // game/ is gitignored; skip cleanly when the BC install is absent.
    const fs::path root = fs::path(OPEN_STBC_PROJECT_ROOT);
    const fs::path nif  = root / "game/data/Models/Ships/Warbird/Warbird.nif";
    const fs::path tex  = root / "game/data/Models/Ships/Warbird/High";
    const fs::path map  = tex / "WarBirdBottomWing_normal.tga";
    if (!fs::is_regular_file(nif)) GTEST_SKIP() << "asset missing: " << nif;
    if (!fs::is_regular_file(map)) GTEST_SKIP() << "asset missing: " << map;

    std::ifstream in(nif, std::ios::binary);
    ASSERT_TRUE(in) << "cannot open " << nif;
    std::vector<std::uint8_t> bytes(
        (std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    nif::File f = nif::parse(bytes);

    assets::PathResolver resolver;
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &resolver;
    ctx.texture_search_paths = {tex, root / "game/data/Models/Ships/Warbird"};
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;

    auto model = assets::detail::build_model(f, ctx);

    using S = assets::Material::StageSlot;
    int bumped = 0;
    for (const auto& m : model.materials) {
        if (m.stages[static_cast<std::size_t>(S::Bump)].texture_index >= 0) ++bumped;
    }
    EXPECT_GT(bumped, 0)
        << "no material picked up WarBirdBottomWing_normal.tga from disk";
}

TEST(ModelBuildNormalDiscovery, ShipWithoutNormalSiblingsLeavesEveryBumpEmpty) {
    // The Galaxy ships no _normal maps. Every material must leave Bump at -1
    // so frame.cc writes u_normal_enabled = 0 and shading is unchanged.
    const fs::path root = fs::path(OPEN_STBC_PROJECT_ROOT);
    const fs::path nif  = root / "game/data/Models/Ships/Galaxy/Galaxy.nif";
    const fs::path tex  = root / "game/data/Models/SharedTextures/FedShips/High";
    if (!fs::is_regular_file(nif)) GTEST_SKIP() << "asset missing: " << nif;

    std::ifstream in(nif, std::ios::binary);
    ASSERT_TRUE(in) << "cannot open " << nif;
    std::vector<std::uint8_t> bytes(
        (std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    nif::File f = nif::parse(bytes);

    assets::PathResolver resolver;
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &resolver;
    ctx.texture_search_paths = {tex};
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;

    auto model = assets::detail::build_model(f, ctx);

    using S = assets::Material::StageSlot;
    for (const auto& m : model.materials) {
        EXPECT_LT(m.stages[static_cast<std::size_t>(S::Bump)].texture_index, 0);
    }
}
```

These need `OPEN_STBC_PROJECT_ROOT` (already baked in by `native/tests/assets/CMakeLists.txt`) and `<istream>` / `<iterator>`; the file already has `<fstream>`, `<filesystem>`, `<vector>`, and the `stub_texture` / `stub_mesh` helpers. If `nif::parse` is spelled differently in this tree, match whatever `model_build_test.cc`'s existing sample-file tests use — grep the file for `nif::` to confirm the parse entry point before writing.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cmake --build build -j --target assets_tests && ./build/native/tests/assets/assets_tests --gtest_filter='ModelBuildNormalDiscovery.*'
```

Expected: `WarbirdBottomWingGetsBumpFromSiblingOnDisk` FAILS with `bumped == 0` (nothing populates Bump yet). The Galaxy test passes vacuously — that is fine and expected; it is a regression guard, not a driver.

- [ ] **Step 3: Add the discovery members to `TextureLoadResult`**

In `native/src/assets/src/model_build.cc`, inside `struct TextureLoadResult` (after `sibling_specular_for_image` at `:131`):

```cpp
    /// Link IDs of external NiImages whose filename is itself a `_normal` /
    /// `_norm` map.
    std::unordered_set<std::uint32_t>      normal_image_links;
    /// NIF link_id of a non-derived NiImage -> Model::textures index of a
    /// sibling "<basename>_normal.tga" found on disk beside it.
    std::unordered_map<std::uint32_t, int> sibling_normal_for_image;
```

- [ ] **Step 4: Classify and probe in `load_all_textures`**

Beside the existing `filename_is_specular` classification (`model_build.cc:203-205`), add:

```cpp
        if (img->use_external != 0 && filename_is_normal(img->file_name)) {
            out.normal_image_links.insert(link_id);
        }
```

Then replace the existing specular-probe guard

```cpp
        if (img->use_external != 0 && !filename_is_specular(img->file_name)) {
```

with a shared guard that also excludes `_normal` sources:

```cpp
        // Derived maps never get siblings probed for them. Without the
        // filename_is_normal half, every _normal image would send the loader
        // hunting for "<name>_normal_specular.tga" on each load.
        const bool is_derived_map = filename_is_specular(img->file_name)
                                 || filename_is_normal(img->file_name);
        if (img->use_external != 0 && !is_derived_map) {
```

Inside that block, after the existing specular probe's closing `catch`, add the normal probe. The two-stage try is deliberate: a **missing** sibling is the common case and stays silent, while a **present but broken** one is logged.

```cpp
            // Sibling normal map. Split resolve from decode so a missing file
            // (the common case) stays silent while a corrupt one is reported.
            const std::string normal_name =
                sibling_normal_filename(img->file_name);
            std::filesystem::path normal_path;
            bool normal_found = false;
            try {
                normal_path =
                    ctx.resolver->resolve(normal_name, ctx.texture_search_paths);
                normal_found = true;
            } catch (const std::exception&) {
                // No sibling on disk. Most ships have none.
            }
            if (normal_found) {
                try {
                    auto normal_bytes = read_file(normal_path);
                    Image normal_decoded = decode_tga(normal_bytes);
                    Texture normal_tex = upload(normal_decoded, true);
                    const int normal_idx =
                        static_cast<int>(model.textures.size());
                    out.sibling_normal_for_image[link_id] = normal_idx;
                    model.textures.push_back(std::move(normal_tex));
                } catch (const std::exception& e) {
                    // SKIP, do not substitute the checkerboard the base-texture
                    // path uses: a checkerboard bound as a normal map is violent
                    // garbage lighting, not a legible error. Bump stays empty and
                    // the hull renders exactly as it does today.
                    std::fprintf(stderr,
                        "[model_build] normal map '%s': %s; skipping (hull "
                        "renders unmapped)\n",
                        normal_name.c_str(), e.what());
                }
            }
```

- [ ] **Step 5: Thread both maps into `MaterialInputs`**

At `model_build.cc:337-346`, add two parameters to that helper's signature, after `sibling_specular_for_image`:

```cpp
    const std::unordered_set<std::uint32_t>& normal_image_links,
    const std::unordered_map<std::uint32_t, int>& sibling_normal_for_image,
```

and two assignments after `in.sibling_specular_for_image = &sibling_specular_for_image;`:

```cpp
    in.normal_image_links = &normal_image_links;
    in.sibling_normal_for_image = &sibling_normal_for_image;
```

At the call site (`model_build.cc:634-636`), pass them in the matching positions:

```cpp
            tex_result.sibling_specular_for_image,
            tex_result.normal_image_links,
            tex_result.sibling_normal_for_image, resolver);
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cmake --build build -j --target assets_tests && ./build/native/tests/assets/assets_tests --gtest_filter='ModelBuildNormalDiscovery.*:ModelBuild*.*:MaterialBuild.*'
```

Expected: all PASS. `WarbirdBottomWingGetsBumpFromSiblingOnDisk` now reports at least one bumped material.

- [ ] **Step 7: Commit**

```bash
git add native/src/assets/src/model_build.cc native/tests/assets/cpu/model_build_test.cc
git commit -m "feat(assets): probe for sibling _normal.tga and bind it to the Bump stage"
```

---

## Task 4: Derivative tangent frame and the shading normal

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag`
- Modify: `native/src/renderer/frame.cc:30-60` (toggle namespace), `:553-566` (material texture binding)
- Test: `native/tests/renderer/frame_test.cc`

**Interfaces:**
- Consumes: `Material::StageSlot::Bump` populated by Tasks 2-3.
- Produces: `namespace dauntless_normal_map { bool enabled(); void set_enabled(bool); float strength(); void set_strength(float); bool flip_green(); void set_flip_green(bool); }` defined in `frame.cc`, consumed by Task 5.

- [ ] **Step 1: Write the failing tests**

Append to `native/tests/renderer/frame_test.cc`.

First, beside the existing `kGalaxyNif` / `kGalaxyTex` definitions (`frame_test.cc:79-82`, inside the anonymous namespace), add:

```cpp
const std::filesystem::path kWarbirdNif =
    kProjectRoot / "game" / "data" / "Models" / "Ships" / "Warbird" / "Warbird.nif";
const std::filesystem::path kWarbirdTex =
    kProjectRoot / "game" / "data" / "Models" / "Ships" / "Warbird" / "High";
```

Beside `block_mean` (`frame_test.cc:489`), add a full-frame reader and a differ. Comparing whole frames rather than a sampled block matters here: only the bottom-wing mesh carries the map, so a fixed sample block could easily miss it entirely and the test would pass for the wrong reason.

```cpp
std::vector<unsigned char> read_frame(int w = 256, int h = 256) {
    std::vector<unsigned char> buf(static_cast<size_t>(w) * h * 4);
    glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
    return buf;
}

size_t differing_texels(const std::vector<unsigned char>& a,
                        const std::vector<unsigned char>& b) {
    size_t n = 0;
    for (size_t i = 0; i + 3 < a.size() && i + 3 < b.size(); i += 4) {
        if (a[i] != b[i] || a[i+1] != b[i+1] || a[i+2] != b[i+2]) ++n;
    }
    return n;
}

template <class Lut>
void render_ship(scenegraph::World& world, renderer::Pipeline& pipeline,
                 Lut&& lut, float eye_z) {
    scenegraph::Camera cam;
    cam.eye = glm::vec3(0, 0, eye_z); cam.target = glm::vec3(0);
    cam.aspect = 1.0f;
    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;
    glViewport(0, 0, 256, 256);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    submitter.submit_opaque_in_pass(world, cam, pipeline, lut, lighting,
                                    scenegraph::Pass::Space, 0.0f);
}
```

Then the tests, with the toggle forward-declared as the file does for `dauntless_decals`:

```cpp
namespace dauntless_normal_map {
    bool enabled(); void set_enabled(bool);
    float strength(); void set_strength(float);
    bool flip_green(); void set_flip_green(bool);
}

TEST(DauntlessNormalMapToggle, DefaultsOnWithUnitStrengthAndRoundTrips) {
    EXPECT_TRUE(dauntless_normal_map::enabled());
    EXPECT_FLOAT_EQ(dauntless_normal_map::strength(), 1.0f);
    EXPECT_FALSE(dauntless_normal_map::flip_green());

    dauntless_normal_map::set_enabled(false);
    EXPECT_FALSE(dauntless_normal_map::enabled());
    dauntless_normal_map::set_strength(2.5f);
    EXPECT_FLOAT_EQ(dauntless_normal_map::strength(), 2.5f);
    dauntless_normal_map::set_flip_green(true);
    EXPECT_TRUE(dauntless_normal_map::flip_green());

    dauntless_normal_map::set_enabled(true);      // restore for other tests
    dauntless_normal_map::set_strength(1.0f);
    dauntless_normal_map::set_flip_green(false);
}

TEST_F(FrameTest, NormalMapChangesShadingAndZeroStrengthMatchesDisabled) {
    if (!std::filesystem::is_regular_file(kWarbirdNif))
        GTEST_SKIP() << "asset missing: " << kWarbirdNif;
    if (!std::filesystem::is_regular_file(
            kWarbirdTex / "WarBirdBottomWing_normal.tga"))
        GTEST_SKIP() << "test normal map not installed";

    auto model_h = cache->load(kWarbirdNif, kWarbirdTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    scenegraph::World world;
    auto iid = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));

    const float kEyeZ = 2500.0f;

    dauntless_normal_map::set_enabled(false);
    render_ship(world, *p, lut, kEyeZ);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const auto frame_off = read_frame();

    dauntless_normal_map::set_enabled(true);
    dauntless_normal_map::set_strength(0.0f);
    render_ship(world, *p, lut, kEyeZ);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const auto frame_zero = read_frame();

    dauntless_normal_map::set_strength(1.0f);
    render_ship(world, *p, lut, kEyeZ);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const auto frame_on = read_frame();

    dauntless_normal_map::set_strength(1.0f);   // leave at defaults
    dauntless_normal_map::set_enabled(true);

    // Sanity: the ship must actually be on screen, or every comparison below
    // is comparing two black frames. If this fails, adjust kEyeZ until the
    // Warbird fills a useful part of the 256x256 viewport.
    size_t lit = 0;
    for (size_t i = 0; i + 3 < frame_on.size(); i += 4)
        if (frame_on[i] || frame_on[i+1] || frame_on[i+2]) ++lit;
    ASSERT_GT(lit, 500u) << "Warbird not visible at eye_z=" << kEyeZ;

    EXPECT_EQ(differing_texels(frame_off, frame_zero), 0u)
        << "strength 0 must collapse to the geometric normal, matching disabled";
    EXPECT_GT(differing_texels(frame_zero, frame_on), 0u)
        << "strength 1 must perturb shading somewhere on the bottom wing";
}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cmake -B build -S . && cmake --build build -j --target renderer_tests
```

Expected: **link error** — `dauntless_normal_map::enabled` and friends are undefined.

- [ ] **Step 3: Add the toggle namespace in `frame.cc`**

In `native/src/renderer/frame.cc`, beside `dauntless_specular` (`:38-46`):

```cpp
// Normal mapping (opaque pass). Default on with unit strength: stock BC ships
// no _normal maps at all, so "on" is inert on stock assets and the switch is a
// tuning/AB-comparison aid rather than a fidelity control. strength scales the
// tangent-space xy before renormalising, so 0 collapses to the geometric
// normal exactly. flip_green handles DirectX-convention maps (-Y).
namespace dauntless_normal_map {
namespace {
    bool  g_enabled    = true;
    float g_strength   = 1.0f;
    bool  g_flip_green = false;
}
    bool  enabled()    { return g_enabled; }
    void  set_enabled(bool v) { g_enabled = v; }
    float strength()   { return g_strength; }
    void  set_strength(float v) { g_strength = v; }
    bool  flip_green() { return g_flip_green; }
    void  set_flip_green(bool v) { g_flip_green = v; }
}
```

- [ ] **Step 4: Bind unit 4 and the uniforms**

In `frame.cc`, immediately after the `u_rim_strength` line (`:566`) in the per-mesh material block:

```cpp
            // Unit 4 = tangent-space normal map (0 base, 1 glow, 2 specular,
            // 3 damage decal, 5 shadow). u_normal_enabled gates the sample, so
            // the fallback bound when a material has no Bump texture is never
            // read; black_fallback keeps the sampler valid regardless.
            const int bump_tex = mat.stages[
                static_cast<std::size_t>(assets::Material::StageSlot::Bump)
            ].texture_index;
            glActiveTexture(GL_TEXTURE4);
            if (bump_tex >= 0) {
                glBindTexture(GL_TEXTURE_2D, model.textures[bump_tex].id());
            } else {
                glBindTexture(GL_TEXTURE_2D, black_fallback);
            }
            glActiveTexture(GL_TEXTURE0);  // restore default active unit
            prog.set_int  ("u_normal_map", 4);
            prog.set_int  ("u_normal_enabled",
                (bump_tex >= 0 && dauntless_normal_map::enabled()) ? 1 : 0);
            prog.set_float("u_normal_strength", dauntless_normal_map::strength());
            prog.set_int  ("u_normal_flip_g",
                dauntless_normal_map::flip_green() ? 1 : 0);
```

- [ ] **Step 5: Add the tangent frame to `opaque.frag`**

In `native/src/renderer/shaders/opaque.frag`, after the `u_specular_enabled` uniform block (`:14-17`), add:

```glsl
// ── Tangent-space normal map (unit 4) ────────────────────────────────────
// BC NIFs carry no tangents and none are added, so the frame is rebuilt
// per-pixel from screen-space derivatives (Mikkelsen). u_normal_enabled == 0
// is the stock path: n_shade == the geometric normal, byte-identical output.
uniform sampler2D u_normal_map;
uniform int   u_normal_enabled;   // 1 only when the material has a Bump texture
uniform float u_normal_strength;  // 0 = flat, 1 = as authored, >1 exaggerates
uniform int   u_normal_flip_g;    // 1 flips green for DirectX-convention maps
```

Then, immediately above `void main()`, add the helper:

```glsl
// Cotangent frame from screen-space derivatives. Returns N unchanged whenever
// the frame or the resulting normal degenerates -- a zero-length tangent would
// divide to NaN, and a NaN normal poisons every downstream term and spreads
// through the HDR bloom chain as hard-edged black rectangles (the same class of
// bug the rim's clamp() above exists to prevent).
vec3 perturb_normal(vec3 N, vec3 p, vec2 uv) {
    vec3 dp1  = dFdx(p);
    vec3 dp2  = dFdy(p);
    vec2 duv1 = dFdx(uv);
    vec2 duv2 = dFdy(uv);

    vec3 dp2perp = cross(dp2, N);
    vec3 dp1perp = cross(N, dp1);
    vec3 T = dp2perp * duv1.x + dp1perp * duv2.x;
    vec3 B = dp2perp * duv1.y + dp1perp * duv2.y;

    float maxlen = max(dot(T, T), dot(B, B));
    if (maxlen <= 1e-20) return N;   // zero-area UV triangle

    vec3 s = texture(u_normal_map, uv).xyz * 2.0 - 1.0;
    if (u_normal_flip_g != 0) s.y = -s.y;
    s.xy *= u_normal_strength;       // strength 0 => s == (0, 0, z) => N

    float invmax = inversesqrt(maxlen);
    vec3 n = mat3(T * invmax, B * invmax, N) * s;
    float len2 = dot(n, n);
    if (len2 <= 1e-20) return N;     // sample or strength collapsed the vector
    return n * inversesqrt(len2);
}
```

- [ ] **Step 6: Use the shading normal in the lighting terms only**

In `main()`, immediately after `vec3 n = normalize(v_normal_ws);` (`:434`), add:

```glsl
    // n stays GEOMETRIC: the shadow bias must offset along real geometry, and
    // the Fresnel rim is a silhouette effect that crawls and sparkles across
    // greeble detail if it tracks a perturbed normal. n_shade carries the
    // normal-map perturbation for the lighting terms.
    vec3 n_shade = (u_normal_enabled != 0)
        ? perturb_normal(n, v_position_ws, v_uv)
        : n;
```

Then substitute `n_shade` for `n` in exactly these places, and nowhere else:

1. The directional-light loop: `float nl = max(dot(n, L), 0.0);` → `dot(n_shade, L)`.
2. The directional specular: `float s = pow(max(dot(n, H), 0.0), u_specular_power) * step(0.0, nl);` → `dot(n_shade, H)`.
3. The N·L term inside the **dynamic-lights** loop (grep the loop body for `dot(n,` and swap that one occurrence).
4. The specular term inside the **dynamic-lights** loop: `float s = pow(max(dot(n, H), 0.0), u_specular_power) * step(0.0, nl);` → `dot(n_shade, H)`. It mirrors the directional specular term (site 2) — the spec's "diffuse, specular, and the dynamic segment lights" always covered this; a torpedo's dynamic light must not perturb diffuse while leaving its specular highlight on flat geometry.

**Leave these on the geometric `n`:**
- `float sun_sf = sun_shadow_factor(v_position_ws, n);`
- `float ndv = clamp(dot(n, V), 0.0, 1.0);` in the rim block
- `vec3 n_body = normalize(mat3(u_ship_world_inv) * v_normal_ws);`
- The `vec3 n = u_carve_normals[i];` **local** inside the carve loop — that is an unrelated variable that shadows the outer one. Do not touch it.

Finally, extend the non-finite probe chain so a bad tangent frame is diagnosable. Insert immediately after the existing `code = 1` line, keeping every existing code number unchanged:

```glsl
        else if (nf3(n_shade))        code = 18;  // perturbed normal — degenerate tangent frame
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
cmake -B build -S . && cmake --build build -j --target renderer_tests
./build/native/tests/renderer/renderer_tests --gtest_filter='DauntlessNormalMapToggle.*:FrameTest.NormalMapChangesShadingAndZeroStrengthMatchesDisabled'
```

Expected: both PASS. The reconfigure is required — shaders are baked at configure time, so `cmake --build` alone will silently run the old `opaque.frag`.

If `NormalMapChangesShadingAndZeroStrengthMatchesDisabled` fails on the sanity assertion, adjust `kEyeZ` until the Warbird is on screen. If it fails the `differing_texels(frame_zero, frame_on) > 0` assertion while the sanity check passes, the bottom-wing mesh is off screen at that camera — rotate the instance or move the camera so the underside is visible.

- [ ] **Step 8: Run the full gate**

```bash
scripts/check_tests.sh
```

Expected: exit 0, with no failure outside `tests/known_failures.txt`.

- [ ] **Step 9: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag native/src/renderer/frame.cc native/tests/renderer/frame_test.cc
git commit -m "feat(renderer): tangent-space normal mapping via derivative TBN on ship hulls"
```

---

## Task 5: Developer tunables

**Files:**
- Modify: `native/src/host/host_bindings.cc:1285-1300` (forward declarations), `:3154` (binding definitions)
- Modify: `engine/renderer.py:40-72` (name whitelist), `:432-440` (wrappers)
- Modify: `engine/ui/developer_options_panel.py`
- Modify: `native/assets/ui-cef/js/developer_options.js`
- Test: `tests/unit/test_developer_options_panel.py`

**Interfaces:**
- Consumes: `dauntless_normal_map::set_enabled / set_strength / set_flip_green` (Task 4).
- Produces: `renderer.set_normal_map_enabled(bool)`, `renderer.set_normal_map_strength(float)`, `renderer.set_normal_map_flip_green(bool)`; Lighting-tab rows `normal_maps`, `normal_flip_g`, `normal_strength`.

**Why a cycling row rather than a slider:** the panel's control vocabulary is toggles and one-shot actions. Strength cycles `0 → 0.5 → 1 → 2 → 4 → 0` on activate, which reuses the existing activate path instead of introducing slider widgets, and covers the calibrate-up-then-down tuning range.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_developer_options_panel.py` (follow the file's existing fixture/import style for constructing the panel):

```python
def test_lighting_tab_exposes_normal_map_rows(panel):
    panel.open()
    panel.dispatch_event("tab:lighting")
    payload = panel.render_payload()
    assert "normal_maps" in payload
    assert "normal_strength" in payload


def test_normal_strength_cycles_through_presets(panel, monkeypatch):
    seen = []
    monkeypatch.setattr(
        "engine.ui.developer_options_panel.renderer.set_normal_map_strength",
        lambda v: seen.append(v))
    panel.open()
    panel.dispatch_event("tab:lighting")
    for _ in range(5):
        panel.dispatch_event("action:normal_strength")
    assert seen == [0.5, 1.0, 2.0, 4.0, 0.0], seen


def test_normal_map_toggle_round_trips(panel, monkeypatch):
    seen = []
    monkeypatch.setattr(
        "engine.ui.developer_options_panel.renderer.set_normal_map_enabled",
        lambda v: seen.append(v))
    panel.open()
    panel.dispatch_event("tab:lighting")
    panel.dispatch_event("toggle:normal_maps")
    panel.dispatch_event("toggle:normal_maps")
    assert seen == [False, True], seen
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/unit/test_developer_options_panel.py -v
```

Expected: FAIL — `normal_maps` is not in the payload.

- [ ] **Step 3: Expose the setters to Python**

In `native/src/host/host_bindings.cc`, beside the `dauntless_specular` forward declaration (`:1288-1291`):

```cpp
// Normal mapping controls. Defined in frame.cc.
namespace dauntless_normal_map {
    void set_enabled(bool v);
    void set_strength(float v);
    void set_flip_green(bool v);
}
```

And beside the `specular_set_enabled` definition (`:3154`):

```cpp
    m.def("normal_map_set_enabled",
          [](bool enabled) { dauntless_normal_map::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle tangent-space normal mapping on ship hulls. Default: on "
          "(inert on stock assets, which ship no _normal maps).");
    m.def("normal_map_set_strength",
          [](float strength) { dauntless_normal_map::set_strength(strength); },
          py::arg("strength"),
          "Scale the normal map's tangent-space xy. 0 = flat (identical to "
          "disabled), 1 = as authored. Default: 1.0.");
    m.def("normal_map_set_flip_green",
          [](bool flip) { dauntless_normal_map::set_flip_green(flip); },
          py::arg("flip"),
          "Flip the normal map's green channel for DirectX-convention maps. "
          "Default: off (OpenGL convention, +Y up).");
```

- [ ] **Step 4: Add the façade wrappers**

In `engine/renderer.py`, add the three names to the required-binding set (the sorted tuple at `:40-72` — insert alphabetically near `"nonfinite_probe_stats"`):

```python
    "normal_map_set_enabled", "normal_map_set_flip_green",
    "normal_map_set_strength",
```

and the wrappers beside `set_specular_enabled` (`:432`):

```python
def set_normal_map_enabled(enabled: bool) -> None:
    """Toggle tangent-space normal mapping on hulls. Default: on after init().

    Inert on stock BC assets, which ship no `_normal` textures at all.
    """
    _h.normal_map_set_enabled(enabled)


def set_normal_map_strength(strength: float) -> None:
    """Scale the normal map's tangent-space xy. 0 == flat, 1 == as authored."""
    _h.normal_map_set_strength(float(strength))


def set_normal_map_flip_green(flip: bool) -> None:
    """Flip green for DirectX-convention maps. Default: off (OpenGL, +Y up)."""
    _h.normal_map_set_flip_green(flip)
```

- [ ] **Step 5: Add the panel rows**

In `engine/ui/developer_options_panel.py`:

Add state in `__init__` beside `self._systems_damaged` (`:34`):

```python
        self._normal_maps = True
        self._normal_flip_g = False
        self._normal_strength = 1.0
```

Add a preset table as a class attribute beside `_ACTION_CONTROLS`:

```python
    _NORMAL_STRENGTHS = (0.0, 0.5, 1.0, 2.0, 4.0)
```

Register `normal_strength` in `_ACTION_CONTROLS` (it fires rather than toggles), then extend `_focusables` (`:158-159`):

```python
        if self._selected_tab == "lighting":
            out += [("ctrl", "systems_damaged"), ("ctrl", "systems_disabled"),
                    ("ctrl", "normal_maps"), ("ctrl", "normal_flip_g"),
                    ("ctrl", "normal_strength")]
```

Extend the `render_payload` snapshot tuple and `settings` dict:

```python
            self._systems_damaged, self._systems_disabled,
            self._normal_maps, self._normal_flip_g, self._normal_strength,
```

```python
                "normal_maps": self._normal_maps,
                "normal_flip_g": self._normal_flip_g,
                "normal_strength": self._normal_strength,
```

And the handlers in `dispatch_event`, following the setter-before-local-write order the file already uses:

```python
        if action == "toggle:normal_maps":
            renderer.set_normal_map_enabled(not self._normal_maps)
            self._normal_maps = not self._normal_maps
            return True

        if action == "toggle:normal_flip_g":
            renderer.set_normal_map_flip_green(not self._normal_flip_g)
            self._normal_flip_g = not self._normal_flip_g
            return True

        if action == "action:normal_strength":
            presets = self._NORMAL_STRENGTHS
            try:
                idx = presets.index(self._normal_strength)
            except ValueError:
                idx = presets.index(1.0)
            nxt = presets[(idx + 1) % len(presets)]
            renderer.set_normal_map_strength(nxt)
            self._normal_strength = nxt
            return True
```

Import `renderer` at the top of the module if it isn't already imported.

- [ ] **Step 6: Render the rows**

In `native/assets/ui-cef/js/developer_options.js`, add a value row helper beside `_doActionRow` (`:65`):

```js
// Value-cycling row: shows the current value on the button; clicking advances
// it. Used for numeric tunables that don't warrant a slider widget.
function _doValueRow(label, key, valueText, focused) {
    return '<div class="cp-row' + (focused ? ' cp-focused' : '') + '">'
         +   '<div class="cp-row__label">' + escapeHtmlDO(label) + '</div>'
         +   '<div class="cp-row__control">'
         +     '<button class="cp-toggle"'
         +        ' onclick="dauntlessEvent(\'developer-options/action:' + key + '\')">'
         +       escapeHtmlDO(valueText)
         +     '</button>'
         +   '</div>'
         + '</div>';
}
```

In the lighting focusables list (`:28-29`) add:

```js
        out.push({kind: 'ctrl', target: 'normal_maps'});
        out.push({kind: 'ctrl', target: 'normal_flip_g'});
        out.push({kind: 'ctrl', target: 'normal_strength'});
```

And in `_doRenderLightingBody`, after the two existing rows (`:99-102`):

```js
    html += _doToggleRow('Normal Maps', 'normal_maps',
                         s.normal_maps, isFoc('normal_maps'));
    html += _doToggleRow('Normal Map Green Flip', 'normal_flip_g',
                         s.normal_flip_g, isFoc('normal_flip_g'));
    html += _doValueRow('Normal Map Strength', 'normal_strength',
                        Number(s.normal_strength).toFixed(1) + '×',
                        isFoc('normal_strength'));
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run pytest tests/unit/test_developer_options_panel.py -v
```

Expected: all PASS.

- [ ] **Step 8: Run the full gate**

```bash
scripts/check_tests.sh
```

Expected: exit 0, no failure outside `tests/known_failures.txt`.

- [ ] **Step 9: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py engine/ui/developer_options_panel.py native/assets/ui-cef/js/developer_options.js tests/unit/test_developer_options_panel.py
git commit -m "feat(dev): normal-map enable, green-flip, and strength tunables in Developer Options"
```

---

## Live verification (not a test — do this before calling the feature done)

A green suite cannot see whether the map actually reads on screen; the asset paths, the green convention, and the strength calibration are all things only a live run shows.

```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless --developer
```

1. Load a mission containing a Warbird (QuickBattle is quickest).
2. Get the ship's **underside** lit by the system's star — the bottom wing carries the only `_normal` map, and a normal map is invisible until light hits at a grazing angle.
3. Pause → Developer Options → Lighting. Toggle **Normal Maps** off/on and watch the wing. Nothing visible means discovery failed (check stderr for a `[model_build] normal map ...` line) or the wing isn't lit.
4. Cycle **Normal Map Strength** to 4× to exaggerate, confirm the greebles read as depth, then dial back — calibrate up, then down.
5. If detail reads **inverted** (lighting appears to come from the wrong side), flip **Normal Map Green Flip**: the map was authored to the DirectX convention.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Filename predicates, `_glow` stripping | 1 |
| `TextureLoadResult` plumbing | 3 |
| Derived-map probe exclusion | 3 |
| `StageSlot::Bump`, standalone (no Base dual-bind) | 2 |
| Source-agnostic Bump contract | 2 (documented on the `MaterialInputs` member) |
| Renderer binding, unit 4, four uniforms | 4 |
| Derivative cotangent frame, decode, strength, flip | 4 |
| Geometric-normal carve-outs (shadow bias, rim) | 4, Step 6 |
| Byte-identical fallback | 4 (`u_normal_enabled` gate; asserted by the strength-0 test) |
| Green convention + global flip | 4, 5 |
| Strength tunable, not persisted | 5 |
| Missing sibling silently skipped | 3 |
| Broken sibling skipped **and logged**, never checkerboarded | 3 |
| Indexed/16bpp TGA handled | 3 (same catch — `decode_tga` throws `UnsupportedTga`) |
| Unit tests for predicates | 1 |
| Material-build Bump tests | 2 |
| Probe-exclusion test | 3 (`ShipWithoutNormalSiblingsLeavesEveryBumpEmpty` covers the negative; the derived-map guard is exercised by the Warbird test, whose `_specular` sibling must not produce a `_specular_normal` probe) |
| Frame test: unmapped unchanged, mapped differs, strength 0 == unmapped | 4 |

**Placeholder scan:** no TBD/TODO; every code step carries the actual code. Two steps name a tolerance the implementer must confirm empirically (`kEyeZ` framing, and the `nif::parse` spelling) — both are stated as explicit verification steps with the failure symptom described, not as unspecified work.

**Type consistency:** `filename_is_normal` / `sibling_normal_filename` are spelled identically in Tasks 1 and 3. `normal_image_links` (set) and `sibling_normal_for_image` (map) keep the same names and types across `TextureLoadResult` (Task 3), `MaterialInputs` (Task 2), and the threading in Task 3 Step 5. `dauntless_normal_map`'s six functions match between the definition (Task 4 Step 3), the frame-test forward declaration (Task 4 Step 1), and the host-bindings forward declaration (Task 5 Step 3). Uniform names `u_normal_map` / `u_normal_enabled` / `u_normal_strength` / `u_normal_flip_g` match between `frame.cc` (Task 4 Step 4) and `opaque.frag` (Task 4 Step 5).

**Known ordering constraint:** Task 4's frame test depends on Tasks 2-3 having landed, because it needs the Warbird's Bump slot actually populated. Execute the tasks in order.
