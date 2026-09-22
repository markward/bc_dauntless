// native/tests/renderer/breach_raymarch_test.cc
//
// Tests for the breach cavity-wall raymarch (raymarched-breach-interior
// Task 2): given a body-frame ray origin/direction, `raymarch_breach_cavity`
// (breach.frag) steps into the damage field until it drops back below
// kHullFieldIsoMargin -- the far wall of the carved cavity -- and reports
// that crossing's position and outward (into-the-cavity) normal, or a MISS
// when no such crossing exists within a bounded step/distance budget.
//
// breach.frag's own main() calls this function directly as of Task 3 round 3
// (one hull-mesh draw per damaged instance, no entry search -- see
// breach_pass.h). It is ALSO tested here in isolation, DIRECTLY against the
// shipped shader text: every test below reads breach.frag off disk, splices its own
// real production source (everything up to its real `void main()`, which
// includes the raymarch function itself) onto a tiny test-only main() that
// calls raymarch_breach_cavity() and reports the result, then compiles and
// runs that through a real GL context. This is deliberately NOT a
// hand-copied reimplementation of the shader logic in C++: this branch has
// already shipped tests that passed without exercising the code they named
// because the sample point never reached it, or because the assertion
// couldn't tell a broken value from a correct one. Compiling the actual file
// under test, and doing the crossing arithmetic below by hand before writing
// each assertion, is how this file avoids repeating that.
//
// Field convention (voxel::DistanceField / field_atlas.h / breach.frag's own
// HULL_FIELD_SAMPLING block): every untouched cell is -127 ("no damage");
// sample_hull_field returns a value whose SIGN matches that convention
// rescaled -- positive means carved, negative means intact -- and
// kHullFieldIsoMargin (0.5/255, the same value opaque.frag's hull clip uses)
// is the only threshold any consumer compares against.

#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <renderer/hdr_target.h>
#include <renderer/shader.h>
#include <renderer/window.h>

#include <voxel/distance_field.h>
#include <voxel/field_atlas.h>

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <memory>
#include <regex>
#include <sstream>
#include <string>
#include <vector>

namespace {

namespace fs = std::filesystem;

constexpr int kW = 4;
constexpr int kH = 4;

fs::path shader_path(const char* rel) {
    return fs::path(OPEN_STBC_PROJECT_ROOT) / "native" / "src" / "renderer" / "shaders" / rel;
}

std::string read_file(const fs::path& p) {
    std::ifstream in(p);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

// Splices breach.frag's own production prefix (everything up to its real
// `void main(`, which is where the drift-guarded field sampling AND the
// raymarch function under test both live) onto a tiny test-only main() that
// calls raymarch_breach_cavity() directly and reports the result packed
// into frag_color: .rgb is either hit_point or hit_normal (selected by
// u_test_mode) and .a is 1.0 on a hit, 0.0 on a miss.
std::string build_test_fragment_source(std::string* err) {
    const std::string src = read_file(shader_path("breach.frag"));
    const std::string anchor = "void main(";
    const auto pos = src.find(anchor);
    if (pos == std::string::npos) {
        *err = "breach.frag: no 'void main(' found -- cannot splice a test main onto it";
        return {};
    }
    if (src.find(anchor, pos + anchor.size()) != std::string::npos) {
        *err = "breach.frag: more than one 'void main(' -- splice point is ambiguous";
        return {};
    }
    std::string out = src.substr(0, pos);
    out += R"GLSL(
// ---- test-only main appended by breach_raymarch_test.cc: NOT shipped ----
uniform vec3 u_test_ro;
uniform vec3 u_test_rd;
uniform int  u_test_mode;   // 0 = report hit_point, 1 = report hit_normal

void main() {
    // Sentinel (NOT zero): the point of UndamagedFieldMisses' zero-init
    // assertion is to prove raymarch_breach_cavity itself writes hit_point/
    // hit_normal to vec3(0.0) before any early return, not merely that this
    // test harness's own locals started at zero. Starting them at a
    // conspicuously non-zero value here means a miss that reads back
    // ~(0,0,0) can only be explained by the CALLEE having written it.
    vec3 hit_point  = vec3(999.0);
    vec3 hit_normal = vec3(999.0);
    bool hit = raymarch_breach_cavity(u_test_ro, u_test_rd, hit_point, hit_normal);
    vec3 payload = (u_test_mode == 0) ? hit_point : hit_normal;
    frag_color = vec4(payload, hit ? 1.0 : 0.0);
}
)GLSL";
    return out;
}

// Fullscreen triangle; the fragment result depends only on the test
// uniforms, not on screen position, so every covered fragment reads the
// same value and it doesn't matter which one glReadPixels lands on.
const char* kTestVertexSrc = R"GLSL(
#version 410 core
layout(location = 0) in vec3 a_pos;
out vec3 v_body_pos;
out vec3 v_body_normal;
out vec3 v_world_pos;
void main() {
    v_body_pos    = vec3(0.0);
    v_body_normal = vec3(0.0, 0.0, 1.0);
    v_world_pos   = vec3(0.0);
    gl_Position   = vec4(a_pos, 1.0);
}
)GLSL";

// Every (x, y) at Z-slice `i` gets `z_values[i]`. A pure single-axis slab,
// so the field's spatial gradient is unambiguous (purely along Z) and the
// X/Y bilinear terms never enter the arithmetic below.
voxel::DistanceField make_slab_field(glm::ivec3 dims, glm::vec3 origin, glm::vec3 cell,
                                     const std::vector<std::int8_t>& z_values) {
    voxel::DistanceField f;
    f.dims   = dims;
    f.origin = origin;
    f.cell   = cell;
    f.scale  = 1.0f;
    f.dist.assign(static_cast<std::size_t>(dims.x) * dims.y * dims.z, 0);
    for (int z = 0; z < dims.z; ++z) {
        for (int y = 0; y < dims.y; ++y) {
            for (int x = 0; x < dims.x; ++x) {
                f.dist[f.index(x, y, z)] = z_values.at(static_cast<std::size_t>(z));
            }
        }
    }
    return f;
}

