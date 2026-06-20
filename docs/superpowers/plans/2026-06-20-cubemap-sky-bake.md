# Cubemap Sky Bake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bake the static map-driven procedural sky to an offscreen cubemap once per system entry, then sample that cheap texture each frame instead of re-rendering 14 noise-heavy backdrop spheres every frame.

**Architecture:** A new `CubemapTarget` render target (6 × RGBA16F faces). `BackdropPass` gains a `bake()` (render the existing backdrop spheres into the 6 faces using the current `proc_main` shader verbatim) and a `render_cubemap()` (draw a skybox sampling the cube by view direction). `host_bindings.cc` diffs the per-frame descriptor list and re-bakes only when it changes; `frame()` samples the cubemap when the map-driven sky is active, else falls back to the existing per-frame path.

**Tech Stack:** C++17, OpenGL 3.3 core (glad), GLM, pybind11, GoogleTest. Spec: [`docs/superpowers/specs/2026-06-20-cubemap-sky-bake-design.md`](../specs/2026-06-20-cubemap-sky-bake-design.md).

## Global Constraints

- Cubemap is **1024² per face, RGBA16F** (`kSkyFaceSize = 1024`), with mipmaps. Window-independent (fixed size).
- **Static until warp:** bake only when descriptors change or the procedural toggle flips. Re-bake trigger is the **implicit descriptor diff** in `set_backdrops` — no new Python API.
- The bake **reuses the existing `proc_main` backdrop shader verbatim** — no change to the sky's appearance, density, or projection.
- **Stock-BC (toggle off) and the unmapped-authored fallback keep the existing per-frame textured backdrop render, byte-identical.** The cubemap path is entered only when the sky is procedural (all descriptors have empty `texture_path`) and the toggle is on.
- HDR: cubemap faces are RGBA16F (linear) so bloom still lights nebula cores.
- Inside-the-sphere passes cull `GL_FRONT` under `glFrontFace(GL_CCW)` (established convention — do not change).
- Matrices are column-vector; `world_rotation` column 1 is forward.
- **Single build tree** at `build/`; binary `build/dauntless`, module `build/python/_dauntless_host.cpython-*.so`. Build: `cmake -B build -S . && cmake --build build -j`.
- **New/edited shader files require `cmake -B build -S .` (reconfigure) before `cmake --build`** — shaders embed at configure time.
- `host_bindings.cc` compiles into BOTH `build/dauntless` and the `_dauntless_host` module; always rebuild via `cmake --build build` (not the module alone).

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `native/src/renderer/include/renderer/cubemap_target.h` | Create | `CubemapTarget` RT interface |
| `native/src/renderer/cubemap_target.cc` | Create | `CubemapTarget` RT implementation |
| `native/src/renderer/shaders/skybox.vert` | Create | Skybox vertex shader (direction passthrough + `z=w`) |
| `native/src/renderer/shaders/skybox.frag` | Create | Skybox fragment shader (`samplerCube` fetch) |
| `native/src/renderer/CMakeLists.txt` | Modify | Embed skybox shaders; add `cubemap_target.cc` to `renderer` lib |
| `native/src/renderer/include/renderer/pipeline.h` | Modify | `skybox_shader()` accessor + `skybox_` member |
| `native/src/renderer/pipeline.cc` | Modify | Construct `skybox_` from embedded sources |
| `native/src/renderer/include/renderer/backdrop_pass.h` | Modify | `bake()`, `render_cubemap()`, `has_cubemap()`, `bakes_count()`, `draw_backdrops()` helper, `CubemapTarget` member; free `backdrops_are_procedural()` / `backdrops_equal()` |
| `native/src/renderer/backdrop_pass.cc` | Modify | Implement the above; extract the per-sphere draw loop into `draw_backdrops()` |
| `native/src/host/host_bindings.cc` | Modify | Descriptor diff → `g_sky_dirty`; `frame()` bake-if-dirty + cubemap-vs-per-frame branch |
| `native/tests/renderer/cubemap_target_test.cc` | Create | GL completeness test for `CubemapTarget` |
| `native/tests/renderer/backdrop_pass_test.cc` | Modify | Pure helper tests + bake/sample directional fidelity test |
| `native/tests/renderer/CMakeLists.txt` | Modify | Add `cubemap_target_test.cc` |

---

### Task 1: CubemapTarget render target

**Files:**
- Create: `native/src/renderer/include/renderer/cubemap_target.h`
- Create: `native/src/renderer/cubemap_target.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `cubemap_target.cc` to `add_library(renderer STATIC ...)`)
- Create: `native/tests/renderer/cubemap_target_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt` (add `cubemap_target_test.cc`)

**Interfaces:**
- Produces: `class renderer::CubemapTarget` with `bool allocate(int face_size)`, `void bind_face(int i)`, `void generate_mips() const`, `std::uint32_t texture() const`, `int face_size() const`, `bool valid() const`.

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/cubemap_target_test.cc`:

