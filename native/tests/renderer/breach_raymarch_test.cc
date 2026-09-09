// native/tests/renderer/breach_raymarch_test.cc
//
// Tests for the breach cavity-wall raymarch (raymarched-breach-interior
// Task 2): given a body-frame ray origin/direction, `raymarch_breach_cavity`
// (breach.frag) steps into the damage field until it drops back below
// kHullFieldIsoMargin -- the far wall of the carved cavity -- and reports
// that crossing's position and outward (into-the-cavity) normal, or a MISS
// when no such crossing exists within a bounded step/distance budget.
//
// Nothing calls this function from breach.frag's own main() yet (Task 3
// wires it in once the per-instance box proxy replaces the per-carve sphere
// draw), so it is tested here in isolation, DIRECTLY against the shipped
// shader text: every test below reads breach.frag off disk, splices its own
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
    vec3 hit_point  = vec3(0.0);
    vec3 hit_normal = vec3(0.0);
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
// analytic crossing is at z = 2.5 + 0.497500 = 2.9975.
TEST_F(BreachRaymarchTest, FindsWallOfKnownCavityWithinOneCell) {
    const std::vector<std::int8_t> z_values = {100, 100, 100, -100, -100, -100, -100, -100};
    const voxel::DistanceField field =
        make_slab_field(glm::ivec3(2, 2, 8), glm::vec3(0.0f), glm::vec3(1.0f), z_values);

    auto prog = compile_probe();
    ASSERT_NE(prog, nullptr);
    set_common_uniforms(*prog);
    bind_field(*prog, field);

    const glm::vec3 ro(0.5f, 0.5f, 0.5f);   // deep in slice 0: already inside carved material
    const glm::vec3 rd(0.0f, 0.0f, 1.0f);   // marching straight into the hull
    const glm::vec4 out = draw_and_read(*prog, ro, rd, /*mode=*/0);

    ASSERT_GT(out.w, 0.5f) << "expected a hit: ro is inside carved material (+100) and the "
                              "field genuinely returns to intact material (-100) past z=2.5";
    EXPECT_NEAR(out.z, 2.9975f, 1.0f)
        << "hit_point.z=" << out.z << " -- more than one cell from the analytic crossing "
           "2.9975 (the brief's own stated acceptance bound)";
    // Tighter check: the march refines within its bracketing step by linear
    // interpolation rather than snapping to the coarse step grid, so a
    // correct implementation should land far closer than the 1-cell bound
    // above -- this is what actually distinguishes "found roughly the right
    // wall" from "found the analytically exact one".
    EXPECT_NEAR(out.z, 2.9975f, 0.05f)
        << "hit_point.z=" << out.z << " -- expected the refined crossing near 2.9975, not "
           "merely somewhere within the generous one-cell bound";
    EXPECT_NEAR(out.x, 0.5f, 1e-3f) << "X must not move: rd has no X component";
    EXPECT_NEAR(out.y, 0.5f, 1e-3f) << "Y must not move: rd has no Y component";
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
}

// ── Clean-through carve: a miss, not a wall on the ship's far side ─────────
//
// Every cell +100 (solidly carved) across the whole field, AND -- because
// sample_hull_field clamps its Z index into [0, dims.z-1] with no border
// fallback beyond that -- the sampled value stays +100 forever past the
// field's own box too. There is no far wall anywhere along this ray; the
// march must run out its bounded budget and report a miss.
//
// Discrimination: if step-budget exhaustion were (wrongly) treated as a hit
// at the last sampled point -- a plausible "ran out of steps, but I found
// SOMETHING" bug -- out.w would read 1.0 here instead of the expected miss,
// and the "wall" would be painted at the far edge of the march (a hole cut
// clean through would show a wall on the ship's far side/the background
// instead of empty space).
TEST_F(BreachRaymarchTest, CleanThroughCarveMissesRatherThanPaintingFarWall) {
    const std::vector<std::int8_t> z_values = {100, 100, 100, 100};
    const voxel::DistanceField field =
        make_slab_field(glm::ivec3(2, 2, 4), glm::vec3(0.0f), glm::vec3(1.0f), z_values);

    auto prog = compile_probe();
    ASSERT_NE(prog, nullptr);
    set_common_uniforms(*prog);
    bind_field(*prog, field);

    const glm::vec4 out = draw_and_read(*prog, glm::vec3(0.5f, 0.5f, 0.5f), glm::vec3(0.0f, 0.0f, 1.0f), 0);
    EXPECT_LT(out.w, 0.5f)
        << "field reads carved everywhere the march can reach -- there is no far wall, so a "
           "hit here (got hit_point=(" << out.x << "," << out.y << "," << out.z
        << ")) would paint a wall where the correct result is to draw nothing";
}

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

// ── Static guards (no GL context needed) ────────────────────────────────────

namespace {

// Regex-based text checks over the actual shipped shader source, not a
// reimplementation -- these two are what let BoundedStepsTerminateOnAPathologicalRay's
// completion (rather than its absence) count as evidence: a bound that is a
// named, small, compile-time constant cannot become an unbounded loop
// without also failing this test.
TEST(BreachRaymarchStaticGuard, LoopBoundIsANamedCompileTimeConstant) {
    const std::string src = read_file(shader_path("breach.frag"));

    static const std::regex loop_re(R"(for\s*\(\s*int\s+\w+\s*=\s*0\s*;\s*\w+\s*<\s*(\w+)\s*;)");
    std::smatch m;
    ASSERT_TRUE(std::regex_search(src, m, loop_re))
        << "breach.frag: no bounded for-loop matching 'for (int i = 0; i < N; ...)' found -- "
           "the raymarch must use a compile-time-bounded loop, never e.g. a while(true)";
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