// Mirrors InstanceFieldCache::upload()'s GL_R8 layout (same helper as
// hull_field_clip_test.cc's; duplicated here rather than shared -- this
// project's existing per-file test convention, see that file). Bound and
// left bound on unit 6, never the caller's active unit.
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
    glPixelStorei(GL_UNPACK_ALIGNMENT, prev_unpack);
    glActiveTexture(static_cast<GLenum>(prev_unit));
    return tex;
}

class BreachRaymarchTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    GLuint vao_       = 0;
    GLuint vbo_       = 0;
    GLuint field_tex_ = 0;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "breach-raymarch-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }

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
        glBindVertexArray(0);
    }

    void TearDown() override {
        if (field_tex_) { glDeleteTextures(1, &field_tex_); field_tex_ = 0; }
        if (vbo_)       { glDeleteBuffers(1, &vbo_);        vbo_       = 0; }
        if (vao_)       { glDeleteVertexArrays(1, &vao_);   vao_       = 0; }
    }

    std::unique_ptr<renderer::Shader> compile_probe() {
        std::string err;
        const std::string fsrc = build_test_fragment_source(&err);
        if (fsrc.empty()) {
            ADD_FAILURE() << err;
            return nullptr;
        }
        try {
            return std::make_unique<renderer::Shader>(kTestVertexSrc, fsrc);
        } catch (const std::exception& e) {
            ADD_FAILURE() << "spliced breach.frag probe failed to compile/link: " << e.what();
            return nullptr;
        }
    }

    // Every uniform the spliced prefix declares that this test doesn't
    // otherwise care about, set defensively (Shader::set_* no-ops for a
    // uniform the compiler optimised away because the test main() never
    // reads it) -- belt-and-braces against the exact "unset sampler
    // collides on unit 0" hazard this project has already been bitten by
    // (see breach.frag's own comment above u_hull_field).
    void set_common_uniforms(renderer::Shader& s) {
        s.use();
        s.set_int("u_fill", 7);
        s.set_int("u_damage_tex", 8);
        s.set_vec3("u_fill_origin", glm::vec3(0.0f));
        s.set_vec3("u_fill_cell", glm::vec3(1.0f));
        s.set_ivec3("u_fill_dims", glm::ivec3(1));
        s.set_float("u_fill_iso", 64.0f / 255.0f);
        s.set_float("u_fill_backing", 0.0f);
        s.set_vec3("u_camera_pos_ws", glm::vec3(0.0f));
        s.set_float("u_tex_scale", 1.0f);
        s.set_float("u_breach_age", 1.0e6f);
        s.set_float("u_rim_life", 1.0f);
    }

    void bind_field(renderer::Shader& s, const voxel::DistanceField& field) {
        voxel::AtlasLayout layout;
        field_tex_ = upload_field_atlas(field, layout);
        s.set_int("u_hull_field", 6);
        s.set_vec3("u_hull_field_origin", field.origin);
        s.set_vec3("u_hull_field_cell", field.cell);
        s.set_vec3("u_hull_field_dims", glm::vec3(field.dims));
        s.set_vec2("u_hull_field_tiles",
                   glm::vec2(static_cast<float>(layout.tiles_x), static_cast<float>(layout.tiles_y)));
        s.set_vec2("u_hull_field_texel",
                   glm::vec2(1.0f / static_cast<float>(layout.width),
                             1.0f / static_cast<float>(layout.height)));
    }

    glm::vec4 draw_and_read(renderer::Shader& s, const glm::vec3& ro, const glm::vec3& rd, int mode) {
        s.use();
        s.set_vec3("u_test_ro", ro);
        s.set_vec3("u_test_rd", rd);
        s.set_int("u_test_mode", mode);

        renderer::HdrTarget hdr;   // RGBA16F: needs values outside [0,1] and negatives
        hdr.resize(kW, kH);
        hdr.bind();
        glDisable(GL_DEPTH_TEST);
        glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glBindVertexArray(vao_);
        glDrawArrays(GL_TRIANGLES, 0, 3);
        glBindVertexArray(0);
        glFinish();

        float px[4] = {0.0f, 0.0f, 0.0f, 0.0f};
        glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_FLOAT, px);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        return glm::vec4(px[0], px[1], px[2], px[3]);
    }
};

}  // namespace

