# Hull Damage Tessellation — Plan 1: Renderer Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the renderer from OpenGL 3.3 to 4.1 core, add tessellation (TCS/TES) support to the `Shader` class, and prove a pass-through tessellation pipeline compiles and links — with zero change to existing rendering.

**Architecture:** A small, additive foundation. Bump the GLFW context hints to 4.1 core (existing `#version 330` shaders compile unchanged). Extend the `Shader` class with a second constructor that accepts optional tessellation-control and tessellation-evaluation stages. Add a capability flag (`tessellation_available`) so later plans and the runtime can fall back to the static path if 4.1 is unavailable. Add a pass-through `#version 410` tessellation shader set (vert→tesc→tese→frag, identity displacement) embedded via the existing `embed_shader` CMake mechanism, and a GTest that compiles+links it. No draw path is wired into `frame.cc` yet — that is Plan 4.

**Tech Stack:** C++17, OpenGL 4.1 core, GLFW, GLAD, GLM, GoogleTest (offscreen GL via Mesa `llvmpipe`), CMake.

**Spec:** `docs/superpowers/specs/2026-06-16-hull-damage-tessellation-design.md` §3 (GPU pipeline — GL bump + Shader class), §8 (GL-unavailable fallback).

**Branch:** `feat/hull-damage-tessellation` (already created; the spec doc lives here).

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `native/src/renderer/window.cc` | GLFW context creation — request GL 4.1 core | Modify (~L40–44) |
| `native/src/renderer/include/renderer/gl_caps.h` | Free function reporting tessellation availability from the live context | Create |
| `native/src/renderer/gl_caps.cc` | Implementation: query `GL_VERSION` major/minor | Create |
| `native/src/renderer/include/renderer/shader.h` | `Shader` — add tessellation-capable constructor | Modify |
| `native/src/renderer/shader.cc` | Compile/attach optional TCS/TES stages | Modify |
| `native/src/renderer/shaders/passthrough_tess.vert` | Pass-through VS for the tess pipeline | Create |
| `native/src/renderer/shaders/passthrough_tess.tesc` | TCS: constant tess level 1, pass control points | Create |
| `native/src/renderer/shaders/passthrough_tess.tese` | TES: identity barycentric interpolation | Create |
| `native/src/renderer/shaders/passthrough_tess.frag` | Trivial FS (solid color) | Create |
| `native/src/renderer/CMakeLists.txt` | Add `gl_caps.cc` to lib; embed the 4 new shaders | Modify |
| `native/tests/renderer/gl_caps_test.cc` | Test capability query returns ≥4.1 under test context | Create |
| `native/tests/renderer/tess_program_test.cc` | Test the pass-through tess program compiles + links | Create |
| `native/tests/renderer/CMakeLists.txt` | Register the two new test files | Modify |

**Convention notes for the implementer (you have zero context — read these):**
- Shaders are **not** loaded from disk at runtime. CMake's `embed_shader(VAR path symbol)` reads each `.vert`/`.frag`/`.tesc`/`.tese` file and generates `embedded_<symbol>.h` containing `constexpr const char* renderer::shader_src::<symbol> = R"GLSL(...)GLSL";`. You `#include "embedded_<symbol>.h"` and pass `shader_src::<symbol>` to the `Shader` constructor. See `native/src/renderer/CMakeLists.txt` and `native/src/renderer/pipeline.cc:6-58`.
- Tests run under Mesa `llvmpipe` (`GALLIUM_DRIVER=llvmpipe`, set in `native/tests/renderer/CMakeLists.txt`), which supports GL 4.5 — so tessellation compiles in CI even though real macOS hardware caps at GL 4.1. Tests that need a GL context create a hidden `renderer::Window` and `GTEST_SKIP()` on `std::runtime_error` when no context is available (mirror `native/tests/renderer/window_test.cc`).
- macOS forward-compatible core contexts: requesting 4.1 core is the documented ceiling and is what we target.

---

## Task 1: Bump GL context to 4.1 core

**Files:**
- Modify: `native/src/renderer/window.cc:40-43`

- [ ] **Step 1: Change the context version hints**

In `native/src/renderer/window.cc`, replace the version hints (currently major 3 / minor 3):

