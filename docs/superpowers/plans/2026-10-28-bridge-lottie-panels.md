# Bridge Lottie Panels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Lottie file (`<stem>.json`, plus optional `<stem>_y/_r/_s.json` per alert state) beside a bridge albedo makes that panel animate in game, rasterised by ThorVG into a live texture that the bridge pass binds in place of the still.

**Architecture:** Three layers. (1) `assets` records, on interior loads only, a `PanelSource` for every external albedo (resolved path + sibling probe dirs + its texture index) and sets `Material::panel_index`. It also sets aside static emissive siblings and the flipbook when a `.json` exists at load. The model stays immutable. (2) A new CPU-only `lottie` library wraps ThorVG (`LottieClip`) and holds the pure helpers (tick, size, composite). It also holds a single `PanelWorker` thread that owns every ThorVG object and the decoded stills. (3) `renderer::BridgePanels`, owned by `BridgePass`, keeps the per-panel playback state and the live GL textures. It marks panels drawn during the frame. Once per frame, before any bridge render, it uploads finished worker results and queues new jobs. `draw_mesh` binds the live texture in place of the still when one exists.

**Tech Stack:** C++20, ThorVG 1.0.4 (software engine + Lottie loader, vendored), OpenGL 4.1, GoogleTest, pybind11, Python (dev panel).

**Spec:** `docs/superpowers/specs/2026-10-28-bridge-lottie-panels-design.md`

**Refinement of spec §4 step 4 (no behaviour change):** the spec puts "the ThorVG animation" in the `LottieTexture` entry. This plan keeps ThorVG objects on the worker thread and keeps only paths on the model (`PanelSource`). It also records a `PanelSource` for *every* interior albedo, not only those with a `.json` at load. That is what lets the §10 reload add slots for files created after load. Static emissive set-aside for a reload-added panel happens at draw time (Task 5): the emissive map is not bound while a live texture is bound.

## Global Constraints

- Interior loads only (`ModelBuildContext::interior_sibling_policy`). Ship loads probe nothing new and stay byte-identical.
- A bridge with no `.json` siblings renders byte-identically (no live texture is ever bound for it).
- File names, beside the albedo, matched case-insensitively: `<stem>.json` (required), `<stem>_y.json`, `<stem>_r.json`, `<stem>_s.json`. State files without `<stem>.json` are ignored with one warning.
- Bridge states (`bridge_pass.h`): 0 green, 1 yellow, 2 red, 3 offline (`kBridgeStateOffline`), 4 special (`kBridgeStateSpecial`). File played: green/offline → default; yellow → `_y` else default; red → `_r` else `_y` else default; special → `_s` else default. Comm sets draw with state 0.
- On a state change, the new file starts from its first frame. Each file loops its whole timeline.
- Live size: canvas aspect, longest edge 512 (Low) / 1024 (Medium) / 2048 (High) from `renderer::BridgeQuality`. Mipmaps are regenerated after every upload.
- Clock: `BridgePass::wall_time_`, which the host feeds game time, so a paused game shows no redraws. Redraw rate is the file's fps capped at **30 Hz**.
- The render thread never waits on the worker. A panel keeps its previous image until a new one is ready, with one frame of latency.
- Warning format: `[lottie] <path>: <reason>; using the still`, printed once per file. A reload clears the once-set.
- ThorVG **1.0.4**, vendored at `native/third_party/thorvg/` with our own CMake. Build only the software raster engine and the Lottie loader. MIT; listed in `THIRD_PARTY_NOTICES.md` and `scripts/package.py`.
- New profiler scope `bridge_lottie` wraps the per-frame update. While the frame profiler is enabled, print one stderr line every 120 updates.
- Shared checkout: never `git checkout -- / restore / stash / clean / reset --hard / add -A / add .`. Stage with explicit paths. Tell every subagent the same.
- Work on branch `feat/bridge-lottie-panels` in a worktree (superpowers:using-git-worktrees). Never commit to main.
- Run focused test files only, never whole suites, never `scripts/check_tests.sh`. Never launch the game without asking Mark.
- Never spell `game` or `sdk` as a path segment in code. One build tree: `build/`.

## Review Focus

1. **Model handle reused after a bridge swap.** A mission swap can free a bridge model and load another under the same handle. A panel entry must never serve the old model's texture. Pinned in Task 5: `BridgePanels.DifferentModelUnderSameHandleDropsTheOldEntry`.
2. **Bridge Quality changed mid-mission.** The live texture is reallocated at the new size. A result rasterised at the old size is discarded, never uploaded into the wrong-size texture. Pinned in Task 5: `BridgePanels.QualityChangeReallocatesAndDiscardsStaleResult`.
3. **A Glaxnimate file whose timeline does not start at 0** (`ip` 10, `op` 40) loads with 30 frames, and frame 0 renders. Pinned in Task 1: `LottieClip.TimelineOffsetCountsFramesFromInPoint`.
4. **Shutdown or bridge unload with a job in flight.** Destroying the worker mid-raster joins promptly, with no crash and no hang. Pinned in Task 4: `PanelWorker.DestroyWithJobInFlightJoins`.
5. **Stock names with spaces and mixed case** (`Map 7.tga` beside `MAP 7_Y.JSON`) are found. Pinned in Task 3: `PanelFiles.MatchesSpacesAndCaseInsensitively`.