// ── Known cavity: finds the wall within one cell of the analytic answer ────
//
// Slab field along Z (cell=1, origin=0, dims=(2,2,8)): slices 0-2 solidly
// carved (+100), slices 3-7 solidly intact (-100). sample_hull_field's own
// derivation (breach.frag) says its return value is byte/255 - 128/255; for
// d=+-100, scale=1: byte = round(d)+128 = 228 or 28, so the two plateau
// values are 228/255 - 128/255 = +0.392157 and 28/255 - 128/255 = -0.392157
// exactly (integer d, scale 1 -> zero quantisation error).
//
// Slice i's own sample sits at body z = i + 0.5 (g.z = (z-origin)/cell - 0.5
// lands exactly on integer i there). Between slice 2 (z=2.5) and slice 3
// (z=3.5) the field is linearly interpolated, so solving
//   mix(+0.392157, -0.392157, wz) == kHullFieldIsoMargin (0.5/255 = 0.0019608)
// for wz gives wz = (0.392157 - 0.0019608) / 0.784314 = 0.497500, i.e. the
// analytic crossing is at z = 2.5 + 0.497500 = 2.9975 -- independent of ro's
// phase (the crossing is intrinsic to the field; ro only decides which step
// lattice samples it).
//
// ro.z = 0.75 (not the lattice-aligned 0.5) is deliberate. With step 0.5
// starting at 0.5, samples land at 1.0, 1.5, 2.0, 2.5, 3.0, ..., and the
// bracket that catches 2.9975 is [2.5, 3.0]; the true crossing sits at
// t=(0.392157-0.0019608)/0.784314=0.995 of THAT bracket -- barely
// distinguishable from simply returning p_next (3.0 is already within 0.003
// of the true 2.9975). Starting at 0.75 instead shifts the lattice to
// 1.25, 1.75, ..., 2.75, 3.25, so the same crossing now falls at t=0.495 of
// the bracket [2.75, 3.25]: genuinely MID-bracket, so returning p_next
// (3.25) instead of the refined point is off by a full quarter cell -- which
// the tight tolerance below actually catches, unlike the original phase.
TEST_F(BreachRaymarchTest, FindsWallOfKnownCavityWithinOneCell) {
    const std::vector<std::int8_t> z_values = {100, 100, 100, -100, -100, -100, -100, -100};
    const voxel::DistanceField field =
        make_slab_field(glm::ivec3(2, 2, 8), glm::vec3(0.0f), glm::vec3(1.0f), z_values);

    auto prog = compile_probe();
    ASSERT_NE(prog, nullptr);
    set_common_uniforms(*prog);
    bind_field(*prog, field);

    const glm::vec3 ro(0.5f, 0.5f, 0.75f);  // deep in slice 0; off-lattice phase, see above
    const glm::vec3 rd(0.0f, 0.0f, 1.0f);   // marching straight into the hull
    const glm::vec4 out = draw_and_read(*prog, ro, rd, /*mode=*/0);

    ASSERT_GT(out.w, 0.5f) << "expected a hit: ro is inside carved material (+100) and the "
                              "field genuinely returns to intact material (-100) past z=2.5";
    EXPECT_NEAR(out.z, 2.9975f, 1.0f)
        << "hit_point.z=" << out.z << " -- more than one cell from the analytic crossing "
           "2.9975 (the brief's own stated acceptance bound)";
    // Tighter check: with this ro, the true crossing sits mid-bracket
    // (t=0.495 -- see the derivation above), so an implementation that skips
    // linear refinement and just returns p_next would read ~3.25, a full
    // quarter cell off and well outside this tolerance.
    EXPECT_NEAR(out.z, 2.9975f, 0.05f)
        << "hit_point.z=" << out.z << " -- expected the refined crossing near 2.9975, not "
           "p_next (~3.25) from skipping linear refinement";
    EXPECT_NEAR(out.x, 0.5f, 1e-3f) << "X must not move: rd has no X component";
    EXPECT_NEAR(out.y, 0.5f, 1e-3f) << "Y must not move: rd has no Y component";
}

// ── kHullFieldIsoMargin actually participates in the crossing, not just 0.0 ─
//
// The mutation this test must kill is BOTH `<= kHullFieldIsoMargin`
// comparisons (the top-of-function precondition and the in-loop check)
// replaced with `<= 0.0`, leaving the refinement line's
// `t = clamp((prev - kHullFieldIsoMargin) / ..., 0, 1)` UNTOUCHED. An
// earlier version of this test used plateaus of +-1 with ro phased so the
// triggering sample landed at EXACTLY field value 0.0 -- but a value of
// exactly 0.0 satisfies `<= 0.0` and `<= margin` at the very same sample,
// so detection timing (which sample triggers) was identical either way,
// and only the (still-correct, untouched) refinement line's arithmetic
// differed. That is not the mutation described above: it does not
// distinguish "the comparison used 0.0" from "the comparison used margin",
// only "the refinement subtracted 0.0 instead of margin" -- a DIFFERENT,
// already-fixed bug (see FindsWallOfKnownCavityWithinOneCell's sibling
// history). To kill the actual mutation, a march sample must exist whose
// value sits STRICTLY inside (0, kHullFieldIsoMargin) = (0, 0.0019608): a
// value there satisfies `<= margin` (triggers correctly) but NOT `<= 0.0`
// (does not trigger under the mutation), so the two implementations
// disagree about WHICH sample the crossing is, not just how it's refined.
//
// A plateau cannot land there: the smallest positive quantised value is
// 1/255 = 0.00392, already 2x the margin. It has to come from
// INTERPOLATION at a chosen fractional slice position wz. Derivation, with
// plateaus +-1 (encoded +-1/255 exactly -- byte=129 or 127, /255 minus
// 128/255):
//   v(wz) = mix(v0, v1, wz) = v0 - wz*(v0 - v1),  v0=1/255, v1=-1/255
//   v(wz) == 0            at wz = v0 / (v0-v1)          = 0.5
//   v(wz) == margin(0.5/255) at wz = (v0-margin) / (v0-v1) = 0.25
// so wz in (0.25, 0.5) gives v in (0, margin). Picking the midpoint,
// wz=0.375 (comfortably clear of both edges), gives
//   v = 1/255 - 0.375*(2/255) = 0.25/255 = 0.00098039,
// which is indeed strictly between 0 and margin (0.5/255=0.00196078).
//
// Realising wz=0.375 physically: with cell=1, origin=0, sample-space is
// g.z = z - 0.5, so g.z=2.375 (s0=2, s1=3, wz=0.375, the carved/intact
// boundary between slice 2 and slice 3) is body z = 2.875. Field:
// slices 0-2 = +1 (carved), 3-7 = -1 (intact), so slice 2 -> 3 is the same
// boundary every other test in this file crosses. ro.z=0.375 puts the
// march's 0.5-spaced sample lattice (step_len = 0.5*breach_min_cell() =
// 0.5*1 = 0.5) exactly on 2.875 (and on 2.375, the sample immediately
// before it, which reads a clean +1 = 0.0039216, comfortably above margin
// -- no premature trigger). ro itself (z=0.375, Z-clamped to slice 0) also
// reads +1, safely above margin, so the top-of-function precondition never
// interferes here either.
//
// CORRECT trajectory: every sample up to and including z=2.375 reads +1
// (0.0039216 > margin, no trigger). At z=2.875, v=0.25/255=0.00098039,
// which IS <= margin (0.0019608) -- triggers. prev (from z=2.375) = 1/255.
//   t = (prev - margin) / (prev - v) = (1/255 - 0.5/255) / (1/255 - 0.25/255)
//     = (0.5/255) / (0.75/255) = 2/3
//   hit.z = mix(2.375, 2.875, 2/3) = 2.375 + (2/3)*0.5 = 2.708333
//
// MUTATED trajectory (both comparisons -> <= 0.0, refinement line
// untouched): at z=2.875, v=0.00098039 does NOT satisfy `<= 0.0` (it's
// positive) -- no trigger; prev advances to 0.00098039, p_prev to 2.875.
// Next sample z=3.375: g.z=2.875, wz=0.875, v = 1/255 - 0.875*(2/255)
// = -0.75/255 = -0.00294118, which DOES satisfy `<= 0.0` -- triggers here
// instead, a full step later than the correct implementation.
//   t = (prev - margin) / (prev - v)  [refinement line itself untouched]
//     = (0.25/255 - 0.5/255) / (0.25/255 - (-0.75/255))
//     = (-0.25/255) / (1.0/255) = -0.25, clamped to 0.0
//   hit.z = mix(2.875, 3.375, 0.0) = 2.875
//
// 2.708333 (correct) vs 2.875 (mutated): a 0.1667 difference, well outside
// the 0.05 tolerance below -- this is what actually kills the mutation
// the finding named, verified live (see the task report).
TEST_F(BreachRaymarchTest, IsoMarginParticipatesInTheCrossingNotJustZero) {
    const std::vector<std::int8_t> z_values = {1, 1, 1, -1, -1, -1, -1, -1};
    const voxel::DistanceField field =
        make_slab_field(glm::ivec3(2, 2, 8), glm::vec3(0.0f), glm::vec3(1.0f), z_values);

    auto prog = compile_probe();
    ASSERT_NE(prog, nullptr);
    set_common_uniforms(*prog);
    bind_field(*prog, field);

    const glm::vec3 ro(0.5f, 0.5f, 0.375f);
    const glm::vec3 rd(0.0f, 0.0f, 1.0f);
    const glm::vec4 out = draw_and_read(*prog, ro, rd, /*mode=*/0);

    ASSERT_GT(out.w, 0.5f) << "expected a hit";
    EXPECT_NEAR(out.z, 2.708333f, 0.05f)
        << "hit_point.z=" << out.z << " -- expected the margin-triggered crossing at "
           "~2.708333; a comparison of <= 0.0 instead of <= kHullFieldIsoMargin would miss "
           "this sample entirely and trigger one step later, at ~2.875";
}

