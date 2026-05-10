# Glow-Map Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the opaque pass to add emissive/glow-map contribution so ship
windows and engine lights illuminate correctly.

**Architecture:** Shader gets two new uniforms (`u_glow_map`, `u_emissive_color`).
`FrameSubmitter` grows a black 1×1 fallback texture (symmetric with the existing
white one) and binds the glow stage texture to unit 1 per mesh. No new render
pass; no post-process bloom.

**Tech Stack:** GLSL 330, OpenGL 3.3, C++20, GoogleTest, pytest + pybind11.

---

## File Map

| File | Change |
|---|---|
| `native/src/renderer/shaders/opaque.frag` | Add `u_glow_map` + `u_emissive_color`; compute `lit + emissive + glow` |
| `native/src/renderer/include/renderer/frame.h` | Add `black_texture_` member + `ensure_black_texture()` declaration |
| `native/src/renderer/frame.cc` | `ensure_black_texture()`, update destructor, `draw_model()`, `submit_opaque()` |
| `native/tests/renderer/frame_test.cc` | New `GlowContributesWithZeroAmbient` test |
| `tests/host/test_glow_pass.py` | New file — Python headless pixel test |

---

## Task 1: Write the failing C++ test

**Files:**
- Modify: `native/tests/renderer/frame_test.cc:48-88` (append after existing test)

- [ ] **Step 1.1: Append the test to frame_test.cc**

  Open `native/tests/renderer/frame_test.cc`. After the closing `}` of
  `TEST_F(FrameTest, OpaquePassRunsWithoutGLError)` and before the final `}`
  of the anonymous namespace, add:

  ```cpp
  TEST_F(FrameTest, GlowContributesWithZeroAmbient) {
      auto model_h = cache->load(kGalaxyNif, kGalaxyTex);

      scenegraph::World world;
      auto iid = world.create_instance(
          reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
      world.set_world_transform(iid, glm::mat4(1.0f));

      scenegraph::Camera cam;
      cam.eye    = glm::vec3(0.0f, 0.0f, 1500.0f);
      cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
      cam.aspect = 1.0f;

      glViewport(0, 0, 256, 256);
      glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
      glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

      renderer::FrameSubmitter submitter;
      renderer::Lighting zero_lighting;
      zero_lighting.ambient           = glm::vec3(0.0f);
      zero_lighting.directional_count = 0;
      submitter.submit_opaque(world, cam, *p,
          [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
              return reinterpret_cast<const assets::Model*>(h);
          }, zero_lighting);

      EXPECT_EQ(glGetError(), GL_NO_ERROR);

      // Scan a 5×5 grid across the saucer section; at least one pixel must be
      // non-zero to prove the glow pass contributed.  Clear colour is black so
      // background pixels are also 0 — only glow raises a pixel above 0.
      int max_total = 0;
      for (int dx = -40; dx <= 40; dx += 20) {
          for (int dy = -40; dy <= 40; dy += 20) {
              unsigned char px[4] = {0};
              glReadPixels(128 + dx, 128 + dy, 1, 1,
                           GL_RGBA, GL_UNSIGNED_BYTE, px);
              int t = px[0] + px[1] + px[2];
              if (t > max_total) max_total = t;
          }
      }
      EXPECT_GT(max_total, 0)
          << "Expected glow to contribute to at least one pixel with zero "
             "ambient lighting; all sampled pixels were black.";
  }
  ```

- [ ] **Step 1.2: Build renderer_tests**

  ```bash
  cmake --build /Users/mward/Documents/Projects/open_stbc/build \
        --target renderer_tests -j$(sysctl -n hw.logicalcpu)
  ```

  Expected: builds successfully (no compile errors — the test uses no new API).

- [ ] **Step 1.3: Run the new test and verify it fails**

  ```bash
  GALLIUM_DRIVER=llvmpipe \
  /Users/mward/Documents/Projects/open_stbc/build/native/tests/renderer/renderer_tests \
      --gtest_filter=FrameTest.GlowContributesWithZeroAmbient
  ```

  Expected: `[ FAILED ] FrameTest.GlowContributesWithZeroAmbient`
  with message like `Expected max_total > 0 but got 0` or the test is
  skipped (no BC assets). Either outcome means the test itself is wired
  correctly; proceed to Task 2.

---

## Task 2: Write the failing Python test

**Files:**
- Create: `tests/host/test_glow_pass.py`

