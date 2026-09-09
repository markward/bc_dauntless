// native/tests/renderer/hull_field_clip_test.cc
//
// Tests for the per-instance hull-field clip (hull-volume-field-transport,
// Task 5): opaque.frag samples voxel::DistanceField data packed into a 2D
// slice atlas (voxel/field_atlas.h) instead of the fixed 24-sphere array, and
// discards a hull fragment when the sampled value reads OUTSIDE the hull by
// more than kHullFieldIsoMargin.
//
//  u_hull_field_enabled == 0                       -> stock path (no discard;
//                                                      zero per-fragment cost)
//  u_hull_field_enabled == 1 AND sample says INSIDE -> renders
//  u_hull_field_enabled == 1 AND sample says OUTSIDE -> discard
//  u_carve_invert == 1 flips both of the enabled cases (the stencil-marking
//  pass keeps exactly what the normal pass would have discarded).
//  A fragment inside a TRACKED sphere carve is governed by the sphere block
//  (struts, jagged noise rim); the field can only add a discard OUTSIDE every
//  tracked oblate.
//
// Test strategy, modelled on hull_clip_test.cc: GL compile + draw + readback,
// skipping without a GL context. With identity view/model/proj/ship_world_inv
// matrices, the fullscreen triangle's interpolated a_position IS p_body, so
// the CENTRE fragment reads p_body ~= (0, 0, 0) -- MEASURED (not exactly:
// glReadPixels(kW/2, kH/2, ...) samples the pixel centred at NDC (1/64,
// 1/64), confirmed with an isolated probe shader that output the
// interpolated position directly; p_body.z IS exactly 0.0, since this
// fixture's triangle is flat in Z). Every field's ORIGIN is chosen per test
// so that p_body lands at whatever sample-space coordinate that test needs
// to probe (an exact integer for the basic on/off tests, a deliberate
// fraction for the interpolation tests) -- see each test's comment for its
// own derivation. The 1/64 X/Y offset is negligible everywhere EXCEPT
// HullFieldIsoMarginTest, whose derivation explains why and how it is
// avoided there.

#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <assets/model.h>
#include <renderer/frame.h>
#include <renderer/hdr_target.h>
#include <renderer/instance_field_cache.h>
#include <renderer/nonfinite_probe.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <renderer/shader.h>

#include <scenegraph/hull_carve.h>
#include <scenegraph/instance.h>

#include <voxel/distance_field.h>
#include <voxel/field_atlas.h>
#include <voxel/field_brush.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <regex>
#include <sstream>
#include <string>
#include <vector>