```cpp
#include <gtest/gtest.h>

#include <renderer/cubemap_target.h>
#include <renderer/window.h>

#include <glad/glad.h>

#include <memory>

TEST(CubemapTarget, AllocatesCompleteFboAndBindsAllFaces) {
    std::unique_ptr<renderer::Window> w;
    try {
        w = std::make_unique<renderer::Window>(64, 64, "cubemap-test", false);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context: " << e.what();
    }

    renderer::CubemapTarget cube;
    ASSERT_TRUE(cube.allocate(128));
    EXPECT_TRUE(cube.valid());
    EXPECT_EQ(cube.face_size(), 128);
    EXPECT_NE(cube.texture(), 0u);

    for (int i = 0; i < 6; ++i) {
        cube.bind_face(i);
        EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER), GL_FRAMEBUFFER_COMPLETE)
            << "cube face " << i << " incomplete";
    }
    cube.generate_mips();

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}
```

Add `cubemap_target_test.cc` to the `add_executable(renderer_tests ...)` list in `native/tests/renderer/CMakeLists.txt` (next to `hdr_target_test.cc`).

- [ ] **Step 2: Run the test to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j renderer_tests`
Expected: compile error — `renderer/cubemap_target.h` not found.

- [ ] **Step 3: Write the header**

Create `native/src/renderer/include/renderer/cubemap_target.h`:

```cpp
// native/src/renderer/include/renderer/cubemap_target.h
#pragma once
#include <cstdint>

namespace renderer {

/// One render-to-cubemap target: a 6-face RGBA16F color cubemap (mip-mapped),
/// a shared depth renderbuffer, and an FBO whose color attachment is rebound
/// per face. Fixed-size and window-independent — used to bake the static
/// procedural sky once per system. Modeled on HdrTarget.
class CubemapTarget {
public:
    CubemapTarget() = default;
    ~CubemapTarget();
    CubemapTarget(const CubemapTarget&) = delete;
    CubemapTarget& operator=(const CubemapTarget&) = delete;

    /// (Re)allocate to face_size x face_size per face. No-op if already that
    /// size. Returns true on a complete FBO; false on failure (caller falls
    /// back to per-frame rendering). Requires a current GL context.
    bool allocate(int face_size);

    /// Bind the FBO with color attachment = face `i` (0..5, matching
    /// GL_TEXTURE_CUBE_MAP_POSITIVE_X + i) and set the viewport to the face.
    void bind_face(int i) const;

    /// Build the mip chain (call once after all 6 faces are rendered).
    void generate_mips() const;

    std::uint32_t texture() const { return cube_tex_; }
    int  face_size() const { return face_size_; }
    bool valid() const { return fbo_ != 0; }

private:
    void destroy();
    std::uint32_t fbo_ = 0;
    std::uint32_t cube_tex_ = 0;
    std::uint32_t depth_rbo_ = 0;
    int face_size_ = 0;
};

}  // namespace renderer
```

- [ ] **Step 4: Write the implementation**

Create `native/src/renderer/cubemap_target.cc`:

```cpp
// native/src/renderer/cubemap_target.cc
#include "renderer/cubemap_target.h"
#include <glad/glad.h>

namespace renderer {

CubemapTarget::~CubemapTarget() { destroy(); }

void CubemapTarget::destroy() {
    if (cube_tex_)  { glDeleteTextures(1, &cube_tex_); cube_tex_ = 0; }
    if (depth_rbo_) { glDeleteRenderbuffers(1, &depth_rbo_); depth_rbo_ = 0; }
    if (fbo_)       { glDeleteFramebuffers(1, &fbo_); fbo_ = 0; }
}

bool CubemapTarget::allocate(int face_size) {
    if (face_size < 1) face_size = 1;
    if (face_size == face_size_ && fbo_ != 0) return true;
    destroy();
    face_size_ = face_size;

    glGenTextures(1, &cube_tex_);
    glBindTexture(GL_TEXTURE_CUBE_MAP, cube_tex_);
    for (int i = 0; i < 6; ++i) {
        glTexImage2D(GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, 0, GL_RGBA16F,
                     face_size, face_size, 0, GL_RGBA, GL_FLOAT, nullptr);
    }
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE);

    glGenRenderbuffers(1, &depth_rbo_);
    glBindRenderbuffer(GL_RENDERBUFFER, depth_rbo_);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, face_size, face_size);

    glGenFramebuffers(1, &fbo_);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                              GL_RENDERBUFFER, depth_rbo_);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_CUBE_MAP_POSITIVE_X, cube_tex_, 0);
    const bool ok =
        glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    if (!ok) destroy();
    return ok;
}

void CubemapTarget::bind_face(int i) const {
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, cube_tex_, 0);
    glViewport(0, 0, face_size_, face_size_);
}

void CubemapTarget::generate_mips() const {
    glBindTexture(GL_TEXTURE_CUBE_MAP, cube_tex_);
    glGenerateMipmap(GL_TEXTURE_CUBE_MAP);
}

}  // namespace renderer
```

Add `cubemap_target.cc` to `add_library(renderer STATIC ...)` in `native/src/renderer/CMakeLists.txt`, right after `hdr_target.cc`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cmake -B build -S . && cmake --build build -j renderer_tests && ctest --test-dir build -R CubemapTarget --output-on-failure`
Expected: PASS (or SKIPPED if the CI box has no GL context — acceptable, matches other RT tests).

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/cubemap_target.h \
        native/src/renderer/cubemap_target.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/cubemap_target_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): CubemapTarget render-to-cubemap target"