// ── Undamaged field: a miss, not a hallucinated wall ────────────────────────
//
// Every cell -127 (the field's own "no damage" default, per field_atlas.h).
// sample_hull_field(ro) itself reads deep negative (well below the margin),
// so there is no carved material at all for the ray to have started inside
// -- the march must refuse to step and report a miss.
//
// Discrimination: if the "must already be inside carved material" guard
// were removed, the very first step would compare two SAME-valued samples
// (both -127) against the margin, both satisfying `v <= margin`, and the
// refinement fraction's denominator (prev - v) would be ~0 -- the clamped
// division still produces a `t` in [0,1] and the function would report a
// spurious hit (out.w = 1.0) at or near `ro` instead of the expected miss.
TEST_F(BreachRaymarchTest, UndamagedFieldMisses) {
    const std::vector<std::int8_t> z_values = {-127, -127, -127, -127};
    const voxel::DistanceField field =
        make_slab_field(glm::ivec3(2, 2, 4), glm::vec3(0.0f), glm::vec3(1.0f), z_values);

    auto prog = compile_probe();
    ASSERT_NE(prog, nullptr);
    set_common_uniforms(*prog);
    bind_field(*prog, field);

    const glm::vec4 out = draw_and_read(*prog, glm::vec3(0.5f, 0.5f, 0.5f), glm::vec3(0.0f, 0.0f, 1.0f), 0);
    EXPECT_LT(out.w, 0.5f)
        << "field is -127 (no damage) everywhere -- there is no cavity to be inside, so the "
           "march must report a miss (paint nothing), not hallucinate a wall at/near ro "
           "(got hit_point=(" << out.x << "," << out.y << "," << out.z << "), hit=" << out.w << ")";
    // hit_point is written vec3(0.0) at raymarch_breach_cavity's own entry
    // (not left undefined on a miss): the GLSL spec leaves an `out`
    // parameter the callee never writes as implementation-defined on
    // return, and this shader's own HDR bloom pass has a documented history
    // of an uninitialised/NaN value turning into a black square downstream
    // -- a caller that reads hit_point without checking the bool return
    // first should still get a defined value.
    //
    // HONESTLY DISCLOSED LIMIT on this assertion's discrimination: I tried
    // to verify it the same way as every other fix in this file -- change
    // this test harness's own local `hit_point`/`hit_normal` sentinel
    // (build_test_fragment_source's test-only main()) from vec3(0.0) to a
    // conspicuous vec3(999.0), then remove breach.frag's explicit zero-init
    // and confirm this test starts failing. It did NOT: even with the
    // sentinel at 999.0 and the explicit init removed, this miss still read
    // back (0,0,0) to within 1e-6. That means on THIS machine's shader
    // toolchain, `out` parameters left unwritten on some path are already
    // auto-zeroed by the compiler itself (a real, observed platform
    // behaviour, not a guess) -- so this specific assertion cannot be
    // proven to catch a regression HERE. The production zero-init is kept
    // anyway because the GLSL spec still calls the unwritten case
    // implementation-defined in general (a different driver/compiler is not
    // guaranteed to zero it), so this remains a live CONTRACT check -- read
    // it as "the function's documented behaviour", not as verified evidence
    // that removing the fix would be caught here.
    EXPECT_NEAR(out.x, 0.0f, 1e-6f) << "hit_point.x must be the zero-initialised default on a miss";
    EXPECT_NEAR(out.y, 0.0f, 1e-6f) << "hit_point.y must be the zero-initialised default on a miss";
    EXPECT_NEAR(out.z, 0.0f, 1e-6f) << "hit_point.z must be the zero-initialised default on a miss";
}