namespace {

// Read a shader straight off disk, the way breach_raymarch_test.cc's
// IsoMarginMatchesOpaqueFragsValue does -- the SAME mechanism, deliberately,
// rather than a second one. These are text-level drift guards, not GL tests.
std::string read_shader_source(const char* rel) {
    const std::filesystem::path p = std::filesystem::path(OPEN_STBC_PROJECT_ROOT)
                                  / "native" / "src" / "renderer" / "shaders" / rel;
    std::ifstream in(p);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

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

// A uniform field: every cell holds `value`. Used where the test wants to
// isolate ONE axis of the sampling maths (X/Y bilinear, the Z lerp, or the
// tile-bleed clamp) without any other cell's value being able to leak in and
// confound the result.
voxel::DistanceField make_uniform_field(glm::ivec3 dims, glm::vec3 origin,
                                        glm::vec3 cell, std::int8_t value) {
    voxel::DistanceField f;
    f.dims   = dims;
    f.origin = origin;
    f.cell   = cell;
    f.scale  = 1.0f;
    f.dist.assign(static_cast<std::size_t>(dims.x) * dims.y * dims.z,
                  value);
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
        // Pure sphere clip: disabled by default -- only CritTwoFieldNeverOverridesATrackedStrut
        // turns it on. Every other test in this file exercises the field in
        // isolation.
        s.set_int("u_carve_enabled", 0);
        s.set_int("u_carve_count", 0);
        s.set_int("u_carve_invert", 0);
        s.set_int("u_frame_enabled", 0);
        {
            std::array<glm::vec3, 24> normals;
            normals.fill(glm::vec3(0.0f, 0.0f, 1.0f));
            s.set_vec3_array("u_carve_normals", normals.data(),
                             static_cast<int>(normals.size()));
        }
        glActiveTexture(GL_TEXTURE3);
        glBindTexture(GL_TEXTURE_2D, black_tex_);
        s.set_int("u_damage_decal", 3);
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

// Behaviour 1: disabled field -> stock path, hull renders. Binds a atlas
// that is ENTIRELY outside (every cell +127) to unit 6 while leaving
// u_hull_field_enabled at 0: a missing/deleted `if (u_hull_field_enabled !=
// 0)` guard would sample this texture, read a clearly-outside value, and
// discard -- so this genuinely exercises the gate, not just "nothing was
// ever bound". (An earlier version of this test bound nothing at all, which
// a deleted guard could still pass vacuously: an incomplete/unbound sampler
// reads back (0,0,0,0), and 0.0 - 128.0/255.0 is negative -- "inside" -- so
// the gate's absence would have been invisible.)
TEST_F(HullFieldClipTest, DisabledFieldRendersHullUnchanged) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    // Every cell +127 (deep outside), not just one probed cell, so the
    // guard is tested regardless of exactly where the fragment samples.
    const voxel::DistanceField field = make_uniform_field(
        glm::ivec3(4, 4, 4), glm::vec3(-2.5f), glm::vec3(1.0f), 127);
    enable_field(prog, field, /*invert=*/false);
    prog.set_int("u_hull_field_enabled", 0);   // the guard under test
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in disabled-field draw";
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2] << ") — disabled field must not discard, even "
           "with an all-outside atlas bound";
}

// Behaviour 2: a fragment inside a carved region (sampled value reads
// OUTSIDE the hull) is discarded. center_value = +80 model units at the
// SOLE cell the centre fragment samples (see file header) -- well past the
// kHullFieldIsoMargin threshold, so this cannot pass by an off-by-one at the
// boundary. (The boundary ITSELF is pinned separately by the IsoMargin*
// tests below.)
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

// ── Critical 1 fix: kHullFieldIsoMargin boundary ────────────────────────────
//
// Every fragment this shader ever shades sits ON the hull's own mesh
// surface (that is what is being drawn), so at that exact point the field's
// TRUE distance is ~0. Comparing the decoded sample against a bare 0.0
// would discard on quantisation-rounding noise alone -- a speckled hull, not
// real damage. opaque.frag now compares against kHullFieldIsoMargin =
// 0.5/255 (see its derivation in the shader). These two tests PIN that
// threshold by walking the sampled value through it via a Z-slice blend
// (slice z=2 at raw distance 0, slice z=3 at raw distance +1 -- i.e. bytes
// 128 and 129), read at two different fractional Z weights that straddle
// the 0.5-of-one-step boundary:
//
//   wz=0.3 -> blended value = 0.3/255 < kHullFieldIsoMargin -> survives
//   wz=0.7 -> blended value = 0.7/255 > kHullFieldIsoMargin -> discards
//
// Both would come out WRONG under the old bare `> 0.0` comparison (both
// blended values are strictly positive, so both would have discarded).
// Together the pair also discriminates a broken/missing Z lerp: a "floor
// only" bug reads byte 128 at both weights (value 0, survives both -- wz=0.7
// would then wrongly survive); a "ceil only" bug reads byte 129 at both
// weights (value 1/255, discards both -- wz=0.3 would then wrongly
// discard); and an inverted weight (1-wz instead of wz) swaps which of the
// two tests fails.
//
// MEASURED, not assumed: the fullscreen triangle's centre fragment does NOT
// land at EXACTLY p_body == (0,0,0), despite that being this file's (and
// hull_clip_test.cc's) documented assumption. glReadPixels(kW/2, kH/2, ...)
// samples the pixel whose CENTRE is at window (32.5, 32.5) of 64, i.e. NDC
// (2*32.5/64 - 1) = 1/64 on both X and Y -- confirmed by an isolated probe
// shader that output the interpolated position directly: (0.015625,
// 0.015625, 0.0). Every OTHER test in this file uses value swings of >=3
// raw distance units, which an ~1.5% cross-contamination from a neighbouring
// cell (bilinear-blending in that 1/64 of a cell) cannot flip the sign of.
// This margin test tries to resolve a ONE-STEP difference, which THAT same
// contamination CAN flip (confirmed: the original single-cell-override
// version of this fixture passed ValueWithinHalfAStepOfTheSurfaceSurvives by
// accident and genuinely failed ValueJustPastHalfAStepDiscards, both because
// of exactly this, not because of a shader bug -- traced with a standalone
// isolated shader reproducing sample_hull_field byte-for-byte, which
// confirmed the sampling maths themselves are exactly correct).
//
// Fix: fill the ENTIRE z=2 and z=3 slices uniformly (not just cell (2,2,*)),
// so bilinear blending across the X/Y sub-cell offset mixes a cell with an
// IDENTICALLY-valued neighbour -- eliminating the contamination rather than
// trying to out-guess it with a compensating offset.
class HullFieldIsoMarginTest : public HullFieldClipTest {
protected:
    // origin.z is the only thing that differs between the two probes: it is
    // chosen so g.z - 0.5 (sample-space z) equals 2 + wz exactly, landing the
    // fullscreen triangle's centre fragment (p_body.z == 0.0 exactly -- the
    // triangle is flat in Z, so unlike X/Y there is no sub-pixel offset to
    // account for) at that fractional Z.
    voxel::DistanceField make_margin_field(float wz) {
        voxel::DistanceField f;
        f.dims   = glm::ivec3(4, 4, 4);
        f.cell   = glm::vec3(1.0f);
        f.scale  = 1.0f;
        const float sample_space_z = 2.0f + wz;
        const float g_z = sample_space_z + 0.5f;
        f.origin = glm::vec3(-2.5f, -2.5f, -g_z);
        f.dist.assign(static_cast<std::size_t>(4 * 4 * 4),
                      static_cast<std::int8_t>(-100));
        for (int y = 0; y < 4; ++y) {
            for (int x = 0; x < 4; ++x) {
                f.dist[f.index(x, y, 2)] = 0;   // byte 128: exactly the hull surface
                f.dist[f.index(x, y, 3)] = 1;   // byte 129: one quantisation step out
            }
        }
        return f;
    }
};

TEST_F(HullFieldIsoMarginTest, ValueWithinHalfAStepOfTheSurfaceSurvives) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    const voxel::DistanceField field = make_margin_field(/*wz=*/0.3f);
    enable_field(prog, field, /*invert=*/false);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — a blended value of 0.3/255 is WITHIN kHullFieldIsoMargin "
           "(0.5/255) and must not discard";
}

TEST_F(HullFieldIsoMarginTest, ValueJustPastHalfAStepDiscards) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    const voxel::DistanceField field = make_margin_field(/*wz=*/0.7f);
    enable_field(prog, field, /*invert=*/false);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 64)
        << "Center pixel is bright (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — a blended value of 0.7/255 is PAST kHullFieldIsoMargin "
           "(0.5/255) and must discard";
}

// ── Important 2 fix: X/Y hardware bilinear ─────────────────────────────────
//
// Both tests probe a fractional X sample-space coordinate between two
// opposite-signed neighbouring cells, at a weight chosen so the CORRECT
// blended sign DIFFERS from what GL_NEAREST (or a "floor only"/"ceil only"
// shader bug) would read -- not just from the two cells' own signs, which a
// coarse ±100 test at wx=0.9/0.1 could satisfy by coincidence even under
// nearest-filtering. See the derivation in each test.
class HullFieldXyBilinearTest : public HullFieldClipTest {
protected:
    // origin.x placed so sample-space x == 1 + wx exactly; y/z stay at the
    // exact-integer (2,2) used elsewhere, so only X blends.
    voxel::DistanceField make_xy_field(float wx, std::int8_t cell1,
                                       std::int8_t cell2) {
        voxel::DistanceField f;
        f.dims   = glm::ivec3(4, 4, 4);
        f.cell   = glm::vec3(1.0f);
        f.scale  = 1.0f;
        const float sample_space_x = 1.0f + wx;
        const float g_x = sample_space_x + 0.5f;
        f.origin = glm::vec3(-g_x, -2.5f, -2.5f);
        f.dist.assign(static_cast<std::size_t>(4 * 4 * 4),
                      static_cast<std::int8_t>(-100));
        f.dist[f.index(1, 2, 2)] = cell1;
        f.dist[f.index(2, 2, 2)] = cell2;
        return f;
    }
};

