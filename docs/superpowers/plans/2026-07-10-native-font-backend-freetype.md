# Native FreeType Font Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render a live `TGParagraph` as real FreeType-rasterized Antonio text in a window on a launch path where CEF is never constructed, validating "keep the SDK interface, swap the backend" on `TGFontGroup`.

**Architecture:** A new CPU-only native `text` library (FreeType) rasterizes glyphs into a fixed R8 atlas and shapes strings (advances + kerning, Latin/LTR). A new screen-space `UiQuadPass` (pixel→NDC quads) draws atlas glyphs to the default framebuffer. Python `TGFontGroup`/`TGFontManager`/`TGParagraph` keep their public surface but proxy to native calls. A `--no-cef`/`--ui-harness` launch path (new C++ flag + mode) bypasses CEF entirely and runs a throwaway Python harness loop.

**Tech Stack:** C++20, FreeType (FetchContent), OpenGL 4.1 core via glad/GLFW, pybind11, Python 3.11, pytest, GoogleTest/ctest.

## Global Constraints

- **Single build tree** at `<root>/build`. Configure `cmake -B build -S .`; build `cmake --build build -j`. Binary is `./build/dauntless`; module is `build/python/_dauntless_host.cpython-*.so`. Never emit to any other path.
- **CMake / shader / new-`.vert`/`.frag` changes require a reconfigure** (`cmake -B build -S .`) before `cmake --build build` — shaders are embedded at configure time.
- **`host_bindings.cc` / `host_main.cc` edits require rebuilding the `dauntless` target** (a module-only rebuild leaves `./build/dauntless` stale).
- **Diagnostics use `print()`**, never `logging.*` — the embedded host has no logging handler.
- **Gate:** `scripts/check_tests.sh` must pass (builds C++, runs pytest + ctest, diffs `tests/known_failures.txt`; only the 7 baselined headless-GL `FrameTest`s may fail). Never call a new failure "pre-existing" by eyeball.
- **CEF must never be constructed on the `--no-cef` / `--ui-harness` path.** Verify by evidence (positive print present, guard print absent), not assumption.
- **Font substitution:** `CreateFontGroup("Crillee", …)` (and any BC family name) resolves to `native/assets/fonts/Antonio-Regular.ttf` (OFL, shippable). Carry `Antonio-OFL.txt` alongside it.
- **Draw-list coordinates are framebuffer pixels, top-left origin.**
- **Committing / branch:** the human runs this plan only once back on `main`. The FIRST execution step is to commit the already-written spec + this plan (`docs/superpowers/specs/2026-07-10-native-font-backend-freetype-design.md`, `docs/superpowers/plans/2026-07-10-native-font-backend-freetype.md`). Per-task commits follow the normal TDD cycle below.

---

## File Structure

**Native — new `text` library (CPU only, FreeType):**
- `native/src/text/CMakeLists.txt` — static lib `text`, links `freetype`.
- `native/src/text/include/text/font_service.h` — `FontService`, `GlyphQuad`, `Atlas` (pImpl hides FreeType).
- `native/src/text/src/font_service.cc` — face load, glyph raster, shelf-packed atlas, shape/measure.
- `native/tests/text/CMakeLists.txt`, `native/tests/text/font_service_test.cc` — `text_tests`.

**Native — GL UI pass (renderer lib):**
- `native/src/renderer/shaders/ui_quad.vert`, `ui_quad.frag` — pixel→NDC glyph quad.
- `native/src/renderer/include/renderer/ui_quad_pass.h`, `native/src/renderer/ui_quad_pass.cc` — `UiQuadPass`, `UiGlyphQuad` (pure GL; no `text` dep).
- `native/tests/renderer/ui_quad_pass_test.cc` — headless GL readback test.

**Native — launch path + bindings:**
- `native/src/host/cef_disabled.h`, `native/src/host/cef_disabled.cc` — process-global `--no-cef` flag (mirrors `developer_mode`).
- `native/src/host/host_main.cc` — early `--no-cef`/`--ui-harness` scan, CEF gating + positive print, `--ui-harness` mode.
- `native/src/host/host_bindings.cc` — `font_create`/`font_measure`/`ui_render`/`ui_should_close` bindings, `g_font_service`/`g_ui_quad_pass` globals, `cef_disabled` module attr.

**Python:**
- `engine/renderer.py` — facade wrappers `font_create`, `font_measure`, `ui_render`, `ui_should_close`.
- `engine/appc/tg_ui/managers.py` — `TGFontManager.CreateFontGroup` native wiring; `TGFontGroup.native_handle`/`GetStringWidth`; `TGFontHandle.GetStringWidth` proxy.
- `engine/appc/tg_ui/widgets.py` — `TGParagraph.SetFont`/`GetFontGroup`; `TGIconGroup.SetSpaceWidth`/`SetHorizontalSpacing`.
- `engine/ui_harness.py` — throwaway harness entry (`run()` + `walk_paragraph`).

**Assets / CMake wiring:**
- `native/assets/fonts/Antonio-Regular.ttf` (+ `Antonio-OFL.txt`) — copied from `native/assets/ui-cef/fonts/`.
- `native/CMakeLists.txt` — FreeType FetchContent; `add_subdirectory(src/text)`.
- `native/tests/CMakeLists.txt` — `add_subdirectory(text)`.
- `native/src/host/CMakeLists.txt` — add `cef_disabled.cc` to `HOST_BINDINGS_SOURCES`; add `text` to both link lines.
- `native/src/renderer/CMakeLists.txt` — `embed_shader` for `ui_quad`; add `ui_quad_pass.cc`.

**Tests (pytest):**
- `tests/unit/test_font_bindings.py`, `tests/unit/test_tg_font_proxy.py`, `tests/unit/test_ui_harness_walk.py`.

---

## Task 1: Vendor FreeType + `text` library skeleton

**Files:**
- Modify: `native/CMakeLists.txt` (FetchContent block after line 59; `add_subdirectory(src/text)` after line 138)
- Create: `native/src/text/CMakeLists.txt`
- Create: `native/src/text/include/text/font_service.h`
- Create: `native/src/text/src/font_service.cc`
- Create: `native/tests/text/CMakeLists.txt`
- Create: `native/tests/text/font_service_test.cc`
- Modify: `native/tests/CMakeLists.txt` (add `add_subdirectory(text)` after line 69)

**Interfaces:**
- Produces: `dauntless::text::FontService` with `bool ok() const` (FreeType initialised); CMake targets `text` (lib) and `text_tests` (ctest suite `FontServiceTest.*`).

- [ ] **Step 1: Write the failing test**

Create `native/tests/text/font_service_test.cc`:
```cpp
#include <gtest/gtest.h>
#include "text/font_service.h"

TEST(FontServiceTest, ConstructsWithFreeTypeInitialised) {
    dauntless::text::FontService svc;
    EXPECT_TRUE(svc.ok());
}
```

- [ ] **Step 2: Add FreeType + the `text` lib + test wiring**

In `native/CMakeLists.txt`, immediately after the OpenAL `FetchContent_MakeAvailable(openal_soft)` (line 59), add:
```cmake
# FreeType for native text rasterization (native font backend, Spec 1).
# Built bare — no HarfBuzz/PNG/zlib/bzip2/brotli — to stay self-contained and
# avoid the FreeType<->HarfBuzz build cycle.
set(FT_DISABLE_HARFBUZZ ON CACHE BOOL "" FORCE)
set(FT_DISABLE_PNG      ON CACHE BOOL "" FORCE)
set(FT_DISABLE_ZLIB     ON CACHE BOOL "" FORCE)
set(FT_DISABLE_BZIP2    ON CACHE BOOL "" FORCE)
set(FT_DISABLE_BROTLI   ON CACHE BOOL "" FORCE)
FetchContent_Declare(
    freetype
    GIT_REPOSITORY https://github.com/freetype/freetype.git
    GIT_TAG        VER-2-13-3
)
FetchContent_MakeAvailable(freetype)
```

In `native/CMakeLists.txt`, after `add_subdirectory(src/assets)` (line 138), add:
```cmake
add_subdirectory(src/text)
```

Create `native/src/text/CMakeLists.txt`:
```cmake
add_library(text STATIC
    src/font_service.cc
)
target_include_directories(text PUBLIC include)
target_compile_features(text PUBLIC cxx_std_20)
target_link_libraries(text PUBLIC freetype)
```