// ── Carved everywhere reachable: a miss, not a wall painted at the budget's edge
//
// Every cell +100 (solidly carved) across the whole field, AND -- because
// sample_hull_field clamps its Z index into [0, dims.z-1] with no border
// fallback beyond that -- the sampled value stays +100 forever past the
// field's own box too. There is no crossing anywhere the march can reach;
// it must exhaust its bounded budget (breach_field_reach(), for this small
// field's dims=(2,2,4)/cell=1 -- see the reach test below for a realistic-
// scale version) and report a miss.
//
// NOTE on naming: an earlier version of this test was called
// "CleanThroughCarveMissesRatherThanPaintingFarWall" and its comment
// claimed this models a carve that "cuts clean through a thin plate". That
// claim was FALSE and has been corrected out of raymarch_breach_cavity's
// own doc comment (see its "KNOWN GAP" paragraph in breach.frag): the field
// carries damage only, never real hull geometry, so a carve punched through
// an actual thin plate still deposits a BOUNDED, brush-shaped positive
// region with its own far edge -- this function currently WOULD find a
// (spurious) hit there. This test's all-+100 field has no such bounded
// region at all (nothing anywhere reverts to intact), which is a different,
// simpler scenario: pure budget exhaustion, not "no far wall by
// construction". The actual bounded-brush case (a carve that punches clean
// through a thin plate) is exercised end-to-end, through the real main()
// and its fill/backing check, by breach_pass_test.cc's
// HitWithNoBackingMaterialDoesNotPaint -- this file's own splice harness
// bypasses main() entirely (see build_test_fragment_source above) and so
// cannot observe that fix; see this file's git history for the test that
// used to document the gap here before Task 3 closed it.
//
// Discrimination: if budget exhaustion were (wrongly) treated as a hit at
// the last sampled point -- a plausible "ran out of budget, but I found
// SOMETHING" bug -- out.w would read 1.0 here instead of the expected miss.
TEST_F(BreachRaymarchTest, CarvedThroughoutTheReachableFieldMissesRatherThanPaintingAFarWall) {
    const std::vector<std::int8_t> z_values = {100, 100, 100, 100};
    const voxel::DistanceField field =
        make_slab_field(glm::ivec3(2, 2, 4), glm::vec3(0.0f), glm::vec3(1.0f), z_values);

    auto prog = compile_probe();
    ASSERT_NE(prog, nullptr);
    set_common_uniforms(*prog);
    bind_field(*prog, field);

    const glm::vec4 out = draw_and_read(*prog, glm::vec3(0.5f, 0.5f, 0.5f), glm::vec3(0.0f, 0.0f, 1.0f), 0);
    EXPECT_LT(out.w, 0.5f)
        << "field reads carved everywhere the march can reach -- there is no crossing, so a "
           "hit here (got hit_point=(" << out.x << "," << out.y << "," << out.z
        << ")) would paint a wall where the correct result is to draw nothing";
}

// ── (Retired) KNOWN GAP: the march alone cannot tell a brush boundary from
// real backing ───────────────────────────────────────────────────────────
//
// A test named RaymarchAloneCannotDistinguishABrushBoundaryFromRealBacking
// used to live here, documenting that raymarch_breach_cavity() alone (same
// field/ro as FindsWallOfKnownCavityWithinOneCell: carved 0-2, intact 3-7,
// cell=1, ro=(0.5,0.5,0.75)) cannot tell a genuine cavity wall from a carve
// brush's far edge floating past a thin plate with nothing behind it --
// because the field carries damage only, both shapes look identical to the
// field alone (see raymarch_breach_cavity's "KNOWN GAP" doc comment in
// breach.frag). That was Task 2's deliberately incomplete state.
//
// Task 3 closed the gap -- NOT inside raymarch_breach_cavity() itself
// (unchanged: it still, correctly, reports a hit for this exact field/ro
// pair; that is its whole documented job) but in main(), which now checks
// the fill/backing volume at hit_point before painting anything. Editing
// the old test to keep asserting hit=true would have kept it green while
// documenting a bug the code no longer has, so it was removed rather than
// patched; breach_pass_test.cc's HitWithNoBackingMaterialDoesNotPaint
// asserts the CORRECTED end-to-end behaviour instead -- through the real
// main(), which this file's splice harness (build_test_fragment_source,
// above) cannot reach, since main() is exactly what it replaces.

// ── Step size catches a one-cell-thin wall, not the far side of it ─────────
//
// Field: slices 0-1 carved (+100), slice 2 ALONE intact (-100: a wall
// exactly one cell thick), slices 3-4 carved again (+100, standing in for
// open space -- or another cavity -- beyond the thin wall). By the same
// derivation as FindsWallOfKnownCavityWithinOneCell, the NEAR (entrance)
// crossing, between slice 1 (z=1.5) and slice 2 (z=2.5), is at
// z = 1.5 + 0.497500 = 1.9975; the FAR (exit) crossing, between slice 2
// and slice 3, is at z = 2.5 + 0.502500 = 3.0025 (by the mirrored fraction,
// crossing upward through the margin instead of downward).
//
// Starting at ro.z=1.0 (still reading carved: g.z=0.5 blends two +100
// slices), the correct step (kHullFieldStepFrac * min cell = 0.5) samples
// at 1.5, 2.0, 2.5, ... and finds the NEAR crossing at ~1.9975 (verified by
// hand in the task report). A step of 2.0 -- double the correct step, e.g.
// from a dropped or doubled step-fraction constant -- samples at 3.0, 5.0,
// ... from the same ro: both prev (ro=1.0, +0.392) and the first next
// (z=3.0) still satisfy prev>margin>=v respectively, so the function still
// reports "a" crossing, but between the WRONG pair of samples: its own
// linear refinement lands at z ~= 2.99 -- the FAR side of the one-cell
// wall, a full cell away from the true near-wall answer. This was verified
// live by temporarily editing kHullFieldStepFrac to 2.0, rebuilding, and
// confirming this exact test fails with hit_point.z near 2.99 (see the
// task report's TDD evidence).
TEST_F(BreachRaymarchTest, StepSizeCatchesAOneCellThinWallNotTheFarSide) {
    const std::vector<std::int8_t> z_values = {100, 100, -100, 100, 100};
    const voxel::DistanceField field =
        make_slab_field(glm::ivec3(2, 2, 5), glm::vec3(0.0f), glm::vec3(1.0f), z_values);

    auto prog = compile_probe();
    ASSERT_NE(prog, nullptr);
    set_common_uniforms(*prog);
    bind_field(*prog, field);

    const glm::vec3 ro(0.5f, 0.5f, 1.0f);
    const glm::vec3 rd(0.0f, 0.0f, 1.0f);
    const glm::vec4 out = draw_and_read(*prog, ro, rd, /*mode=*/0);

    ASSERT_GT(out.w, 0.5f) << "expected a hit -- the thin wall is real and the correct step "
                              "size must find it";
    EXPECT_NEAR(out.z, 1.9975f, 0.2f)
        << "hit_point.z=" << out.z << " -- expected the NEAR crossing (the thin wall's own "
           "entrance, ~1.9975), not its far side (~3.0, roughly a whole cell further, which is "
           "what a too-coarse step size finds by tunnelling straight through the wall)";
}