// wx=0.6 (majority weight on cell x=2, byte 131 i.e. raw +3 -- barely
// outside on its own). GL_NEAREST at wx=0.6 (>= 0.5) would round to x=2 and
// read +3 -> discard. The CORRECT bilinear blend pulls in x=1's byte 28
// (raw -100) at 40% weight: mix(28,131,0.6) = 89.8 -> value = -38.2/255,
// clearly negative -> survives. Also catches a "ceil only" shader bug
// (reads byte 131 -> discard, wrong).
TEST_F(HullFieldXyBilinearTest, BlendPullsAcrossZeroTowardTheMinorityWeightedNearCell) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    const voxel::DistanceField field =
        make_xy_field(/*wx=*/0.6f, /*cell1=*/-100, /*cell2=*/3);
    enable_field(prog, field, /*invert=*/false);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — bilinear blend of -100 (40%) and +3 (60%) is negative and "
           "must survive; a nearest-filter or ceil-only bug reads +3 alone";
}

// wx=0.4 (majority weight on cell x=1, byte 131 i.e. raw +3). GL_NEAREST at
// wx=0.4 (< 0.5) would round to x=1 and read +3 -> discard. The CORRECT
// bilinear blend pulls in x=2's byte 28 (raw -100) at 40% weight:
// mix(131,28,0.4) = 89.8 -> value = -38.2/255 -> survives. Also catches a
// "floor only" shader bug (reads byte 131 -> discard, wrong).
TEST_F(HullFieldXyBilinearTest, BlendPullsAcrossZeroTowardTheMinorityWeightedFarCell) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    const voxel::DistanceField field =
        make_xy_field(/*wx=*/0.4f, /*cell1=*/3, /*cell2=*/-100);
    enable_field(prog, field, /*invert=*/false);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — bilinear blend of +3 (60%) and -100 (40%) is negative and "
           "must survive; a nearest-filter or floor-only bug reads +3 alone";
}

// ── Important 2 fix: cross-tile bleed (the anti-bleed clamp) ───────────────
//
// dims (4,4,2) puts TWO slices side by side in the SAME atlas row
// (atlas_layout_for: tiles_x=ceil(sqrt(2))=2, tiles_y=1) -- adjacent tiles,
// exactly the seam field_atlas.h's border exists to protect. Slice 0 is
// UNIFORMLY -100 (deep inside); slice 1 is UNIFORMLY +100 (deep outside).
// The probe's body position is chosen so the UNCLAMPED sample-space X is a
// wildly out-of-range +50 -- if the shader's `clamp(g.xy, -1, dims)` guard
// is missing, that reaches past slice 0's own tile into slice 1's texels
// (bleed); Z is pinned at sample-space 0 (wz == 0 exactly) so the Z lerp
// contributes NOTHING (slice 1's value cannot reach the result via Z
// blending) -- any slice-1 contamination here can only come from the X
// clamp failing, isolating that one mechanism.
//
// NOTE: this test cannot distinguish the correct clamp range [-1, dims] from
// a NARROWER one like [0, dims-1] -- both stay inside slice 0's own tile for
// any overshoot, because the border texel at sample-space `dims` always
// holds the SAME byte as the interior edge cell at `dims-1`
// (pack_field_to_atlas replicates it there by construction), so the two
// clamp bounds are value-indistinguishable except when the clamp is REMOVED
// or WIDENED enough to reach a genuinely different tile -- which is what
// this test exercises.
TEST_F(HullFieldClipTest, CrossTileBleedDoesNotReachTheNeighbouringSlice) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);

    const float unclamped_sample_space_x = 50.0f;
    const float g_x = unclamped_sample_space_x + 0.5f;
    const float g_z = 0.5f;   // sample-space z == 0 exactly -> wz == 0
    voxel::DistanceField slice0 = make_uniform_field(
        glm::ivec3(4, 4, 2), glm::vec3(-g_x, -2.5f, -g_z), glm::vec3(1.0f), -100);
    // Overwrite slice 1 (z=1) to the opposite extreme so any bleed is visible.
    for (int y = 0; y < 4; ++y)
        for (int x = 0; x < 4; ++x)
            slice0.dist[slice0.index(x, y, 1)] = 100;

    enable_field(prog, slice0, /*invert=*/false);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — a wildly out-of-bounds X must clamp within slice 0's own "
           "tile (deep inside, -100), not bleed into slice 1's tile (+100)";
}

// ── Important 2 fix: non-cubic dims / tile-axis transposition ──────────────
//
// dims (3,5,6): every dimension distinct, and tiles_x=ceil(sqrt(6))=3 !=
// tiles_y=ceil(6/3)=2 -- so an x<->y swap in the shader's cell coordinates,
// OR a tiles_x<->tiles_y swap in the tile-offset maths, relocates the probe
// to a DIFFERENT tile/cell instead of merely misreading within the same one.
// The whole field is uniformly deep-inside (-100) except ONE cell at
// (x=1, y=2, slice=4) set to +100 (outside). The probe samples that exact
// cell at an exact integer sample-space coordinate (no interpolation, so
// this isolates tile-axis correctness from the interpolation tests above).
// Any transposition bug reads a DIFFERENT (still -100) cell and wrongly
// survives.
TEST_F(HullFieldClipTest, NonCubicDimsDoesNotTransposeTileAxes) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);

    voxel::DistanceField field = make_uniform_field(
        glm::ivec3(3, 5, 6), glm::vec3(-1.5f, -2.5f, -4.5f), glm::vec3(1.0f), -100);
    field.dist[field.index(1, 2, 4)] = 100;   // the one cell the probe hits

    enable_field(prog, field, /*invert=*/false);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 64)
        << "Center pixel is bright (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — cell (1,2, slice 4) of a (3,5,6) field is +100 (outside) and "
           "must discard; a tile-axis transposition would read a different, "
           "still-deep-inside cell instead";
}