---

### Task 1: Vendor ThorVG and wrap it as `LottieClip`

**Files:**
- Create: `native/third_party/thorvg/` (upstream `inc/` + the `src/` subset for the common renderer, software engine and Lottie loader with its bundled JSON parser), `native/third_party/thorvg/CMakeLists.txt`, `LICENSE`, `UPSTREAM_VERSION` (`v1.0.4` + commit hash, as `dr_libs/UPSTREAM_VERSION` does)
- Create: `native/src/lottie/CMakeLists.txt`, `native/src/lottie/include/lottie/lottie_clip.h`, `native/src/lottie/src/lottie_clip.cc`
- Create: `native/tests/lottie/CMakeLists.txt`, `native/tests/lottie/lottie_clip_test.cc`, `native/tests/lottie/fixtures/{solid_red,slide,offset_ip,not_lottie,broken}.json`
- Modify: `native/CMakeLists.txt` (`add_subdirectory(third_party/thorvg)` beside the other third_party lines; `add_subdirectory(src/lottie)` after `src/assets`), `native/tests/CMakeLists.txt` (add `lottie`)
- Modify: `THIRD_PARTY_NOTICES.md` (a `### ThorVG` entry in the dr_mp3 entry's shape: upstream `https://github.com/thorvg/thorvg`, pinned release see `UPSTREAM_VERSION`, MIT, `licenses/ThorVG-LICENSE.txt` (`native/third_party/thorvg/LICENSE`)), `scripts/package.py:third_party_licenses` (`"ThorVG-LICENSE.txt": third / "thorvg" / "LICENSE"`)
- Test: `native/tests/lottie/lottie_clip_test.cc`, `tests/unit/test_package_docs.py` (existing, unchanged)

**Interfaces:**
- Produces (namespace `lottie`, target `lottie`, links `thorvg` PRIVATE and `assets` PUBLIC):
  - `void ensure_thorvg_initialised();`: idempotent and thread-safe (`std::call_once`). Initialises ThorVG with 0 worker threads.
  - `class LottieClip` with `static std::unique_ptr<LottieClip> load(const std::filesystem::path& file, std::string* error);`, `float canvas_width() const`, `float canvas_height() const`, `float total_frames() const`, `float duration_s() const`, `float fps() const` (= total/duration), and `bool render(float frame, std::uint32_t w, std::uint32_t h, std::vector<std::uint8_t>& out_premul_rgba);`
  - `render` output is w·h·4 bytes of **premultiplied** RGBA (ThorVG `ColorSpace::ABGR8888`, which is R,G,B,A byte order on little-endian), cleared to transparent before each draw.
  - `load` returns null and sets `*error` to exactly one of `"not a Lottie animation"`, `"zero canvas size"`, `"no frames"`, `"unreadable file"`.

- [ ] **Step 1: Write the fixtures**, by hand and tiny, so that no BC content is used:
  - `solid_red.json`: 64×32 canvas, 30 fps, `ip` 0, `op` 30, one rect covering the canvas, filled opaque red.
  - `slide.json`: 64×32 canvas, 60 fps, `op` 60, transparent background. A white 10×10 rect whose position goes linearly from centre (5,16) at frame 0 to (59,16) at frame 60.
  - `offset_ip.json`: like `solid_red` but `ip` 10, `op` 40.
  - `not_lottie.json`: `{"hello": 1}`.
  - `broken.json`: the first half of `solid_red.json`.

- [ ] **Step 2: Write the failing tests** in `lottie_clip_test.cc`. Fixtures are found via a `LOTTIE_FIXTURES` compile definition.
  - `LottieClip.LoadsSolidRed`: canvas 64×32, `total_frames()` 30, `fps()` 30 within 1e-3.
  - `LottieClip.RenderSolidRedIsOpaqueRed`: render frame 0 at 64×32; every pixel is `{255,0,0,255}`.
  - `LottieClip.SlideMovesTheSquare`: frame 0 at 64×32. Pixel (5,16) is `{255,255,255,255}` and pixel (59,16) has alpha 0. Frame 59: the reverse.
  - `LottieClip.RenderIsDeterministic`: two renders of `slide` frame 30 give identical bytes.
  - `LottieClip.RenderScalesToTargetSize`: `solid_red` at 256×128 gives 256·128·4 bytes, all opaque red.
  - `LottieClip.TimelineOffsetCountsFramesFromInPoint`: `offset_ip` has `total_frames()` 30; `render(0, …)` returns true with opaque red.
  - `LottieClip.RejectsNonLottie` / `RejectsBrokenJson` / `RejectsMissingFile`: null return; `error` is `"not a Lottie animation"`, `"not a Lottie animation"` and `"unreadable file"` respectively.

- [ ] **Step 3: Run to verify they fail.** Run: `cmake -B build -S . && cmake --build build -j --target lottie_tests`. Expected: the build fails because `lottie/lottie_clip.h` is missing.

- [ ] **Step 4: Vendor ThorVG 1.0.4 and write `native/third_party/thorvg/CMakeLists.txt`.**
  - It is a static target `thorvg`.
  - Compile definitions replace Meson's generated `config.h`: `THORVG_SW_RASTER_SUPPORT`, `THORVG_LOTTIE_LOADER_SUPPORT`, `THORVG_VERSION_STRING="1.0.4"`. No SVG loader, no GL/WG engines, no savers, and no `THORVG_THREAD_SUPPORT` (we use 0 threads; Task 4 owns threading). If upstream insists on a `config.h`, generate one with `configure_file` in the build tree.
  - It must compile with clang, gcc and MSVC. Silence upstream warnings on this target only.

- [ ] **Step 5: Implement `LottieClip`** in `lottie_clip.cc`. Read the bytes with `assets::read_file`, or the assets file-bytes helper `file_bytes_test.cc` covers, and load them from memory as Lottie, so wide paths work on Windows. `render` owns one `SwCanvas` per clip, retargeted when w/h change.

- [ ] **Step 6: Run the tests to verify they pass.** Run: `cmake --build build -j --target lottie_tests && ./build/native/tests/lottie/lottie_tests && uv run pytest tests/unit/test_package_docs.py -q`. Expected: all pass.

- [ ] **Step 7: Commit.** Stage `native/third_party/thorvg native/src/lottie native/tests/lottie native/CMakeLists.txt native/tests/CMakeLists.txt THIRD_PARTY_NOTICES.md scripts/package.py` explicitly. Message: `feat(lottie): vendor ThorVG 1.0.4 and wrap Lottie playback`.

### Task 2: Pure panel helpers: tick, size, composite

**Files:**
- Create: `native/src/lottie/include/lottie/panel_math.h`, `native/src/lottie/src/panel_math.cc`
- Modify: `native/src/renderer/include/renderer/bridge_quality.h` (add `panel_edge_for`)
- Test: `native/tests/lottie/panel_math_test.cc`, `native/tests/renderer/bridge_quality_test.cc` (create it if no quality test exists; add it to `renderer_tests`)

**Interfaces:**
- Produces (namespace `lottie`):
  - `struct PanelTick { std::int64_t tick; float frame; };`
  - `PanelTick panel_tick(double t, double start, float total_frames, float fps);`
    - rate = min(fps, 30); duration = total_frames / fps; local = (t − start) mod duration (non-negative).
    - tick = floor((t − start)/duration) · ticks_per_loop + floor(local · rate), where ticks_per_loop = ceil(duration · rate).
    - frame = min(floor(local · rate) · fps / rate, total_frames − 1).
  - `struct PanelSize { std::uint32_t w, h; };`, `PanelSize panel_size(float canvas_w, float canvas_h, std::uint32_t longest_edge);`: the long side = edge; short side = max(1, lround(edge · short/long)).
  - `std::vector<std::uint8_t> composite_panel(const assets::Image& still, std::span<const std::uint8_t> lottie_premul_rgba, std::uint32_t w, std::uint32_t h);`
    - The still (RGBA8, RGB8 or R8) is converted to RGBA and bilinear-scaled to w×h.
    - Per texel: out.rgb = L.rgb + S.rgb·(1 − L.a); out.a = L.a + S.a·(1 − L.a). Work in 0–1 floats and round to the nearest byte. The still's RGB is used as-is (not premultiplied by its alpha) because BC alpha is a test mask.
- Produces (namespace `renderer`): `std::uint32_t panel_edge_for(BridgeQuality q);` returns 512 / 1024 / 2048.

- [ ] **Step 1: Write the failing tests.**
  - `PanelTick.SixtyFpsFileAdvancesAtThirtyHz`: (t=10, start=10, 144, 60) gives {0, 0}. t=10+1/60 gives tick 0. t=10+1/30 gives {1, 2}.
  - `PanelTick.WrapsAndKeepsCounting`: t = start + 2.4 gives frame 0, tick 72.
  - `PanelTick.SlowFileTicksAtItsOwnRate`: fps 24, t = start + 0.5 gives {12, 12}.
  - `PanelTick.SameTimeSameTick`: two calls with equal t are equal (the paused clock).
  - `PanelSize.Rounds`: (640,320,1024) gives {1024,512}; (320,640,512) gives {256,512}; (640,321,1024) gives {1024,514}; (1,1000,2048) gives {2,2048}.
  - `Composite.TransparentLottieShowsStill`: a 2×2 RGBA still with distinct texels at its own size and all-zero Lottie gives output == still.
  - `Composite.OpaqueLottieReplaces`: opaque `{0,255,0,255}` gives every texel `{0,255,0,255}`.
  - `Composite.HalfAlphaOverAlphaZeroStill`: Lottie `{128,128,128,128}` over a still texel `{0,0,0,0}` gives `{128,128,128,128}`.
  - `Composite.ScalesTheStill`: a 1×1 still `{10,20,30,40}` at 4×2 gives every texel `{10,20,30,40}` under a transparent Lottie.
  - `Composite.AcceptsRgbStill`: an RGB8 still gives alpha 255.
  - `BridgeQuality.PanelEdge`: Low/Medium/High give 512/1024/2048.

- [ ] **Step 2: Run to verify they fail.** Run: `cmake --build build -j --target lottie_tests renderer_tests`. Expected: compile errors for the missing symbols.

- [ ] **Step 3: Implement** `panel_math.cc` and `panel_edge_for` to the formulas above.

- [ ] **Step 4: Run to verify they pass.** Run: `./build/native/tests/lottie/lottie_tests --gtest_filter='PanelTick*:PanelSize*:Composite*' && ./build/native/tests/renderer/renderer_tests --gtest_filter='BridgeQuality*'`. Expected: PASS.

- [ ] **Step 5: Commit.** Stage `native/src/lottie native/tests/lottie native/src/renderer/include/renderer/bridge_quality.h` plus the quality test and the renderer test CMake. Message: `feat(lottie): panel tick, size and still compositing`.

### Task 3: Loader: panel files, `PanelSource`, set-asides

**Files:**
- Create: `native/src/assets/include/assets/panel_files.h`, `native/src/assets/src/panel_files.cc` (add to the assets target)
- Modify: `native/src/assets/include/assets/model.h` (`PanelSource`, `Model::panel_sources`), `native/src/assets/include/assets/material.h` (`int panel_index = -1;` after `animation_index`, documented like it), `native/src/assets/src/model_build.cc` (`load_all_textures` around the sibling probe at `:312-380`; the material loop at `:1081-1092`), `native/src/assets/src/material_build.{h,cc}` (pass the image→panel map through `MaterialInputs`), `native/src/assets/src/model_compose.cc:253` (`copy.panel_index = -1;`)
- Test: `native/tests/assets/cpu/panel_files_test.cc` (new; add to `assets_tests`), `native/tests/assets/cpu/model_build_test.cc`, `native/tests/assets/cpu/model_compose_test.cc`, `native/tests/host/model_identity_maps_test.cc`

**Interfaces:**
- Produces (namespace `assets`):
  - `inline constexpr int kPanelDefault = 0, kPanelYellow = 1, kPanelRed = 2, kPanelSpecial = 3, kPanelVariants = 4;`
  - `struct PanelFiles { std::array<std::filesystem::path, kPanelVariants> by_variant; };` An empty path means absent. If the default is absent, every entry is empty.
  - `PanelFiles find_panel_files(const std::filesystem::path& albedo, const std::vector<std::filesystem::path>& dirs);`
    - Stem = the albedo's filename stem. The default is taken from the first dir that holds `<stem>.json`, case-insensitively.
    - State files are searched only in that same dir.
    - State files found with no default produce one `[lottie] <dir>/<file>: no <stem>.json beside it; ignored` warning per call.
  - `int select_panel_variant(int bridge_state, const std::array<bool, kPanelVariants>& valid);` follows the Global Constraints mapping and its fallback chain. It returns −1 when nothing on the chain is valid.
  - `struct PanelSource { std::filesystem::path albedo; std::vector<std::filesystem::path> probe_dirs; int base_texture_index = -1; };` and `std::vector<PanelSource> Model::panel_sources;`, documented as interior loads only and empty otherwise.
  - `int Material::panel_index` indexes `Model::panel_sources`; −1 for none.

- [ ] **Step 1: Write the failing tests.**
  - `PanelFiles.FindsDefaultAndStates`: `hull.tga` dir holding `hull.json` and `hull_r.json` gives slot 0 and slot 2 set; 1 and 3 empty.
  - `PanelFiles.MatchesSpacesAndCaseInsensitively`: `Map 7.tga`, with `map 7.JSON` and `MAP 7_Y.JSON` on disk, gives slots 0 and 1 found.
  - `PanelFiles.StateFileWithoutDefaultIsIgnored`: only `hull_y.json` gives all empty.
  - `PanelFiles.FirstDirWithDefaultWins`: dirs {a, b}, where b has `hull.json` and a has only `hull_r.json`, gives slot 0 from b and slot 2 empty.
  - `PanelVariant.Chain`: with valid {1,1,0,0}, states 0,1,2,3,4 give 0,1,1,0,0. With valid {1,0,1,1}: state 2 gives 2, state 1 gives 0, state 4 gives 3. With valid {0,0,1,0}: state 0 gives −1, state 2 gives 2.
  - In `model_build_test.cc`, using the existing `interior_mod_ctx` / `write_tga_at` helpers:
    - `InteriorLoadRecordsAPanelSourceForEachAlbedo`: an interior load with `hull_ID.tga` gives `panel_sources.size()==1`, the material's `panel_index==0`, `base_texture_index` equal to the Base stage index, and `albedo` equal to the resolved path.
    - `ShipLoadRecordsNoPanelSources`: policy off gives an empty `panel_sources` and `panel_index==-1`.
    - `LottieAtLoadSetsAsideEmissiveSiblings`: `hull_ID.json` plus `hull_ID_emissive.tga` gives Emissive/Yellow/Red/Special stages all −1.
    - `EmissiveSiblingsStayWithoutLottie`: the existing behaviour with no `.json` (Emissive bound).
    - `LottieAtLoadClearsFlipbook`: a flipbook material whose frame-0 image has a `.json` gives `animation_index==-1`. Use the `mesh_fix_flipbook_test.cc` route to build a flipbook if `file_with_textured_shape` cannot.
  - `ModelCompose.HeadMaterialsDropPanelIndex` in `model_compose_test.cc`.
  - `ModelIdentityMaps.EmissiveFalseWhenLottieSetsItAside` in `model_identity_maps_test.cc`: this is the data `engine/bridge_editor/glow.py` reads via `maps["emissive"]`, so no Python change is needed.

- [ ] **Step 2: Run to verify they fail.** Run: `cmake --build build -j --target assets_tests host_tests`, using whatever the host test target in `native/tests/host/CMakeLists.txt` is named. Expected: compile errors.

- [ ] **Step 3: Implement `panel_files.cc`** to the interface above.

- [ ] **Step 4: Wire the loader.**
  - In `load_all_textures`, inside the existing `use_external && !is_derived_map` block, when `ctx.interior_sibling_policy` is set and `resolved_albedo` is non-empty and decoded (not the checkerboard): append a `PanelSource{resolved_albedo, sibling_dirs, <this image's texture index>}` and record `link_id → panel index` in a new `TextureLoadResult::panel_for_image`.
  - Call `find_panel_files` and record `link_id` in `lottie_at_load` when slot 0 is non-empty.
  - For those images, the four `_emissive*` probes only resolve, never decode or bind. If any resolved, print one `[lottie] <json path>: static emissive maps set aside: <names>` line.
  - The material loop assigns `panel_index` from `panel_for_image[effective_image_link]`. Right after `animation_index` is set (`:1091`), clear it when the link is in `lottie_at_load`, printing `[lottie] <json path>: replaces the flipbook on this material` once per json.

- [ ] **Step 5: Run to verify they pass.** Run: `./build/native/tests/assets/assets_tests --gtest_filter='PanelFiles*:PanelVariant*:ModelBuildTest.*Panel*:ModelBuildTest.*Lottie*:ModelBuildTest.*Emissive*:ModelCompose*'`, then the host test binary with `--gtest_filter='ModelIdentityMaps*'`. Expected: PASS, including every pre-existing emissive test.

- [ ] **Step 6: Commit.** Stage the files above explicitly. Message: `feat(assets): record bridge panel sources; Lottie sets aside emissive and flipbook`.

### Task 4: `PanelWorker`, the one thread that owns ThorVG

**Files:**
- Create: `native/src/lottie/include/lottie/panel_worker.h`, `native/src/lottie/src/panel_worker.cc`
- Test: `native/tests/lottie/panel_worker_test.cc`

**Interfaces:**
- Consumes: `LottieClip` (Task 1); `composite_panel` (Task 2); `assets::PanelFiles`, `kPanelVariants` (Task 3); `assets::decode_tga` / `decode_image`.
- Produces (namespace `lottie`):
  - `struct PanelInfo { std::array<bool, assets::kPanelVariants> valid{}; std::array<float, assets::kPanelVariants> total_frames{}, fps{}; float canvas_w = 0, canvas_h = 0; std::uint64_t generation = 0; };` The canvas is the default file's.
  - `struct PanelJob { std::uint64_t key; int variant; float frame; std::uint32_t w, h; std::uint64_t generation; };`
  - `struct PanelResult { std::uint64_t key; std::uint64_t generation; std::uint32_t w, h; std::vector<std::uint8_t> rgba; double raster_ms; };` `rgba` is straight RGBA from `composite_panel`, w·h·4.
  - `class PanelWorker` with:
    - `PanelWorker(); ~PanelWorker();`: the destructor drops queued jobs and joins.
    - `void set_panel(std::uint64_t key, assets::PanelFiles files, std::filesystem::path albedo);`: always (re)loads from disk on the worker and bumps the key's generation.
    - `void remove_panel(std::uint64_t key);`
    - `std::optional<PanelInfo> info(std::uint64_t key) const;`: nullopt until that key's load finishes.
    - `bool submit(const PanelJob& job);`: false when a job for the key is already queued or running.
    - `std::vector<PanelResult> take_results();`: non-blocking.
    - `void clear_warnings();`
    - `void set_test_raster_delay(std::chrono::milliseconds d);`
- Behaviour:
  - Loads use `LottieClip::load`. Each failure prints the Global Constraints warning once per path.
  - A state file whose canvas aspect differs from the default's by more than 1% prints `[lottie] <path>: canvas aspect differs from <stem>.json; stretched` once.
  - An unreadable still makes the job composite over transparent black, with one warning.
  - A result whose generation is older than the key's current one is dropped on the worker.
  - Calls `ensure_thorvg_initialised()` on the worker thread.

- [ ] **Step 1: Write the failing tests.** Use Task 1's fixtures and a small TGA written to a temp dir. Helper `wait_for(pred, 2s)` polls every 5 ms.
  - `PanelWorker.InfoAppearsAfterLoad`: `set_panel` with `solid_red.json` as default; info becomes valid {1,0,0,0} with canvas 64×32.
  - `PanelWorker.JobProducesCompositedResult`: submit {variant 0, frame 0, 64×32}; one result with 64·32·4 bytes, all `{255,0,0,255}`.
  - `PanelWorker.SecondSubmitWhileBusyIsRefused`: with the test delay at 200 ms, the first submit is true and the second false; after the result, submit is true again.
  - `PanelWorker.InvalidDefaultIsNotValid`: `broken.json` as default gives info valid[0] false, and stderr contains `using the still` once across two `set_panel` calls. Capture with `testing::internal::CaptureStderr`.
  - `PanelWorker.ClearWarningsWarnsAgain`.
  - `PanelWorker.SetPanelDropsOlderGenerationResults`: with the delay at 200 ms, submit, then `set_panel` again, then wait; no result carries the old generation.
  - `PanelWorker.EmptyFilesClearsValidity`: `set_panel` with an empty `PanelFiles` gives all valid false.
  - `PanelWorker.DestroyWithJobInFlightJoins`: delay 300 ms, submit, destroy; the destructor returns in < 1 s.

- [ ] **Step 2: Run to verify they fail.** Run: `cmake --build build -j --target lottie_tests`. Expected: compile errors.

- [ ] **Step 3: Implement** one `std::thread`, a mutex + condition-variable queue, per-key state (clips, decoded still, generation, busy flag) touched only on the worker, and `info` published under the mutex.

- [ ] **Step 4: Run to verify they pass.** Run: `./build/native/tests/lottie/lottie_tests --gtest_filter='PanelWorker*' --gtest_repeat=20`. Expected: PASS on every repeat.

- [ ] **Step 5: Commit.** Stage `native/src/lottie native/tests/lottie`. Message: `feat(lottie): panel worker thread`.

### Task 5: `BridgePanels` store, bridge pass binding, per-frame hook

**Files:**
- Create: `native/src/renderer/include/renderer/bridge_panels.h`, `native/src/renderer/bridge_panels.cc` (add to the `renderer` target; `target_link_libraries(renderer PUBLIC … lottie)`)
- Modify: `native/src/renderer/include/renderer/bridge_pass.h` (member `BridgePanels panels_;`, public `void update_panels(BridgeQuality q);` and `void reload_panels();`), `native/src/renderer/bridge_pass.cc`, `native/src/host/host_bindings.cc` (frame hook before the `viewscreen.rtt` block at about `:2043`)
- Test: `native/tests/renderer/bridge_panels_test.cc` (new, in `renderer_tests`; GL via `gl_fixture`), `native/tests/renderer/bridge_pass_test.cc`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces (namespace `renderer`), `class BridgePanels` with:
  - `void mark_drawn(unsigned long long handle, const assets::Model& model, int panel_index, int bridge_state);`: render thread, per draw. A known (handle, panel_index) whose stored `const Model*` differs from `&model` is dropped first, deleting its texture and `remove_panel`, then recreated.
  - `GLuint live_texture(unsigned long long handle, const assets::Model& model, int panel_index) const;`: 0 unless the entry exists for this exact `&model`, has a valid variant, and has an uploaded image.
  - `void update(double t, BridgeQuality q);`: once per frame. It:
    1. uploads `take_results()` whose w/h match the entry's current size (others are discarded), using `glTexImage2D` on first upload then `glTexSubImage2D`, followed by `glGenerateMipmap` with min filter `GL_LINEAR_MIPMAP_LINEAR`;
    2. resizes entries whose `panel_size(canvas, panel_edge_for(q))` changed (texture deleted, image cleared);
    3. for entries drawn since the last update: `variant = select_panel_variant(state, info.valid)`, where a change restarts `start = t` and −1 clears the image; `tick = panel_tick(t, start, …)`; submits a job when the tick changed;
    4. clears the drawn flags.
  - `void reload();`: for every entry, re-runs `find_panel_files(source.albedo, source.probe_dirs)` and calls `set_panel`. It also calls `clear_warnings()`. Entries exist for every drawn interior albedo, so files created since load are picked up.
  - `struct Stats { int uploads; int jobs; double raster_ms; };` and `Stats take_stats();`.
- `draw_mesh` gains a trailing `GLuint live_base = 0`. When it is non-zero and neither `base_override` nor `face_blend` applies, it binds `live_base` on unit 0 instead of `model.textures[base_tex]`, and forces the emissive map id to 0. This is the draw-time set-aside for reload-added panels.
- `draw_shell` computes `live` from `panels_.live_texture(mh, m, mat.panel_index)` when `mat.panel_index >= 0`. When `!capture_pass_ && !normal_pass_`, it also calls `panels_.mark_drawn(mh, m, mat.panel_index, emissive_alert)`. Comm sets therefore mark state 0. Probe faces bind the current image but never mark.
- Host frame hook: `if (g_bridge_pass) { DAUNTLESS_FRAME_SCOPE("bridge_lottie"); g_bridge_pass->update_panels(g_bridge_quality); }`. When `frame_timer().enabled()`, every 120 updates print `[bridge_lottie] uploads=%d jobs=%d raster=%.3f ms/frame avg`.

- [ ] **Step 1: Write the failing tests.** Build an `assets::Model` by hand: one 2×2 RGBA still texture, one `PanelSource` whose albedo is a temp-dir TGA beside a copy of a Task 1 fixture, and a material with `panel_index` 0. Helper `pump(panels, t, until)` calls `update` every 5 ms for up to 2 s.
  - `BridgePanels.NoJsonNeverMakesALiveTexture`: a source with no `.json`, marked and pumped 200 ms, gives `live_texture == 0`.
  - `BridgePanels.MarkedPanelGetsALiveTexture`: with `solid_red.json`, mark + pump gives a non-zero texture. `glGetTexImage` returns 1024×512 (Medium) of red.
  - `BridgePanels.ImageChangesWithTime`: with `slide.json`, after the first upload at t=0, update at t=0.5 with a mark gives different readback bytes.
  - `BridgePanels.PausedClockSubmitsNoJobs`: repeated `update` at the same t gives `take_stats().jobs == 0` after the first.
  - `BridgePanels.UnmarkedPanelSubmitsNoJobs`: no mark gives no jobs, even as t advances.
  - `BridgePanels.StateChangeRestartsAndFallsBack`: `hull.json` = slide, `hull_y.json` = solid_red. State 2 (red) with no `_r` shows the yellow file (red pixels); state 0 shows slide.
  - `BridgePanels.InvalidJsonShowsStill`: `broken.json` gives 0.
  - `BridgePanels.UpdateNeverBlocks`: with the worker test delay at 300 ms (exposed via a `BridgePanels::worker_for_test()` accessor), each `update` returns in < 5 ms.
  - `BridgePanels.DifferentModelUnderSameHandleDropsTheOldEntry`: mark with model A until live; mark the same handle with model B; `live_texture(handle, A, 0) == 0`, and B's comes up independently.
  - `BridgePanels.QualityChangeReallocatesAndDiscardsStaleResult`: live at Medium (1024×512); switch to Low with a job in flight; the next uploaded image is 512×256 and no 1024-wide upload lands after the switch.
  - `BridgePanels.ReloadPicksUpAddedAndDeletedFiles`: start with no `.json`, mark, then write the fixture and `reload()`; it becomes live. Delete the file and `reload()`; it becomes 0.
  - `BridgePassTest.LivePanelReplacesTheStillAndDropsEmissive` in `bridge_pass_test.cc`, using the `bridge_test_room.h` helpers: a material with a panel and an `_emissive` stage; after pumping, the drawn pixel is the panel's colour and the emissive term is absent.
  - `BridgePassTest.NoPanelSourcesRendersByteIdentically`: an existing room rendered with and without `update_panels` calls gives identical framebuffers.

- [ ] **Step 2: Run to verify they fail.** Run: `cmake --build build -j --target renderer_tests`. Expected: compile errors.

- [ ] **Step 3: Implement `BridgePanels`**, the `draw_mesh`/`draw_shell` changes and the host hook to the interfaces above. The `BridgePanels` destructor deletes its textures; BridgePass is destroyed with a live context, as `white_texture_` already assumes.

- [ ] **Step 4: Run to verify they pass.** Run: `./build/native/tests/renderer/renderer_tests --gtest_filter='BridgePanels*:BridgePassTest*:BridgeQuality*'`. Expected: PASS, including every existing `BridgePassTest`.

- [ ] **Step 5: Commit.** Stage `native/src/renderer/bridge_panels.cc native/src/renderer/include/renderer/bridge_panels.h native/src/renderer/bridge_pass.cc native/src/renderer/include/renderer/bridge_pass.h native/src/renderer/CMakeLists.txt native/src/host/host_bindings.cc native/tests/renderer/bridge_panels_test.cc native/tests/renderer/bridge_pass_test.cc native/tests/renderer/CMakeLists.txt`. Message: `feat(renderer): live Lottie bridge panels`.

### Task 6: Developer reload: binding, host_io, Lighting row

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`m.def("reload_bridge_panels", …)` next to `set_bridge_quality`, calling `g_bridge_pass->reload_panels()` when present), `engine/host_io.py` (`reload_bridge_panels()` in the `set_bridge_pbr_enabled` shape: a no-op headless or when the binding is missing), `engine/ui/developer_options_panel.py` (add `"reload_bridge_panels"` to the action-key set at `:98`, the Lighting focusables, and a dispatch branch for `action:reload_bridge_panels` that calls `host_io.reload_bridge_panels()`, prints `[bridge_lottie] panels reloaded` to stderr and returns True), `native/assets/ui-cef/js/developer_options.js` (Lighting focusable `reload_bridge_panels` after `bridge_debug_view`, plus `_doActionRow('Reload Bridge Panels', 'reload_bridge_panels', 'Reload', isFoc('reload_bridge_panels'))` in the Lighting body)
- Test: `tests/unit/test_developer_options_panel.py`, `tests/ui/test_developer_options_lighting_tab.py`, `tests/unit/test_host_io_bridge_panels.py` (new)