// ── breach_min_cell() uses the SMALLEST axis, not X, not the largest ───────
//
// Identical field/ro/rd to StepSizeCatchesAOneCellThinWallNotTheFarSide
// above, EXCEPT cell=(4,4,1): the march axis (Z) now has the SMALLEST cell
// (1.0) while X and Y are much larger (4.0). All the Z-axis arithmetic in
// that test's derivation is keyed only on cell.z, so it is unchanged:
// step_len = 0.5 * breach_min_cell() must still equal 0.5 * 1.0 = 0.5 (using
// the small Z axis) for the march to find the near crossing at ~1.9975, the
// same way it did with an isotropic cell=(1,1,1).
//
// If breach_min_cell() picked the wrong axis -- `max` instead of `min`, or
// just `.x`/`.y` -- it would return 4.0 here instead of 1.0, giving
// step_len = 0.5*4.0 = 2.0. That is the EXACT step length this project
// already proved (by live mutation, see the task report) tunnels through
// this one-cell wall and lands on its far side instead, at z ~= 2.99 rather
// than 1.9975 -- so a min-vs-max/axis bug reproduces that same, already-
// measured failure here.
TEST_F(BreachRaymarchTest, StepSizeUsesTheSmallestCellAxisEvenWhenItIsNotTheMarchAxis) {
    const std::vector<std::int8_t> z_values = {100, 100, -100, 100, 100};
    const voxel::DistanceField field =
        make_slab_field(glm::ivec3(2, 2, 5), glm::vec3(0.0f), glm::vec3(4.0f, 4.0f, 1.0f), z_values);

    auto prog = compile_probe();
    ASSERT_NE(prog, nullptr);
    set_common_uniforms(*prog);
    bind_field(*prog, field);

    const glm::vec3 ro(0.5f, 0.5f, 1.0f);
    const glm::vec3 rd(0.0f, 0.0f, 1.0f);
    const glm::vec4 out = draw_and_read(*prog, ro, rd, /*mode=*/0);

    ASSERT_GT(out.w, 0.5f) << "expected a hit -- the thin wall is real and the correct "
                              "(smallest-axis) step size must find it";
    EXPECT_NEAR(out.z, 1.9975f, 0.2f)
        << "hit_point.z=" << out.z << " -- expected the NEAR crossing (~1.9975); a step "
           "derived from the LARGER X/Y cell (4.0) instead of the smaller Z cell (1.0) would "
           "tunnel through the thin wall and land near its far side (~2.99) instead, exactly "
           "as measured when kHullFieldStepFrac was live-mutated to 2.0 in the sibling test";
}

// ── Gradient normal points out of the wall, not into it ────────────────────
//
// Same field/ray as FindsWallOfKnownCavityWithinOneCell: field value
// DECREASES as z increases through the crossing (+100 carved -> -100
// intact), so the gradient -- which points toward INCREASING field value,
// i.e. toward the carved/cavity side (see breach_field_gradient's own
// comment) -- must point toward -Z: back toward the cavity the ray marched
// in from, roughly opposite `rd`.
//
// Discrimination: an inverted gradient (computed from -field, or with the
// two central-difference taps swapped) would flip this to +Z -- pointing
// further INTO the solid material -- lighting the interior inside-out. The
// checks below assert the SIGN of n.z and of dot(n, rd), not merely that a
// normal exists: a magnitude-only check (e.g. "the normal is unit length")
// would pass identically whichever way the sign came out.
TEST_F(BreachRaymarchTest, GradientNormalPointsOutOfTheWallNotIntoIt) {
    const std::vector<std::int8_t> z_values = {100, 100, 100, -100, -100, -100, -100, -100};
    const voxel::DistanceField field =
        make_slab_field(glm::ivec3(2, 2, 8), glm::vec3(0.0f), glm::vec3(1.0f), z_values);

    auto prog = compile_probe();
    ASSERT_NE(prog, nullptr);
    set_common_uniforms(*prog);
    bind_field(*prog, field);

    const glm::vec3 rd(0.0f, 0.0f, 1.0f);
    const glm::vec4 out = draw_and_read(*prog, glm::vec3(0.5f, 0.5f, 0.5f), rd, /*mode=*/1);

    ASSERT_GT(out.w, 0.5f) << "expected a hit to have a normal to check";
    const glm::vec3 n(out.x, out.y, out.z);
    const float len = glm::length(n);
    EXPECT_GT(len, 0.9f) << "hit_normal should be close to unit length, got length=" << len
                          << " (" << n.x << "," << n.y << "," << n.z << ")";
    EXPECT_LT(n.z, -0.9f)
        << "hit_normal=(" << n.x << "," << n.y << "," << n.z << ") -- expected it to point "
           "strongly toward -Z (back into the open cavity, opposite the march direction +Z); "
           "an inverted gradient would read close to +1.0 here instead, lighting the interior "
           "inside-out";
    EXPECT_LT(glm::dot(n, rd), -0.9f)
        << "the normal should oppose the march direction (it points back out of the wall "
           "toward the cavity/camera, not further into the solid material behind it)";
}