// ── Critical 2 fix: the field must not override a TRACKED oblate ──────────
//
// Sphere carve centred at c=(-1.85,0,0), radius 2, normal (0,0,1); the
// centre fragment sits at p_body=(0,0,0), so v=(1.85,0,0), along=0,
// lateral=(1.85,0,0), ld=1.85, az=(1,0,0) exactly (along==0, so az is exact,
// not a normalized-noise direction). These numbers were run through a
// standalone re-implementation of opaque.frag's vh3/vnoise3/oblate maths
// (not shipped here, but reproducible from the shader's own formulas) to
// confirm, with the ACTUAL noise value at this az/c: r_eff ~= 2.370,
// e ~= 0.609 (comfortably < 1.0, so this fragment IS inside the tracked
// oblate) and frac = sqrt(e) ~= 0.781 (comfortably > kOpenCore = 0.75, so
// the framework lattice's strut branch is reachable). u_frame_enabled=1 and
// a damage-decal texture bound with alpha=255 everywhere satisfies
// `a > kStrutAlpha` unconditionally, so `cut` resolves to `false` --this
// fragment is a KEPT STRUT.
//
// The field is ALSO enabled and marks this exact point as outside (+80, via
// make_probe_field, same body-frame origin the sphere geometry above was
// derived against). Before the Critical-2 fix, the field's independent
// discard fired regardless of the sphere block's decision, silently erasing
// every strut the moment Task 6 turns the field on. After the fix, the
// field is gated on `!inside_any_oblate`, which is false here, so the field
// is never consulted and the strut survives.
TEST_F(HullFieldClipTest, FieldNeverOverridesAFragmentInsideATrackedOblate) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);

    // Framework lattice: enabled, opaque (alpha=255) stencil so `a >
    // kStrutAlpha` unconditionally, satisfying the strut branch regardless
    // of the UV this fragment happens to land on.
    GLuint strut_tex = make_tex(255, 255, 255);   // RGBA(255,255,255,255)
    glActiveTexture(GL_TEXTURE3);
    glBindTexture(GL_TEXTURE_2D, strut_tex);
    prog.set_int("u_damage_decal", 3);
    prog.set_int("u_frame_enabled", 1);
    glActiveTexture(GL_TEXTURE0);

    // Tracked sphere carve covering the centre fragment (verified geometry
    // above: e ~= 0.609 < 1, frac ~= 0.781 > kOpenCore).
    const glm::vec4 sphere(-1.85f, 0.0f, 0.0f, 2.0f);
    const glm::vec3 normal(0.0f, 0.0f, 1.0f);
    prog.set_int("u_carve_enabled", 1);
    prog.set_int("u_carve_count", 1);
    prog.set_vec4_array("u_carve_spheres", &sphere, 1);
    prog.set_vec3_array("u_carve_normals", &normal, 1);

    // Field ALSO marks the same point outside -- must be suppressed.
    const voxel::DistanceField field = make_probe_field(/*center_value=*/80);
    enable_field(prog, field, /*invert=*/false);

    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in tracked-oblate draw";
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — a fragment inside a TRACKED oblate that the framework "
           "lattice kept as a strut must survive even though the field "
           "independently marks it outside";

    glDeleteTextures(1, &strut_tex);
}

// ── N1 fix: the gate must be the UNION of the perturbed and unperturbed
// oblate, not the perturbed one alone ───────────────────────────────────
//
// field_carve_oblate carves the UNPERTURBED oblate -- full radius `r`, no
// noise (it has no access to opaque.frag's per-fragment screen-space hash).
// The sphere block's own `e < 1.0` test uses the NOISE-PERTURBED radius
// r_eff, which can be SMALLER than r on azimuths where the noise dips
// inward. On exactly that band (r_eff < ld < r), a fragment is OUTSIDE
// e<1.0 -- so gating suppression on e<1.0 alone leaves `inside_any_oblate`
// false there -- while still being INSIDE what the field actually carved.
// An ungated field would cut a ring there with no scoop behind it
// (breach.vert builds the scoop from r_eff too), showing space instead of
// interior around roughly half of every tracked breach's rim -- reopening
// the exact drift Critical 2's fix exists to close.
//
// Geometry found by an EMPIRICAL GPU SEARCH, not a hand or CPU derivation.
// A first attempt hand-picked c=(0,23,0) after checking the noise value in
// a standalone Python re-implementation of vh3/vnoise3 (predicted e~=1.198,
// e_unpert~=0.846) -- run for real it FAILED: the sphere block discarded
// the fragment on its own, meaning e < 1.0 on the actual GPU, contradicting
// the CPU prediction. Root cause: vh3's `sin(dot(p, (127.1,311.7,74.7)))`
// evaluates sin() of arguments in the hundreds; this driver's sin/cosine
// hardware does not reproduce a CPU double's range reduction at that
// magnitude for every input, and there is no way to know in advance which
// inputs it disagrees on. So this candidate was instead found by rendering
// a 360x512 target where pixel (x,y) evaluates THIS SHADER'S OWN
// vh3/vnoise3 (copied verbatim into a standalone probe program) at
// theta=x degrees, ld=12.5+(y/512)*12.5 (r=25 fixed, c=-ld*(cos theta,
// sin theta,0), normal=(0,0,1)), and scanning the read-back e/e_unpert for
// the largest simultaneous margin on both sides of 1.0. Best found on THIS
// GPU: theta=129 deg, ld=23.05 -> c=(14.505837,-17.913212,0), giving
// (measured, not predicted) e=1.1465 (margin 0.1465 above 1.0: OUTSIDE the
// perturbed oblate) and e_unpert=0.8506 (margin 0.1494 below 1.0: INSIDE
// the unperturbed one) -- comfortable margins on a driver where a coarser
// margin could plausibly not exist at all for some other geometry.
TEST_F(HullFieldClipTest, FieldSuppressedInTheBandBetweenThePerturbedAndUnperturbedRadius) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);

    const glm::vec4 sphere(14.505837f, -17.913212f, 0.0f, 25.0f);
    const glm::vec3 normal(0.0f, 0.0f, 1.0f);
    prog.set_int("u_carve_enabled", 1);
    prog.set_int("u_carve_count", 1);
    prog.set_vec4_array("u_carve_spheres", &sphere, 1);
    prog.set_vec3_array("u_carve_normals", &normal, 1);
    // Framework lattice stays off (set_uniforms default): irrelevant here,
    // since e >= 1.0 means the sphere loop's own `if (e < 1.0)` body -- the
    // only place u_frame_enabled is read -- never executes for this
    // fragment regardless.

    // Field independently marks the SAME point outside/cut -- must be
    // suppressed by the union gate now that this fragment sits inside the
    // UNPERTURBED oblate, even though it is outside the perturbed one.
    const voxel::DistanceField field = make_probe_field(/*center_value=*/80);
    enable_field(prog, field, /*invert=*/false);

    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — a fragment between the perturbed and unperturbed oblate "
           "radii is inside what the field actually carved (unperturbed "
           "e<1) even though it is outside the sphere block's own "
           "noise-perturbed e<1 test; the union gate must still suppress "
           "the field there, or every tracked breach grows a see-through "
           "ring where the noise happens to dip the rim inward";
}