Create `native/src/text/include/text/font_service.h`:
```cpp
// native/src/text/include/text/font_service.h
//
// CPU-only FreeType text backend: face loading, glyph rasterization into a
// fixed R8 atlas, and LTR shaping/measurement. No GL — unit-testable headless.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace dauntless::text {

// One positioned glyph: destination rect in pixels (top-left origin) and the
// source rect in the atlas as normalized UVs.
struct GlyphQuad {
    float dst_x = 0.0f, dst_y = 0.0f, dst_w = 0.0f, dst_h = 0.0f;
    float u0 = 0.0f, v0 = 0.0f, u1 = 0.0f, v1 = 0.0f;
};

// The CPU glyph atlas. Fixed size for Spec 1 (no resize); `version` bumps each
// time new glyphs are rasterized so the GL side knows to re-upload.
struct Atlas {
    int width = 0;
    int height = 0;
    std::uint32_t version = 0;
    std::vector<std::uint8_t> pixels;  // R8 coverage, width*height bytes
};

class FontService {
public:
    FontService();
    ~FontService();
    FontService(const FontService&) = delete;
    FontService& operator=(const FontService&) = delete;

    // True if FreeType initialised.
    bool ok() const;

    // Load `font_path` at `size_px`; returns a handle (>=0) or -1 on failure.
    // Cached by (path, size_px).
    int create_font(const std::string& font_path, int size_px);

    // Shape `text` (LTR, '\n' newlines) at the origin into positioned quads.
    // Rasterizes+caches any missing glyphs into the atlas.
    std::vector<GlyphQuad> shape(int handle, const std::string& text);

    // Bounding box of shaped `text` in pixels.
    void measure(int handle, const std::string& text, float* out_w, float* out_h);

    // Pixel line height for `handle` (0 if invalid).
    float line_height(int handle) const;

    const Atlas& atlas() const;

private:
    struct Impl;
    Impl* impl_;
};

}  // namespace dauntless::text
```

Create `native/src/text/src/font_service.cc`:
```cpp
// native/src/text/src/font_service.cc
#include "text/font_service.h"

#include <ft2build.h>
#include FT_FREETYPE_H

namespace dauntless::text {

struct FontService::Impl {
    FT_Library lib = nullptr;
    bool ready = false;
    Atlas atlas;
};

FontService::FontService() : impl_(new Impl) {
    if (FT_Init_FreeType(&impl_->lib) == 0) {
        impl_->ready = true;
    }
    impl_->atlas.width = 512;
    impl_->atlas.height = 512;
    impl_->atlas.pixels.assign(512 * 512, 0);
}

FontService::~FontService() {
    if (impl_->lib) FT_Done_FreeType(impl_->lib);
    delete impl_;
}

bool FontService::ok() const { return impl_->ready; }

int FontService::create_font(const std::string&, int) { return -1; }  // Task 2
std::vector<GlyphQuad> FontService::shape(int, const std::string&) { return {}; }  // Task 3/4
void FontService::measure(int, const std::string&, float* w, float* h) {  // Task 4
    if (w) *w = 0.0f;
    if (h) *h = 0.0f;
}
float FontService::line_height(int) const { return 0.0f; }  // Task 2
const Atlas& FontService::atlas() const { return impl_->atlas; }

}  // namespace dauntless::text
```

Create `native/tests/text/CMakeLists.txt`:
```cmake
add_executable(text_tests
    font_service_test.cc
)
target_link_libraries(text_tests PRIVATE text GTest::gtest_main)
target_compile_definitions(text_tests PRIVATE
    OPEN_STBC_PROJECT_ROOT="${CMAKE_SOURCE_DIR}")
gtest_discover_tests(text_tests)
```

In `native/tests/CMakeLists.txt`, after `add_subdirectory(voxel)` (line 69), add:
```cmake
add_subdirectory(text)
```

- [ ] **Step 3: Reconfigure, build, run the test — expect PASS**

Run:
```bash
cmake -B build -S . && cmake --build build -j --target text_tests
ctest --test-dir build -R 'FontServiceTest.ConstructsWithFreeTypeInitialised' --output-on-failure
```
Expected: 1 test, PASS. (First configure fetches FreeType — allow extra time.)

- [ ] **Step 4: Commit**

```bash
git add native/CMakeLists.txt native/src/text native/tests/text native/tests/CMakeLists.txt
git commit -m "feat(text): vendor FreeType + text library skeleton"
```

---

## Task 2: Copy Antonio + FontService face load & metrics

**Files:**
- Create: `native/assets/fonts/Antonio-Regular.ttf` (copy), `native/assets/fonts/Antonio-OFL.txt` (copy)
- Modify: `native/src/text/src/font_service.cc` (`create_font`, `line_height`)
- Test: `native/tests/text/font_service_test.cc`

**Interfaces:**
- Consumes: `FontService` from Task 1.
- Produces: `create_font(path, size_px) -> int` (valid handle for a real TTF); `line_height(handle) -> float > 0`.

- [ ] **Step 1: Copy the font asset**

Run:
```bash
mkdir -p native/assets/fonts
cp native/assets/ui-cef/fonts/Antonio-Regular.ttf native/assets/fonts/Antonio-Regular.ttf
cp native/assets/ui-cef/THIRD_PARTY/Antonio-OFL.txt native/assets/fonts/Antonio-OFL.txt
```

- [ ] **Step 2: Write the failing test**

Append to `native/tests/text/font_service_test.cc`:
```cpp
#include <string>
static std::string antonio_path() {
    return std::string(OPEN_STBC_PROJECT_ROOT) + "/native/assets/fonts/Antonio-Regular.ttf";
}

TEST(FontServiceTest, CreateFontReturnsHandleAndPositiveLineHeight) {
    dauntless::text::FontService svc;
    int h = svc.create_font(antonio_path(), 18);
    ASSERT_GE(h, 0);
    EXPECT_GT(svc.line_height(h), 0.0f);
}

TEST(FontServiceTest, CreateFontFailsForMissingFile) {
    dauntless::text::FontService svc;
    EXPECT_LT(svc.create_font("/no/such/font.ttf", 18), 0);
}
```

- [ ] **Step 3: Run the test — expect FAIL**

Run:
```bash
cmake --build build -j --target text_tests
ctest --test-dir build -R 'FontServiceTest.CreateFontReturnsHandleAndPositiveLineHeight' --output-on-failure
```
Expected: FAIL (`create_font` returns -1, `line_height` is 0).

- [ ] **Step 4: Implement face load + metrics**

In `native/src/text/src/font_service.cc`, add includes and a face table to `Impl`, and replace `create_font`/`line_height`.

Add under the existing includes:
```cpp
#include <map>
#include <utility>
```

Replace `struct FontService::Impl { ... };` with:
```cpp
struct Face {
    FT_Face ft = nullptr;
    int size_px = 0;
};

struct FontService::Impl {
    FT_Library lib = nullptr;
    bool ready = false;
    Atlas atlas;
    std::vector<Face> faces;                       // index == handle
    std::map<std::pair<std::string,int>, int> by_key;
    // Atlas shelf-packer cursor.
    int cursor_x = 0, cursor_y = 0, shelf_h = 0;
    // Per-(handle,codepoint) cached glyph placement.
    struct GlyphInfo {
        int ax = 0, ay = 0;        // atlas top-left (px)
        int w = 0, h = 0;          // bitmap size (px)
        int bearing_x = 0, bearing_y = 0;
        float advance = 0.0f;      // pen advance (px)
        bool ok = false;
    };
    std::map<std::pair<int,std::uint32_t>, GlyphInfo> glyphs;
};
```

Replace `create_font` and `line_height`:
```cpp
int FontService::create_font(const std::string& path, int size_px) {
    if (!impl_->ready || size_px <= 0) return -1;
    auto key = std::make_pair(path, size_px);
    auto it = impl_->by_key.find(key);
    if (it != impl_->by_key.end()) return it->second;

    FT_Face ft = nullptr;
    if (FT_New_Face(impl_->lib, path.c_str(), 0, &ft) != 0) return -1;
    if (FT_Set_Pixel_Sizes(ft, 0, static_cast<FT_UInt>(size_px)) != 0) {
        FT_Done_Face(ft);
        return -1;
    }
    int handle = static_cast<int>(impl_->faces.size());
    impl_->faces.push_back(Face{ft, size_px});
    impl_->by_key[key] = handle;
    return handle;
}

float FontService::line_height(int handle) const {
    if (handle < 0 || handle >= static_cast<int>(impl_->faces.size())) return 0.0f;
    FT_Face ft = impl_->faces[handle].ft;
    // 26.6 fixed point → pixels.
    return static_cast<float>(ft->size->metrics.height) / 64.0f;
}
```