- [ ] **Step 2.1: Create the test file**

  Create `tests/host/test_glow_pass.py` with the following content:

  ```python
  """Test that the glow/emissive pass adds light to a zero-ambient render.

  The Galaxy NIF has glow textures on its hull, nacelles, and bridge section.
  With ambient=0 and no directionals, a correctly-implemented glow pass
  illuminates mesh pixels above zero; without it every mesh pixel is black
  (total brightness 0, below the background clear-colour level of ≈57).
  """
  import os
  from pathlib import Path

  import pytest

  PROJECT_ROOT = Path(__file__).parent.parent.parent
  GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
  GALAXY_TEX = PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "FedShips" / "High"


  def test_glow_contributes_to_unlit_frame():
      """With zero ambient and no directionals, glow textures must illuminate
      at least one sampled pixel above the background clear-colour level.

      The Galaxy has multiple glow textures (hull, nacelles, bridge); scanning
      a 7×5 grid across the saucer section ensures at least one sample lands on
      a glow-textured face even if the exact centre pixel is on dark hull.
      """
      if not GALAXY_NIF.is_file():
          pytest.skip(f"BC asset not available at {GALAXY_NIF}")
      if not GALAXY_TEX.is_dir():
          pytest.skip(f"BC texture dir not available at {GALAXY_TEX}")

      os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
      import _open_stbc_host

      _open_stbc_host.init(640, 360, "test_glow_unlit")
      try:
          h = _open_stbc_host.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
          iid = _open_stbc_host.create_instance(h)
          _open_stbc_host.set_world_transform(iid, [
              1.0, 0.0, 0.0, 0.0,
              0.0, 1.0, 0.0, 0.0,
              0.0, 0.0, 1.0, 0.0,
              0.0, 0.0, 0.0, 1.0,
          ])
          _open_stbc_host.set_camera(
              eye=(0.0, 0.0, 1500.0),
              target=(0.0, 0.0, 0.0),
              up=(0.0, 1.0, 0.0),
              fov_y_rad=1.0472,
              near=1.0,
              far=100000.0,
          )

          # Zero ambient, no directionals: only glow contributes to mesh pixels.
          _open_stbc_host.set_lighting((0.0, 0.0, 0.0), [])
          _open_stbc_host.frame()

          fw, fh = _open_stbc_host.framebuffer_size()
          cx, cy = fw // 2, fh // 2

          # Scan a 7×5 grid centred on the saucer.  Background pixels have
          # r+g+b ≈ 57 (clear colour 0.05/0.07/0.10 × 255); mesh pixels with
          # zero lighting are 0; glowing mesh pixels must exceed 80.
          max_brightness = 0
          for dx in range(-60, 61, 20):
              for dy in range(-40, 41, 20):
                  r, g, b, _ = _open_stbc_host.read_pixel(cx + dx, cy + dy)
                  max_brightness = max(max_brightness, r + g + b)

          assert max_brightness > 80, (
              f"Expected glow to illuminate at least one sampled pixel above "
              f"background level (≈57) with zero ambient lighting; "
              f"max r+g+b across saucer region = {max_brightness}."
          )
      finally:
          _open_stbc_host.destroy_instance(iid)
          _open_stbc_host.shutdown()
          os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)
  ```

- [ ] **Step 2.2: Run the test and verify it fails**

  ```bash
  cd /Users/mward/Documents/Projects/open_stbc && \
  uv run pytest tests/host/test_glow_pass.py::test_glow_contributes_to_unlit_frame -v
  ```

  Expected outcomes (either is acceptable at this stage):
  - `SKIPPED` if BC assets are not present — proceed to Task 3.
  - `FAILED` with `AssertionError: max r+g+b ... = 57` — proves the test
    correctly catches missing glow.

---

## Task 3: Update the fragment shader

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag`

- [ ] **Step 3.1: Replace opaque.frag with the glow-aware version**

  Replace the entire file with:

  ```glsl
  #version 330 core

  in vec3 v_normal_ws;
  in vec2 v_uv;

  uniform sampler2D u_base_color;
  uniform vec3 u_diffuse_color;

  uniform sampler2D u_glow_map;
  uniform vec3 u_emissive_color;

  uniform vec3 u_ambient_light;

  const int MAX_DIR_LIGHTS = 4;
  uniform int  u_dir_light_count;
  uniform vec3 u_dir_light_dir_ws[MAX_DIR_LIGHTS];   // direction TOWARD the light
  uniform vec3 u_dir_light_color[MAX_DIR_LIGHTS];    // color × dimmer

  out vec4 frag_color;

  void main() {
      vec3 n = normalize(v_normal_ws);
      vec3 lit_dir = vec3(0.0);
      for (int i = 0; i < u_dir_light_count; ++i) {
          float ndotl = max(dot(n, normalize(u_dir_light_dir_ws[i])), 0.0);
          lit_dir += ndotl * u_dir_light_color[i];
      }
      vec4 tex  = texture(u_base_color, v_uv);
      vec3 lit  = (u_ambient_light + lit_dir) * u_diffuse_color * tex.rgb;
      vec4 glow = texture(u_glow_map, v_uv);
      frag_color = vec4(lit + u_emissive_color + glow.rgb * glow.a, 1.0);
  }
  ```

  No other files need touching for this step.

---

## Task 4: Update frame.h

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h:71-77`