// ── Task 2(a): the suppression bound must be the DILATED carve region ─────
//
// field_brush.cc rounds every carve up to the smallest shape the lattice can
// hold (kCarveDepthFloorCells, kCarveFieldOffsetCells), so the field reads
// "damaged" in a ring OUTSIDE the nominal oblate. Suppressing the field only
// inside the nominal oblate lets it cut that ring with its own smooth edge --
// visibly enlarging every tracked hole and erasing the jagged noise rim and
// the struts the live pass approved.
//
// Geometry (all exact, no GPU noise involved -- the fragment never enters the
// sphere block's noise branch at all):
//   probe field cell = 1.0 on every axis  =>  cellmin = 1.0
//   r = 2.0  =>  lat = r*(1+kShapeAmp) = 2.5
//                dep = max(kDepthFactor*r, kFieldDepthFloor*cellmin)
//                    = max(0.9, 1.25) = 1.25
//                dil = 1 + kFieldSdfOffset*cellmin / min(lat,dep)
//                    = 1 + 1.25/1.25 = 2.0
//   carve centre 3.5 to the -X side of the centre fragment, normal +Z and the
//   fixture's triangle flat in Z, so along = 0 and ld ~= 3.516.
//     ld > r*(1+kShapeAmp) = 2.5  -> the sphere block's own guard is FALSE:
//        this fragment is outside the nominal oblate on BOTH the perturbed
//        (e < 1) and the unperturbed test, so the pre-Task-2 gate left it
//        unsuppressed and the field discarded it.
//     unit = ld/lat ~= 1.406 < dil = 2.0 -> inside the region the brush
//        actually dilated this carve to, so the field must be suppressed and
//        the hull fragment must SURVIVE.
TEST_F(HullFieldClipTest, FieldSuppressedOutToTheBrushesDilatedBound) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);

    const glm::vec4 sphere(-3.5f, 0.0f, 0.0f, 2.0f);
    const glm::vec3 normal(0.0f, 0.0f, 1.0f);
    prog.set_int("u_carve_enabled", 1);
    prog.set_int("u_carve_count", 1);
    prog.set_vec4_array("u_carve_spheres", &sphere, 1);
    prog.set_vec3_array("u_carve_normals", &normal, 1);

    // Field independently marks this point cut (the same +80 probe cell
    // FragmentInsideCarvedRegionIsDiscarded proves does discard on its own).
    const voxel::DistanceField field = make_probe_field(/*center_value=*/80);
    enable_field(prog, field, /*invert=*/false);

    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") -- this fragment is outside the nominal oblate but inside the "
           "region field_brush.cc dilated the carve to. The field must be "
           "suppressed out to the DILATED bound, or it cuts a smooth ring "
           "around every tracked hole and erases the noise rim and struts";
}

// ── Important 3 fix: frame.cc's draw_model uniform-setting block ──────────
//
// Everything above drives opaque.frag's uniforms directly via the test's
// own set_uniforms()/enable_field() -- none of it exercises frame.cc's new
// block in draw_model() at all. These two tests call the REAL draw_model()
// free function (same one skinned_render_test.cc calls directly) with an
// empty assets::Model (no nodes/meshes, so its per-mesh loop is a no-op --
// but the hull-field uniform block runs unconditionally BEFORE that loop),
// then read the uniforms back via glGetUniform* the way
// particle_pass_test.cc already does for u_roll. This is code frame.cc sets
// on its own initiative, not the test's -- so it is real coverage of
// Constraint 2 (unit 6 assigned on every path) and the geometry uniforms,
// not just a restatement of what the fixture already pokes in.
class HullFieldDrawModelTest : public HullFieldClipTest {
protected:
    assets::Model empty_model;
    scenegraph::DamageDecalRing no_decals;
    const std::array<scenegraph::Instance::GlowRegion,
                     scenegraph::Instance::kMaxGlowRegions> no_glow{};
    scenegraph::HullCarveField no_carve;
    std::vector<glm::mat4> no_palette;
    std::array<renderer::DynamicLightDescriptor, renderer::kMaxDynamicLightsPerDraw>
        no_lights{};
};

