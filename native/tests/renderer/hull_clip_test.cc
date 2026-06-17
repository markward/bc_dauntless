// native/tests/renderer/hull_clip_test.cc
//
// Tests for hull-breach carve-sphere fragment discard (Task 8).
//
// Test strategy: two layers.
//
// Layer 1 — CPU-only invariant (always runs, no GL):
//   A default-constructed HullCarveField has zero active slots. frame.cc
//   counts active slots into `nc` and calls set_int("u_carve_count", nc),
//   so a fresh instance produces u_carve_count == 0 and the shader's loop
//   never executes. This is the stock-path safety lock.
//
// Layer 2 — GL compile + draw + readback (skips without a GL context):
//   Draw a fullscreen triangle through the Pipeline's opaque program, reading
//   back from the default FBO (matching frame_test.cc's approach). Tests:
//     A) u_carve_count = 0  → hull renders (pixel non-zero)
//     B) u_carve_count = 1, covering sphere → fragments discarded (pixel zero)
//
//   The opaque.vert computes gl_Position = u_proj * u_view * u_model * a_position
//   and v_position_ws = (u_model * a_position).xyz. With all matrices identity:
//     v_position_ws = a_position (NDC coords of the vertex).
//   The opaque.frag computes p_body = u_ship_world_inv * v_position_ws. With
//   u_ship_world_inv = identity: p_body == v_position_ws == a_position.
//   A carve sphere at (0,0,0) with radius 1000 covers all fragments of the
//   fullscreen triangle (whose verts are at (-1,-1,0), (3,-1,0), (-1,3,0)).

#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <renderer/shader.h>

#include <scenegraph/hull_carve.h>
#include <scenegraph/instance.h>

// ── CPU invariant ──────────────────────────────────────────────────────────────

// Lock: a default-constructed HullCarveField has ALL slots inactive.
// This is the invariant that makes frame.cc produce u_carve_count == 0 for a
// fresh instance, keeping the stock-BC path byte-identical.
TEST(HullCarveProductionPath, DefaultFieldHasNoActiveSlots) {
    scenegraph::HullCarveField f;
    for (const auto& s : f.slots()) {
        EXPECT_FALSE(s.active)
            << "default HullCarveField slot is active; frame.cc would set "
               "u_carve_count > 0 for a fresh instance, breaking the stock path";
    }
}

// Lock: replicating frame.cc's active-count loop over a default field yields 0.
TEST(HullCarveProductionPath, ActiveCountLoopYieldsZeroForDefaultField) {
    scenegraph::HullCarveField f;
    int nc = 0;
    for (const auto& s : f.slots()) {  // mirrors frame.cc draw_model carve block
        if (!s.active) continue;
        ++nc;
    }
    EXPECT_EQ(nc, 0)
        << "frame.cc would set u_carve_count == " << nc << " for a default "
           "HullCarveField; must be 0 so the shader skips the carve loop";
}

// ── GL compile + draw + readback ───────────────────────────────────────────────

namespace {

// Width/height chosen to match the window dimensions exactly to avoid
// HiDPI / framebuffer scaling confusion on macOS. We read back at center.
static constexpr int kW = 64;
static constexpr int kH = 64;

class HullClipTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   w;
    std::unique_ptr<renderer::Pipeline> pipeline;
    GLuint vao_       = 0;
    GLuint vbo_       = 0;
    GLuint white_tex_ = 0;
    GLuint black_tex_ = 0;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "hull-clip-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }

        // Build the full pipeline so we have the real compiled opaque.frag.
        pipeline = std::make_unique<renderer::Pipeline>();

