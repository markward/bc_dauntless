// native/tests/renderer/hull_clip_test.cc
//
// Tests for the hull-breach hole clip (Path C / hull-breach-2b).
//
// The hull fragment shader discards a fragment iff it is inside ANY active
// carve sphere. No fill texture is sampled — the sphere IS the clip primitive.
//
//  u_carve_enabled == 0  OR  u_carve_count == 0  → stock path (no discard).
//  u_carve_enabled == 1  AND fragment inside a sphere  → discard.
//  u_carve_enabled == 1  AND fragment OUTSIDE all spheres → renders.
//
// Test strategy: two layers.
//
// Layer 1 — CPU-only invariant (always runs, no GL):
//   A default-constructed HullCarveField has zero active slots / count()==0.
//   frame.cc only enables the clip when count() > 0, so a fresh instance
//   keeps u_carve_enabled==0 / u_carve_count==0 → stock path.
//
// Layer 2 — GL compile + draw + readback (skips without a GL context):
//   Draw a fullscreen triangle through the Pipeline's opaque program, reading
//   back from the default FBO. With identity matrices p_body == a_position,
//   so the centre fragment maps to body (0,0,0). Tests:
//     A) u_carve_enabled = 0                               → renders (no clip)
//     B) enabled, u_carve_count = 0                        → renders (stock)
//     C) enabled, covering sphere (radius 2, centre origin)→ DISCARDED
//     D) enabled, sphere NOT covering origin (offset 10)   → renders

#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <renderer/frame.h>
#include <renderer/hdr_target.h>
#include <renderer/nonfinite_probe.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <renderer/shader.h>
#include <renderer/carve_field_cache.h>

#include <scenegraph/hull_carve.h>
#include <scenegraph/instance.h>

#include <array>

// ── CPU invariant ──────────────────────────────────────────────────────────────

// Lock: a default-constructed HullCarveField has ALL slots inactive and
// count()==0.  frame.cc only enables the clip when count() > 0, so a fresh
// instance keeps the stock-BC path byte-identical (u_carve_enabled == 0).
TEST(HullCarveProductionPath, DefaultFieldHasNoActiveSlots) {
    scenegraph::HullCarveField f;
    for (const auto& s : f.slots()) {
        EXPECT_FALSE(s.active)
            << "default HullCarveField slot is active; frame.cc would enable the "
               "clip for a fresh instance, breaking the stock path";
    }
    EXPECT_EQ(f.count(), 0u)
        << "default HullCarveField count() must be 0 so the clip stays disabled";
}

// ── GL compile + draw + readback ───────────────────────────────────────────────

namespace {

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

        pipeline = std::make_unique<renderer::Pipeline>();