Also update the destructor to free faces:
```cpp
FontService::~FontService() {
    for (auto& f : impl_->faces) if (f.ft) FT_Done_Face(f.ft);
    if (impl_->lib) FT_Done_FreeType(impl_->lib);
    delete impl_;
}
```

- [ ] **Step 5: Run the tests — expect PASS**

Run:
```bash
cmake --build build -j --target text_tests
ctest --test-dir build -R 'FontServiceTest' --output-on-failure
```
Expected: all `FontServiceTest.*` PASS.

- [ ] **Step 6: Commit**

```bash
git add native/assets/fonts native/src/text/src/font_service.cc native/tests/text/font_service_test.cc
git commit -m "feat(text): load Antonio face + line-height metric"
```

---

## Task 3: Glyph rasterization + shelf-packed R8 atlas

**Files:**
- Modify: `native/src/text/include/text/font_service.h` (private `ensure_glyph` declaration)
- Modify: `native/src/text/src/font_service.cc` (glyph raster member + `shape`)
- Test: `native/tests/text/font_service_test.cc`

**Interfaces:**
- Consumes: `create_font`, the `Impl::GlyphInfo` cache/atlas from Task 2.
- Produces: private member `void ensure_glyph(int handle, std::uint32_t cp)` that rasterizes into `Impl::atlas`, bumps `atlas.version`, and caches placement in `Impl::glyphs`. `shape()` reads back the cached `GlyphInfo`. `atlas().version` increases when new glyphs are added. (`ensure_glyph` is a **member** — a free function cannot name the private nested `FontService::Impl`.)

- [ ] **Step 1: Write the failing test**

Append to `native/tests/text/font_service_test.cc`:
```cpp
TEST(FontServiceTest, ShapingRasterizesGlyphsIntoAtlas) {
    dauntless::text::FontService svc;
    int h = svc.create_font(antonio_path(), 24);
    ASSERT_GE(h, 0);
    std::uint32_t v0 = svc.atlas().version;
    auto quads = svc.shape(h, "AB");
    ASSERT_EQ(quads.size(), 2u);
    // Each glyph has a non-empty destination rect.
    EXPECT_GT(quads[0].dst_w, 0.0f);
    EXPECT_GT(quads[1].dst_w, 0.0f);
    // The two glyphs occupy disjoint atlas UV columns (B is to the right of A).
    EXPECT_NE(quads[0].u0, quads[1].u0);
    // Atlas grew (new glyphs uploaded).
    EXPECT_GT(svc.atlas().version, v0);
    // Some coverage was written.
    const auto& px = svc.atlas().pixels;
    std::uint32_t sum = 0;
    for (auto b : px) sum += b;
    EXPECT_GT(sum, 0u);
}
```

- [ ] **Step 2: Run the test — expect FAIL**

Run:
```bash
cmake --build build -j --target text_tests
ctest --test-dir build -R 'FontServiceTest.ShapingRasterizesGlyphsIntoAtlas' --output-on-failure
```
Expected: FAIL (`shape` returns empty).

- [ ] **Step 3: Implement glyph raster + shelf packing + `shape`**

In `native/src/text/include/text/font_service.h`, add a private member declaration to the `private:` section (after `Impl* impl_;`):
```cpp
    void ensure_glyph(int handle, std::uint32_t cp);  // rasterize+cache into the atlas
```

In `native/src/text/src/font_service.cc`, add the padding constant, the `ensure_glyph` **member** (not a free function — it must name the private nested `Impl` types), and implement `shape`. Add above `FontService::shape`:
```cpp
namespace {
constexpr int kPad = 1;
}  // namespace

void FontService::ensure_glyph(int handle, std::uint32_t cp) {
    auto key = std::make_pair(handle, cp);
    if (impl_->glyphs.count(key)) return;

    Impl::GlyphInfo gi;
    FT_Face ft = impl_->faces[handle].ft;
    if (FT_Load_Char(ft, cp, FT_LOAD_RENDER) == 0) {
        FT_GlyphSlot g = ft->glyph;
        const int gw = static_cast<int>(g->bitmap.width);
        const int gh = static_cast<int>(g->bitmap.rows);
        gi.w = gw;
        gi.h = gh;
        gi.bearing_x = g->bitmap_left;
        gi.bearing_y = g->bitmap_top;
        gi.advance = static_cast<float>(g->advance.x) / 64.0f;

        if (gw > 0 && gh > 0) {
            Atlas& at = impl_->atlas;
            if (impl_->cursor_x + gw + kPad > at.width) {
                impl_->cursor_x = 0;
                impl_->cursor_y += impl_->shelf_h + kPad;
                impl_->shelf_h = 0;
            }
            if (impl_->cursor_y + gh + kPad <= at.height) {
                const int ox = impl_->cursor_x, oy = impl_->cursor_y;
                for (int row = 0; row < gh; ++row) {
                    const unsigned char* src = g->bitmap.buffer + row * g->bitmap.pitch;
                    std::uint8_t* dst = at.pixels.data() + (oy + row) * at.width + ox;
                    for (int col = 0; col < gw; ++col) dst[col] = src[col];
                }
                gi.ax = ox;
                gi.ay = oy;
                gi.ok = true;
                impl_->cursor_x += gw + kPad;
                if (gh > impl_->shelf_h) impl_->shelf_h = gh;
                at.version += 1;
            }
        } else {
            gi.ok = true;  // whitespace: no bitmap, valid advance
        }
    }
    impl_->glyphs.emplace(key, gi);
}

std::vector<GlyphQuad> FontService::shape(int handle, const std::string& text) {
    std::vector<GlyphQuad> out;
    if (handle < 0 || handle >= static_cast<int>(impl_->faces.size())) return out;
    FT_Face ft = impl_->faces[handle].ft;
    const float lh = line_height(handle);
    const float aw = static_cast<float>(impl_->atlas.width);
    const float ah = static_cast<float>(impl_->atlas.height);
    float pen_x = 0.0f, pen_y = 0.0f;
    const float ascender = static_cast<float>(ft->size->metrics.ascender) / 64.0f;
    std::uint32_t prev = 0;

    for (unsigned char ch : text) {
        if (ch == '\n') { pen_x = 0.0f; pen_y += lh; prev = 0; continue; }
        std::uint32_t cp = ch;
        ensure_glyph(handle, cp);
        const Impl::GlyphInfo& gi = impl_->glyphs.at(std::make_pair(handle, cp));
        // Kerning (advance-only; may be 0 for GPOS-only fonts).
        if (prev && FT_HAS_KERNING(ft)) {
            FT_Vector k;
            FT_Get_Kerning(ft, FT_Get_Char_Index(ft, prev),
                           FT_Get_Char_Index(ft, cp), FT_KERNING_DEFAULT, &k);
            pen_x += static_cast<float>(k.x) / 64.0f;
        }
        if (gi.ok && gi.w > 0 && gi.h > 0) {
            GlyphQuad q;
            q.dst_x = pen_x + static_cast<float>(gi.bearing_x);
            q.dst_y = pen_y + (ascender - static_cast<float>(gi.bearing_y));
            q.dst_w = static_cast<float>(gi.w);
            q.dst_h = static_cast<float>(gi.h);
            q.u0 = static_cast<float>(gi.ax) / aw;
            q.v0 = static_cast<float>(gi.ay) / ah;
            q.u1 = static_cast<float>(gi.ax + gi.w) / aw;
            q.v1 = static_cast<float>(gi.ay + gi.h) / ah;
            out.push_back(q);
        }
        pen_x += gi.advance;
        prev = cp;
    }
    return out;
}
```

Note: `Impl::GlyphInfo`, `Impl::atlas`, `Impl::faces`, `Impl::glyphs`, and the shelf cursor are all private nested members defined in Task 2's `Impl`; `ensure_glyph`/`shape`/`measure` are members of `FontService`, so they can name them. A free helper could not.

- [ ] **Step 4: Run the test — expect PASS**