```cpp
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 4);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 1);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GL_TRUE);
```

(Only the first two lines change from `3,3` to `4,1`; the profile + forward-compat lines stay exactly as they are.)

- [ ] **Step 2: Build the renderer library**

Run: `cmake -B build -S . && cmake --build build -j --target renderer`
Expected: compiles cleanly (no behavior change — just a context hint).

- [ ] **Step 3: Run the existing window tests to confirm context still comes up**

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R Window --output-on-failure`
Expected: PASS (or `SKIPPED` if the CI box truly has no GL — both are acceptable; a FAIL means 4.1 could not be obtained and must be investigated).

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/window.cc
git commit -m "feat(renderer): request OpenGL 4.1 core context for tessellation"
```

---

## Task 2: GL capability reporting (`gl_caps`)

A free function the runtime + later plans use to decide whether the tessellation path is available. Must be called with a current GL context.

**Files:**
- Create: `native/src/renderer/include/renderer/gl_caps.h`
- Create: `native/src/renderer/gl_caps.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `gl_caps.cc` to the `renderer` library sources)
- Test: `native/tests/renderer/gl_caps_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/gl_caps_test.cc`:

```cpp
// native/tests/renderer/gl_caps_test.cc
#include <gtest/gtest.h>

#include <renderer/gl_caps.h>
#include <renderer/window.h>