        // Fullscreen triangle, wound CCW to be front-facing under Pipeline's
        // glFrontFace(GL_CCW) (right-handed un-mirror, 2026-06-18). This test
        // exercises the carve-discard fragment shader, not winding, but culling
        // is on (GL_BACK), so the triangle must present its front face.
        const float verts[9] = {
            -1.0f, -1.0f, 0.0f,   // CCW: bottom-left
             3.0f, -1.0f, 0.0f,   //      bottom-right
            -1.0f,  3.0f, 0.0f,   //      top-left
        };
        glGenVertexArrays(1, &vao_);
        glGenBuffers(1, &vbo_);
        glBindVertexArray(vao_);
        glBindBuffer(GL_ARRAY_BUFFER, vbo_);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, nullptr);
        // a_normal (location 1) is left disabled, so opaque.vert reads the
        // "current value" below instead of a per-vertex array. This test's
        // synthetic triangle previously left it at the GL default (0,0,0),
        // and normalize(0,0,0) is NaN. That is not just a synthetic-fixture
        // artifact: mesh_build.cc only copies NIF vertex normals `if
        // (data.has_normals)`, and Mesh::Vertex::normal defaults to (0,0,0)
        // -- nothing in this codebase generates normals for a NIF that ships
        // without them, so a real mesh with has_normals == false reaches
        // opaque.frag with exactly this all-zero normal. It was harmless
        // before the ambient-gradient term: every existing use of n_shade is
        // behind max(x, 0.0), and GLSL specifies max(x,y) so that a NaN
        // operand loses to the other one -- a guaranteed spec behaviour, not
        // driver luck. The new `amb_d` multiply had no such clamp, so a NaN
        // n_shade poisoned the whole ambient term to NaN regardless of
        // u_ambient_gradient (fixed in opaque.frag with a clamp()). Facing
        // +Z here is correct for a fullscreen quad standing in for a hull
        // facing the camera.
        glVertexAttrib3f(1, 0.0f, 0.0f, 1.0f);
        glBindVertexArray(0);

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

    // Minimum uniforms opaque.frag needs. u_ship_world_inv = identity →
    // p_body == v_position_ws == a_position. Clip disabled by default.
    void set_uniforms(renderer::Shader& s) {
        s.use();
        s.set_mat4("u_view",  glm::mat4(1.0f));
        s.set_mat4("u_proj",  glm::mat4(1.0f));
        s.set_mat4("u_model", glm::mat4(1.0f));
        s.set_mat4("u_ship_world_inv", glm::mat4(1.0f));
        s.set_vec3("u_ambient_light",   glm::vec3(1.0f));
        // Two new uniforms the shader now reads. Set explicitly, matching
        // every other uniform in this function, so this hand-rolled minimal
        // set stays current with the shader's real minimum requirement: the
        // real render path (set_ambient_uniforms, frame.cc) always pushes
        // both of these every draw, and this test should not rely on
        // whatever the GL spec's zero default happens to be when it can
        // just say what it means. gradient=0 is the stock no-op value.
        // (This was NOT the cause of this test's earlier NaN failure --
        // that was a degenerate a_normal, see the glVertexAttrib3f comment
        // below. Leaving it here anyway is a correctness improvement, not
        // a workaround for anything measured on this driver.)
        s.set_vec3("u_ambient_dir_ws",    glm::vec3(0.0f, 1.0f, 0.0f));
        s.set_float("u_ambient_gradient", 0.0f);
        s.set_int("u_dir_light_count",  0);
        s.set_vec3("u_camera_pos_ws",   glm::vec3(0.0f, 0.0f, 1.0f));
        s.set_vec3("u_diffuse_color",   glm::vec3(1.0f));
        s.set_vec3("u_emissive_color",  glm::vec3(0.0f));
        s.set_float("u_emissive_scale", 1.0f);
        s.set_int("u_specular_enabled", 0);
        s.set_vec3("u_specular_color",  glm::vec3(0.0f));
        s.set_float("u_specular_power", 1.0f);
        s.set_float("u_rim_strength",   0.0f);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, white_tex_);
        s.set_int("u_base_color", 0);
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D, black_tex_);
        s.set_int("u_glow_map", 1);
        glActiveTexture(GL_TEXTURE2);
        glBindTexture(GL_TEXTURE_2D, black_tex_);
        s.set_int("u_specular_map", 2);
        // Shadows off, but the sampler2DShadow must still get its own unit (5)
        // so it never collides with the base sampler2D on unit 0
        // (GL_INVALID_OPERATION) — mirrors draw_model's unconditional assignment.
        s.set_int("u_shadows_enabled", 0);
        s.set_int("u_shadow_map", 5);
        s.set_int("u_decal_count",       0);
        s.set_float("u_decal_time",      0.0f);
        s.set_int("u_glow_region_count", 0);
        // Pure sphere clip: disabled by default.
        s.set_int("u_carve_enabled", 0);
        s.set_int("u_carve_count", 0);
        // Default carve normal (+Z) for every slot so the shallow-cap offset is
        // well-defined even before a test sets specific spheres.
        {
            std::array<glm::vec3, 24> normals;
            normals.fill(glm::vec3(0.0f, 0.0f, 1.0f));
            s.set_vec3_array("u_carve_normals", normals.data(),
                             static_cast<int>(normals.size()));
        }
        glActiveTexture(GL_TEXTURE0);
    }

    std::array<unsigned char, 4> read_center() const {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::array<unsigned char, 4> px{0, 0, 0, 0};
        glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        return px;
    }

    void draw() {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, kW, kH);
        glDisable(GL_DEPTH_TEST);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glBindVertexArray(vao_);
        glDrawArrays(GL_TRIANGLES, 0, 3);
        glBindVertexArray(0);
        glFinish();
    }
};

}  // namespace