Run:
```bash
cmake --build build -j --target text_tests
ctest --test-dir build -R 'FontServiceTest' --output-on-failure
```
Expected: all `FontServiceTest.*` PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/text/src/font_service.cc native/tests/text/font_service_test.cc
git commit -m "feat(text): glyph rasterization into shelf-packed R8 atlas"
```

---

## Task 4: `measure()` with advances + newline height

**Files:**
- Modify: `native/src/text/src/font_service.cc` (`measure`)
- Test: `native/tests/text/font_service_test.cc`

**Interfaces:**
- Consumes: `shape` from Task 3.
- Produces: `measure(handle, text, &w, &h)` — width = max pen extent (px), height = line count × line height.

- [ ] **Step 1: Write the failing test**

Append to `native/tests/text/font_service_test.cc`:
```cpp
TEST(FontServiceTest, MeasureGrowsWithLengthAndLines) {
    dauntless::text::FontService svc;
    int h = svc.create_font(antonio_path(), 20);
    ASSERT_GE(h, 0);
    float w1 = 0, h1 = 0, w2 = 0, h2 = 0;
    svc.measure(h, "A", &w1, &h1);
    svc.measure(h, "AA", &w2, &h2);
    EXPECT_GT(w1, 0.0f);
    EXPECT_GT(w2, w1);                       // longer string is wider
    EXPECT_NEAR(h1, svc.line_height(h), 0.5f);
    float wl = 0, hl = 0;
    svc.measure(h, "A\nA", &wl, &hl);
    EXPECT_NEAR(hl, 2.0f * svc.line_height(h), 0.5f);  // two lines tall
}
```

- [ ] **Step 2: Run the test — expect FAIL**

Run:
```bash
cmake --build build -j --target text_tests
ctest --test-dir build -R 'FontServiceTest.MeasureGrowsWithLengthAndLines' --output-on-failure
```
Expected: FAIL (`measure` returns 0,0).

- [ ] **Step 3: Implement `measure`**

Replace `FontService::measure` in `native/src/text/src/font_service.cc`:
```cpp
void FontService::measure(int handle, const std::string& text, float* out_w, float* out_h) {
    float w = 0.0f, h = 0.0f;
    if (handle >= 0 && handle < static_cast<int>(impl_->faces.size())) {
        FT_Face ft = impl_->faces[handle].ft;
        const float lh = line_height(handle);
        int lines = 1;
        float pen_x = 0.0f, max_x = 0.0f;
        std::uint32_t prev = 0;
        for (unsigned char ch : text) {
            if (ch == '\n') { if (pen_x > max_x) max_x = pen_x; pen_x = 0.0f; ++lines; prev = 0; continue; }
            ensure_glyph(handle, ch);
            const Impl::GlyphInfo& gi = impl_->glyphs.at(std::make_pair(handle, static_cast<std::uint32_t>(ch)));
            if (prev && FT_HAS_KERNING(ft)) {
                FT_Vector k;
                FT_Get_Kerning(ft, FT_Get_Char_Index(ft, prev),
                               FT_Get_Char_Index(ft, ch), FT_KERNING_DEFAULT, &k);
                pen_x += static_cast<float>(k.x) / 64.0f;
            }
            pen_x += gi.advance;
            prev = ch;
        }
        if (pen_x > max_x) max_x = pen_x;
        w = max_x;
        h = static_cast<float>(lines) * lh;
    }
    if (out_w) *out_w = w;
    if (out_h) *out_h = h;
}
```

- [ ] **Step 4: Run the tests — expect PASS**

Run:
```bash
cmake --build build -j --target text_tests
ctest --test-dir build -R 'FontServiceTest' --output-on-failure
```
Expected: all `FontServiceTest.*` PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/text/src/font_service.cc native/tests/text/font_service_test.cc
git commit -m "feat(text): measure() with advances, kerning, multi-line height"
```

---

## Task 5: `UiQuadPass` + shaders + pipeline wiring (headless GL readback)

**Files:**
- Create: `native/src/renderer/shaders/ui_quad.vert`, `native/src/renderer/shaders/ui_quad.frag`
- Create: `native/src/renderer/include/renderer/ui_quad_pass.h`, `native/src/renderer/ui_quad_pass.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (embed_shader lines + `ui_quad_pass.cc`)
- Modify: `native/src/renderer/include/renderer/pipeline.h` (accessor + member)
- Modify: `native/src/renderer/pipeline.cc` (include + construct)
- Modify: `native/tests/renderer/CMakeLists.txt` (add test source)
- Test: `native/tests/renderer/ui_quad_pass_test.cc`

**Interfaces:**
- Consumes: `renderer::Pipeline`, `renderer::Shader`, `renderer::Window` (offscreen).
- Produces: `renderer::UiGlyphQuad { float x,y,w,h,u0,v0,u1,v1,r,g,b,a; }`; `renderer::UiQuadPass` with `void set_atlas(const std::uint8_t* px, int w, int h)` and `void render(const std::vector<UiGlyphQuad>&, int vw, int vh, Pipeline&)`; `Pipeline::ui_quad_shader()`.

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/ui_quad_pass_test.cc`:
```cpp
#include <gtest/gtest.h>
#include <glad/gl.h>
#include <memory>
#include <vector>
#include "renderer/window.h"
#include "renderer/pipeline.h"
#include "renderer/ui_quad_pass.h"

class UiQuadPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64, 64, "ui-quad-test", false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
        p = std::make_unique<renderer::Pipeline>();
    }
};

TEST_F(UiQuadPassTest, DrawsWhiteQuadFromFullCoverageAtlas) {
    renderer::UiQuadPass pass;
    // 4x4 fully-opaque R8 atlas.
    std::vector<std::uint8_t> atlas(4 * 4, 255);
    pass.set_atlas(atlas.data(), 4, 4);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::UiGlyphQuad q{16, 16, 32, 32, 0, 0, 1, 1, 1, 1, 1, 1};
    pass.render({q}, 64, 64, *p);

    unsigned char px[4] = {0, 0, 0, 0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    EXPECT_GT(px[0], 200);
    EXPECT_GT(px[1], 200);
    EXPECT_GT(px[2], 200);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}
```

- [ ] **Step 2: Add shaders, pass, pipeline wiring, CMake**

Create `native/src/renderer/shaders/ui_quad.vert`:
```glsl
#version 410 core
layout(location = 0) in vec2 corner;   // unit quad, [0,1]
uniform vec4 u_rect_px;                 // x, y, w, h (top-left origin, px)
uniform vec4 u_uv;                      // u0, v0, u1, v1
uniform vec2 u_viewport;                // vw, vh (px)
out vec2 v_uv;
void main() {
    vec2 px = u_rect_px.xy + corner * u_rect_px.zw;
    vec2 ndc = vec2(px.x / u_viewport.x * 2.0 - 1.0,
                    1.0 - px.y / u_viewport.y * 2.0);
    v_uv = mix(u_uv.xy, u_uv.zw, corner);
    gl_Position = vec4(ndc, 0.0, 1.0);
}
```

Create `native/src/renderer/shaders/ui_quad.frag`:
```glsl
#version 410 core
in vec2 v_uv;
uniform sampler2D u_atlas;
uniform vec4 u_tint;
out vec4 frag;
void main() {
    float a = texture(u_atlas, v_uv).r;
    if (a < 0.01) discard;
    frag = vec4(u_tint.rgb, u_tint.a * a);
}
```

Create `native/src/renderer/include/renderer/ui_quad_pass.h`:
```cpp
// native/src/renderer/include/renderer/ui_quad_pass.h
//
// Screen-space textured-quad pass for native UI: draws R8-atlas glyph quads in
// pixel coordinates (top-left origin) to the currently-bound framebuffer.
#pragma once

#include <cstdint>
#include <vector>

namespace renderer {

class Pipeline;

struct UiGlyphQuad {
    float x = 0, y = 0, w = 0, h = 0;         // destination rect, pixels
    float u0 = 0, v0 = 0, u1 = 0, v1 = 0;     // atlas UVs [0,1]
    float r = 1, g = 1, b = 1, a = 1;         // tint
};

class UiQuadPass {
public:
    UiQuadPass() = default;
    ~UiQuadPass();
    UiQuadPass(const UiQuadPass&) = delete;
    UiQuadPass& operator=(const UiQuadPass&) = delete;

    // Upload/replace the R8 coverage atlas.
    void set_atlas(const std::uint8_t* pixels, int width, int height);

    // Draw quads. The caller has bound the target FBO and cleared as desired.
    void render(const std::vector<UiGlyphQuad>& quads, int viewport_w, int viewport_h,
                Pipeline& pipeline);

private:
    void ensure_quad();
    unsigned int quad_vao_ = 0, quad_vbo_ = 0, atlas_tex_ = 0;
    int atlas_w_ = 0, atlas_h_ = 0;
};

}  // namespace renderer
```