TEST_F(HullFieldDrawModelTest, EntryPresentBindsTextureAndSetsGeometryUniforms) {
    renderer::Shader& prog = pipeline->opaque_shader();

    const voxel::DistanceField field = make_probe_field(/*center_value=*/0);
    voxel::AtlasLayout layout;
    GLuint tex = upload_field_atlas(field, layout);

    renderer::InstanceFieldCache::Entry entry;
    entry.tex2d  = tex;
    entry.layout = layout;
    entry.origin = field.origin;
    entry.cell   = field.cell;
    entry.dims   = field.dims;
    entry.scale  = field.scale;

    renderer::draw_model(empty_model, glm::mat4(1.0f), prog, pipeline->skinned_shader(),
                         white_tex_, black_tex_, /*rim_strength=*/0.0f,
                         no_decals, no_glow, /*decal_time=*/0.0f,
                         /*emissive_scale=*/1.0f, no_palette, no_carve,
                         no_lights, /*dyn_light_count=*/0,
                         /*carve_fill=*/nullptr, /*carve_invert=*/false,
                         &entry);

    GLuint program = prog.program();
    GLint unit_val = -1;
    glGetUniformiv(program, glGetUniformLocation(program, "u_hull_field"), &unit_val);
    EXPECT_EQ(unit_val, 6) << "draw_model must assign u_hull_field to unit 6";

    GLint enabled_val = -1;
    glGetUniformiv(program, glGetUniformLocation(program, "u_hull_field_enabled"),
                   &enabled_val);
    EXPECT_EQ(enabled_val, 1) << "draw_model must enable the field when an Entry is passed";

    GLfloat origin_val[3] = {0, 0, 0};
    glGetUniformfv(program, glGetUniformLocation(program, "u_hull_field_origin"), origin_val);
    EXPECT_FLOAT_EQ(origin_val[0], field.origin.x);
    EXPECT_FLOAT_EQ(origin_val[1], field.origin.y);
    EXPECT_FLOAT_EQ(origin_val[2], field.origin.z);

    GLfloat dims_val[3] = {0, 0, 0};
    glGetUniformfv(program, glGetUniformLocation(program, "u_hull_field_dims"), dims_val);
    EXPECT_FLOAT_EQ(dims_val[0], static_cast<float>(field.dims.x));

    GLfloat tiles_val[2] = {0, 0};
    glGetUniformfv(program, glGetUniformLocation(program, "u_hull_field_tiles"), tiles_val);
    EXPECT_FLOAT_EQ(tiles_val[0], static_cast<float>(layout.tiles_x));
    EXPECT_FLOAT_EQ(tiles_val[1], static_cast<float>(layout.tiles_y));

    // Confirm the ACTUAL GL binding, not just the uniform int: unit 6 must
    // hold the Entry's own texture object.
    GLint prev_active = 0;
    glGetIntegerv(GL_ACTIVE_TEXTURE, &prev_active);
    glActiveTexture(GL_TEXTURE6);
    GLint bound_tex = 0;
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &bound_tex);
    EXPECT_EQ(static_cast<GLuint>(bound_tex), tex)
        << "draw_model must bind the Entry's tex2d to unit 6";
    glActiveTexture(static_cast<GLenum>(prev_active));

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    glDeleteTextures(1, &tex);
}