**Interfaces:**
- Consumes: `BridgePass::reload_panels()` (Task 5).
- Produces: `_dauntless_host.reload_bridge_panels() -> None` and `engine.host_io.reload_bridge_panels() -> None`.

- [ ] **Step 1: Write the failing tests.**
  - `test_reload_bridge_panels_ctrl_is_a_lighting_tab_focusable`: after `tab:lighting`, `("ctrl", "reload_bridge_panels") in p._focusables()`.
  - `test_reload_bridge_panels_action_calls_host_io`: monkeypatch `host_io.reload_bridge_panels` to record calls. `dispatch_event("action:reload_bridge_panels") is True` and it is called once.
  - `test_js_has_a_reload_bridge_panels_row_and_focusable`: the JS source contains `'Reload Bridge Panels'` and `target: 'reload_bridge_panels'` inside the Lighting block.
  - `test_reload_bridge_panels_is_a_noop_without_the_binding`: with `host_io._h` set to an object lacking the attribute, the call returns None without raising.

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/unit/test_developer_options_panel.py tests/ui/test_developer_options_lighting_tab.py tests/unit/test_host_io_bridge_panels.py -q -k reload_bridge_panels`. Expected: FAIL.

- [ ] **Step 3: Implement** to the interfaces above, then rebuild `dauntless`: `cmake --build build -j`.

- [ ] **Step 4: Run to verify they pass.** Same command; expected PASS.

- [ ] **Step 5: Commit.** Stage the six files explicitly. Message: `feat(dev): Reload Bridge Panels`.

### Task 7: DBridge running light, live check, measurement, docs

The quickest acceptance path uses spec §4 step 6: a `running_0.json` beside the overlay's existing flipbook frame 0. It replaces the 12-frame flipbook on b0688 with no Blender or fix change, and the frames stay on disk. Mark may later repoint the object at a `running.tga` in Blender (§3). That is not needed for acceptance.

**Files:**
- Create: `native/assets/replacements/data/Models/Sets/DBridge/High/running_0.json`. This is the spike's Glaxnimate-checked `running.json` (scratchpad `lottie_spike/running.json`), minified, unchanged in content. It is project-authored, not BC content.
- Modify: `docs/reference/engine/perf-register.md` (a new signal), `CLAUDE.md` (a "Bridge Lottie panels" row in the reference table: authoring contract, state files, reload, ThorVG pin, the warning prefix)

- [ ] **Step 1: Place the file**, then check the loader picks it up headlessly with the existing asset dump tool (`build/native/tools/dump_bridge_assets` or the nearest equivalent). Expected stderr: `[lottie] …running_0.json: replaces the flipbook on this material`.

- [ ] **Step 2: Commit the asset.** Message: `content(dbridge): running light as a Lottie panel`.

- [ ] **Step 3: Ask Mark** to run the game on the DBridge (the plain launch command, `./build/dauntless`) and compare the running light with the old flipbook: same path and speed, smooth motion, glow only if he has an editor material on it. Then press Reload Bridge Panels after editing the file in Glaxnimate. Do not launch the game yourself.

- [ ] **Step 4: Measure** (spec §7), on Mark's go-ahead: the frame profiler on the DBridge at Medium, Debug build. Record `bridge_lottie` CPU time and the `[bridge_lottie]` raster line as a new signal in `perf-register.md`, with capture ID, command and evidence tier "measured". Compare against the 0.3 ms target and bring a miss to Mark with the numbers.

- [ ] **Step 5: Write the CLAUDE.md row and commit the docs.** Message: `docs: bridge Lottie panels reference row and perf signal`.