Create `native/src/renderer/ui_quad_pass.cc`:
```cpp
// native/src/renderer/ui_quad_pass.cc
#include "renderer/ui_quad_pass.h"

#include <glad/gl.h>

#include "renderer/pipeline.h"
#include "renderer/shader.h"

namespace renderer {

UiQuadPass::~UiQuadPass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
    if (atlas_tex_) glDeleteTextures(1, &atlas_tex_);
}

void UiQuadPass::ensure_quad() {
    if (quad_vao_) return;
    const float verts[] = {
        0.0f, 0.0f, 1.0f, 0.0f, 1.0f, 1.0f,
        0.0f, 0.0f, 1.0f, 1.0f, 0.0f, 1.0f,
    };
    glGenVertexArrays(1, &quad_vao_);
    glGenBuffers(1, &quad_vbo_);
    glBindVertexArray(quad_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), (void*)0);
    glBindVertexArray(0);
}

void UiQuadPass::set_atlas(const std::uint8_t* pixels, int width, int height) {
    if (!atlas_tex_) glGenTextures(1, &atlas_tex_);
    glBindTexture(GL_TEXTURE_2D, atlas_tex_);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, width, height, 0, GL_RED, GL_UNSIGNED_BYTE, pixels);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    atlas_w_ = width;
    atlas_h_ = height;
}

void UiQuadPass::render(const std::vector<UiGlyphQuad>& quads, int viewport_w, int viewport_h,
                        Pipeline& pipeline) {
    if (quads.empty() || !atlas_tex_) return;
    ensure_quad();

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);

    Shader& sh = pipeline.ui_quad_shader();
    sh.use();
    sh.set_vec2("u_viewport", glm::vec2((float)viewport_w, (float)viewport_h));
    sh.set_int("u_atlas", 0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, atlas_tex_);
    glBindVertexArray(quad_vao_);

    for (const auto& q : quads) {
        sh.set_vec4("u_rect_px", glm::vec4(q.x, q.y, q.w, q.h));
        sh.set_vec4("u_uv", glm::vec4(q.u0, q.v0, q.u1, q.v1));
        sh.set_vec4("u_tint", glm::vec4(q.r, q.g, q.b, q.a));
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    glBindVertexArray(0);
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_CULL_FACE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
```

In `native/src/renderer/CMakeLists.txt`, after the `target_reticle` embed lines (line 57), add:
```cmake
embed_shader(SHADER_UI_QUAD_VS shaders/ui_quad.vert ui_quad_vs)
embed_shader(SHADER_UI_QUAD_FS shaders/ui_quad.frag ui_quad_fs)
```
And in the `add_library(renderer STATIC ...)` list, after `target_reticle_pass.cc` (line 136), add:
```cmake
    ui_quad_pass.cc
```

In `native/src/renderer/include/renderer/pipeline.h`, after the `target_reticle_shader()` accessor (line 35) add:
```cpp
    Shader& ui_quad_shader() noexcept  { return *ui_quad_; }
```
And after the `target_reticle_` member (line 67) add:
```cpp
    std::unique_ptr<Shader> ui_quad_;
```

In `native/src/renderer/pipeline.cc`, after the target_reticle includes (line 47) add:
```cpp
#include "embedded_ui_quad_vs.h"
#include "embedded_ui_quad_fs.h"
```
And after the `target_reticle_ = ...` construction (line 89) add:
```cpp
    ui_quad_ = std::make_unique<Shader>(shader_src::ui_quad_vs, shader_src::ui_quad_fs);
```

In `native/tests/renderer/CMakeLists.txt`, add to the `add_executable(renderer_tests ...)` list (after `target_reticle` tests — anywhere in the list is fine):
```cmake
    ui_quad_pass_test.cc
```

- [ ] **Step 3: Reconfigure, build, run — expect PASS**

Run:
```bash
cmake -B build -S . && cmake --build build -j --target renderer_tests
ctest --test-dir build -R 'UiQuadPassTest' --output-on-failure
```
Expected: `UiQuadPassTest.DrawsWhiteQuadFromFullCoverageAtlas` PASS (or SKIP if no GL — then run once locally where GL is available).

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/shaders/ui_quad.vert native/src/renderer/shaders/ui_quad.frag \
        native/src/renderer/include/renderer/ui_quad_pass.h native/src/renderer/ui_quad_pass.cc \
        native/src/renderer/include/renderer/pipeline.h native/src/renderer/pipeline.cc \
        native/src/renderer/CMakeLists.txt native/tests/renderer/CMakeLists.txt \
        native/tests/renderer/ui_quad_pass_test.cc
git commit -m "feat(renderer): screen-space UiQuadPass drawing R8 atlas glyphs"
```

---

## Task 6: `font_create` / `font_measure` bindings + facade wrappers

**Files:**
- Modify: `native/src/host/host_bindings.cc` (globals + two `m.def`s)
- Modify: `native/src/host/CMakeLists.txt` (add `text` to both link lines)
- Modify: `engine/renderer.py` (`font_create`, `font_measure` wrappers + optional manifest)
- Test: `tests/unit/test_font_bindings.py`

**Interfaces:**
- Consumes: `dauntless::text::FontService` (Task 4).
- Produces: `_dauntless_host.font_create(path:str, size_px:int) -> int`; `_dauntless_host.font_measure(handle:int, text:str) -> (w:float, h:float)`; `engine.renderer.font_create` / `font_measure` wrappers.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_font_bindings.py`:
```python
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "build" / "python"))
_ANTONIO = str(_ROOT / "native" / "assets" / "fonts" / "Antonio-Regular.ttf")


def test_font_create_and_measure_via_module():
    _h = pytest.importorskip("_dauntless_host")
    handle = _h.font_create(_ANTONIO, 18)
    assert handle >= 0
    w1, h1 = _h.font_measure(handle, "A")
    w2, _ = _h.font_measure(handle, "AA")
    assert w1 > 0 and h1 > 0
    assert w2 > w1


def test_renderer_font_wrappers_use_native(monkeypatch):
    from engine import renderer

    class _Fake:
        def font_create(self, path, px):
            return 7
        def font_measure(self, handle, text):
            return (float(len(text)) * 5.0, 12.0)

    monkeypatch.setattr(renderer, "_h", _Fake())
    assert renderer.font_create("x.ttf", 12) == 7
    assert renderer.font_measure(7, "abc") == (15.0, 12.0)
```

- [ ] **Step 2: Run the tests — expect FAIL**

Run:
```bash
uv run pytest tests/unit/test_font_bindings.py -v
```
Expected: `test_renderer_font_wrappers_use_native` FAILs (`renderer.font_create` missing); the module test SKIPs until the binding exists + module rebuilt.

- [ ] **Step 3: Add the bindings + facade + link the `text` lib**

In `native/src/host/CMakeLists.txt`, add `text` to BOTH link lines. Line 13 becomes:
```cmake
target_link_libraries(_dauntless_host PRIVATE renderer scenegraph assets dauntless_audio text)
```
And the `dauntless` block (lines 27-35) gains `text`:
```cmake
target_link_libraries(dauntless
    PRIVATE
        Python3::Python
        pybind11::embed
        renderer
        scenegraph
        assets
        dauntless_audio
        text
)
```

In `native/src/host/host_bindings.cc`, add the include near the other renderer/text includes (top of file, alongside existing `#include` lines):
```cpp
#include "text/font_service.h"
```
Add a global + accessor near the other pass globals (around line 226):
```cpp
std::unique_ptr<dauntless::text::FontService> g_font_service;
static dauntless::text::FontService& font_service() {
    if (!g_font_service) g_font_service = std::make_unique<dauntless::text::FontService>();
    return *g_font_service;
}
```
Inside `PYBIND11_MODULE`, near the other `m.def(...)` render setters (e.g. after `set_target_reticle` at ~line 2443), add:
```cpp
    m.def("font_create",
          [](const std::string& path, int size_px) {
              return font_service().create_font(path, size_px);
          },
          py::arg("path"), py::arg("size_px"),
          "Load a font at a pixel size; returns a handle (>=0) or -1.");

    m.def("font_measure",
          [](int handle, const std::string& text) {
              float w = 0.0f, h = 0.0f;
              font_service().measure(handle, text, &w, &h);
              return py::make_tuple(w, h);
          },
          py::arg("handle"), py::arg("text"),
          "Measure text; returns (width_px, height_px).");
```

In `engine/renderer.py`, add wrappers (near the `set_target_reticle` optional wrappers) and register them in the `_OPTIONAL_BINDINGS` manifest:
```python
def font_create(path: str, size_px: int) -> int:
    """Load a font at a pixel size; returns a native handle (>=0), or -1.

    Returns -1 when the host binding is unavailable (headless tests).
    """
    fn = getattr(_h, "font_create", None)
    if fn is None:
        return -1
    return fn(path, size_px)


def font_measure(handle: int, text: str):
    """Measure text via the native font backend; returns (width_px, height_px).

    Returns (0.0, 0.0) when the host binding is unavailable.
    """
    fn = getattr(_h, "font_measure", None)
    if fn is None:
        return (0.0, 0.0)
    return fn(handle, text)
```
Add `"font_create"` and `"font_measure"` to the `_OPTIONAL_BINDINGS` list/manifest (near line 80).