// GL Test A: clip disabled (u_carve_enabled=0) → hull renders. Stock path.
TEST_F(HullClipTest, DisabledClipRendersHull) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);  // u_carve_enabled = 0
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in disabled-clip draw";
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2] << ") — disabled clip must not discard";
}

// GL Test B: clip enabled but no spheres (u_carve_count=0) → hull renders.
// This is the whole-hull-erosion regression guard: no sphere = no discard,
// even if u_carve_enabled is set.
TEST_F(HullClipTest, EnabledClipNoSpheresRendersHull) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    prog.set_int("u_carve_enabled", 1);
    prog.set_int("u_carve_count",   0);  // no spheres → no clip
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in enabled/no-spheres draw";
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — u_carve_count=0 must not discard (no whole-hull erosion)";
}

// GL Test C: clip enabled, covering sphere (radius 2, centre origin) →
// fragment at p_body=(0,0,0) is inside the sphere → DISCARDED.
TEST_F(HullClipTest, FragmentInsideSphereIsDiscarded) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    prog.set_int("u_carve_enabled", 1);
    // One sphere centred at origin, radius 2, normal +Z. The shallow cap sits at
    // cp = c + 0.55*r*n = (0,0,1.1); the fragment at p_body=(0,0,0) is L=1.1 from
    // the cap centre, well inside the minimum deformed radius (r*(1-0.25)=1.5),
    // so it discards regardless of the noise term. This is the breach hole.
    const glm::vec4 sphere(0.0f, 0.0f, 0.0f, 2.0f);
    const glm::vec3 normal(0.0f, 0.0f, 1.0f);
    prog.set_int("u_carve_count", 1);
    prog.set_vec4_array("u_carve_spheres", &sphere, 1);
    prog.set_vec3_array("u_carve_normals", &normal, 1);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in covering-sphere draw";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 64)
        << "Center pixel is bright (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — fragment inside carve sphere should be discarded (breach hole)";
}

// GL Test D: clip enabled, sphere offset far from origin → centre fragment
// p_body=(0,0,0) is OUTSIDE the sphere → hull renders.
TEST_F(HullClipTest, FragmentOutsideSphereRendersHull) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    prog.set_int("u_carve_enabled", 1);
    // Sphere centred at (10,10,10) with radius 1: nowhere near the origin.
    const glm::vec4 sphere(10.0f, 10.0f, 10.0f, 1.0f);
    const glm::vec3 normal(0.0f, 0.0f, 1.0f);
    prog.set_int("u_carve_count", 1);
    prog.set_vec4_array("u_carve_spheres", &sphere, 1);
    prog.set_vec3_array("u_carve_normals", &normal, 1);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in non-covering-sphere draw";
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — fragment outside carve sphere must NOT be discarded";
}