// ── Bounded steps: a pathological ray terminates ────────────────────────────
//
// Zero-length direction: p_next == ro on every iteration, so the sampled
// value never changes across the whole budget and the crossing condition
// can never trigger. If the loop were reachable via something unbounded
// (e.g. a `while(true)` instead of the `for (int i = 0; i < kBreachMaxSteps;
// ...)` this shader actually uses), this exact ray would spin the GPU
// forever: glFinish() below would never return, and this test -- and the
// whole binary -- would hang instead of failing cleanly. That this test
// completes at all, returning a well-defined miss, is itself the thing
// being verified; BreachRaymarchStaticGuard.LoopBoundIsANamedCompileTimeConstant
// below verifies the SAME property at the source level, so this hang can
// never be the only signal of a regression.
TEST_F(BreachRaymarchTest, BoundedStepsTerminateOnAPathologicalRay) {
    const std::vector<std::int8_t> z_values = {100, 100, 100, 100};
    const voxel::DistanceField field =
        make_slab_field(glm::ivec3(2, 2, 4), glm::vec3(0.0f), glm::vec3(1.0f), z_values);

    auto prog = compile_probe();
    ASSERT_NE(prog, nullptr);
    set_common_uniforms(*prog);
    bind_field(*prog, field);

    const glm::vec4 out = draw_and_read(*prog, glm::vec3(0.5f, 0.5f, 0.5f), glm::vec3(0.0f), /*mode=*/0);
    EXPECT_LT(out.w, 0.5f)
        << "field never drops below the margin (all +100, even via the sampler's edge clamp) "
           "and the direction never advances the sample point -- the correct, BOUNDED result "
           "is a miss once the step budget runs out, not a hang";
}

// ── Reach scales with the field's own extent, at a REALISTIC cell size ─────
//
// dims=(4,4,20), cell=(7.5,7.5,7.5) -- BC's authored cell is
// authored_res/quality (voxel/hull_volume_cache.h, quality=2.0); with
// authored_res running 6-15 across the fleet (docs/engine/damagetool-and-
// hull-damage-gaps.md), cell runs 3.0-7.5 model units. 7.5 is the TOP of
// that range (authored_res=15), chosen as a concrete, real, sourced value
// rather than a round number picked for convenience -- not because it is
// more "demanding": the crossing this test places (~97.48 model units,
// see below) is beyond the OLD fixed 64.0-unit cap regardless of which
// real cell size is used, since that old cap was a fixed distance, not a
// cell count.
// Slices 0-12 carved (+100), 13-19 intact (-100, 7 slices). Same margin
// fraction as every other crossing in this file (wz=0.497500 -- it depends
// only on the field VALUES, not on cell scale), applied at THIS cell's
// scale:
//   slice 12 centre z = (12+0.5)*7.5 = 93.75
//   slice 13 centre z = (13+0.5)*7.5 = 101.25
//   crossing z = 93.75 + 0.497500*7.5 = 97.48125
//
// ro=(0.5,0.5,0.5) (reads slice 0, deep carved via the Z clamp), rd=(0,0,1),
// step_len = 0.5*breach_min_cell() = 0.5*7.5 = 3.75. Reaching z~=97.48 from
// ro.z=0.5 takes ~26 steps -- far under kBreachMaxSteps=64, so the STEP
// BUDGET is not what's tested here; only the DISTANCE cap could plausibly
// stop this march short.
//
// This is exactly the scenario Important-1 in code review flagged: the
// field's own reach here is length(dims*cell) = length(30,30,150) ~= 155.9
// model units, comfortably past the crossing at 97.48, so the fix (deriving
// the cap from the field's own extent) finds it -- hit=true. The FIRST
// version of this shader used a flat `kBreachMaxDist = 64.0` model-unit
// constant instead: that cap fires at i=17 (dist=67.5>64), at z~=64.25,
// roughly a third of the way to the true crossing -- a MISS, wrongly, on a
// wall that genuinely exists. Verified live: temporarily reverting
// breach_field_reach() to return a fixed 64.0 and rebuilding makes this
// exact test fail with hit=false (see the task report's TDD evidence for
// the reviewer's follow-up), then reverted.
TEST_F(BreachRaymarchTest, RealisticCellSizeReachesAWallTheOldFixedCapWouldHaveMissed) {
    std::vector<std::int8_t> z_values(20, 100);
    for (int i = 13; i < 20; ++i) z_values[static_cast<std::size_t>(i)] = -100;
    const voxel::DistanceField field =
        make_slab_field(glm::ivec3(4, 4, 20), glm::vec3(0.0f), glm::vec3(7.5f), z_values);

    auto prog = compile_probe();
    ASSERT_NE(prog, nullptr);
    set_common_uniforms(*prog);
    bind_field(*prog, field);

    const glm::vec4 out = draw_and_read(*prog, glm::vec3(0.5f, 0.5f, 0.5f), glm::vec3(0.0f, 0.0f, 1.0f), 0);
    ASSERT_GT(out.w, 0.5f)
        << "expected a hit -- the crossing at z~=97.48 is well within the field's own extent "
           "(reach ~=155.9) even though it is well beyond the old, too-small fixed 64.0 cap";
    EXPECT_NEAR(out.z, 97.48125f, 1.0f)
        << "hit_point.z=" << out.z << " -- expected the crossing near 97.48";
}

// ── Static guards (no GL context needed) ────────────────────────────────────