- [ ] **Step 4: Reconfigure, rebuild the module, run tests — expect PASS**

Run:
```bash
cmake -B build -S . && cmake --build build -j --target _dauntless_host
uv run pytest tests/unit/test_font_bindings.py -v
```
Expected: both tests PASS (module test now imports the freshly built `_dauntless_host`).

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc native/src/host/CMakeLists.txt \
        engine/renderer.py tests/unit/test_font_bindings.py
git commit -m "feat(host): font_create/font_measure bindings + renderer facade"
```

---

## Task 7: Python `TGFontGroup`/`TGParagraph` proxies (interface preserved)

**Files:**
- Modify: `engine/appc/tg_ui/managers.py` (`TGFontManager.CreateFontGroup`, `TGFontGroup`, `TGFontHandle`)
- Modify: `engine/appc/tg_ui/widgets.py` (`TGParagraph.SetFont`/`GetFontGroup`; `TGIconGroup.SetSpaceWidth`/`SetHorizontalSpacing`)
- Test: `tests/unit/test_tg_font_proxy.py`

**Interfaces:**
- Consumes: `engine.renderer.font_create`/`font_measure` (Task 6).
- Produces: `TGFontGroup.native_handle() -> int | None`; `TGFontGroup.GetStringWidth(text) -> float`; `TGParagraph.GetFontGroup() -> TGFontGroup | None`; `TGParagraph.SetFont(group)` stores the group.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_tg_font_proxy.py`:
```python
import pytest

from engine.appc.tg_ui import managers as mgr
from engine.appc.tg_ui.widgets import TGParagraph


class _FakeRenderer:
    def __init__(self):
        self.created = []
    def font_create(self, path, px):
        self.created.append((path, px))
        return 42
    def font_measure(self, handle, text):
        return (float(len(text)) * 3.0, 10.0)


def test_create_font_group_binds_native_handle(monkeypatch):
    fake = _FakeRenderer()
    monkeypatch.setattr(mgr, "renderer", fake)
    group = mgr.g_kFontManager.CreateFontGroup("Crillee", 12.0)
    assert group.native_handle() == 42
    # BC family name mapped to the bundled Antonio TTF.
    assert fake.created and fake.created[0][0].endswith("Antonio-Regular.ttf")
    assert fake.created[0][1] == 12


def test_group_string_width_uses_native_measure(monkeypatch):
    fake = _FakeRenderer()
    monkeypatch.setattr(mgr, "renderer", fake)
    group = mgr.g_kFontManager.CreateFontGroup("Crillee", 12.0)
    assert group.GetStringWidth("abcd") == pytest.approx(12.0)  # 4 * 3.0 native


def test_group_string_width_falls_back_without_native(monkeypatch):
    class _NoBind:
        def font_create(self, path, px):
            return -1
        def font_measure(self, handle, text):
            return (0.0, 0.0)
    monkeypatch.setattr(mgr, "renderer", _NoBind())
    group = mgr.g_kFontManager.CreateFontGroup("Crillee", 10)
    # Fallback synthetic metric: 0.6 * size * len.
    assert group.GetStringWidth("ab") == pytest.approx(0.6 * 10 * 2)


def test_paragraph_setfont_stores_group():
    para = TGParagraph("hi")
    group = mgr.g_kFontManager.CreateFontGroup("Crillee", 12)
    para.SetFont(group)
    assert para.GetFontGroup() is group
```

- [ ] **Step 2: Run the tests — expect FAIL**

Run:
```bash
uv run pytest tests/unit/test_tg_font_proxy.py -v
```
Expected: FAIL (`native_handle`/`GetFontGroup` missing; `SetFont` no-op).

- [ ] **Step 3: Implement the proxies**

In `engine/appc/tg_ui/managers.py`, add the import at the top:
```python
from engine import renderer
```
Add a family→font-file map and resolve helper near the top of the module (after imports):
```python
import os as _os

# Licensing forces a substitution for BC's proprietary faces. Every BC family
# name resolves to the bundled OFL Antonio for now.
_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))))
_ANTONIO_PATH = _os.path.join(_PROJECT_ROOT, "native", "assets", "fonts", "Antonio-Regular.ttf")

def _resolve_font_path(family: str) -> str:
    return _ANTONIO_PATH  # all families → Antonio (Spec 1)
```
Extend `TGFontGroup` (currently `managers.py:25-35`) to carry a native handle and proxy width:
```python
class TGFontGroup(TGIconGroup):
    def __init__(self, family="", size=0):
        super().__init__("%s%d" % (family, int(size)))
        self._family = str(family)
        self._size = int(size)
        self._native_handle = None

    def GetFontName(self):
        return self._family

    def GetFontSize(self):
        return self._size

    def SetNativeHandle(self, handle):
        self._native_handle = handle if (handle is not None and handle >= 0) else None

    def native_handle(self):
        return self._native_handle

    def GetStringWidth(self, text):
        if self._native_handle is not None:
            w, _ = renderer.font_measure(self._native_handle, text)
            if w > 0.0:
                return w
        # Fallback synthetic metric (headless / no native backend).
        spacing = getattr(self, "_space_width_override", None)
        base = 0.6 * self._size * len(text)
        return base if spacing is None else base
```
Update `TGFontManager.CreateFontGroup` (currently `managers.py:61`) to bind the native handle:
```python
    def CreateFontGroup(self, family, size, *args):
        group = TGFontGroup(family, int(size))
        handle = renderer.font_create(_resolve_font_path(family), int(size))
        group.SetNativeHandle(handle)
        return group
```
Update `TGFontHandle.GetStringWidth` (currently `managers.py:9-22`, synthetic) to proxy through the manager's group when a native handle exists:
```python
    def GetStringWidth(self, text):
        group = g_kFontManager.GetFontGroup(self._family, self._size)
        if group is not None and group.native_handle() is not None:
            return group.GetStringWidth(text)
        return 0.6 * self._size * len(text)
```
(Keep `TGFontHandle.GetHeight` returning `float(self._size)`.)

In `engine/appc/tg_ui/widgets.py`, replace `TGParagraph.SetFont` (currently `widgets.py:235`, a no-op) and add a getter:
```python
    def SetFont(self, group=None, *args):
        # Store the font group so the native walker can resolve a handle.
        # Previously a no-op; the render-free tree discarded the font.
        self._font_group = group

    def GetFontGroup(self):
        return getattr(self, "_font_group", None)
```
Ensure `TGParagraph.__init__` initializes `self._font_group = None` (add the line in `__init__`, currently `widgets.py:189-196`).

Add real (additive) spacing setters to `TGIconGroup` (currently `widgets.py:239-273`) — the SDK calls these; our tree never defined them. They affect only the fallback metric:
```python
    def SetSpaceWidth(self, width, *args):
        self._space_width_override = float(width)

    def SetHorizontalSpacing(self, spacing, *args):
        self._h_spacing_override = float(spacing)
```

Document `TGIconGroup.SetIconLocation` (currently `widgets.py:259`) as a no-op under the native backend by prepending to its docstring/body a comment:
```python
        # NOTE: deletable under the native FreeType backend — the atlas is
        # dynamic, so baked per-glyph slots are ignored. Retained for SDK
        # call-site compatibility.
```

- [ ] **Step 4: Run the tests — expect PASS**

Run:
```bash
uv run pytest tests/unit/test_tg_font_proxy.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/tg_ui/managers.py engine/appc/tg_ui/widgets.py tests/unit/test_tg_font_proxy.py
git commit -m "feat(tg-ui): TGFontGroup/TGParagraph proxy to native font backend"
```

---

## Task 8: `--no-cef` flag + `--ui-harness` mode + CEF-absence guard

**Files:**
- Create: `native/src/host/cef_disabled.h`, `native/src/host/cef_disabled.cc`
- Modify: `native/src/host/CMakeLists.txt` (add `cef_disabled.cc` to `HOST_BINDINGS_SOURCES`)
- Modify: `native/src/host/host_main.cc` (early scan, CEF gating + positive print, `--ui-harness` mode)
- Modify: `native/src/host/host_bindings.cc` (`cef_disabled` module attr)
- Create: `engine/ui_harness.py` (stub `run()` returning 0)