// GL Test E (regression): degenerate vertex normal + ambient gradient ON
// must not go non-finite -- AND must actually render, not just "not crash".
// n_shade = normalize(a_normal); with a_normal == (0,0,0) (this fixture's
// own attribute-1 default before this test overrides it -- see
// set_uniforms's comment on the +Z default) that is normalize(vec3(0)) ==
// NaN. This is not a synthetic-fixture-only concern: mesh_build.cc only
// copies NIF vertex normals `if (data.has_normals)`, and Mesh::Vertex::normal
// defaults to (0,0,0) -- nothing generates normals for a NIF that ships
// without them, so any real mesh with has_normals == false reaches
// opaque.frag with exactly this all-zero normal.
//
// Every OTHER use of n_shade in opaque.frag sits behind max(x, 0.0). GLSL
// defines max(x,y) as `y < x ? x : y`, so when x is NaN the comparison is
// false and y (the finite operand) wins -- a spec guarantee, not driver
// luck, and MEASURED to hold on this driver (NanMaxProbe scratch check:
// max(NaN,0.0) == max(0.0,NaN) == 0.0, min(NaN,1.0) == 1.0). The
// ambient-gradient dot product had no such clamp, so 0.0 * NaN == NaN (not
// 0 under IEEE 754) poisoned the whole ambient term even with the gradient
// mathematically "off". opaque.frag now guards it with
// clamp(amb_d, -1.0, 1.0) -- a no-op for the correct [-1,1] range of a
// dot product of two unit vectors, going through the same NaN-losing
// min/max machinery, and (unlike isnan()) also catching +-Inf. Two other
// idioms were tried and MEASURED not to survive this driver: a `v == v`
// self-compare and a bare isnan() both still left this test non-finite.
//
// Asserting only "no NaN/Inf" would pass vacuously on an undrawn or
// all-clear-color frame -- exactly the failure mode a wrong sample
// coordinate produced in FrameTest.AmbientGradientBrightensTheLitSideRelat-
// iveToTheShadowSide (see the report). Reading back the centre texel and
// checking it against the value the clamp's measured NaN->(-1) behaviour
// predicts rules that out: an undrawn frame would read the clear colour
// (0,0,0), not this.
TEST_F(HullClipTest, DegenerateNormalWithGradientOnStaysFinite) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    prog.set_vec3("u_ambient_dir_ws",   glm::vec3(1.0f, 0.0f, 0.0f));
    // 0.5, not 1.0: at gradient 1.0 the clamped-to-(-1) NaN drives
    // amb = light * (1 + 1*(-1)) = light * 0 to EXACTLY black, which is
    // indistinguishable from an undrawn frame reading back the clear
    // colour -- precisely the vacuous-pass risk this test exists to rule
    // out. At 0.5, amb = light * (1 + 0.5*(-1)) = light * 0.5, a specific
    // mid-grey no clear/undrawn/fully-lit frame would produce.
    prog.set_float("u_ambient_gradient", 0.5f);  // the vulnerable path: ON
    glVertexAttrib3f(1, 0.0f, 0.0f, 0.0f);       // force a_normal to (0,0,0)

    // An 8-bit backbuffer cannot hold a NaN -- it would already be baked
    // into some clamped value by the time anything reads it back, destroying
    // the evidence. Render to a float target instead, matching
    // FrameTest.RimEnabledPassProducesNoNonFiniteTexels's pattern.
    renderer::HdrTarget hdr;
    hdr.resize(kW, kH);
    hdr.bind();
    glDisable(GL_DEPTH_TEST);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);
    glFinish();

    // Read back while hdr's own FBO is still bound (read framebuffer ==
    // draw framebuffer after HdrTarget::bind()), before handing the texture
    // to the probe.
    float center[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_FLOAT, center);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);

    // u_ambient_light defaults to (1,1,1) in set_uniforms, u_diffuse_color
    // (1,1,1), base texture white, no directional/dynamic lights (count 0)
    // -- so the expected lit colour IS the ambient term alone, ~0.5 in every
    // channel. Only R is asserted: MEASURED (by reproducing it against the
    // pre-Task-2 shader, i.e. with none of this feature's code present) that
    // this driver has a separate, pre-existing artifact where a degenerate
    // (NaN) vertex normal zeroes the G and B channels of this synthetic
    // triangle's shaded output, regardless of the ambient-gradient guard --
    // R alone is unaffected by it and is sufficient to prove the guard
    // produces the intended ~0.5 value rather than an undrawn/clear-colour
    // frame (which would read exactly 0.0, not ~0.5).
    EXPECT_NEAR(center[0], 0.5f, 0.05f)
        << "R channel is " << center[0] << ", not the expected ~0.5 ambient "
           "-- the frame may not have rendered at all";

    renderer::NonfiniteProbe probe;
    const auto& r = probe.run(hdr.color_texture(), kW, kH);
    EXPECT_FALSE(r.any)
        << r.flagged_cells << " cell(s) went non-finite with a degenerate "
        << "normal and the ambient gradient on (cause code " << r.max_code
        << ") -- the amb_d NaN guard in opaque.frag is missing or broken";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