namespace {

TEST(GlCaps, ReportsTessellationAvailableUnderTestContext) {
    try {
        renderer::Window w(64, 64, "gl-caps-test", /*visible=*/false);
        const renderer::GlCaps caps = renderer::query_gl_caps();
        // The context was requested at 4.1; llvmpipe gives 4.5. Either way
        // tessellation (GL 4.0+) must be reported available.
        EXPECT_GE(caps.version_major, 4);
        EXPECT_TRUE(caps.tessellation_available);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

}  // namespace
```

Register it in `native/tests/renderer/CMakeLists.txt` by adding `gl_caps_test.cc` to the `add_executable(renderer_tests ...)` source list (alphabetical-ish; place after `glow_region_test.cc`).

- [ ] **Step 2: Run the test to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests`
Expected: FAIL to compile — `renderer/gl_caps.h` not found.

- [ ] **Step 3: Create the header**

Create `native/src/renderer/include/renderer/gl_caps.h`:

```cpp
// native/src/renderer/include/renderer/gl_caps.h
#pragma once

namespace renderer {

/// Snapshot of GL capabilities relevant to the hull-deformation pipeline.
/// Must be queried with a current GL context (see query_gl_caps()).
struct GlCaps {
    int  version_major = 0;
    int  version_minor = 0;
    bool tessellation_available = false;  // true iff context is >= GL 4.0
};

/// Query the current GL context. Requires a current context (call after
/// renderer::Window construction / glfwMakeContextCurrent).
GlCaps query_gl_caps();

}  // namespace renderer
```

- [ ] **Step 4: Create the implementation**

Create `native/src/renderer/gl_caps.cc`:

```cpp
// native/src/renderer/gl_caps.cc
#include "renderer/gl_caps.h"

#include <glad/glad.h>

namespace renderer {

GlCaps query_gl_caps() {
    GlCaps caps;
    glGetIntegerv(GL_MAJOR_VERSION, &caps.version_major);
    glGetIntegerv(GL_MINOR_VERSION, &caps.version_minor);
    // Tessellation control/evaluation shaders are core since GL 4.0.
    caps.tessellation_available =
        (caps.version_major > 4) ||
        (caps.version_major == 4 && caps.version_minor >= 0);
    return caps;
}

}  // namespace renderer
```

- [ ] **Step 5: Add `gl_caps.cc` to the renderer library**

In `native/src/renderer/CMakeLists.txt`, add `gl_caps.cc` to the `add_library(renderer STATIC ...)` source list (place it next to `shader.cc`).

- [ ] **Step 6: Build and run the test to verify it passes**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests && ctest --test-dir build -R GlCaps --output-on-failure`
Expected: PASS (or SKIPPED with no GL).

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/include/renderer/gl_caps.h \
        native/src/renderer/gl_caps.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/gl_caps_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): add gl_caps query for tessellation availability"
```

---

## Task 3: Tessellation-capable `Shader` constructor

Add a second constructor accepting optional TCS/TES sources. The existing 2-arg constructor is untouched (all current call sites keep working).

**Files:**
- Modify: `native/src/renderer/include/renderer/shader.h`
- Modify: `native/src/renderer/shader.cc`
- Test: `native/tests/renderer/shader_test.cc` (existing file — append a test)

- [ ] **Step 1: Write the failing test**

Append to `native/tests/renderer/shader_test.cc`:

```cpp
TEST(Shader, CompilesTessellationProgram) {
    try {
        renderer::Window w(64, 64, "tess-shader-test", /*visible=*/false);

        const char* vs = R"GLSL(#version 410 core
layout(location=0) in vec3 a_pos;
void main() { gl_Position = vec4(a_pos, 1.0); }
)GLSL";
        const char* tcs = R"GLSL(#version 410 core
layout(vertices=3) out;
void main() {
    if (gl_InvocationID == 0) {
        gl_TessLevelInner[0] = 1.0;
        gl_TessLevelOuter[0] = 1.0;
        gl_TessLevelOuter[1] = 1.0;
        gl_TessLevelOuter[2] = 1.0;
    }
    gl_out[gl_InvocationID].gl_Position = gl_in[gl_InvocationID].gl_Position;
}
)GLSL";
        const char* tes = R"GLSL(#version 410 core
layout(triangles, equal_spacing, cw) in;
void main() {
    gl_Position = gl_TessCoord.x * gl_in[0].gl_Position
                + gl_TessCoord.y * gl_in[1].gl_Position
                + gl_TessCoord.z * gl_in[2].gl_Position;
}
)GLSL";
        const char* fs = R"GLSL(#version 410 core
out vec4 frag;
void main() { frag = vec4(1.0); }
)GLSL";

        renderer::Shader prog(vs, tcs, tes, fs);
        EXPECT_NE(prog.program(), 0u);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}
```

(If `shader_test.cc` does not already `#include <renderer/window.h>`, add it near the top with the other includes.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `cmake --build build -j --target renderer_tests`
Expected: FAIL to compile — no `Shader(const char*, const char*, const char*, const char*)` overload (4-arg constructor does not exist).

- [ ] **Step 3: Declare the tessellation constructor**

In `native/src/renderer/include/renderer/shader.h`, add a second constructor declaration directly below the existing one (line 11):

```cpp
    Shader(const std::string& vertex_src, const std::string& fragment_src);

    /// Construct a tessellation pipeline program: vertex -> tessellation
    /// control -> tessellation evaluation -> fragment. Requires a GL 4.0+
    /// context. Pass GLSL with `#version 410 core`.
    Shader(const std::string& vertex_src,
           const std::string& tess_control_src,
           const std::string& tess_eval_src,
           const std::string& fragment_src);
```

- [ ] **Step 4: Implement the tessellation constructor**

In `native/src/renderer/shader.cc`, add after the existing constructor (after line 63). The `compile_stage` helper in the anonymous namespace already handles any stage enum, so reuse it. `GL_TESS_CONTROL_SHADER` / `GL_TESS_EVALUATION_SHADER` are provided by GLAD for a 4.1 loader.

```cpp
Shader::Shader(const std::string& vsrc,
               const std::string& tcsrc,
               const std::string& tesrc,
               const std::string& fsrc) {
    GLuint vs = compile_stage(GL_VERTEX_SHADER, vsrc);
    GLuint tcs = 0, tes = 0, fs = 0;
    auto cleanup = [&]() {
        if (vs) glDeleteShader(vs);
        if (tcs) glDeleteShader(tcs);
        if (tes) glDeleteShader(tes);
        if (fs) glDeleteShader(fs);
    };
    try {
        tcs = compile_stage(GL_TESS_CONTROL_SHADER, tcsrc);
        tes = compile_stage(GL_TESS_EVALUATION_SHADER, tesrc);
        fs = compile_stage(GL_FRAGMENT_SHADER, fsrc);
    } catch (...) {
        cleanup();
        throw;
    }
    program_ = glCreateProgram();
    glAttachShader(program_, vs);
    glAttachShader(program_, tcs);
    glAttachShader(program_, tes);
    glAttachShader(program_, fs);
    glLinkProgram(program_);
    GLint ok = 0;
    glGetProgramiv(program_, GL_LINK_STATUS, &ok);
    if (!ok) {
        GLint len = 0;
        glGetProgramiv(program_, GL_INFO_LOG_LENGTH, &len);
        std::vector<char> log(len > 0 ? len : 1);
        if (len > 0) glGetProgramInfoLog(program_, len, nullptr, log.data());
        glDeleteProgram(program_);
        program_ = 0;
        cleanup();
        throw std::runtime_error("renderer::Shader tess link failed: " +
                                 std::string(log.data()));
    }
    cleanup();
}
```

- [ ] **Step 5: Build and run the test to verify it passes**

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R "Shader.CompilesTessellationProgram" --output-on-failure`
Expected: PASS (or SKIPPED with no GL).

- [ ] **Step 6: Run the full shader test group to confirm no regression**

Run: `ctest --test-dir build -R Shader --output-on-failure`
Expected: all Shader tests PASS/SKIPPED.

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/include/renderer/shader.h \
        native/src/renderer/shader.cc \
        native/tests/renderer/shader_test.cc
git commit -m "feat(renderer): add tessellation (TCS/TES) Shader constructor"
```

---

## Task 4: Pass-through tessellation shader set + embed

Author the four GLSL files for an identity tessellation pass and wire them through the `embed_shader` mechanism so later plans (and the next task's test) can construct the program from embedded sources rather than inline literals.

**Files:**
- Create: `native/src/renderer/shaders/passthrough_tess.vert`
- Create: `native/src/renderer/shaders/passthrough_tess.tesc`
- Create: `native/src/renderer/shaders/passthrough_tess.tese`
- Create: `native/src/renderer/shaders/passthrough_tess.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (4 `embed_shader` calls)

- [ ] **Step 1: Create the vertex shader**

`native/src/renderer/shaders/passthrough_tess.vert`:

```glsl
#version 410 core
layout(location = 0) in vec3 a_pos;
void main() {
    gl_Position = vec4(a_pos, 1.0);
}
```

- [ ] **Step 2: Create the tessellation control shader**

`native/src/renderer/shaders/passthrough_tess.tesc`:

```glsl
#version 410 core
layout(vertices = 3) out;
void main() {
    if (gl_InvocationID == 0) {
        gl_TessLevelInner[0] = 1.0;
        gl_TessLevelOuter[0] = 1.0;
        gl_TessLevelOuter[1] = 1.0;
        gl_TessLevelOuter[2] = 1.0;
    }
    gl_out[gl_InvocationID].gl_Position = gl_in[gl_InvocationID].gl_Position;
}
```

- [ ] **Step 3: Create the tessellation evaluation shader**

`native/src/renderer/shaders/passthrough_tess.tese`:

```glsl
#version 410 core
layout(triangles, equal_spacing, cw) in;
void main() {
    gl_Position = gl_TessCoord.x * gl_in[0].gl_Position
                + gl_TessCoord.y * gl_in[1].gl_Position
                + gl_TessCoord.z * gl_in[2].gl_Position;
}
```

- [ ] **Step 4: Create the fragment shader**

`native/src/renderer/shaders/passthrough_tess.frag`:

```glsl
#version 410 core
out vec4 frag_color;
void main() {
    frag_color = vec4(1.0, 1.0, 1.0, 1.0);
}
```

- [ ] **Step 5: Embed the four shaders**

In `native/src/renderer/CMakeLists.txt`, add after the last existing `embed_shader(...)` line (the bloom ones):

```cmake
embed_shader(SHADER_PASSTHROUGH_TESS_VS  shaders/passthrough_tess.vert  passthrough_tess_vs)
embed_shader(SHADER_PASSTHROUGH_TESS_TCS shaders/passthrough_tess.tesc  passthrough_tess_tcs)
embed_shader(SHADER_PASSTHROUGH_TESS_TES shaders/passthrough_tess.tese  passthrough_tess_tes)
embed_shader(SHADER_PASSTHROUGH_TESS_FS  shaders/passthrough_tess.frag  passthrough_tess_fs)
```

**Note for implementer:** the `embed_shader` output variables (e.g. `SHADER_OPAQUE_VS`) are passed to `configure_file`/added to a custom target elsewhere in this same `CMakeLists.txt`. Find where the existing `SHADER_*` variables are consumed (search for `SHADER_OPAQUE_VS` in the file) and add the four new `SHADER_PASSTHROUGH_TESS_*` variables to the same list/target so the headers are generated. Do not invent a new mechanism.

- [ ] **Step 6: Build the renderer to generate the embedded headers**

Run: `cmake -B build -S . && cmake --build build -j --target renderer`
Expected: compiles; generated headers `embedded_passthrough_tess_{vs,tcs,tes,fs}.h` appear under `build/.../renderer/`.

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/shaders/passthrough_tess.vert \
        native/src/renderer/shaders/passthrough_tess.tesc \
        native/src/renderer/shaders/passthrough_tess.tese \
        native/src/renderer/shaders/passthrough_tess.frag \
        native/src/renderer/CMakeLists.txt
git commit -m "feat(renderer): add embedded pass-through tessellation shaders"
```

---

## Task 5: Prove the embedded tessellation program builds + tessellates

A GTest that constructs the `Shader` from the embedded sources and renders one patch into a tiny offscreen framebuffer, confirming the pipeline executes end-to-end (compile + link + draw with `GL_PATCHES`). This is the integration smoke test for the foundation.

**Files:**
- Create: `native/tests/renderer/tess_program_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/tess_program_test.cc`:

```cpp
// native/tests/renderer/tess_program_test.cc
#include <gtest/gtest.h>

#include <glad/glad.h>

#include <renderer/shader.h>
#include <renderer/window.h>

#include "embedded_passthrough_tess_vs.h"
#include "embedded_passthrough_tess_tcs.h"
#include "embedded_passthrough_tess_tes.h"
#include "embedded_passthrough_tess_fs.h"

namespace {

TEST(TessProgram, EmbeddedPassthroughCompilesLinksAndDraws) {
    try {
        renderer::Window w(64, 64, "tess-program-test", /*visible=*/false);

        renderer::Shader prog(renderer::shader_src::passthrough_tess_vs,
                              renderer::shader_src::passthrough_tess_tcs,
                              renderer::shader_src::passthrough_tess_tes,
                              renderer::shader_src::passthrough_tess_fs);
        ASSERT_NE(prog.program(), 0u);

        // One triangle patch (3 control points) in NDC.
        const float verts[] = {
            -0.5f, -0.5f, 0.0f,
             0.5f, -0.5f, 0.0f,
             0.0f,  0.5f, 0.0f,
        };
        GLuint vao = 0, vbo = 0;
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
        glEnableVertexAttribArray(0);

        glViewport(0, 0, 64, 64);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);

        prog.use();
        glPatchParameteri(GL_PATCH_VERTICES, 3);
        glDrawArrays(GL_PATCHES, 0, 3);

        // The pass-through FS writes white. Sample the centroid pixel; it
        // must be lit, proving the tessellated patch rasterized.
        unsigned char px[4] = {0, 0, 0, 0};
        glReadPixels(32, 24, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);

        EXPECT_EQ(glGetError(), GLenum(GL_NO_ERROR));
        EXPECT_GT(px[0], 200);  // red channel ~white

        glDeleteBuffers(1, &vbo);
        glDeleteVertexArrays(1, &vao);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

}  // namespace
```

Register `tess_program_test.cc` in `native/tests/renderer/CMakeLists.txt` (add to the `add_executable(renderer_tests ...)` source list).

**Note for implementer:** `tess_program_test.cc` `#include`s the generated `embedded_passthrough_tess_*.h` headers. Those land in the renderer library's binary dir. The `renderer_tests` target must have that directory on its include path. Check whether `renderer_tests` already sees the embedded headers (other tests may include them). If not, add the renderer binary include dir to `target_include_directories(renderer_tests PRIVATE ...)` — find how `embedded_opaque_vs.h` is made visible to existing tests and follow that exact pattern.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests`
Expected: FAIL — either the test isn't registered yet / embedded headers not found (before wiring), or once it builds it must actually run. First confirm a clean compile failure if the include path is missing, then fix the include path, then expect a real PASS in Step 3.

- [ ] **Step 3: Build and run the test to verify it passes**

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R "TessProgram" --output-on-failure`
Expected: PASS (or SKIPPED with no GL).

- [ ] **Step 4: Run the whole renderer test suite to confirm no regression from the GL bump**

Run: `ctest --test-dir build --output-on-failure`
Expected: all PASS/SKIPPED. (This is the key check that moving 3.3→4.1 broke nothing.)

- [ ] **Step 5: Commit**

```bash
git add native/tests/renderer/tess_program_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "test(renderer): smoke-test embedded pass-through tessellation pipeline"
```

---

## Task 6: Verify the full app still renders (manual)

The unit tests prove compile/link; this confirms the real binary still renders ships under the 4.1 context with no visual change.

**Files:** none (verification only)

- [ ] **Step 1: Build the full binary**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: `build/dauntless` builds.

- [ ] **Step 2: Launch and observe**

Run: `./build/dauntless`
Expected: the app launches and renders ships exactly as before the GL bump. No crash, no GL-version error at startup. (Per project memory, do not synthetic-click or full-screen capture Mark's workstation — a visual eyeball that ships render normally is sufficient. Close the window when done.)

- [ ] **Step 3: Record the result**

If rendering is unchanged, the foundation is complete. If the context fails to create at 4.1 on the target hardware, that is the §8 fallback case — note it; Plan 4 will gate the tessellation draw path on `query_gl_caps().tessellation_available` and fall back to the static path. No commit (no file change).

---

## Self-Review

**Spec coverage (Plan 1 scope = spec §3 GL bump + Shader class, §8 fallback signal):**
- §3 "GL context bump 3.3 → 4.1 core" → Task 1. ✓
- §3 "Shader class extended to accept optional TCS/TES stages" → Task 3. ✓
- §3 new `#version 410` tessellation shaders (foundation/pass-through) → Tasks 4–5. ✓
- §8 "detect at context creation … disable the deform pipeline … fall back" → Task 2 provides `query_gl_caps().tessellation_available`; Task 6 Step 3 names where the gate is consumed (Plan 4). ✓
- Adaptive TCS, TES displacement, crater uniforms, gouge FS, patch draw path in `frame.cc`, thickness bake, eligibility, config → **deferred to Plans 2–6 by design** (not Plan 1 gaps).

**Placeholder scan:** No TBD/TODO. Two "Note for implementer" callouts (Task 4 Step 5, Task 5 Step 1) point to existing in-file patterns to follow rather than prescribing exact CMake line numbers — this is deliberate because the embed-consumption block and the test include-path block are codebase-specific plumbing best discovered in-context; both name the exact existing symbol to grep for.

**Type consistency:** `GlCaps { version_major, version_minor, tessellation_available }` and `query_gl_caps()` are used identically in the header, impl, and `gl_caps_test.cc`. The 4-arg `Shader(vs, tcs, tes, fs)` signature matches across `shader.h`, `shader.cc`, `shader_test.cc`, and `tess_program_test.cc`. Embedded symbol names `passthrough_tess_{vs,tcs,tes,fs}` match between the `embed_shader` calls and the `#include`/`shader_src::` references in Task 5. ✓

---

## What comes next (not this plan)

- **Plan 2:** `HullCraterField` data layer + `Instance` member + `hull_deform_add` host binding (world→body transform, GU→model radius). Pure data; unit-tested.
- **Plan 3:** offline thickness bake + crushability vertex attribute + sidecar cache.
- **Plan 4:** real displacement pipeline (adaptive TCS, TES displacement + normal recompute, crater uniform upload, `frame.cc` patch draw path gated on `tessellation_available`).
- **Plan 5:** dent/gouge FS shading (triplanar `Damage.tga` + procedural) + Modern VFX config toggles.
- **Plan 6:** eligibility manager + `hull_deformation.py` mapping + `hit_feedback` dispatch hook.
