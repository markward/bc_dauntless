// native/tests/renderer/hull_field_clip_test.cc
//
// Tests for the per-instance hull-field clip (hull-volume-field-transport,
// Task 5): opaque.frag samples voxel::DistanceField data packed into a 2D
// slice atlas (voxel/field_atlas.h) instead of the fixed 24-sphere array, and
// discards a hull fragment when the sampled value reads OUTSIDE the hull.
//
//  u_hull_field_enabled == 0                       -> stock path (no discard;
//                                                      zero per-fragment cost)
//  u_hull_field_enabled == 1 AND sample says INSIDE -> renders
//  u_hull_field_enabled == 1 AND sample says OUTSIDE -> discard
//  u_carve_invert == 1 flips both of the enabled cases (the stencil-marking
//  pass keeps exactly what the normal pass would have discarded).
//
// Test strategy, modelled on hull_clip_test.cc: GL compile + draw + readback,
// skipping without a GL context. With identity view/model/proj/ship_world_inv
// matrices, the fullscreen triangle's interpolated a_position IS p_body, so
// the CENTRE fragment always reads p_body == (0, 0, 0).
//
// Every probe field here is built so p_body == (0,0,0) samples EXACTLY ONE
// stored cell with zero interpolation blend on any axis: dims (4,4,4), cell
// (1,1,1), origin (-2.5,-2.5,-2.5) puts (0,0,0) at cell-space g = (2.5,2.5,2.5),
// and the shader's sample-space is g - 0.5 = (2,2,2) exactly -- an integer on
// every axis, so X/Y hardware bilinear and the hand-rolled Z lerp both
// degenerate to reading cell (2,2,2) alone. That is the ONE cell each test
// sets to a specific value; every other cell stays deep inside (-100) so nothing
// else can leak into the sampled result even with sub-ULP filtering fuzz.

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

#include <scenegraph/hull_carve.h>
#include <scenegraph/instance.h>

#include <voxel/distance_field.h>
#include <voxel/field_atlas.h>

#include <array>
#include <cstdint>
#include <vector>

namespace {

static constexpr int kW = 64;
static constexpr int kH = 64;

// Deep-inside baseline everywhere except cell (2,2,2), which the centre
// fragment samples exactly (see file header). `center_value` is the raw
// int8 distance-field byte (model units, scale == 1.0 here): positive means
// outside the hull (a carved cavity, or genuinely outside), negative means
// solidly inside.
voxel::DistanceField make_probe_field(std::int8_t center_value) {
    voxel::DistanceField f;
    f.dims   = glm::ivec3(4, 4, 4);
    f.origin = glm::vec3(-2.5f, -2.5f, -2.5f);
    f.cell   = glm::vec3(1.0f);
    f.scale  = 1.0f;
    f.dist.assign(static_cast<std::size_t>(4 * 4 * 4),
                  static_cast<std::int8_t>(-100));
    f.dist[f.index(2, 2, 2)] = center_value;
    return f;
}

// Mirrors InstanceFieldCache::upload()'s GL_R8 upload (renderer/
// instance_field_cache.cc), so the test exercises the SAME texture format
// and filtering the production path uploads. Builds and leaves the texture
// bound directly on unit 6 (never on "whatever unit happens to be active"):
// an earlier version of this helper built the texture on the CALLER's
// active unit, which was unit 0 (set_uniforms leaves it there) -- silently
// clobbering the base-colour texture set_uniforms had just bound, so every
// "enabled" test rendered black regardless of the clip logic under test.
// Caught by running the RED build: FragmentInsideCarvedRegionIsDiscarded
// passed even against the pre-Task-5 shader, which cannot legitimately
// discard anything.
GLuint upload_field_atlas(const voxel::DistanceField& f, voxel::AtlasLayout& layout_out) {
    layout_out = voxel::atlas_layout_for(f.dims);
    const std::vector<std::uint8_t> pixels = voxel::pack_field_to_atlas(f, layout_out);

    GLint prev_unit = 0;
    glGetIntegerv(GL_ACTIVE_TEXTURE, &prev_unit);
    GLint prev_unpack = 0;
    glGetIntegerv(GL_UNPACK_ALIGNMENT, &prev_unpack);

    glActiveTexture(GL_TEXTURE6);
    GLuint tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, layout_out.width, layout_out.height, 0,
                GL_RED, GL_UNSIGNED_BYTE, pixels.data());
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    // Deliberately left BOUND on unit 6 (unlike InstanceFieldCache::upload,
    // which unbinds because draw_model rebinds unit 0 itself later) -- this
    // test never goes through draw_model, so nothing else will bind it.
    glPixelStorei(GL_UNPACK_ALIGNMENT, prev_unpack);
    glActiveTexture(static_cast<GLenum>(prev_unit));
    return tex;
}

class HullFieldClipTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   w;
    std::unique_ptr<renderer::Pipeline> pipeline;
    GLuint vao_       = 0;
    GLuint vbo_       = 0;
    GLuint white_tex_ = 0;
    GLuint black_tex_ = 0;
    GLuint field_tex_ = 0;   // owned per-test when a test builds one

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "hull-field-clip-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }

        pipeline = std::make_unique<renderer::Pipeline>();

        // Fullscreen triangle, CCW-wound to be front-facing under Pipeline's
        // glFrontFace(GL_CCW). Same fixture as HullClipTest.
        const float verts[9] = {
            -1.0f, -1.0f, 0.0f,
             3.0f, -1.0f, 0.0f,
            -1.0f,  3.0f, 0.0f,
        };
        glGenVertexArrays(1, &vao_);
        glGenBuffers(1, &vbo_);
        glBindVertexArray(vao_);
        glBindBuffer(GL_ARRAY_BUFFER, vbo_);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, nullptr);
        // a_normal (location 1): +Z, matching HullClipTest -- facing the
        // camera at (0,0,1). The degenerate-normal canary test overrides this.
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
        if (field_tex_) { glDeleteTextures(1, &field_tex_); field_tex_ = 0; }
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

    // Minimum uniforms opaque.frag needs -- identical baseline to
    // HullClipTest::set_uniforms, plus the new hull-field uniforms defaulted
    // to the disabled/stock state (unit 6 assigned regardless, per Global
    // Constraint 2 -- a test that never rebinds unit 6 must still not collide
    // with the base-colour sampler on unit 0).
    void set_uniforms(renderer::Shader& s) {
        s.use();
        s.set_mat4("u_view",  glm::mat4(1.0f));
        s.set_mat4("u_proj",  glm::mat4(1.0f));
        s.set_mat4("u_model", glm::mat4(1.0f));
        s.set_mat4("u_ship_world_inv", glm::mat4(1.0f));
        s.set_vec3("u_ambient_light",   glm::vec3(1.0f));
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
        s.set_int("u_shadows_enabled", 0);
        s.set_int("u_shadow_map", 5);
        s.set_int("u_decal_count",       0);
        s.set_float("u_decal_time",      0.0f);
        s.set_int("u_glow_region_count", 0);
        // Pure sphere clip: disabled for every test in this file -- only the
        // field mechanism is under test here.
        s.set_int("u_carve_enabled", 0);
        s.set_int("u_carve_count", 0);
        s.set_int("u_carve_invert", 0);
        {
            std::array<glm::vec3, 24> normals;
            normals.fill(glm::vec3(0.0f, 0.0f, 1.0f));
            s.set_vec3_array("u_carve_normals", normals.data(),
                             static_cast<int>(normals.size()));
        }
        // Hull field: baseline disabled/stock. Unit 6 assigned regardless of
        // enabled state (Global Constraint 2).
        s.set_int("u_hull_field", 6);
        s.set_int("u_hull_field_enabled", 0);
        glActiveTexture(GL_TEXTURE0);
    }

    // Enable the field clip and bind `field`'s atlas to unit 6. Stores the
    // uploaded texture in field_tex_ so TearDown releases it.
    void enable_field(renderer::Shader& s, const voxel::DistanceField& field,
                      bool invert) {
        voxel::AtlasLayout layout;
        field_tex_ = upload_field_atlas(field, layout);   // already bound on unit 6
        s.set_int("u_hull_field", 6);
        s.set_int("u_hull_field_enabled", 1);
        s.set_vec3("u_hull_field_origin", field.origin);
        s.set_vec3("u_hull_field_cell",   field.cell);
        s.set_vec3("u_hull_field_dims",   glm::vec3(field.dims));
        s.set_vec2("u_hull_field_tiles",
                   glm::vec2(static_cast<float>(layout.tiles_x),
                             static_cast<float>(layout.tiles_y)));
        s.set_vec2("u_hull_field_texel",
                   glm::vec2(1.0f / static_cast<float>(layout.width),
                             1.0f / static_cast<float>(layout.height)));
        s.set_int("u_carve_invert", invert ? 1 : 0);
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

// Behaviour 1: disabled field -> stock path, hull renders (matches
// HullClipTest.DisabledClipRendersHull's discrimination: a broken "always
// discard" implementation would fail this).
TEST_F(HullFieldClipTest, DisabledFieldRendersHullUnchanged) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);   // u_hull_field_enabled = 0
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in disabled-field draw";
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2] << ") — disabled field must not discard";
}

