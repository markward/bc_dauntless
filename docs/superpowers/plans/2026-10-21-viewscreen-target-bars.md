# Viewscreen Target Bars Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the bridge viewscreen shows a target, draw an affiliation-coloured header band (target name) and footer band (`"<range> km / <speed> kph"`) into the viewscreen RTT.

**Architecture:** A Python tool generates a committed Antonio bitmap font (PNG atlas + JSON metrics). A pure Python builder computes the bars' text and colours from the watched target, sharing the reticle's readout code. A new native `ViewscreenBarsPass` draws the two rounded bands and their text over the 640×360 viewscreen target on the scene-feed path only; the host loop pushes/clears the bars every frame through two new bindings.

**Tech Stack:** Python 3.11 + Pillow 12 (tool), pytest; C++20, OpenGL 4.1 / GLSL 410, gtest, nlohmann/json, pybind11.

**Spec:** `docs/superpowers/specs/2026-10-21-viewscreen-target-bars-design.md` — read it first.

## Global Constraints

- Work in the worktree `.claude/worktrees/viewscreen-target-bars`, branch `feat/viewscreen-target-bars` (native build already configured, Debug). Rebuild with `cmake --build build -j`. **After adding a new shader file, re-run the configure** with the exact flags: `U=~/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none; cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=$PWD/.venv/bin/python3 -DPython3_ROOT_DIR=$U -DPython3_FIND_FRAMEWORK=NEVER -DPython3_FIND_STRATEGY=LOCATION`. Never change the build type, never run cmake from `native/`.
- ⛔ Focused tests only: `uv run pytest <file> -v` and `./build/native/tests/renderer/renderer_tests --gtest_filter=<Suite>*`. Never a whole pytest suite, never bare `ctest`, never `scripts/check_tests.sh`.
- ⛔ No destructive git (`checkout --`, `restore`, `stash`, `clean`, `reset --hard`, `add -A`/`add .`). Explicit pathspecs. `git commit -F <file>`; end messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Never spell `game`/`sdk` as a path segment; project assets resolve via `renderer::project_asset_root()` (default `native/assets`).
- Affiliation colours (sRGB 0-255): FRIENDLY `(80,112,230)`, ENEMY `(216,43,43)`, NEUTRAL `(255,255,175)`, UNKNOWN `(128,128,128)`. Text white `(255,255,255)`, black `(0,0,0)` on NEUTRAL only.
- Bottom text format, exactly the reticle's: `"%.2f km / %.0f kph" % (surface_gu * GU_TO_KM, speed_gu * GUPS_TO_KPH)`.
- Viewscreen RTT 640×360 (`kViewscreenRttW/H`). Band height `0.10 × RTT height`; inner-corner radius `18 px` at 640 wide (scale with width); colour channel cap `0.85` (no band channel above it after converting to 0..1).
- Font source: `native/assets/ui-cef/fonts/Antonio-Regular.ttf`; glyph set printable ASCII 32-126.
- GENERATED files (`native/assets/fonts/viewscreen_antonio.*`) are never hand-edited.

## Review Focus

1. A target name with characters outside ASCII 32-126 (mod ship names) → missing glyphs advance one space and draw nothing; never a crash or garbage quad. Test in Task 3.
2. A name wider than the band → ellipsis-truncated inside the band, never spilling past the rounded corners. Test in Task 3.
3. Target dies / is removed mid-feed → bars cleared the same frame the scene feed returns None; nothing stale appears on the next target or a hail. Test in Task 4.
4. A planet or a non-ship watched object (no `GetVelocity`, not in any mission group) → name + `"x km / 0 kph"`, grey band, no exception. Test in Task 2.
5. An unidentified contact the player has a subsystem locked on → placeholder name, grey band, ship-surface distance (never leaks the real or subsystem name). Test in Task 2.

---

### Task 1: Bitmap font generator + committed atlas

**Files:**
- Create: `tools/fonts/gen_bitmap_font.py`, `native/assets/fonts/viewscreen_antonio.png`, `native/assets/fonts/viewscreen_antonio.json`, `native/assets/fonts/README.md` (one paragraph: generated, how to regenerate, OFL source)
- Test: `tests/tools/test_viewscreen_font_drift.py`