namespace {

// Regex-based text checks over the actual shipped shader source, not a
// reimplementation -- these two are what let BoundedStepsTerminateOnAPathologicalRay's
// completion (rather than its absence) count as evidence: a bound that is a
// named, small, compile-time constant cannot become an unbounded loop
// without also failing this test.
//
// UPDATED across three rounds of the raymarched-breach-interior task. Round
// 1 shipped with exactly one loop (raymarch_breach_cavity's own). Round 2
// added a second, find_breach_entry, to search a box proxy for where a ray
// entered carved material -- necessary because the box (unlike the old
// per-carve sphere, whose geometry guaranteed the ray already started
// inside a carve) covered an instance's WHOLE hull, so most rays through it
// touched no carve at all. Round 3 removed find_breach_entry (and the box
// proxy it searched) entirely: breach_pass.cc now draws the REAL hull mesh
// under the carve stencil, so a fragment reaching main() already sits
// exactly on the hull surface at a carved point -- there is nothing left to
// search for, and no second loop's own bound to validate. A round-2 fix
// that widened find_breach_entry's stride to the smallest legal carve's
// DIAMETER could still step over that same carve's much narrower
// along-normal depth (kCarveDepthFactor=0.45 of radius, not the full
// diameter) -- removing the search removed that failure mode too, rather
// than trading one bound for another. This guard is back to validating the
// ONE loop that has ever been genuinely necessary.
//
// Round 4 (scene-lit interior) added a SECOND loop to this file, in main():
// the directional-light accumulation. It is not a march and has nothing to do
// with this guard's subject, so the search is now scoped to
// raymarch_breach_cavity's own BODY rather than to the whole file -- the
// function's text from its signature to the first line-initial `}`, which is
// its closing brace (every brace inside it is indented). The light loop is
// covered by its own assertion below instead: it must be bounded by the named
// array-size constant, never by the raw uniform, for the same reason this
// function's own bound must be a compile-time constant.
//
// Matches EXACTLY ONE for-loop within that body (asserted below) and
// additionally requires it to appear textually after
// `bool raymarch_breach_cavity(` -- the anchor is a second, independent
// reason the SAME match couldn't silently be validating the wrong loop.
TEST(BreachRaymarchStaticGuard, LoopBoundIsANamedCompileTimeConstant) {
    const std::string src = read_file(shader_path("breach.frag"));

    const std::size_t fn_pos = src.find("bool raymarch_breach_cavity(");
    ASSERT_NE(fn_pos, std::string::npos) << "breach.frag: raymarch_breach_cavity not found";

    // raymarch_breach_cavity's body: signature to its own closing brace, which
    // is the first `}` at the start of a line after fn_pos (inner braces are
    // all indented).
    const std::size_t body_end = src.find("\n}", fn_pos);
    ASSERT_NE(body_end, std::string::npos)
        << "breach.frag: raymarch_breach_cavity's closing brace not found";
    const std::string body = src.substr(fn_pos, body_end - fn_pos);

    static const std::regex loop_re(R"(for\s*\(\s*int\s+\w+\s*=\s*0\s*;\s*\w+\s*<\s*(\w+)\s*;)");
    const auto matches_begin = std::sregex_iterator(body.begin(), body.end(), loop_re);
    const auto matches_end   = std::sregex_iterator();
    const std::vector<std::smatch> matches(matches_begin, matches_end);
    ASSERT_EQ(matches.size(), 1u)
        << "breach.frag: expected exactly one bounded for-loop inside "
           "raymarch_breach_cavity's body, found " << matches.size()
        << " -- this guard validates THAT loop's bound and must be updated (not "
           "silently pass) if the march gains or loses a loop";

    // The other loop in this file (main()'s directional-light accumulation)
    // must be bounded by the named array-size constant, never by the raw
    // uniform: the uniform is set by the CPU and an over-long value is both a
    // hang and an out-of-bounds read of u_dir_light_dir_ws.
    EXPECT_NE(src.find("int dir_count = min(u_dir_light_count, MAX_DIR_LIGHTS);"),
              std::string::npos)
        << "breach.frag: the directional-light loop must clamp its bound to "
           "MAX_DIR_LIGHTS rather than trusting u_dir_light_count directly";
    const std::smatch& m = matches.front();
    ASSERT_GT(static_cast<std::size_t>(m.position(0)) + fn_pos, fn_pos)
        << "breach.frag: the matched for-loop appears before raymarch_breach_cavity's own "
           "signature -- this guard is meant to validate THAT function's loop bound";
    const std::string bound_name = m[1].str();

    const std::regex const_re("const\\s+int\\s+" + bound_name + "\\s*=\\s*(\\d+)\\s*;");
    std::smatch cm;
    ASSERT_TRUE(std::regex_search(src, cm, const_re))
        << bound_name << " must be declared 'const int " << bound_name
        << " = <literal>;' -- a uniform bound could be set to something huge/degenerate at "
           "runtime, and a variable computed inside the loop is not a fixed bound at all";
    const int bound_value = std::stoi(cm[1].str());
    EXPECT_GT(bound_value, 0);
    EXPECT_LE(bound_value, 256)
        << bound_name << " = " << bound_value
        << " -- suspiciously large for a per-fragment loop; confirm this is intentional";
}

// Global Constraint / brief instruction: "kHullFieldIsoMargin is the
// threshold the hull clip uses. Reuse it; do not invent a second one." A
// GLSL `const` has no linkage across two separately compiled programs, so
// breach.frag necessarily carries its OWN copy of the declaration -- this
// guard is what stops that copy's VALUE drifting from opaque.frag's over
// time (the same risk Task 1's byte-identical block guard exists for,
// applied to a single constant instead of a whole shared block).
TEST(BreachRaymarchStaticGuard, IsoMarginMatchesOpaqueFragsValue) {
    const std::string opaque_src = read_file(shader_path("opaque.frag"));
    const std::string breach_src = read_file(shader_path("breach.frag"));

    static const std::regex margin_re(R"(const\s+float\s+kHullFieldIsoMargin\s*=\s*([^;]+);)");
    std::smatch om, bm;
    ASSERT_TRUE(std::regex_search(opaque_src, om, margin_re))
        << "opaque.frag: kHullFieldIsoMargin not found -- did its declaration move or get renamed?";
    ASSERT_TRUE(std::regex_search(breach_src, bm, margin_re))
        << "breach.frag: kHullFieldIsoMargin not found -- Task 2 must define its own copy of "
           "this constant (with the SAME value) alongside the raymarch";

    auto trim = [](std::string s) {
        const std::size_t a = s.find_first_not_of(" \t");
        const std::size_t b = s.find_last_not_of(" \t");
        return (a == std::string::npos) ? std::string() : s.substr(a, b - a + 1);
    };
    EXPECT_EQ(trim(om[1].str()), trim(bm[1].str()))
        << "opaque.frag's kHullFieldIsoMargin = " << om[1].str()
        << " but breach.frag's = " << bm[1].str()
        << " -- these must be the SAME margin, never a second, independently chosen one";
}

}  // namespace