- [ ] **Step 4.1: Add black_texture_ member and ensure_black_texture() declaration**

  In the `private:` section of `FrameSubmitter`, after the `ensure_white_texture()`
  declaration, add the symmetric black counterpart:

  ```cpp
  private:
      std::uint32_t white_texture_ = 0;
      std::uint32_t ensure_white_texture();

      std::uint32_t black_texture_ = 0;
      std::uint32_t ensure_black_texture();
  ```

  The full updated `private:` block should look exactly like this:

  ```cpp
  private:
      /// Lazily-allocated 1x1 white texture used as a fallback when a material
      /// has no Base-stage texture. Keeps the sampler bound to a valid object
      /// so the shader's texture(...) sample returns white instead of black
      /// (the GL "zero texture") and the lighting math actually shows up.
      std::uint32_t white_texture_ = 0;
      std::uint32_t ensure_white_texture();

      /// Lazily-allocated 1x1 black texture (RGBA 0,0,0,255) used as the
      /// fallback for the Glow stage when a mesh has no glow texture.
      /// Sampling it returns (0,0,0,1) so the glow term contributes nothing.
      std::uint32_t black_texture_ = 0;
      std::uint32_t ensure_black_texture();
  ```

---

## Task 5: Update frame.cc

**Files:**
- Modify: `native/src/renderer/frame.cc`

- [ ] **Step 5.1: Add ensure_black_texture() implementation**

  After `ensure_white_texture()` (ends around line 91), add the symmetric
  black version:

  ```cpp
  std::uint32_t FrameSubmitter::ensure_black_texture() {
      if (black_texture_ != 0) return black_texture_;
      GLuint t = 0;
      glGenTextures(1, &t);
      glBindTexture(GL_TEXTURE_2D, t);
      const std::uint8_t black[4] = {0, 0, 0, 255};
      glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, black);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
      black_texture_ = t;
      return black_texture_;
  }
  ```

- [ ] **Step 5.2: Update the destructor to release black_texture_**

  The existing destructor only releases `white_texture_`. Replace it with:

  ```cpp
  FrameSubmitter::~FrameSubmitter() {
      if (white_texture_ != 0) {
          GLuint t = white_texture_;
          glDeleteTextures(1, &t);
          white_texture_ = 0;
      }
      if (black_texture_ != 0) {
          GLuint t = black_texture_;
          glDeleteTextures(1, &t);
          black_texture_ = 0;
      }
  }
  ```

- [ ] **Step 5.3: Update draw_model() to bind the glow stage**

  Add `GLuint black_fallback` as a fifth parameter and, inside the mesh loop,
  bind the Glow stage texture to unit 1 and set `u_emissive_color`.

  Replace the entire `draw_model` function (lines 24–66) with:

  ```cpp
  void draw_model(const assets::Model& model,
                  const glm::mat4& world,
                  Shader& shader,
                  GLuint white_fallback,
                  GLuint black_fallback) {
      std::vector<glm::mat4> world_per_node(model.nodes.size(), glm::mat4(1.0f));
      if (!model.nodes.empty()) {
          world_per_node[model.root_node] = world * model.nodes[model.root_node].local_transform;
      }
      for (std::size_t i = 0; i < model.nodes.size(); ++i) {
          const auto& node = model.nodes[i];
          if (node.parent_index >= 0) {
              world_per_node[i] = world_per_node[node.parent_index] * node.local_transform;
          }
          for (int mesh_idx : node.meshes) {
              const auto& mesh = model.meshes[mesh_idx];
              shader.set_mat4("u_model", world_per_node[i]);

              const auto& mat = (mesh.material_index() >= 0
                  ? model.materials[mesh.material_index()]
                  : assets::Material{});
              shader.set_vec3("u_diffuse_color", mat.diffuse);
              shader.set_vec3("u_emissive_color", mat.emissive);

              const int base_tex = mat.stages[
                  static_cast<std::size_t>(assets::Material::StageSlot::Base)
              ].texture_index;
              glActiveTexture(GL_TEXTURE0);
              if (base_tex >= 0) {
                  glBindTexture(GL_TEXTURE_2D, model.textures[base_tex].id());
              } else {
                  glBindTexture(GL_TEXTURE_2D, white_fallback);
              }
              shader.set_int("u_base_color", 0);

              const int glow_tex = mat.stages[
                  static_cast<std::size_t>(assets::Material::StageSlot::Glow)
              ].texture_index;
              glActiveTexture(GL_TEXTURE1);
              if (glow_tex >= 0) {
                  glBindTexture(GL_TEXTURE_2D, model.textures[glow_tex].id());
              } else {
                  glBindTexture(GL_TEXTURE_2D, black_fallback);
              }
              shader.set_int("u_glow_map", 1);

              glBindVertexArray(mesh.vao());
              glDrawElements(GL_TRIANGLES, mesh.index_count(), GL_UNSIGNED_INT, nullptr);
          }
      }
      glBindVertexArray(0);
  }
  ```