**Interfaces:**
- Produces: the JSON schema the native pass reads —
  `{"generator": "tools/fonts/gen_bitmap_font.py", "font": "Antonio-Regular.ttf", "pixel_size": int, "atlas": "viewscreen_antonio.png", "atlas_w": int, "atlas_h": int, "line_height": int, "ascent": int, "glyphs": {"<codepoint as decimal string>": {"x": int, "y": int, "w": int, "h": int, "bearing_x": int, "bearing_y": int, "advance": int}}}`
  (`bearing_y` = pixels from baseline up to the glyph box top). Atlas: single-channel coverage stored as a greyscale PNG (`L` mode), white glyphs on black.
- Produces: `gen_bitmap_font.py` CLI: `--out-dir <dir>` (default `native/assets/fonts`), `--check` (regenerate to a temp dir and exit 1 if PNG pixels or JSON differ from the committed files). Constant `PIXEL_SIZE = 28` at module top (cap height ≈ 65% of the 36 px band) — the single live-tuning knob.

- [ ] **Step 1: Write the failing tests** in `tests/tools/test_viewscreen_font_drift.py`:
  - `test_committed_font_matches_the_generator`: run the tool with `--out-dir <tmp>`; decoded PNG pixels (via Pillow `Image.open().tobytes()`) and parsed JSON equal the committed ones.
  - `test_every_printable_ascii_glyph_is_present`: JSON `glyphs` keys == `{str(c) for c in range(32, 127)}`; space has `w == 0 or h == 0` and `advance > 0`.
  - `test_glyph_rects_lie_inside_the_atlas_and_do_not_overlap`.
  - `test_generation_is_deterministic`: two runs into two temp dirs produce identical files.