**Interfaces:**
- Produces: `dauntless::is_cef_disabled()` / `set_cef_disabled(bool)`; the binary prints `CEF: framework not loaded (--no-cef)` and never `!!! CEF CONSTRUCTED` on `--ui-harness`; `_dauntless_host.cef_disabled` attr.

- [ ] **Step 1: Create the flag module + stub harness**

Create `native/src/host/cef_disabled.h`:
```cpp
// native/src/host/cef_disabled.h
//
// Process-global "CEF disabled" flag. Parsed from argv in host_main.cc before
// any CEF bootstrap; read by C++ and exposed to Python via the _dauntless_host
// `cef_disabled` attribute. Mirrors developer_mode.{h,cc}.
#pragma once

namespace dauntless {

bool is_cef_disabled();
void set_cef_disabled(bool disabled);

}  // namespace dauntless
```

Create `native/src/host/cef_disabled.cc`:
```cpp
// native/src/host/cef_disabled.cc
#include "cef_disabled.h"

namespace dauntless {

namespace {
bool g_cef_disabled = false;
}

bool is_cef_disabled() { return g_cef_disabled; }
void set_cef_disabled(bool disabled) { g_cef_disabled = disabled; }

}  // namespace dauntless
```

Create `engine/ui_harness.py`:
```python
"""Throwaway harness: native UI stack with CEF absent (Spec 1).

Launched via `./build/dauntless --ui-harness` (implies --no-cef). Task 8 ships a
stub that only proves the CEF-free launch path; Task 9 fills in the render loop.
"""


def run() -> int:
    print("[ui-harness] native UI harness starting (CEF absent)")
    return 0
```

In `native/src/host/CMakeLists.txt`, add `cef_disabled.cc` to `HOST_BINDINGS_SOURCES` (lines 5-8):
```cmake
set(HOST_BINDINGS_SOURCES
    host_bindings.cc
    developer_mode.cc
    cef_disabled.cc
)
```

- [ ] **Step 2: Wire the flag + mode + guard into host_main.cc**

In `native/src/host/host_main.cc`, add the include (after `#include "developer_mode.h"`, line 7):
```cpp
#include "cef_disabled.h"
```
Add a `run_ui_harness()` helper in the anonymous namespace (after `run_host_loop()`, line 87):
```cpp
int run_ui_harness() {
    PyObject* mod = PyImport_ImportModule("engine.ui_harness");
    if (!mod) { PyErr_Print(); return 1; }
    PyObject* fn = PyObject_GetAttrString(mod, "run");
    if (!fn) { PyErr_Print(); Py_DECREF(mod); return 1; }
    PyObject* result = PyObject_CallNoArgs(fn);
    Py_DECREF(fn);
    Py_DECREF(mod);
    if (!result) { PyErr_Print(); return 1; }
    int rc = 0;
    if (PyLong_Check(result)) rc = static_cast<int>(PyLong_AsLong(result));
    Py_DECREF(result);
    return rc;
}
```
At the very top of `main`, right after `if (argc < 1) return 1;` (line 92), add the early scan and positive print:
```cpp
    // Parse the CEF-disable flag before any CEF bootstrap. --ui-harness implies
    // it so the harness can never run with CEF alive.
    for (int i = 1; i < argc; ++i) {
        std::string a(argv[i]);
        if (a == "--no-cef" || a == "--ui-harness") {
            dauntless::set_cef_disabled(true);
            break;
        }
    }
    if (dauntless::is_cef_disabled()) {
        std::printf("CEF: framework not loaded (--no-cef)\n");
    }
```
Gate the CEF bootstrap block (lines 94-112) on the flag. Change the `#ifdef DAUNTLESS_ENABLE_CEF` body so both CEF calls are skipped when disabled:
```cpp
#ifdef DAUNTLESS_ENABLE_CEF
    if (!dauntless::is_cef_disabled()) {
        dauntless::ui_cef::install_macos_app();
        const int subprocess_rc = dauntless::ui_cef::dispatch_subprocess(argc, argv);
        if (subprocess_rc >= 0) return subprocess_rc;
    }
#endif
```
Add the `--ui-harness` mode branch in the mode dispatch (change the final `else` at lines 155-158):
```cpp
    } else if (mode == "--ui-harness") {
        rc = run_ui_harness();
    } else {
        // Default: run the visible ship gate via engine.host_loop.run().
        rc = run_host_loop();
    }
```

In `native/src/host/host_bindings.cc`, add the include (near `#include "developer_mode.h"`, line 79):
```cpp
#include "cef_disabled.h"
```
And in `PYBIND11_MODULE`, right after the `developer_mode` attr (line 1126), add:
```cpp
    // Process-global CEF-disabled flag. Set in host_main.cc from --no-cef /
    // --ui-harness. Lets Python assert the CEF-free launch path.
    m.attr("cef_disabled") = dauntless::is_cef_disabled();
```

- [ ] **Step 3: Reconfigure, rebuild the binary, run — expect CEF-absent evidence**

Run:
```bash
cmake -B build -S . && cmake --build build -j --target dauntless
./build/dauntless --ui-harness
```
Expected stdout contains both:
```
CEF: framework not loaded (--no-cef)
[ui-harness] native UI harness starting (CEF absent)
```
and does NOT contain `!!! CEF CONSTRUCTED`. Assert programmatically:
```bash
./build/dauntless --ui-harness 2>&1 | tee /tmp/harness_out.txt
grep -q "CEF: framework not loaded" /tmp/harness_out.txt && echo "POSITIVE-OK"
grep -q "CEF CONSTRUCTED" /tmp/harness_out.txt && echo "GUARD-TRIPPED (BAD)" || echo "GUARD-CLEAN"
```
Expected: `POSITIVE-OK` and `GUARD-CLEAN`.

- [ ] **Step 4: Commit**

```bash
git add native/src/host/cef_disabled.h native/src/host/cef_disabled.cc \
        native/src/host/CMakeLists.txt native/src/host/host_main.cc \
        native/src/host/host_bindings.cc engine/ui_harness.py
git commit -m "feat(host): --no-cef flag + --ui-harness mode, CEF never constructed"
```

---

## Task 9: `ui_render` / `ui_should_close` + full harness render loop

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`g_ui_quad_pass` global + init/shutdown + `ui_render`/`ui_should_close`)
- Modify: `engine/renderer.py` (`ui_render`, `ui_should_close` wrappers)
- Modify: `engine/ui_harness.py` (`walk_paragraph` + real `run()` loop)
- Test: `tests/unit/test_ui_harness_walk.py`

**Interfaces:**
- Consumes: `FontService` (`g_font_service`, Task 6), `UiQuadPass` (Task 5), font proxies (Task 7), `--ui-harness` mode (Task 8).
- Produces: `_dauntless_host.ui_render(draw_list)`, `_dauntless_host.ui_should_close() -> bool`; `engine.ui_harness.walk_paragraph(para, x, y) -> list[tuple]`.

- [ ] **Step 1: Write the failing test (pure Python — `walk_paragraph`)**

Create `tests/unit/test_ui_harness_walk.py`:
```python
from engine import ui_harness
from engine.appc.tg_ui.widgets import TGParagraph


class _Group:
    def __init__(self, handle):
        self._handle = handle
    def native_handle(self):
        return self._handle


def test_walk_paragraph_emits_text_run():
    para = TGParagraph("Hello")
    para.SetFont(_Group(handle=3))
    runs = ui_harness.walk_paragraph(para, 80, 300)
    assert len(runs) == 1
    kind, handle, x, y, text, rgba = runs[0]
    assert kind == "text"
    assert handle == 3
    assert (x, y) == (80.0, 300.0)
    assert text == "Hello"
    assert len(rgba) == 4


def test_walk_paragraph_empty_without_handle():
    para = TGParagraph("Hello")
    para.SetFont(_Group(handle=None))
    assert ui_harness.walk_paragraph(para, 0, 0) == []
```

- [ ] **Step 2: Run the test — expect FAIL**

Run:
```bash
uv run pytest tests/unit/test_ui_harness_walk.py -v
```
Expected: FAIL (`walk_paragraph` does not exist).

- [ ] **Step 3: Add the render bindings + facade + harness loop**