```

---

### Task 2: Skybox sample shader + pipeline accessor

**Files:**
- Create: `native/src/renderer/shaders/skybox.vert`
- Create: `native/src/renderer/shaders/skybox.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (two `embed_shader()` calls)
- Modify: `native/src/renderer/include/renderer/pipeline.h` (`skybox_shader()` + `skybox_` member)
- Modify: `native/src/renderer/pipeline.cc` (includes + construct `skybox_`)
- Modify: `native/tests/renderer/pipeline_test.cc` (link/compile assertion)

**Interfaces:**
- Consumes: `renderer::Shader` (`use()`, `set_mat4`, `set_int`, `program()`), the embedded-shader mechanism.
- Produces: `Shader& renderer::Pipeline::skybox_shader()`. Skybox shader uniforms: `mat4 u_view_no_translation`, `mat4 u_proj`, `samplerCube u_skybox`. Vertex input `layout(location=0) a_pos` (unit-sphere position = world direction).

- [ ] **Step 1: Write the failing test**

Add to `native/tests/renderer/pipeline_test.cc` (after `SunShaderCompilesAndLinks`):

```cpp
TEST_F(PipelineTest, SkyboxShaderCompilesAndLinks) {
    renderer::Pipeline p;
    EXPECT_NE(p.skybox_shader().program(), 0u);
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j renderer_tests`
Expected: compile error — `Pipeline` has no member `skybox_shader`.

- [ ] **Step 3: Write the shaders**

Create `native/src/renderer/shaders/skybox.vert`:

```glsl
#version 330 core

layout(location=0) in vec3 a_pos;
layout(location=1) in vec3 a_normal;   // unused; VAO layout compatibility
layout(location=2) in vec2 a_uv;       // unused

uniform mat4 u_view_no_translation;
uniform mat4 u_proj;

out vec3 v_dir;

void main() {
    // The sphere is drawn world-axis-aligned and camera-anchored, so each
    // vertex position IS the world-space view direction for that fragment.
    v_dir = a_pos;
    vec4 clip = u_proj * u_view_no_translation * vec4(a_pos, 1.0);
    clip.z = clip.w;            // skybox-depth idiom: force to the far plane
    gl_Position = clip;
}
```

Create `native/src/renderer/shaders/skybox.frag`:

```glsl
#version 330 core

in vec3 v_dir;

uniform samplerCube u_skybox;

out vec4 frag_color;

void main() {
    frag_color = vec4(texture(u_skybox, normalize(v_dir)).rgb, 1.0);
}
```

- [ ] **Step 4: Embed the shaders + wire the pipeline**

In `native/src/renderer/CMakeLists.txt`, add after the backdrop embed lines (17–18):

```cmake
embed_shader(SHADER_SKYBOX_VS shaders/skybox.vert skybox_vs)
embed_shader(SHADER_SKYBOX_FS shaders/skybox.frag skybox_fs)
```

In `native/src/renderer/include/renderer/pipeline.h`, add the accessor next to `backdrop_shader()`:

```cpp
    Shader& skybox_shader() noexcept     { return *skybox_; }
```

and the member next to `backdrop_`:

```cpp
    std::unique_ptr<Shader> skybox_;
```

In `native/src/renderer/pipeline.cc`, add the includes after the backdrop ones (lines 9–10):

```cpp
#include "embedded_skybox_vs.h"
#include "embedded_skybox_fs.h"
```

and construct the shader after the `backdrop_` line (52):

```cpp
    skybox_ = std::make_unique<Shader>(shader_src::skybox_vs, shader_src::skybox_fs);
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cmake -B build -S . && cmake --build build -j renderer_tests && ctest --test-dir build -R "PipelineTest.SkyboxShaderCompilesAndLinks" --output-on-failure`
Expected: PASS (or SKIPPED without a GL context).

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/shaders/skybox.vert native/src/renderer/shaders/skybox.frag \
        native/src/renderer/CMakeLists.txt \
        native/src/renderer/include/renderer/pipeline.h native/src/renderer/pipeline.cc \
        native/tests/renderer/pipeline_test.cc
git commit -m "feat(renderer): skybox cubemap-sample shader + pipeline accessor"
```

---

### Task 3: Descriptor helper functions

Pure (no-GL) free functions used by the host integration (Task 5) and as the bake fidelity test's inputs. Defined in the renderer so both the host and tests link them.

**Files:**
- Modify: `native/src/renderer/include/renderer/backdrop_pass.h` (declare two free functions)
- Modify: `native/src/renderer/backdrop_pass.cc` (implement them)
- Modify: `native/tests/renderer/backdrop_pass_test.cc` (unit tests)

**Interfaces:**
- Produces:
  - `bool renderer::backdrops_are_procedural(const std::vector<Backdrop>&)` — true iff the list is non-empty AND every entry has an empty `texture_path` (the map-driven procedural case).
  - `bool renderer::backdrops_equal(const std::vector<Backdrop>& a, const std::vector<Backdrop>& b)` — true iff same size and every field of every entry is equal.

- [ ] **Step 1: Write the failing tests**

Add to `native/tests/renderer/backdrop_pass_test.cc` (top-level, no fixture — these need no GL):

```cpp
#include <renderer/backdrop_pass.h>   // ensure included at top of file

static renderer::Backdrop make_proc(int proc_kind, float span) {
    renderer::Backdrop b;
    b.texture_path = "";
    b.kind = renderer::BackdropKind::Backdrop;
    b.proc_kind = proc_kind;
    b.h_span = b.v_span = span;
    return b;
}