- [ ] **Step 5.4: Update submit_opaque() to pass the black fallback**

  In `submit_opaque()`, after `ensure_white_texture()`, call
  `ensure_black_texture()` and pass it to `draw_model`. Replace:

  ```cpp
      const GLuint white = ensure_white_texture();

      world.for_each_visible([&](const scenegraph::Instance& inst) {
          const assets::Model* m = lookup(inst.model_handle);
          if (m) draw_model(*m, inst.world, shader, white);
      });
  ```

  With:

  ```cpp
      const GLuint white = ensure_white_texture();
      const GLuint black = ensure_black_texture();

      world.for_each_visible([&](const scenegraph::Instance& inst) {
          const assets::Model* m = lookup(inst.model_handle);
          if (m) draw_model(*m, inst.world, shader, white, black);
      });
  ```

---

## Task 6: Build and verify C++ tests

- [ ] **Step 6.1: Build renderer_tests and _open_stbc_host**

  ```bash
  cmake --build /Users/mward/Documents/Projects/open_stbc/build \
        --target renderer_tests _open_stbc_host -j$(sysctl -n hw.logicalcpu)
  ```

  Expected: clean build, no errors or warnings about unused uniforms.

- [ ] **Step 6.2: Run the full renderer test suite**

  ```bash
  GALLIUM_DRIVER=llvmpipe \
  /Users/mward/Documents/Projects/open_stbc/build/native/tests/renderer/renderer_tests \
      --gtest_filter=FrameTest.*
  ```

  Expected both pass (or skip when BC assets absent):
  - `[ OK ] FrameTest.OpaquePassRunsWithoutGLError`
  - `[ OK ] FrameTest.GlowContributesWithZeroAmbient`

---

## Task 7: Run the Python test

- [ ] **Step 7.1: Run the glow integration test**

  ```bash
  cd /Users/mward/Documents/Projects/open_stbc && \
  uv run pytest tests/host/test_glow_pass.py -v
  ```

  Expected:
  - `PASSED tests/host/test_glow_pass.py::test_glow_contributes_to_unlit_frame`
    (when BC assets present), or
  - `SKIPPED` (when BC assets absent — acceptable).

- [ ] **Step 7.2: Run the full Python test suite for regressions**

  ```bash
  cd /Users/mward/Documents/Projects/open_stbc && uv run pytest tests/ -x -q
  ```

  Expected: no new failures.

---

## Task 8: Commit

- [ ] **Step 8.1: Stage and commit all changes**

  ```bash
  git add \
    native/src/renderer/shaders/opaque.frag \
    native/src/renderer/include/renderer/frame.h \
    native/src/renderer/frame.cc \
    native/tests/renderer/frame_test.cc \
    tests/host/test_glow_pass.py
  git commit -m "$(cat <<'EOF'
  feat(renderer): emissive/glow-map rendering for ship models

  Extends the opaque pass to sample NiTexturingProperty.glow (StageSlot::Glow)
  and add NiMaterialProperty.emissive as an additive term over the lit result.
  Ships with glow textures (windows, engine nacelles) now self-illuminate
  correctly in fully-dark scenes.

  - opaque.frag: u_glow_map (unit 1) + u_emissive_color; final output is
    lit + emissive_color + glow.rgb * glow.a
  - FrameSubmitter: symmetric black 1×1 fallback for missing Glow stage
  - draw_model: binds glow texture to GL_TEXTURE1, sets both new uniforms
  - Tests: C++ GlowContributesWithZeroAmbient (reliable GL_BACK read);
           Python test_glow_contributes_to_unlit_frame (headless pixel scan)

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Self-Review

**Spec coverage:**
- ✅ `u_glow_map` + `u_emissive_color` uniforms in fragment shader
- ✅ Formula: `out = lit + emissive_color + glow.rgb * glow.a`
- ✅ Black 1×1 fallback for missing glow stage
- ✅ Same StageSlot::Glow lookup as Base (just different slot)
- ✅ `u_emissive_color` set per mesh from `mat.emissive`
- ✅ `u_glow_map = 1` (tex unit 1)
- ✅ C++ test reads GL_BACK (pre-swap); Python test follows headless pattern
- ✅ Neither test skips on platform — only on missing BC assets
- ✅ No bloom pass, no specular, no AddLOD search-string logic

**Placeholder scan:** None found.

**Type consistency:** `GLuint white_fallback, GLuint black_fallback` — both
`GLuint`, added in Task 4→5 and consumed in same Task 5. `std::uint32_t` in
the header matches `GLuint` (both `unsigned int` on all GL targets).