- [ ] **Step 2: Run** `uv run pytest tests/tools/test_viewscreen_font_drift.py -v` — FAIL (tool missing).
- [ ] **Step 3: Implement** the tool with Pillow `ImageFont.truetype(path, PIXEL_SIZE)`: shelf-pack glyphs left-to-right with 2 px padding into the smallest power-of-two-width atlas (≥ 256 wide); metrics from `font.getbbox` / `getlength` / `getmetrics`. Resolve the TTF relative to the repo root (the file's own location), never the cwd. Generate and commit the outputs.
- [ ] **Step 4: Run** the Step 2 command — PASS.
- [ ] **Step 5: Commit** `feat(fonts): generated Antonio bitmap font for the viewscreen bars`.

### Task 2: Bars data builder (Python) + shared readout

**Files:**
- Create: `engine/ui/viewscreen_bars.py`
- Modify: `engine/ui/reticle_text.py` (extract shared helpers; behaviour unchanged)
- Test: `tests/ui/test_viewscreen_bars.py`; regression guard: the existing reticle-text tests (find them: `grep -rln "build_reticle_text" tests`)

**Interfaces:**
- Produces in `engine/ui/reticle_text.py`:
  - `readout_line(target, player) -> str` — the bottom-line string (surface distance via `target_menu.surface_gu_to`, speed via `implements(target, "GetVelocity")`, else 0).
  - `identity_name(target) -> str | None` — the placeholder for an unidentified `ShipClass` (`unknown_labels.placeholder`), else `None`.
  - `build_reticle_text` uses both; its output is byte-identical to today's.
- Produces in `engine/ui/viewscreen_bars.py`:
  - `AFFILIATION_RGB: dict[str, tuple[int, int, int]]` (the four Global Constraints colours) and `TEXT_RGB_ON: dict[str, tuple[int,int,int]]` (white; NEUTRAL black).
  - `build_viewscreen_bars(player, target) -> dict` → `{"visible": bool, "top_text": str, "bottom_text": str, "band_rgb": (r,g,b), "text_rgb": (r,g,b)}` (ints 0-255). `{"visible": False}` when `target` is None or not alive (`camera_modes._target_alive`). `top_text` = `identity_name(target)` or `target.GetDisplayName()` (never a subsystem). Affiliation: `"UNKNOWN"` when `identity_name(target)` is not None, else `target_menu.resolve_affiliation(target, <current mission>)` (mission via `Game_GetCurrentGame().GetCurrentEpisode().GetCurrentMission()`, None-safe); anything not in `AFFILIATION_RGB` → UNKNOWN.

- [ ] **Step 1: Write the failing tests** in `tests/ui/test_viewscreen_bars.py` (real `ShipClass` objects in a real set + a real `Mission` whose groups hold the names, following existing target-list tests' setup):
  - `test_enemy_target_gets_the_red_band_and_white_text` → band `(216,43,43)`, text `(255,255,255)`, `top_text == "Kessok"`.
  - `test_friendly_and_neutral_colours` → `(80,112,230)` white; `(255,255,175)` black.
  - `test_ungrouped_object_is_grey` → `(128,128,128)`.
  - `test_unidentified_contact_shows_its_placeholder_and_grey` (Review Focus 5): `sensor_contacts.shows_identity` false → `top_text == unknown_labels.placeholder(target)`, grey, even when the player has a subsystem locked on it; the real name appears nowhere in the dict.
  - `test_subsystem_lock_still_shows_the_ship_name`.
  - `test_bottom_text_equals_the_reticle_line` → `bottom_text == reticle_text.readout_line(target, player)` and matches `r"^\d+\.\d\d km / \d+ kph$"`.
  - `test_planet_reads_zero_speed_and_grey` (Review Focus 4): a `Planet` (engine/appc/planet.py) target → `bottom_text.endswith(" 0 kph")`, grey, no exception.
  - `test_no_target_or_dead_target_is_hidden` → `{"visible": False}`.
- [ ] **Step 2: Run** `uv run pytest tests/ui/test_viewscreen_bars.py -v` — FAIL.
- [ ] **Step 3: Implement** the helpers and builder per Interfaces.
- [ ] **Step 4: Run** the Step 2 command plus the reticle-text test files found above — all PASS, reticle tests unchanged.
- [ ] **Step 5: Commit** `feat(viewscreen): bars data builder sharing the reticle readout`.

### Task 3: Native `ViewscreenBarsPass`

**Files:**
- Create: `native/src/renderer/include/renderer/viewscreen_bars_pass.h`, `native/src/renderer/viewscreen_bars_pass.cc`, `native/src/renderer/shaders/viewscreen_bars.vert`, `native/src/renderer/shaders/viewscreen_bars.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (source + two `embed_shader` lines like `viewscreen_static`), `native/src/renderer/pipeline.{h,cc}` (`Shader& viewscreen_bars_shader()`), link `nlohmann_json` to `renderer` if `assets` does not already expose it publicly
- Test: `native/tests/renderer/viewscreen_bars_pass_test.cc` (+ add to `native/tests/renderer/CMakeLists.txt`)

**Interfaces:**
- Consumes: Task 1's JSON schema and PNG.
- Produces:
  ```cpp
  namespace renderer {
  struct ViewscreenBars {
      bool visible = false;
      std::string top, bottom;
      std::array<float,3> band_rgb{};   // 0..1, sRGB as sent by Python /255
      std::array<float,3> text_rgb{};
  };
  class ViewscreenBarsPass {
  public:
      bool load_font(const std::string& json_path);   // false (and logs once) on any failure; render() is then a no-op
      bool has_font() const;
      void render(Shader& shader, const ViewscreenBars& bars, int target_w, int target_h);
      // Test seams:
      std::vector<std::pair<float,float>> layout_line_for_test(const std::string& s, float max_w) const; // glyph pen x, per drawn glyph
      std::string fit_for_test(const std::string& s, float max_w) const;  // the string actually drawn (ellipsis-truncated)
  };
  constexpr float kVsBarsHeightFrac  = 0.10f;
  constexpr float kVsBarsRadiusPx640 = 18.0f;
  constexpr float kVsBarsChannelCap  = 0.85f;
  }
  ```
  `render` draws over the currently bound framebuffer (the viewscreen HDR target), alpha-blended, saving/restoring blend/depth/cull/program/texture/VAO state like `ViewscreenStaticPass`. No-op when `!bars.visible` or no font. Band colour = `band_rgb` scaled so its max channel ≤ `kVsBarsChannelCap`; text colour clamped to the same cap. Top band rounds its two **bottom** corners, bottom band its two **top** corners (SDF in the fragment shader). Text centred horizontally, vertically centred on the band using `ascent`/`line_height`. A codepoint missing from the atlas advances by the space glyph's advance and draws nothing. Strings wider than `target_w − 2 × radius` are cut and end in `"..."`.

- [ ] **Step 1: Write the failing gtests** (pattern: `viewscreen_static_pass_test.cc` — `Window` 640×360 headless, `GTEST_SKIP` if no GL; `HdrTarget` cleared to a known feed colour; load the real committed font via `project_asset_root()`-relative path or the source-tree path):
  All pixel coordinates below are **GL framebuffer coordinates (origin bottom-left, y up)**, which is how the scene is stored in the RTT (the bridge pass V-flips when sampling). So the **top band occupies y ∈ [324, 360)** and the bottom band y ∈ [0, 36) on a 640×360 target.
  - `ViewscreenBarsPass.DrawsTheBandColourInBothBands`: empty strings, band `(216,43,43)/255`; pixels `(4, 357)` (top band, by its square outer corner) and `(4, 2)` (bottom band) ≈ the band colour (±0.02); mid-picture `(320,180)` == feed colour.
  - `ViewscreenBarsPass.CapsBrightChannels`: NEUTRAL `(1,1,0.686)` → band pixel max channel ≤ 0.85 + 0.01.
  - `ViewscreenBarsPass.RoundsOnlyTheInnerCorners`: top band: `(1, 325)` (its inner bottom-left corner, outside the radius) == feed, `(1, 358)` == band; bottom band: `(1, 34)` == feed, `(1, 1)` == band.
  - `ViewscreenBarsPass.DrawsTextInsideTheBand`: white text `"KESSOK"` → some pixel in the top band's middle third differs from the band colour.
  - `ViewscreenBarsPass.TextIsRightWayUp`: top string `"T"` only, white on a band; within the glyph's pixel box, the coverage of its upper half (higher y) exceeds its lower half — a `T` is wide at the top. Guards an upside-down atlas.
  - `ViewscreenBarsPass.InvisibleDrawsNothing`: `visible=false` → `(4,357)` == feed.
  - `ViewscreenBarsPass.MissingGlyphAdvancesWithoutDrawing` (Review Focus 1): `layout_line_for_test("A\xc3\xa9B", 1e9)` returns pen positions for `A` and `B` only, and B's pen x == A's advance + 2 × the space advance (each of é's two UTF-8 bytes is an unknown code unit that advances one space).
  - `ViewscreenBarsPass.LongNameIsEllipsised` (Review Focus 2): `fit_for_test(std::string(200,'W'), 604.f)` ends with `"..."` and its laid-out width ≤ 604.
  - `ViewscreenBarsPass.BadFontPathFailsSoft`: `load_font("/nonexistent.json")` false, `render` no-op (feed unchanged).
- [ ] **Step 2: Build and run** `cmake --build build -j && ./build/native/tests/renderer/renderer_tests --gtest_filter='ViewscreenBarsPass*'` — FAIL/compile error (after re-running configure for the new shaders per Global Constraints).
- [ ] **Step 3: Implement** per Interfaces. Atlas upload: `assets::decode_image` + `assets::upload_image(img, /*mipmaps=*/true)`, `GL_LINEAR_MIPMAP_LINEAR` min filter; read the PNG path from the JSON's `atlas` key relative to the JSON's directory.
- [ ] **Step 4: Run** the Step 2 test command, plus `--gtest_filter='ViewscreenStaticPass*'` — PASS.
- [ ] **Step 5: Commit** `feat(renderer): viewscreen bars pass — rounded affiliation bands with bitmap text`.

### Task 4: Wiring — bindings, RTT call, host loop, docs

**Files:**
- Modify: `native/src/host/host_bindings.cc` (global `ViewscreenBarsPass` + `ViewscreenBars` state; create + `load_font` at init next to `g_viewscreen_static_pass` using `project_asset_root() + "/fonts/viewscreen_antonio.json"`; reset at shutdown; in the RTT block call `render` **after the static overlay**, guarded by `!g_comm_source.active && g_scene_source.active` so it can only ever draw on the target feed; bindings below), `engine/renderer.py` (wrappers + `_REQUIRED_BINDINGS` entries), `engine/host_loop.py`, `CLAUDE.md` (one table row), spec status line
- Test: `tests/unit/test_renderer_viewscreen_wrappers.py`, `tests/unit/test_host_loop_viewscreen_drive.py`, `tests/host/test_viewscreen_scene_feed.py`

**Interfaces:**
- Consumes: Task 2 `build_viewscreen_bars(player, target) -> dict`; Task 3 `ViewscreenBarsPass`, `ViewscreenBars`.
- Produces:
  - Bindings `set_viewscreen_bars(top: str, bottom: str, band_rgb: tuple[int,int,int], text_rgb: tuple[int,int,int])` (sets `visible=true`, converts /255) and `clear_viewscreen_bars()`.
  - `engine/renderer.py`: `set_viewscreen_bars(top, bottom, band_rgb, text_rgb)` / `clear_viewscreen_bars()` — thin passthroughs in the style of `set_viewscreen_static`; both names added to `_REQUIRED_BINDINGS`.
  - `engine/host_loop.py`:
    - `_viewscreen_feed_target(player) -> object | None` — the watched-object resolution extracted from `_viewscreen_scene_feed` (including the `_vs_last_player_target` stand-in for PlayerTargetChanged; idempotent within a frame); `_viewscreen_scene_feed` calls it.
    - `drive_viewscreen_bars(r, player, target) -> None` — `r.set_viewscreen_bars(...)` from `build_viewscreen_bars(player, target)` when visible, else `r.clear_viewscreen_bars()`.
    - At the call site (~12979-12985), after `_select_viewscreen_source`: `drive_viewscreen_bars(r, player, _viewscreen_feed_target(player) if _vs_src == "scene" else None)` — so a hail, the forward view, a dead target and the bridge-off path all clear it the same frame.

- [ ] **Step 1: Write the failing tests:**
  - `test_renderer_viewscreen_wrappers.py::test_viewscreen_bars_wrappers_passthrough` — fake `_h` records `set_viewscreen_bars("A", "1.00 km / 0 kph", (1,2,3), (4,5,6))` and `clear_viewscreen_bars()`.
  - `test_host_loop_viewscreen_drive.py::test_drive_viewscreen_bars_sets_when_visible_and_clears_otherwise` — fake renderer; a live target → one `set` with the builder's values; `None` → one `clear` (Review Focus 3: call with a target, then with None, assert the last call is `clear`).
  - `test_viewscreen_scene_feed.py::test_feed_target_matches_the_feed` — using the `wired` fixture: `_viewscreen_feed_target(player)` is the object the feed framed; a mission `ViewscreenWatchObject` target persists until the player retargets (mirror the existing mission-watch tests).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_renderer_viewscreen_wrappers.py tests/unit/test_host_loop_viewscreen_drive.py tests/host/test_viewscreen_scene_feed.py -v` — FAIL.
- [ ] **Step 3: Implement** per Interfaces; rebuild (`cmake --build build -j`).
- [ ] **Step 4: Run** the Step 2 command, plus `tests/ui/test_viewscreen_bars.py`, `tests/unit/test_viewscreen_zoom_target_mode.py`, `tests/host/test_comm_viewscreen_feed.py`, `tests/host/test_viewscreen_feed_precedence.py`, and `./build/native/tests/renderer/renderer_tests --gtest_filter='ViewscreenBarsPass*:ViewscreenStaticPass*'` — all PASS.
- [ ] **Step 5: Docs** — CLAUDE.md row "Viewscreen target bars" (paths: `engine/ui/viewscreen_bars.py`, `native/src/renderer/viewscreen_bars_pass.cc`, `tools/fonts/gen_bitmap_font.py`, spec); rule line: bands drawn INTO the RTT on the scene feed only, colours = target-list affiliation capped at 0.85 so pale yellow can't bloom, text from the GENERATED Antonio atlas (regenerate, never hand-edit; `PIXEL_SIZE` is the size knob); ⚠️ not live-verified. Spec status → `built on feat/viewscreen-target-bars, not live-verified`.
- [ ] **Step 6: Commit** `feat(viewscreen): target bars wired into the viewscreen feed`.

Live check (Mark, not a task): spec §7.