In `native/src/host/host_bindings.cc`, add the include (near the `text/font_service.h` include from Task 6):
```cpp
#include "renderer/ui_quad_pass.h"
```
Add a global near `g_target_reticle_pass` (line 226):
```cpp
std::unique_ptr<renderer::UiQuadPass> g_ui_quad_pass;
std::uint32_t g_ui_atlas_version = 0;
```
Instantiate in `init()` (after `g_target_reticle_pass = ...`, line 450):
```cpp
    g_ui_quad_pass = std::make_unique<renderer::UiQuadPass>();
```
Tear down in `shutdown()` (near `g_target_reticle_pass.reset();`, line 528):
```cpp
    g_ui_quad_pass.reset();
```
Add the bindings inside `PYBIND11_MODULE` (after `font_measure` from Task 6):
```cpp
    m.def("ui_should_close", []() {
        return g_window ? g_window->should_close() : true;
    }, "True if the harness window wants to close.");

    m.def("ui_render", [](py::list draw_list) {
        if (!g_window || !g_ui_quad_pass || !g_pipeline) return;
        int fw = 0, fh = 0;
        g_window->framebuffer_size(&fw, &fh);

        // Upload the glyph atlas if it grew since last frame.
        const auto& atlas = font_service().atlas();
        if (atlas.version != g_ui_atlas_version) {
            g_ui_quad_pass->set_atlas(atlas.pixels.data(), atlas.width, atlas.height);
            g_ui_atlas_version = atlas.version;
        }

        // Build glyph quads from the text runs.
        std::vector<renderer::UiGlyphQuad> quads;
        for (auto item : draw_list) {
            auto t = item.cast<py::tuple>();
            std::string kind = t[0].cast<std::string>();
            if (kind != "text") continue;
            int handle = t[1].cast<int>();
            float ox = t[2].cast<float>();
            float oy = t[3].cast<float>();
            std::string text = t[4].cast<std::string>();
            auto rgba = t[5].cast<std::array<float, 4>>();
            for (const auto& g : font_service().shape(handle, text)) {
                renderer::UiGlyphQuad q;
                q.x = g.dst_x + ox; q.y = g.dst_y + oy;
                q.w = g.dst_w;      q.h = g.dst_h;
                q.u0 = g.u0; q.v0 = g.v0; q.u1 = g.u1; q.v1 = g.v1;
                q.r = rgba[0]; q.g = rgba[1]; q.b = rgba[2]; q.a = rgba[3];
                quads.push_back(q);
            }
        }
        // Re-upload if shaping added new glyphs mid-build.
        const auto& atlas2 = font_service().atlas();
        if (atlas2.version != g_ui_atlas_version) {
            g_ui_quad_pass->set_atlas(atlas2.pixels.data(), atlas2.width, atlas2.height);
            g_ui_atlas_version = atlas2.version;
        }

        g_window->poll_events();
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, fw, fh);
        glClearColor(0.04f, 0.05f, 0.07f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        g_ui_quad_pass->render(quads, fw, fh, *g_pipeline);
        g_window->swap_buffers();
    }, py::arg("draw_list"),
       "Poll, clear FBO0, draw the UI text-run draw-list, and swap.");
```

In `engine/renderer.py`, add wrappers + register in `_OPTIONAL_BINDINGS`:
```python
def ui_should_close() -> bool:
    """True if the harness window wants to close (or no host)."""
    fn = getattr(_h, "ui_should_close", None)
    return True if fn is None else fn()


def ui_render(draw_list) -> None:
    """Render one harness frame from a text-run draw-list. No-op headless."""
    fn = getattr(_h, "ui_render", None)
    if fn is not None:
        fn(draw_list)
```
Add `"ui_render"` and `"ui_should_close"` to the `_OPTIONAL_BINDINGS` manifest.

Replace `engine/ui_harness.py` with the real loop:
```python
"""Throwaway harness: native UI stack with CEF absent (Spec 1).

Launched via `./build/dauntless --ui-harness` (implies --no-cef). Renders a live
TGParagraph as real FreeType Antonio text on a CEF-free launch path.
"""

from engine import renderer as r
from engine.appc.tg_ui.managers import g_kFontManager
from engine.appc.tg_ui.widgets import TGParagraph

_TEXT_RGBA = (0.85, 0.90, 1.0, 1.0)


def walk_paragraph(para, x, y):
    """Flatten a TGParagraph into text-run draw commands.

    Returns [("text", handle, x, y, string, rgba)] or [] if no native handle.
    """
    group = para.GetFontGroup() or g_kFontManager.GetDefaultFont()
    handle = group.native_handle() if group is not None else None
    if handle is None:
        return []
    return [("text", handle, float(x), float(y), para.GetText(), _TEXT_RGBA)]


def run() -> int:
    print("[ui-harness] native UI harness starting (CEF absent)")
    r.init(1280, 720, "ui-harness")
    group = g_kFontManager.CreateFontGroup("Crillee", 18.0)
    para = TGParagraph("Dauntless native text - CEF absent. 0123456789")
    para.SetFont(group)
    print("[ui-harness] TGParagraph built; entering render loop")
    while not r.ui_should_close():
        r.ui_render(walk_paragraph(para, 80, 320))
    return 0
```

- [ ] **Step 4: Run the pure-Python test — expect PASS**

Run:
```bash
uv run pytest tests/unit/test_ui_harness_walk.py -v
```
Expected: both tests PASS.

- [ ] **Step 5: Reconfigure, rebuild the binary, run the end-to-end harness**

Run:
```bash
cmake -B build -S . && cmake --build build -j --target dauntless
./build/dauntless --ui-harness
```
Expected: a window opens showing the Antonio string as crisp text on a dark background; stdout shows the CEF-absence lines and the harness prints; no `CEF CONSTRUCTED` line. Close the window to exit 0. (Manual visual verification — no synthetic desktop interaction on the live workstation. If it crashes or renders nothing, record the exact failing subsystem per the spec's useful-failure protocol instead of working around it.)

- [ ] **Step 6: Run the full gate**

Run:
```bash
scripts/check_tests.sh
```
Expected: green — only the 7 baselined headless-GL `FrameTest`s in `tests/known_failures.txt` may fail; any other failure is a regression to fix before committing.

- [ ] **Step 7: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py engine/ui_harness.py \
        tests/unit/test_ui_harness_walk.py
git commit -m "feat(ui-harness): render live TGParagraph via native font backend, CEF absent"
```

---

## Self-Review

**Spec coverage (each spec section → task):**
- §4.1 draw-list contract → Task 9 (`ui_render` tuple shape; `walk_paragraph`).
- §4.2 FontService (FreeType, atlas, shape/measure) → Tasks 1–4.
- §4.3 UiQuadPass (pixel→NDC, R8 atlas, FBO 0) → Task 5.
- §4.4 launch + CEF-absence proof (`--no-cef`, `--ui-harness`, guard prints) → Task 8.
- §4.5 harness present loop → Task 9.
- §5 Python interface changes (proxies, `SetFont`, spacing setters, `SetIconLocation` no-op doc) → Tasks 6–7.
- §6 build/deps (FreeType FetchContent, `text` target, embed_shader, asset copy) → Tasks 1, 2, 5.
- §7 testing (C++ ctest, pytest, gate, end-to-end, useful-failure) → per-task tests + Task 9 steps 5–6.
- §8 success criteria → Task 8 (CEF-absence) + Task 9 (render + gate).

**Placeholder scan:** no `TBD`/`TODO`/"add error handling"/"similar to Task N" — every code step carries full content. (The only `TODO` strings are pre-existing CEF-platform SHA lines in `native/CMakeLists.txt`, untouched by this plan.)

**Type consistency:**
- `FontService::create_font(path, size_px) -> int`, `measure(handle, text, &w, &h)`, `shape(handle, text) -> vector<GlyphQuad>`, `atlas() -> const Atlas&`, `line_height(handle) -> float` — consistent across Tasks 1–4, 6, 9.
- `GlyphQuad` fields (`dst_x/dst_y/dst_w/dst_h/u0/v0/u1/v1`) match between `font_service.h` and the `ui_render` conversion in Task 9.
- `UiGlyphQuad` fields (`x/y/w/h/u0/v0/u1/v1/r/g/b/a`) match between `ui_quad_pass.h` (Task 5) and `ui_render` (Task 9).
- `Pipeline::ui_quad_shader()` defined in Task 5, consumed by `UiQuadPass::render` in Task 5.
- Native binding names (`font_create`, `font_measure`, `ui_render`, `ui_should_close`) match facade wrappers and harness call sites (Tasks 6, 9).
- `TGFontGroup.native_handle()`, `TGParagraph.GetFontGroup()`/`SetFont()` defined in Task 7, consumed by `walk_paragraph` in Task 9.

**Sequencing note:** Task 9's `ui_render` re-checks `atlas.version` after shaping because glyphs are rasterized lazily during `shape()`; the double-check ensures newly-added glyphs are uploaded before the draw in the same frame.