// Behaviour 2: a fragment inside a carved region (sampled value reads
// OUTSIDE the hull) is discarded. center_value = +80 model units at the
// SOLE cell the centre fragment samples (see file header) -- well past the
// zero surface threshold, so this cannot pass by an off-by-one at the
// boundary.
TEST_F(HullFieldClipTest, FragmentInsideCarvedRegionIsDiscarded) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    const voxel::DistanceField field = make_probe_field(/*center_value=*/80);
    enable_field(prog, field, /*invert=*/false);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in carved-region draw";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 64)
        << "Center pixel is bright (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — a fragment the field marks OUTSIDE the hull should be discarded";
}

// Behaviour 3: a fragment well inside the hull (sampled value reads INSIDE)
// survives. center_value = -80, same sole sampled cell.
TEST_F(HullFieldClipTest, FragmentOutsideCarvedRegionSurvives) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    const voxel::DistanceField field = make_probe_field(/*center_value=*/-80);
    enable_field(prog, field, /*invert=*/false);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in solid-region draw";
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — a fragment the field marks INSIDE the hull must NOT be discarded";
}

// Behaviour 4a: u_carve_invert flips the carved-region case from discarded
// to rendered -- the stencil-marking pass keeps exactly what the normal pass
// would have cut. Same field as FragmentInsideCarvedRegionIsDiscarded
// (center_value = +80); only `invert` differs, and the expectation is the
// OPPOSITE pixel outcome, so this genuinely exercises the flip rather than a
// second copy of the same assertion.
TEST_F(HullFieldClipTest, InvertFlipsDiscardedFragmentToRendered) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    const voxel::DistanceField field = make_probe_field(/*center_value=*/80);
    enable_field(prog, field, /*invert=*/true);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in inverted carved-region draw";
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — u_carve_invert=1 must KEEP the fragment the normal pass discards";
}

// Behaviour 4b: u_carve_invert flips the solid-region case from rendered to
// discarded. Same field as FragmentOutsideCarvedRegionSurvives
// (center_value = -80); only `invert` differs.
TEST_F(HullFieldClipTest, InvertFlipsSurvivingFragmentToDiscarded) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    const voxel::DistanceField field = make_probe_field(/*center_value=*/-80);
    enable_field(prog, field, /*invert=*/true);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in inverted solid-region draw";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 64)
        << "Center pixel is bright (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — u_carve_invert=1 must DISCARD the fragment the normal pass renders";
}

// Behaviour 5 (regression canary): degenerate vertex normal + ambient
// gradient ON must stay finite -- AND must actually render, not just "not
// crash". Copied structure from
// HullClipTest.DegenerateNormalWithGradientOnStaysFinite: THIS is the test
// that caught the sampler3D driver corruption last time (measured to leave
// this exact path non-finite even though the corrupting fetch never
// executed). Running it again through a shader that now ALSO carries the
// new sampler2D + hull-field sampling functions (compiled in, though
// disabled at runtime here) proves the new code doesn't reopen that hazard
// in a new form.
TEST_F(HullFieldClipTest, DegenerateNormalWithGradientOnStaysFinite) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);   // u_hull_field_enabled = 0 (stock path, but compiled)
    prog.set_vec3("u_ambient_dir_ws",   glm::vec3(1.0f, 0.0f, 0.0f));
    prog.set_float("u_ambient_gradient", 0.5f);   // the vulnerable path: ON
    glVertexAttrib3f(1, 0.0f, 0.0f, 0.0f);        // force a_normal to (0,0,0)

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

    float center[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_FLOAT, center);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);

    EXPECT_NEAR(center[0], 0.5f, 0.05f)
        << "R channel is " << center[0] << ", not the expected ~0.5 ambient "
           "-- the frame may not have rendered at all";

    renderer::NonfiniteProbe probe;
    const auto& r = probe.run(hdr.color_texture(), kW, kH);
    EXPECT_FALSE(r.any)
        << r.flagged_cells << " cell(s) went non-finite with a degenerate "
        << "normal and the ambient gradient on (cause code " << r.max_code
        << ") -- adding the hull-field sampler/sampling code reopened the "
           "same class of driver hazard the sphere-clip guard fixed";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}