TEST_F(HullFieldDrawModelTest, EntryAbsentStillAssignsUnitSixAndDisables) {
    renderer::Shader& prog = pipeline->opaque_shader();

    renderer::draw_model(empty_model, glm::mat4(1.0f), prog, pipeline->skinned_shader(),
                         white_tex_, black_tex_, /*rim_strength=*/0.0f,
                         no_decals, no_glow, /*decal_time=*/0.0f,
                         /*emissive_scale=*/1.0f, no_palette, no_carve,
                         no_lights, /*dyn_light_count=*/0,
                         /*carve_fill=*/nullptr, /*carve_invert=*/false,
                         /*hull_field=*/nullptr);

    GLuint program = prog.program();
    GLint unit_val = -1;
    glGetUniformiv(program, glGetUniformLocation(program, "u_hull_field"), &unit_val);
    EXPECT_EQ(unit_val, 6)
        << "draw_model must assign u_hull_field to unit 6 even when hull_field "
           "is nullptr (Global Constraint 2: on EVERY path)";

    GLint enabled_val = -1;
    glGetUniformiv(program, glGetUniformLocation(program, "u_hull_field_enabled"),
                   &enabled_val);
    EXPECT_EQ(enabled_val, 0)
        << "draw_model must leave the field disabled when hull_field is nullptr";

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// N2 fix: u_ship_world_inv must not be left STALE for a field-enabled
// instance with no active carve spheres, decals, or glow regions -- the
// only three places draw_model otherwise sets it. An InstanceFieldCache::
// Entry persists independently of those, so before this fix a field-only
// instance would sample the field through whatever matrix the PREVIOUS
// draw call happened to leave behind (a different ship's body frame, or --
// as reproduced here -- an arbitrary sentinel nobody drew with at all).
//
// Proof: explicitly poke u_ship_world_inv to a value draw_model could not
// possibly compute from `world` (a translation nowhere near the identity or
// `world`'s own inverse) BEFORE calling draw_model with a hull_field entry
// and every other body-frame-writing input (decals/glow/carve) empty. If
// the fix is missing, that sentinel survives untouched and this test reads
// it back; if the fix is present, draw_model's own glm::inverse(world)
// overwrites it regardless.
TEST_F(HullFieldDrawModelTest, EntryPresentForcesShipWorldInvEvenWithNoOtherBodyFrameSource) {
    renderer::Shader& prog = pipeline->opaque_shader();

    const voxel::DistanceField field = make_probe_field(/*center_value=*/0);
    voxel::AtlasLayout layout;
    GLuint tex = upload_field_atlas(field, layout);
    renderer::InstanceFieldCache::Entry entry;
    entry.tex2d  = tex;
    entry.layout = layout;
    entry.origin = field.origin;
    entry.cell   = field.cell;
    entry.dims   = field.dims;
    entry.scale  = field.scale;

    // Sentinel: a matrix draw_model's glm::inverse(world) call (world ==
    // identity below) could never produce -- a large translation, easy to
    // tell apart from the identity inverse (itself the identity) at a
    // glance.
    prog.use();
    const glm::mat4 sentinel = glm::translate(glm::mat4(1.0f), glm::vec3(999.0f, 888.0f, 777.0f));
    prog.set_mat4("u_ship_world_inv", sentinel);

    renderer::draw_model(empty_model, glm::mat4(1.0f), prog, pipeline->skinned_shader(),
                         white_tex_, black_tex_, /*rim_strength=*/0.0f,
                         no_decals, no_glow, /*decal_time=*/0.0f,
                         /*emissive_scale=*/1.0f, no_palette, no_carve,
                         no_lights, /*dyn_light_count=*/0,
                         /*carve_fill=*/nullptr, /*carve_invert=*/false,
                         &entry);

    GLuint program = prog.program();
    GLfloat readback[16];
    glGetUniformfv(program, glGetUniformLocation(program, "u_ship_world_inv"), readback);
    const glm::mat4 expected = glm::inverse(glm::mat4(1.0f));   // == identity
    bool matches_expected = true, matches_sentinel = true;
    for (int col = 0; col < 4; ++col) {
        for (int row = 0; row < 4; ++row) {
            const float got = readback[col * 4 + row];
            if (std::abs(got - expected[col][row]) > 1e-5f) matches_expected = false;
            if (std::abs(got - sentinel[col][row]) > 1e-5f) matches_sentinel = false;
        }
    }
    EXPECT_TRUE(matches_expected)
        << "u_ship_world_inv was not set to glm::inverse(world) by draw_model's "
           "hull-field block -- a field-enabled instance with no carves, decals, "
           "or glow regions would sample the field through a stale matrix";
    EXPECT_FALSE(matches_sentinel)
        << "u_ship_world_inv still reads the pre-draw sentinel -- draw_model's "
           "hull-field block did not write it at all";

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    glDeleteTextures(1, &tex);
}

// ── Task 2(b): no baked field => no holes ────────────────────────────────
//
// breach_pass.cc returns early when the instance has no InstanceFieldCache
// entry, so it draws no interior. draw_model used to set u_carve_enabled = 1
// regardless, which meant a hull whose bake failed got holes from the sphere
// path with nothing behind them: unconditional see-through. A hole is a hole
// -- if we cannot draw what is behind it, we do not cut it.
//
// Both halves are asserted in one test on purpose: "carves disabled" alone
// would pass against a draw_model that simply never enables carves at all.
TEST_F(HullFieldDrawModelTest, CarvesAreDisabledWithoutAFieldAndEnabledWithOne) {
    renderer::Shader& prog = pipeline->opaque_shader();

    scenegraph::HullCarveField carve;
    scenegraph::HullCarve& c = carve.add(glm::vec3(0.0f), /*influ_radius=*/2.0f,
                                         /*strength=*/500.0f,
                                         glm::vec3(0.0f, 0.0f, 1.0f));
    c.radius = 2.0f;   // caller owns the visible radius; >0 or frame.cc skips it
    ASSERT_EQ(carve.count(), 1u);

    const GLuint program = prog.program();
    auto carve_enabled = [&]() {
        GLint v = -1;
        glGetUniformiv(program, glGetUniformLocation(program, "u_carve_enabled"), &v);
        return v;
    };

    renderer::draw_model(empty_model, glm::mat4(1.0f), prog, pipeline->skinned_shader(),
                         white_tex_, black_tex_, /*rim_strength=*/0.0f,
                         no_decals, no_glow, /*decal_time=*/0.0f,
                         /*emissive_scale=*/1.0f, no_palette, carve,
                         no_lights, /*dyn_light_count=*/0,
                         /*carve_fill=*/nullptr, /*carve_invert=*/false,
                         /*hull_field=*/nullptr);
    EXPECT_EQ(carve_enabled(), 0)
        << "draw_model cut holes on an instance with no baked field -- "
           "breach_pass draws no interior there, so the hole is see-through";

    // Same carve, now WITH a field entry: the holes must come back.
    const voxel::DistanceField field = make_probe_field(/*center_value=*/0);
    voxel::AtlasLayout layout;
    GLuint tex = upload_field_atlas(field, layout);
    renderer::InstanceFieldCache::Entry entry;
    entry.tex2d  = tex;
    entry.layout = layout;
    entry.origin = field.origin;
    entry.cell   = field.cell;
    entry.dims   = field.dims;
    entry.scale  = field.scale;

    renderer::draw_model(empty_model, glm::mat4(1.0f), prog, pipeline->skinned_shader(),
                         white_tex_, black_tex_, /*rim_strength=*/0.0f,
                         no_decals, no_glow, /*decal_time=*/0.0f,
                         /*emissive_scale=*/1.0f, no_palette, carve,
                         no_lights, /*dyn_light_count=*/0,
                         /*carve_fill=*/nullptr, /*carve_invert=*/false,
                         &entry);
    EXPECT_EQ(carve_enabled(), 1)
        << "draw_model must still cut holes when the instance HAS a field";

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    glDeleteTextures(1, &tex);
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

// The GLSL and C++ copies of the brush constants are separate literals in
// separately compiled languages; nothing but this test stops them drifting.
// If they drift, the shader suppresses the field over a different region
// than the brush dilated, and a ring of un-backed hull reappears around
// every tracked hole -- the exact defect Task 1 exists to remove.
//
// Matched with a REGEX, not a fixed "const float <name> = " prefix: this
// shader column-aligns its constant declarations (`const float kShapeAmp    =
// 0.25;`), so a fixed-prefix find() would report kShapeAmp missing and the
// guard would fail for the wrong reason.
TEST(HullFieldClip, GlslBrushConstantsMatchCxx) {
    const std::string src = read_shader_source("opaque.frag");
    ASSERT_FALSE(src.empty()) << "opaque.frag could not be read";
    auto glsl_const = [&](const char* name) -> float {
        const std::regex re(std::string("const\\s+float\\s+") + name
                            + "\\s*=\\s*([^;]+);");
        std::smatch m;
        EXPECT_TRUE(std::regex_search(src, m, re))
            << name << " missing from opaque.frag";
        if (!std::regex_search(src, m, re)) return -1.0f;
        return std::stof(m[1].str());
    };
    EXPECT_FLOAT_EQ(glsl_const("kFieldDepthFloor"), voxel::kCarveDepthFloorCells);
    EXPECT_FLOAT_EQ(glsl_const("kFieldSdfOffset"),  voxel::kCarveFieldOffsetCells);
    EXPECT_FLOAT_EQ(glsl_const("kShapeAmp"),        voxel::kCarveRimAmp);
    EXPECT_FLOAT_EQ(glsl_const("kDepthFactor"),     voxel::kCarveDepthFactor);
}

// ── Task 3: the FIELD's hole edge gets a body-space noise rim ─────────────
//
// The field rim perturbation must be one-sided. A term that can LOWER the
// threshold grows the hole past the region field_brush.cc's conservative
// brush guaranteed damage in, which is the see-through defect this whole
// plan exists to remove. Guard the source: the noise must be ADDED to the
// margin, and its factor must be a bare vnoise3 in [0,1] with no remap into
// [-1,1] (the sphere block's own rim noise does exactly such a remap two
// dozen lines above, so copying that line is a live hazard).
//
// This is a TEXT guard and it is not sufficient on its own -- it passes
// against a shader that declares the constant and never uses it, which is
// the failure mode Task 2 hit with its own constant-parity test. The two
// FieldRimNoise* TEST_Fs below are the behavioural half.
TEST(HullFieldClip, FieldRimNoiseOnlyShrinksTheHole) {
    const std::string src = read_shader_source("opaque.frag");
    ASSERT_FALSE(src.empty()) << "opaque.frag could not be read";
    const std::size_t at = src.find("kFieldRimNoise * ");
    ASSERT_NE(at, std::string::npos) << "field rim noise term missing";
    const std::string line = src.substr(at, src.find('\n', at) - at);
    // A "* 2.0 - 1.0" remap on this term would make it signed.
    EXPECT_EQ(line.find("2.0 - 1.0"), std::string::npos)
        << "rim noise is signed; it must only raise the threshold: " << line;
    EXPECT_NE(src.find("kHullFieldIsoMargin + kFieldRimNoise"), std::string::npos)
        << "rim noise must be ADDED to the iso margin";
}

namespace {

// Classify EVERY pixel of the frame, not just the centre one.
//
// The centre fragment is useless for this feature: with identity matrices
// p_body IS the fragment's NDC position, so the centre sits at
// (1/64, 1/64, 0) -- within 0.006 of the noise lattice's origin, where
// vh3(0,0,0) = fract(sin(0)*k) = 0 EXACTLY on any precision. vnoise3 there
// is ~1e-4, i.e. the rim term is invisible at the one pixel every other test
// in this file reads. Scanning the whole frame sweeps p_body across
// [-1,1]^2, which at kFieldRimFreq = 0.35 covers parts of four noise cells
// and gives the term room to differ from pixel to pixel.
//
// Deliberately NOT predicting which pixels: vh3 is fract(sin(x)*43758), so a
// float32 GPU and a double host disagree wildly on any individual lattice
// hash. Only frame-wide "some, and not all" statements are portable.
struct FrameCoverage {
    int lit  = 0;   // hull survived
    int dark = 0;   // discarded (cleared black shows through)
    int other = 0;  // neither -- would mean the fixture stopped being binary
};

FrameCoverage classify_frame() {
    glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
    std::vector<unsigned char> px(static_cast<std::size_t>(kW) * kH * 4);
    glReadPixels(0, 0, kW, kH, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
    FrameCoverage c;
    for (std::size_t i = 0; i < px.size(); i += 4) {
        const int sum = px[i] + px[i + 1] + px[i + 2];
        if (sum >= 384)     ++c.lit;
        else if (sum <= 32) ++c.dark;
        else                ++c.other;
    }
    return c;
}

// A uniform field whose sampled value is `value / 255` everywhere (uniform
// in, uniform out: bilinear, the Z lerp and the replicated atlas border all
// preserve a constant). Same geometry as make_probe_field, so p_body's
// [-1,1]^2 sweep stays inside the field's box on every pixel.
voxel::DistanceField make_flat_field(std::int8_t value) {
    return make_uniform_field(glm::ivec3(4, 4, 4), glm::vec3(-2.5f),
                              glm::vec3(1.0f), value);
}

}  // namespace

// BEHAVIOURAL half of Task 3, and the reason it exists: the text guard above
// passes against a shader that declares kFieldRimNoise and never uses it --
// the exact failure mode Task 2's constant-parity test was found to have.
//
// Field value +1 (1/255 = 0.00392) is ABOVE the plain iso margin (0.5/255 =
// 0.00196) and BELOW margin + kFieldRimNoise (0.0620), so it sits inside the
// band the rim noise governs. Without the noise term the threshold is the
// bare margin and EVERY pixel is discarded; with it, a pixel is cut only
// where vnoise3(p_body * kFieldRimFreq) < (0.00392 - 0.00196)/0.06 = 0.033.
//
// Both directions are asserted from the SAME uniform field, which is what
// makes the pair meaningful: the field value is identical at every pixel, so
// the only position-dependent term left in the comparison is the rim noise.
//   - some pixels lit  => the noise term exists and raises the threshold
//                         (impossible without it: 0.00392 > 0.00196)
//   - some pixels dark => the field clip is still live and the noise is
//                         bounded (a huge or unbounded term would spare the
//                         whole frame, and "something survived" would then
//                         pass against a shader that cuts nothing at all)
TEST_F(HullFieldClipTest, FieldRimNoiseSparesFragmentsTheBareMarginWouldCut) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    const voxel::DistanceField field = make_flat_field(/*value=*/1);
    enable_field(prog, field, /*invert=*/false);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    const FrameCoverage c = classify_frame();
    EXPECT_EQ(c.other, 0) << "frame is no longer binary lit/discarded: "
                          << c.other << " intermediate pixels";
    EXPECT_GT(c.lit, 0)
        << "every one of " << (kW * kH) << " pixels was discarded -- a field "
           "value of 1/255 exceeds the bare iso margin, so this is exactly "
           "the frame the shader produces with NO rim-noise term. The hole's "
           "edge is the brush's smooth ellipsoid again.";
    EXPECT_GT(c.dark, 0)
        << "no pixel was discarded anywhere (lit=" << c.lit << ") -- the "
           "field clip is not cutting at all, so the surviving pixels above "
           "prove nothing about the rim noise";
}

// ONE-SIDEDNESS, behaviourally. The rim noise may only RAISE the threshold.
// A signed version (`* 2.0 - 1.0`, the remap the sphere block's own rim noise
// uses, one copy-paste away) would drop the threshold as low as
// 0.00196 - 0.06 = -0.058, cutting hull the field says is UNDAMAGED -- hull
// with no interior behind it, which is the see-through defect this plan
// exists to remove.
//
// Field value -10 (-0.0392) is comfortably below the plain margin -- 10.5
// quantisation steps below it, so no rounding can flip the sign -- and
// comfortably inside the [-0.058, +0.062] window a signed term would sweep.
// So: nothing may be cut here, at any pixel, ever.
TEST_F(HullFieldClipTest, FieldRimNoiseNeverCutsBelowThePlainMargin) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    const voxel::DistanceField field = make_flat_field(/*value=*/-10);
    enable_field(prog, field, /*invert=*/false);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    const FrameCoverage c = classify_frame();
    EXPECT_EQ(c.other, 0) << "frame is no longer binary lit/discarded: "
                          << c.other << " intermediate pixels";
    EXPECT_EQ(c.dark, 0)
        << c.dark << " of " << (kW * kH) << " pixels were discarded where the "
           "field reads -10/255, i.e. NO damage. The rim noise is signed: it "
           "lowered the threshold below the field value and grew the hole "
           "past the region field_brush.cc guarantees damage in.";
    EXPECT_EQ(c.lit, kW * kH);
}