TEST(BackdropHelpers, AreProceduralRequiresAllEmptyTexturePaths) {
    std::vector<renderer::Backdrop> proc = {make_proc(0, 1.0f), make_proc(2, 1.5f)};
    EXPECT_TRUE(renderer::backdrops_are_procedural(proc));

    std::vector<renderer::Backdrop> empty;
    EXPECT_FALSE(renderer::backdrops_are_procedural(empty));

    auto mixed = proc;
    mixed[1].texture_path = "stars.tga";   // authored entry present
    EXPECT_FALSE(renderer::backdrops_are_procedural(mixed));
}

TEST(BackdropHelpers, EqualDetectsAnyFieldChange) {
    std::vector<renderer::Backdrop> a = {make_proc(0, 1.0f), make_proc(2, 1.5f)};
    auto b = a;
    EXPECT_TRUE(renderer::backdrops_equal(a, b));

    b[1].h_span = 1.6f;                    // changed span
    EXPECT_FALSE(renderer::backdrops_equal(a, b));

    auto c = a;
    c.pop_back();                          // changed size
    EXPECT_FALSE(renderer::backdrops_equal(a, c));
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cmake --build build -j renderer_tests`
Expected: compile error — `backdrops_are_procedural` / `backdrops_equal` not declared.

- [ ] **Step 3: Declare the helpers**

In `native/src/renderer/include/renderer/backdrop_pass.h`, add inside `namespace renderer`, after the `class BackdropPass { ... };` closing brace:

```cpp
/// True iff `backdrops` is non-empty and every entry is procedural (empty
/// texture_path) — the map-driven sky case that the cubemap bake handles.
bool backdrops_are_procedural(const std::vector<Backdrop>& backdrops);

/// True iff `a` and `b` are the same length and every field of every entry is
/// equal. Used to detect when the per-frame descriptor list actually changed
/// (and the cubemap must be re-baked).
bool backdrops_equal(const std::vector<Backdrop>& a,
                     const std::vector<Backdrop>& b);
```

- [ ] **Step 4: Implement the helpers**

In `native/src/renderer/backdrop_pass.cc`, add at the end of `namespace renderer` (before the closing brace):

```cpp
bool backdrops_are_procedural(const std::vector<Backdrop>& backdrops) {
    if (backdrops.empty()) return false;
    for (const auto& b : backdrops) {
        if (!b.texture_path.empty()) return false;
    }
    return true;
}

bool backdrops_equal(const std::vector<Backdrop>& a,
                     const std::vector<Backdrop>& b) {
    if (a.size() != b.size()) return false;
    for (std::size_t i = 0; i < a.size(); ++i) {
        const Backdrop& x = a[i];
        const Backdrop& y = b[i];
        if (x.texture_path != y.texture_path) return false;
        if (x.kind != y.kind) return false;
        if (x.h_tile != y.h_tile || x.v_tile != y.v_tile) return false;
        if (x.h_span != y.h_span || x.v_span != y.v_span) return false;
        if (x.world_rotation != y.world_rotation) return false;
        if (x.target_poly_count != y.target_poly_count) return false;
        if (x.proc_kind != y.proc_kind) return false;
        if (x.color != y.color) return false;
        if (x.coverage != y.coverage) return false;
        if (x.seed != y.seed) return false;
    }
    return true;
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cmake --build build -j renderer_tests && ctest --test-dir build -R "BackdropHelpers" --output-on-failure`
Expected: PASS (these need no GL — they run everywhere).

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/backdrop_pass.h \
        native/src/renderer/backdrop_pass.cc \
        native/tests/renderer/backdrop_pass_test.cc
git commit -m "feat(renderer): backdrops_are_procedural + backdrops_equal helpers"
```

---

### Task 4: BackdropPass bake + cubemap sample

**Files:**
- Modify: `native/src/renderer/include/renderer/backdrop_pass.h`
- Modify: `native/src/renderer/backdrop_pass.cc`
- Modify: `native/tests/renderer/backdrop_pass_test.cc` (directional bake/sample fidelity test)

**Interfaces:**
- Consumes: `CubemapTarget` (Task 1), `Pipeline::skybox_shader()` and `backdrop_shader()` (Task 2), `scenegraph::Camera`.
- Produces (on `BackdropPass`):
  - `bool bake(const std::vector<Backdrop>& backdrops, Pipeline& pipeline, float now_seconds)` — renders the backdrops into all 6 cube faces; returns false if the cubemap could not be allocated. Increments the bake counter.
  - `void render_cubemap(const scenegraph::Camera& camera, Pipeline& pipeline)` — draws the skybox sampling the baked cubemap.
  - `bool has_cubemap() const` — true once a successful bake exists.
  - `int bakes_count() const` — number of completed bakes (test/observability).
  - Private `void draw_backdrops(const std::vector<Backdrop>&, const glm::mat4& view_no_translation, const glm::mat4& proj, Pipeline&, bool procedural, float now_seconds)` — the extracted per-sphere draw loop, shared by `render()` and `bake()`.

- [ ] **Step 1: Write the failing test**

Add to `native/tests/renderer/backdrop_pass_test.cc` inside the existing GL fixture (it has a `Window` + `Pipeline`; if the file's fixture differs, mirror `frame_test.cc`'s `FrameTest` SetUp which builds `renderer::Window` 256×256 and `renderer::Pipeline`). This test uses a 256×256 window:

```cpp
// Helper: a column-major mat3 [right, fwd, up] pointing `fwd` at +Z.
static std::vector<float> rot_forward_pz() {
    // right=+X, forward=+Z, up=+Y  (columns)
    return {1,0,0,  0,0,1,  0,1,0};
}

TEST_F(BackdropPassFixture, BakeCapturesDirectionalContentAndSamplesBack) {
    // One always-on base starfield + one bright nebula pointing at +Z.
    renderer::Backdrop base;
    base.texture_path = "";
    base.kind = renderer::BackdropKind::Star;
    base.proc_kind = 0;
    base.seed = 1.0f;

    renderer::Backdrop neb;
    neb.texture_path = "";
    neb.kind = renderer::BackdropKind::Backdrop;
    neb.proc_kind = 2;                       // nebula
    neb.h_span = neb.v_span = 8.0f;          // large cap so it dominates +Z
    neb.color = glm::vec3(0.8f, 0.3f, 0.9f);
    neb.coverage = 0.9f;
    neb.seed = 5.0f;
    {
        auto m = rot_forward_pz();
        neb.world_rotation = glm::mat3(m[0],m[1],m[2], m[3],m[4],m[5], m[6],m[7],m[8]);
    }
    std::vector<renderer::Backdrop> sky = {base, neb};

    renderer::BackdropPass pass;
    ASSERT_TRUE(pass.bake(sky, *p, 0.0f));
    EXPECT_TRUE(pass.has_cubemap());
    EXPECT_EQ(pass.bakes_count(), 1);

    auto mean_center = [&](glm::vec3 look_dir) -> double {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, 256, 256);
        glClearColor(0, 0, 0, 1);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        scenegraph::Camera cam;
        cam.eye = glm::vec3(0.0f);
        cam.target = look_dir;
        cam.up = glm::vec3(0, 1, 0);
        cam.aspect = 1.0f;
        pass.render_cubemap(cam, *p);
        unsigned char buf[16 * 16 * 4];
        glReadPixels(120, 120, 16, 16, GL_RGBA, GL_UNSIGNED_BYTE, buf);
        double sum = 0;
        for (int i = 0; i < 16 * 16; ++i)
            sum += buf[i*4] + buf[i*4+1] + buf[i*4+2];
        return sum / (16 * 16);
    };

    const double toward = mean_center(glm::vec3(0, 0, 1));   // at the nebula
    const double away   = mean_center(glm::vec3(0, 0, -1));  // opposite
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_GT(toward, away * 1.3)
        << "baked nebula should make the +Z view brighter than -Z (toward="
        << toward << " away=" << away << ")";
}
```

If `backdrop_pass_test.cc` has no GL fixture named `BackdropPassFixture`, add one mirroring `frame_test.cc`'s `FrameTest` (creates `w` = `renderer::Window(256,256,"backdrop-test",false)` with a `GTEST_SKIP()` on failure, and `p` = `renderer::Pipeline`). Include `<scenegraph/camera.h>`, `<glm/glm.hpp>`, `<glad/glad.h>`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cmake --build build -j renderer_tests`
Expected: compile error — `BackdropPass` has no member `bake` / `render_cubemap` / `has_cubemap` / `bakes_count`.

- [ ] **Step 3: Extend the header**

In `native/src/renderer/include/renderer/backdrop_pass.h`:

Add the include near the top (after the existing includes):

```cpp
#include <renderer/cubemap_target.h>
#include <glm/glm.hpp>
```

Forward-declare nothing new (Camera already forward-declared). Add to the `public:` section after `render(...)`:

```cpp
    /// Bake `backdrops` into all 6 cubemap faces (camera at origin, 6 x 90deg
    /// views) using the same procedural shader path as render(). Returns false
    /// if the cubemap could not be allocated. Call once per system entry.
    bool bake(const std::vector<Backdrop>& backdrops,
              Pipeline& pipeline,
              float now_seconds);

    /// Draw the skybox sampling the baked cubemap by view direction into the
    /// currently-bound framebuffer. No-op if no successful bake exists.
    void render_cubemap(const scenegraph::Camera& camera, Pipeline& pipeline);

    bool has_cubemap() const { return cubemap_.valid(); }
    int  bakes_count() const { return bakes_count_; }
```

Add to the `private:` section:

```cpp
    /// Shared per-sphere draw loop used by render() and bake(). Caller sets the
    /// target framebuffer/viewport and (for bake) the per-face view/proj.
    void draw_backdrops(const std::vector<Backdrop>& backdrops,
                        const glm::mat4& view_no_translation,
                        const glm::mat4& proj,
                        Pipeline& pipeline,
                        bool procedural,
                        float now_seconds);

    CubemapTarget cubemap_;
    int bakes_count_ = 0;
    static constexpr int kSkyFaceSize = 1024;
```

- [ ] **Step 4: Implement in backdrop_pass.cc**

Add the GLM transform include near the top of `native/src/renderer/backdrop_pass.cc` (after `#include <glm/glm.hpp>`):

```cpp
#include <glm/gtc/matrix_transform.hpp>
```

Replace the body of `render()` (everything from `auto& shader = pipeline.backdrop_shader();` through the final `glBindVertexArray(0);`, keeping the leading `if (backdrops.empty()) return;`) so `render()` delegates to `draw_backdrops()`:

```cpp
void BackdropPass::render(const std::vector<Backdrop>& backdrops,
                          const scenegraph::Camera& camera,
                          Pipeline& pipeline,
                          bool procedural,
                          float now_seconds) {
    if (backdrops.empty()) return;
    const glm::mat4 view_no_t = glm::mat4(glm::mat3(camera.view_matrix()));
    draw_backdrops(backdrops, view_no_t, camera.proj_matrix(),
                   pipeline, procedural, now_seconds);
}
```

Add `draw_backdrops()` — this is the existing per-sphere loop verbatim, parameterized by the view/proj matrices instead of reading them from a Camera:

```cpp
void BackdropPass::draw_backdrops(const std::vector<Backdrop>& backdrops,
                                  const glm::mat4& view_no_translation,
                                  const glm::mat4& proj,
                                  Pipeline& pipeline,
                                  bool procedural,
                                  float now_seconds) {
    auto& shader = pipeline.backdrop_shader();
    shader.use();
    shader.set_mat4("u_view_no_translation", view_no_translation);
    shader.set_mat4("u_proj", proj);

    glDepthMask(GL_FALSE);
    glDepthFunc(GL_LEQUAL);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_FRONT);  // we render the inside of the sphere

    for (const auto& b : backdrops) {
        assets::Mesh* sphere = ensure_sphere(b.target_poly_count);
        assets::Texture* tex = ensure_texture(b.texture_path);
        if (!sphere) continue;
        if (!tex && !procedural) continue;

        if (b.kind == BackdropKind::Backdrop) {
            glEnable(GL_BLEND);
            glBlendFunc(GL_SRC_ALPHA, GL_ONE);
            shader.set_int("u_use_alpha", 1);
        } else {
            glDisable(GL_BLEND);
            shader.set_int("u_use_alpha", 0);
        }

        shader.set_mat3("u_world_rotation", b.world_rotation);
        shader.set_vec2("u_tile", glm::vec2(b.h_tile, b.v_tile));
        shader.set_vec2("u_span", glm::vec2(b.h_span, b.v_span));

        shader.set_int("u_procedural", procedural ? 1 : 0);
        shader.set_int("u_proc_kind", b.proc_kind);
        shader.set_vec3("u_color", b.color);
        shader.set_float("u_coverage", b.coverage);
        shader.set_float("u_seed", b.seed);
        shader.set_float("u_time", now_seconds);

        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, tex ? tex->id() : 0);
        shader.set_int("u_texture", 0);

        glBindVertexArray(sphere->vao());
        glDrawElements(GL_TRIANGLES,
                       static_cast<GLsizei>(sphere->index_count()),
                       GL_UNSIGNED_INT, nullptr);
    }

    glDisable(GL_BLEND);
    glCullFace(GL_BACK);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glBindVertexArray(0);
}
```

> Note: the loop above is the current `render()` body — copy it from the existing file rather than retyping, then delete it from `render()`. The `glBlendFunc(GL_SRC_ALPHA, GL_ONE)` and `glCullFace(GL_FRONT)` lines must match the current shipped values exactly.

Add `bake()`:

```cpp
bool BackdropPass::bake(const std::vector<Backdrop>& backdrops,
                        Pipeline& pipeline, float now_seconds) {
    if (backdrops.empty()) return false;
    if (!cubemap_.allocate(kSkyFaceSize)) return false;

    GLint prev_fbo = 0;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &prev_fbo);
    GLint prev_vp[4] = {0, 0, 0, 0};
    glGetIntegerv(GL_VIEWPORT, prev_vp);

    glEnable(GL_TEXTURE_CUBE_MAP_SEAMLESS);
    const glm::mat4 proj = glm::perspective(glm::radians(90.0f), 1.0f, 0.1f, 10.0f);

    // Canonical GL cubemap face orientations (camera at origin). The up vectors
    // follow the cube's left-handed face convention so a later
    // texture(cube, worldDir) sample returns the colour baked for worldDir.
    struct Face { glm::vec3 dir; glm::vec3 up; };
    static const Face kFaces[6] = {
        {{ 1,  0,  0}, {0, -1,  0}},  // +X
        {{-1,  0,  0}, {0, -1,  0}},  // -X
        {{ 0,  1,  0}, {0,  0,  1}},  // +Y
        {{ 0, -1,  0}, {0,  0, -1}},  // -Y
        {{ 0,  0,  1}, {0, -1,  0}},  // +Z
        {{ 0,  0, -1}, {0, -1,  0}},  // -Z
    };

    for (int i = 0; i < 6; ++i) {
        cubemap_.bind_face(i);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        const glm::mat4 view =
            glm::lookAt(glm::vec3(0.0f), kFaces[i].dir, kFaces[i].up);
        const glm::mat4 view_no_t = glm::mat4(glm::mat3(view));
        draw_backdrops(backdrops, view_no_t, proj, pipeline,
                       /*procedural=*/true, now_seconds);
    }
    cubemap_.generate_mips();

    glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(prev_fbo));
    glViewport(prev_vp[0], prev_vp[1], prev_vp[2], prev_vp[3]);
    ++bakes_count_;
    return true;
}
```

Add `render_cubemap()`:

```cpp
void BackdropPass::render_cubemap(const scenegraph::Camera& camera,
                                  Pipeline& pipeline) {
    if (!cubemap_.valid()) return;
    auto& shader = pipeline.skybox_shader();
    shader.use();
    const glm::mat4 view_no_t = glm::mat4(glm::mat3(camera.view_matrix()));
    shader.set_mat4("u_view_no_translation", view_no_t);
    shader.set_mat4("u_proj", camera.proj_matrix());

    glDepthMask(GL_FALSE);
    glDepthFunc(GL_LEQUAL);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_FRONT);  // inside of the proxy sphere
    glDisable(GL_BLEND);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_CUBE_MAP, cubemap_.texture());
    shader.set_int("u_skybox", 0);

    assets::Mesh* sphere = ensure_sphere(256);  // sample proxy; detail is in the cube
    if (sphere) {
        glBindVertexArray(sphere->vao());
        glDrawElements(GL_TRIANGLES,
                       static_cast<GLsizei>(sphere->index_count()),
                       GL_UNSIGNED_INT, nullptr);
    }

    glCullFace(GL_BACK);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glBindVertexArray(0);
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cmake --build build -j renderer_tests && ctest --test-dir build -R "BackdropPassFixture.BakeCapturesDirectionalContentAndSamplesBack" --output-on-failure`
Expected: PASS (or SKIPPED without a GL context).

- [ ] **Step 6: Run the full renderer suite (regression guard for the render() refactor)**

Run: `ctest --test-dir build -R "renderer_tests" --output-on-failure`
Expected: existing backdrop/frame tests still PASS (the `render()` refactor is behavior-preserving).

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/include/renderer/backdrop_pass.h \
        native/src/renderer/backdrop_pass.cc \
        native/tests/renderer/backdrop_pass_test.cc
git commit -m "feat(renderer): BackdropPass cubemap bake + skybox sample"
```

---

### Task 5: Host integration — diff trigger + frame() branch

Wire the per-frame descriptor diff (sets the dirty flag) and the `frame()` decision to bake-once + sample the cubemap when the map-driven sky is active.

**Files:**
- Modify: `native/src/host/host_bindings.cc`

**Interfaces:**
- Consumes: `renderer::backdrops_are_procedural`, `renderer::backdrops_equal` (Task 3); `BackdropPass::bake/has_cubemap/render_cubemap` (Task 4); existing `dauntless_procedural_sky::enabled()`.

- [ ] **Step 1: Add the dirty-tracking state**

In `native/src/host/host_bindings.cc`, next to `std::vector<renderer::Backdrop> g_backdrops;` (line ~125) add:

```cpp
bool g_sky_dirty = true;            // cubemap needs (re)baking
bool g_sky_last_procedural = false; // procedural-toggle state at the last frame
```

In both `init`/reset spots that already do `g_backdrops.clear();` (lines ~310 and ~359), set `g_sky_dirty = true;` immediately after, so a fresh session/mission bakes on the first bakeable frame.

- [ ] **Step 2: Diff descriptors in set_backdrops**

In the `set_backdrops` binding (line ~1417), build into a temporary, diff against the current list, set the dirty flag, then store. Replace the existing `g_backdrops.clear(); g_backdrops.reserve(...); for (...) { ... g_backdrops.push_back(...); }` with the same loop building a local `next`, followed by the diff:

```cpp
    m.def("set_backdrops",
          [](const std::vector<py::dict>& descriptors) {
              std::vector<renderer::Backdrop> next;
              next.reserve(descriptors.size());
              for (const auto& d : descriptors) {
                  renderer::Backdrop b;
                  b.texture_path      = d["texture_path"].cast<std::string>();
                  std::string kind    = d["kind"].cast<std::string>();
                  b.kind = (kind == "star") ? renderer::BackdropKind::Star
                                            : renderer::BackdropKind::Backdrop;
                  b.h_tile            = d["h_tile"].cast<float>();
                  b.v_tile            = d["v_tile"].cast<float>();
                  b.h_span            = d["h_span"].cast<float>();
                  b.v_span            = d["v_span"].cast<float>();
                  b.target_poly_count = d["target_poly_count"].cast<int>();
                  if (d.contains("proc_kind")) {
                      std::string pk = d["proc_kind"].cast<std::string>();
                      b.proc_kind = (pk == "stars") ? 0 : (pk == "starcloud") ? 1 : 2;
                      auto col = d["color"].cast<std::vector<float>>();
                      if (col.size() == 3) b.color = glm::vec3(col[0], col[1], col[2]);
                      b.coverage = d["coverage"].cast<float>();
                      b.seed = d["seed"].cast<float>();
                  }
                  auto m9 = d["world_rotation"].cast<std::vector<float>>();
                  if (m9.size() == 9) {
                      b.world_rotation = glm::mat3(
                          m9[0], m9[1], m9[2],
                          m9[3], m9[4], m9[5],
                          m9[6], m9[7], m9[8]);
                  }
                  next.push_back(std::move(b));
              }
              if (!renderer::backdrops_equal(next, g_backdrops)) {
                  g_sky_dirty = true;
              }
              g_backdrops = std::move(next);
          },
          py::arg("backdrops"),
```

(Keep the rest of the binding registration — `py::arg`, docstring — unchanged.)

- [ ] **Step 3: Decide + bake once in frame(), before the render_space lambda**

In `frame()`, immediately after `now`/`dt` are computed (lines ~458–460) and BEFORE the `render_space` lambda is defined (~478), add:

```cpp
    // ── Cubemap sky bake (static-per-system) ───────────────────────────────
    // The map-driven procedural sky is fixed per vantage; bake it once into a
    // cubemap (on first sight or when the descriptor diff flagged a change) and
    // sample it each frame instead of re-rendering 14 noise spheres. Stock-BC
    // and the unmapped-authored fallback keep the per-frame textured path.
    const bool sky_procedural = dauntless_procedural_sky::enabled();
    if (sky_procedural != g_sky_last_procedural) {
        g_sky_dirty = true;
        g_sky_last_procedural = sky_procedural;
    }
    const bool sky_bakeable =
        sky_procedural && renderer::backdrops_are_procedural(g_backdrops);
    bool sky_use_cubemap = false;
    if (sky_bakeable && g_backdrop_pass) {
        if (g_sky_dirty || !g_backdrop_pass->has_cubemap()) {
            g_backdrop_pass->bake(g_backdrops, *g_pipeline,
                                  static_cast<float>(now));
            g_sky_dirty = false;
        }
        sky_use_cubemap = g_backdrop_pass->has_cubemap();  // false if alloc failed
    }
```

- [ ] **Step 4: Branch the backdrop draw in render_space**

In the `render_space` lambda, replace the existing backdrop render call (line ~479):

```cpp
        g_backdrop_pass->render(g_backdrops, cam, *g_pipeline,
                                dauntless_procedural_sky::enabled(), static_cast<float>(now));
```

with:

```cpp
        if (sky_use_cubemap)
            g_backdrop_pass->render_cubemap(cam, *g_pipeline);
        else
            g_backdrop_pass->render(g_backdrops, cam, *g_pipeline,
                                    dauntless_procedural_sky::enabled(),
                                    static_cast<float>(now));
```

(The lambda captures `[&]`, so it sees `sky_use_cubemap`; it is set before the lambda is invoked for either the viewscreen RTT or the main view, so both sample the same freshly-baked cubemap.)

- [ ] **Step 5: Build the whole tree**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: `build OK` — `dauntless` and `_dauntless_host` both build.

- [ ] **Step 6: Manual verification (live)**

Run: `./build/dauntless`
Confirm:
- The sky looks the same as the pre-bake build (the bake reuses the same shader) — sparse stars, soft circular nebula/galaxy glows, no seams.
- At Vesuvi: the large purple nebula is present.
- Frame time is improved / steady (the per-frame noise is gone). The one-time bake hitch on system entry is acceptable.
- Toggling the procedural sky off (Configuration → Graphics, if wired) shows stock BC unchanged; toggling back on re-bakes.

- [ ] **Step 7: Run the Python suite (no regressions)**

Run: `scripts/run_tests.sh` (or `python3 -m pytest tests/ -q`)
Expected: PASS — Python is unchanged; existing `sky_projection` tests still pass.

- [ ] **Step 8: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(host): bake sky to cubemap on descriptor change, sample per-frame"
```

---

## Self-Review

**Spec coverage:**
- §4 `CubemapTarget` → Task 1. ✓
- §4 skybox sample shader + `render_cubemap` → Tasks 2, 4. ✓
- §4 `bake` reusing `proc_main` → Task 4 (`draw_backdrops` shared with `render`). ✓
- §4/§5 dirty tracking via descriptor diff → Tasks 3 (helpers) + 5 (wiring). ✓
- §5 "bakeable" detection (empty `texture_path`) → `backdrops_are_procedural` (Task 3), used in `frame()` (Task 5). ✓
- §6 HDR (RGBA16F) → Task 1 face format. ✓
- §6 viewscreen shares one bake → Task 5 bakes before the lambda; both invocations sample. ✓
- §6 lifecycle (dtor releases handles; `g_backdrop_pass.reset()` already in shutdown) → `CubemapTarget` is a member, freed with `BackdropPass`. ✓
- §7 allocation-failure fallback → `bake()` returns false / `has_cubemap()` false → `sky_use_cubemap=false` → per-frame path (Task 5). ✓
- §7 toggle flip / unmapped fallback / first frame → Task 5 dirty logic + `backdrops_are_procedural`. ✓
- §9 tests: bake fidelity (Task 4 directional), dirty logic (Task 3 `backdrops_equal`), toggle-off parity (existing renderer suite, Task 4 Step 6 + Task 5 Step 7). ✓

**Placeholder scan:** none — every code step contains complete code.

**Type consistency:** `bake(const std::vector<Backdrop>&, Pipeline&, float)`, `render_cubemap(const scenegraph::Camera&, Pipeline&)`, `has_cubemap()`, `bakes_count()`, `backdrops_are_procedural`, `backdrops_equal`, `CubemapTarget::{allocate,bind_face,generate_mips,texture,face_size,valid}`, `skybox_shader()` — names and signatures are identical across the tasks that declare and consume them.

## Notes for the implementer

- `BackdropPass`'s sphere cache is keyed by `target_poly_count`; the bake uses the descriptors' own poly counts and `render_cubemap` requests `256` — both hit the same cache, no extra cost.
- The `draw_backdrops` body in Task 4 must be **copied from the current `render()`** so the shipped blend (`GL_SRC_ALPHA, GL_ONE`), cull (`GL_FRONT`), and uniform set are preserved byte-for-byte; do not re-derive them.
- If `backdrop_pass_test.cc` lacks a GL fixture, add one mirroring `frame_test.cc`'s `FrameTest::SetUp` (256×256 `Window`, `Pipeline`, `GTEST_SKIP()` when no context/assets).