        // Fullscreen triangle: vertices cover the entire NDC square.
        // With u_proj = u_view = u_model = identity:
        //   gl_Position = a_position → fills the entire viewport.
        //   v_position_ws = a_position (used by opaque.frag as world pos).
        //
        // Pipeline::Pipeline() sets glFrontFace(GL_CW) (BC NIF models are
        // D3D-wound CW). Our triangle must also wind CW so it is treated as
        // a front face and drawn, not culled as a back face.
        const float verts[9] = {
            -1.0f, -1.0f, 0.0f,   // CW: bottom-left
            -1.0f,  3.0f, 0.0f,   //     top-left
             3.0f, -1.0f, 0.0f,   //     bottom-right
        };
        glGenVertexArrays(1, &vao_);
        glGenBuffers(1, &vbo_);
        glBindVertexArray(vao_);
        glBindBuffer(GL_ARRAY_BUFFER, vbo_);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        // a_position is at attribute location 0 in opaque.vert.
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, nullptr);
        glBindVertexArray(0);

        // 1×1 white / black fallback textures for base_color / glow / spec.
        white_tex_ = make_tex(255, 255, 255);
        black_tex_ = make_tex(0, 0, 0);
    }

    void TearDown() override {
        if (vbo_)       { glDeleteBuffers(1, &vbo_);        vbo_       = 0; }
        if (vao_)       { glDeleteVertexArrays(1, &vao_);   vao_       = 0; }
        if (white_tex_) { glDeleteTextures(1, &white_tex_); white_tex_ = 0; }
        if (black_tex_) { glDeleteTextures(1, &black_tex_); black_tex_ = 0; }
    }

    static GLuint make_tex(unsigned char r, unsigned char g, unsigned char b) {
        GLuint t = 0;
        glGenTextures(1, &t);
        glBindTexture(GL_TEXTURE_2D, t);
        const unsigned char px[4] = {r, g, b, 255};
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, px);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        return t;
    }

    // Upload the minimum uniforms opaque.frag needs so it does not crash.
    // u_ship_world_inv = identity → p_body == v_position_ws == a_position.
    // u_carve_count is set to 0; call set_int("u_carve_count", 1) + set_vec4_array
    // afterward to activate the carve loop.
    void set_uniforms(renderer::Shader& s) {
        s.use();
        s.set_mat4("u_view",  glm::mat4(1.0f));
        s.set_mat4("u_proj",  glm::mat4(1.0f));
        s.set_mat4("u_model", glm::mat4(1.0f));
        // world→body: identity so p_body == v_position_ws.
        s.set_mat4("u_ship_world_inv", glm::mat4(1.0f));
        // Full ambient + no dir lights → lit = ambient * diffuse * base = white.
        s.set_vec3("u_ambient_light",   glm::vec3(1.0f));
        s.set_int("u_dir_light_count",  0);
        s.set_vec3("u_camera_pos_ws",   glm::vec3(0.0f, 0.0f, 1.0f));
        // White diffuse, no emissive, no specular, no rim.
        s.set_vec3("u_diffuse_color",   glm::vec3(1.0f));
        s.set_vec3("u_emissive_color",  glm::vec3(0.0f));
        s.set_float("u_emissive_scale", 1.0f);
        s.set_int("u_specular_enabled", 0);
        s.set_vec3("u_specular_color",  glm::vec3(0.0f));
        s.set_float("u_specular_power", 1.0f);
        s.set_float("u_rim_strength",   0.0f);
        // Bind 1×1 white/black textures.
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, white_tex_);
        s.set_int("u_base_color", 0);
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D, black_tex_);
        s.set_int("u_glow_map", 1);
        glActiveTexture(GL_TEXTURE2);
        glBindTexture(GL_TEXTURE_2D, black_tex_);
        s.set_int("u_specular_map", 2);
        // Disable decals, glow regions, and carves.
        s.set_int("u_decal_count",       0);
        s.set_float("u_decal_time",      0.0f);
        s.set_int("u_glow_region_count", 0);
        s.set_int("u_carve_count",       0);
    }

    // Read the center pixel from the default (window) framebuffer.
    std::array<unsigned char, 4> read_center() const {
        // Ensure we're reading from the default framebuffer (same as frame_test.cc).
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::array<unsigned char, 4> px{0, 0, 0, 0};
        glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        return px;
    }
};

}  // namespace

// GL Test A: with u_carve_count = 0, the hull renders (pixel != clear black).
// Regression guard: zero carves must not discard any fragment.
//
// Lit output = ambient * diffuse * base = (1,1,1) * (1,1,1) * white = white.
// If discard fires spuriously, pixel stays black (clear color).
TEST_F(HullClipTest, ZeroCarveCountRendersHull) {
    // Draw to the default (window) FBO, mirroring frame_test.cc.
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, kW, kH);
    glDisable(GL_DEPTH_TEST);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);   // black clear
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);  // u_carve_count = 0

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in zero-carve draw";

    auto px = read_center();
    // Hull = white (255, 255, 255). Zero carves must NOT discard.
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0]
        << " G=" << (int)px[1] << " B=" << (int)px[2]
        << ") — u_carve_count=0 must not discard any fragment";
}

// GL Test B: with u_carve_count = 1 and a sphere covering all fragments,
// the center pixel stays the clear color (all fragments discarded).
//
// Clear to black. Hull = white. Discard → pixel = black (clear).
TEST_F(HullClipTest, CarveSphereDiscardsCoveredFragment) {
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, kW, kH);
    glDisable(GL_DEPTH_TEST);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);   // black clear
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::Shader& prog = pipeline->opaque_shader();
    // u_ship_world_inv = identity → p_body == v_position_ws == a_position.
    // Triangle verts are within [-1, 3] in XY, z=0.
    // Carve sphere at (0,0,0) radius 1000 covers all fragments.
    set_uniforms(prog);

    const glm::vec4 sphere(0.0f, 0.0f, 0.0f, 1000.0f);
    prog.set_int("u_carve_count", 1);
    prog.set_vec4_array("u_carve", &sphere, 1);

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in carve draw";

    auto px = read_center();
    // Discard → framebuffer stays at clear (black = 0,0,0).
    // No discard → hull renders white (255,255,255).
    // The test distinguishes: if carve discard doesn't work, pixel is bright.
    EXPECT_LT(px[0] + px[1] + px[2], 64)
        << "Center pixel is bright (R=" << (int)px[0]
        << " G=" << (int)px[1] << " B=" << (int)px[2]
        << ") — carve sphere should have discarded all fragments (pixel = clear black)";
}
