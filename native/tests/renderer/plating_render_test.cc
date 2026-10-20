// native/tests/renderer/plating_render_test.cc
//
// SPIKE (damage redesign), plan 2026-10-20 step 2a, Task 4: the opaque pass
// chooses the program PER DRAW. A hull whose plating damage list is empty
// draws through the stock program; a hull with listed damage draws through
// Pipeline::plating_shader(), and only that draw goes double-sided. Rendered
// through the real FrameSubmitter::submit_opaque_in_pass on the real
// Ambassador, because shader errors only surface at runtime.
#include <gtest/gtest.h>

#include <renderer/aabb.h>
#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/plating_damage.h>
#include <renderer/ray_trace.h>
#include <renderer/scuff_texture.h>
#include <renderer/window.h>

#include <scenegraph/camera.h>
#include <scenegraph/damage_decals.h>
#include <scenegraph/world.h>

#include <assets/cache.h>
#include <assets/mesh.h>
#include <assets/model.h>

#include <glm/glm.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <memory>
#include <optional>
#include <vector>

#include "plating_gl_fixture.h"
#include "support/content_root.h"

namespace fs = std::filesystem;
using namespace plating_gl;

namespace {

fs::path ambassador_dir() {
    return test_support::game_root() / "data/Models/Ships/Ambassador";
}
fs::path ambassador_nif() { return ambassador_dir() / "Ambassador.nif"; }
std::vector<fs::path> ambassador_search() {
    return {ambassador_dir() / "High",
            test_support::game_root() / "data/Models/SharedTextures/FedShips/High"};
}

class PlatingRenderTest : public PlatingGLFixture {
protected:
    std::unique_ptr<assets::AssetCache> cache;

    void SetUp() override {
        PlatingGLFixture::SetUp();
        if (!w) return;
        assets::AssetCache::Config cfg;
        cfg.keep_cpu_data = true;  // compute_model_aabb + ray_trace read CPU data
        cfg.mesh_fix_dir = [] {
            return fs::path(OPEN_STBC_PROJECT_ROOT) / "native/assets/mesh_fixes";
        };
        cache = std::make_unique<assets::AssetCache>(cfg);
    }

    void TearDown() override {
        cache.reset();
        PlatingGLFixture::TearDown();
    }

    assets::ModelHandle ambassador() {
        if (!fs::is_regular_file(ambassador_nif())) return nullptr;
        return cache->load(ambassador_nif(), ambassador_search());
    }

    // Straight down -z onto `box` (screen right = +x, screen up = +y).
    scenegraph::Camera top_down(const renderer::Aabb& box) const {
        scenegraph::Camera cam;
        const float half = std::max(box.half_extents.x, box.half_extents.y);
        const float dist = box.half_extents.z + 1.2f * half / std::tan(cam.fov_y_rad * 0.5f);
        cam.target = glm::vec3(box.center.x, box.center.y, 0.0f);
        cam.eye = glm::vec3(box.center.x, box.center.y, box.center.z + dist);
        cam.up = glm::vec3(0.0f, 1.0f, 0.0f);
        cam.aspect = 1.0f;
        return cam;
    }

    // One instance of `model` at identity, its ring = `ring`, drawn through
    // submit_opaque_in_pass (the per-draw program choice under test), or
    // through submit_opaque (always the stock program) when `stock_submit`.
    std::vector<std::uint8_t> render(const assets::Model& model,
                                     const scenegraph::DamageDecalRing& ring,
                                     const scenegraph::Camera& cam,
                                     bool stock_submit = false) {
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(&model));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.get(iid)->decals = ring;
        // far_fade 0: no u_dither_fade use() after draw_model, so the program
        // bound after a render is the one the draw chose (program-choice test).
        EXPECT_EQ(world.get(iid)->far_fade, 0.0f);

        glViewport(0, 0, kSize, kSize);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        renderer::reset_model_radius_cache();

        renderer::FrameSubmitter submitter;
        const auto lookup = [](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        };
        if (stock_submit) {
            submitter.submit_opaque(world, cam, *p, lookup, test_lighting(), kDecalTime);
        } else {
            submitter.submit_opaque_in_pass(world, cam, *p, lookup, test_lighting(),
                                            scenegraph::Pass::Space, kDecalTime);
        }
        std::vector<std::uint8_t> px(static_cast<std::size_t>(kSize) * kSize * 4);
        glReadPixels(0, 0, kSize, kSize, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        return px;
    }

    // The first surface the pixel centre's view ray meets, or nullopt.
    static std::optional<renderer::RayHit> trace_pixel(const assets::Model& m,
                                                       const scenegraph::Camera& cam,
                                                       int x, int y) {
        const glm::mat4 inv = glm::inverse(cam.proj_matrix() * cam.view_matrix());
        const glm::vec2 ndc((x + 0.5f) / kSize * 2.0f - 1.0f,
                            (y + 0.5f) / kSize * 2.0f - 1.0f);
        glm::vec4 a = inv * glm::vec4(ndc, -1.0f, 1.0f);
        glm::vec4 b = inv * glm::vec4(ndc, 1.0f, 1.0f);
        const glm::vec3 o = glm::vec3(a) / a.w;
        const glm::vec3 d = glm::normalize(glm::vec3(b) / b.w - o);
        return renderer::ray_trace_instance(m, glm::mat4(1.0f), o, d, 1.0e6f);
    }

    // A point on the saucer's top skin, straight below (0, 170).
    static std::optional<renderer::RayHit> saucer_top_point(const assets::Model& m,
                                                            const renderer::Aabb& box) {
        const glm::vec3 o(0.0f, 170.0f, box.center.z + box.half_extents.z + 10.0f);
        return renderer::ray_trace_instance(m, glm::mat4(1.0f), o,
                                            glm::vec3(0.0f, 0.0f, -1.0f), 1.0e5f);
    }

    // submit_opaque_in_pass then submit_plating_interior over one instance;
    // returns the stencil plane (row 0 = bottom) and the mark count.
    struct Marked { std::vector<std::uint8_t> stencil; int marks = -1; int cull = 0; };
    Marked render_marked(const assets::Model& model, const scenegraph::DamageDecalRing& ring,
                         const scenegraph::Camera& cam) {
        scenegraph::World world;
        auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(&model));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.get(iid)->decals = ring;
        glViewport(0, 0, kSize, kSize);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glStencilMask(0xFF);
        glClearStencil(0);
        glEnable(GL_CULL_FACE);
        glCullFace(GL_BACK);
        glDepthFunc(GL_LESS);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        renderer::reset_model_radius_cache();
        renderer::FrameSubmitter submitter;
        const auto lookup = [](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        };
        submitter.submit_opaque_in_pass(world, cam, *p, lookup, test_lighting(),
                                        scenegraph::Pass::Space, kDecalTime);
        submitter.submit_plating_interior(world, cam, *p, lookup, nullptr, test_lighting(),
                                          1.0f, kDecalTime);
        Marked out;
        out.marks = submitter.plating_marks_last_frame();
        out.stencil.assign(static_cast<std::size_t>(kSize) * kSize, 0);
        glReadPixels(0, 0, kSize, kSize, GL_STENCIL_INDEX, GL_UNSIGNED_BYTE, out.stencil.data());
        return out;
    }
};

}  // namespace

// The selection rule itself: plating enabled AND at least one listed record.
TEST_F(PlatingRenderTest, WantsPlatingNeedsEnabledAndAListedRecord) {
    std::array<float, renderer::plating::kParamCount> params{};
    params[0] = 1.0f;
    params[7] = 0.4f;
    params[16] = 4.5f;
    params[19] = 0.9f;
    scenegraph::DamageDecalRing glow;
    glow.add({0, 0, 0}, {0, 0, 1}, 10.0f, 1.0f, scenegraph::WeaponClass::HeatGlow, 0.0f);
    EXPECT_FALSE(renderer::plating::wants_plating(
        renderer::plating::build_damage_list(glow, params.data()), params.data()));
    const auto ring = internal_ring({0, 0, 0}, 30.0f, 10.0f);
    const auto list = renderer::plating::build_damage_list(ring, params.data());
    EXPECT_TRUE(renderer::plating::wants_plating(list, params.data()));
    params[0] = 0.0f;
    EXPECT_FALSE(renderer::plating::wants_plating(list, params.data()));
}

// An undamaged hull, and a hull whose only record is a HeatGlow (never
// listed), draw exactly the stock program's pixels with plating enabled.
TEST_F(PlatingRenderTest, UndamagedHullUsesTheStockProgramPixels) {
    auto m = ambassador();
    ASSERT_TRUE(m) << "BC asset not available at " << ambassador_nif()
                   << " -- set DAUNTLESS_GAME_DIR";
    const renderer::Aabb box = renderer::compute_model_aabb(*m);
    const auto cam = top_down(box);
    dauntless_plating::g_params[0] = 1.0f;

    const scenegraph::DamageDecalRing empty;
    const auto stock_empty = render(*m, empty, cam, /*stock_submit=*/true);
    const auto in_pass_empty = render(*m, empty, cam);
    ASSERT_GT(count_non_black(stock_empty), 2000) << "hull not in view";
    EXPECT_EQ(in_pass_empty, stock_empty);

    const auto hit = saucer_top_point(*m, box);
    ASSERT_TRUE(hit);
    scenegraph::DamageDecalRing glow;
    glow.add(hit->point, hit->normal, 30.0f, 1.0f,
             scenegraph::WeaponClass::HeatGlow, 0.0f);
    const auto stock_glow = render(*m, glow, cam, /*stock_submit=*/true);
    const auto in_pass_glow = render(*m, glow, cam);
    EXPECT_EQ(in_pass_glow, stock_glow);
}

// A strong Internal blast at the saucer skin tears the hull through: the
// centre pixel no longer shows the hull there.
TEST_F(PlatingRenderTest, TornCentreIsDiscarded) {
    auto m = ambassador();
    ASSERT_TRUE(m) << "BC asset not available at " << ambassador_nif()
                   << " -- set DAUNTLESS_GAME_DIR";
    const renderer::Aabb box = renderer::compute_model_aabb(*m);
    const auto cam = top_down(box);
    dauntless_plating::g_params[0] = 1.0f;
    const auto hit = saucer_top_point(*m, box);
    ASSERT_TRUE(hit);
    ASSERT_GT(hit->normal.z, 0.8f) << "not the saucer's top skin";

    const auto undamaged = render(*m, scenegraph::DamageDecalRing{}, cam);
    const auto torn = render(*m, internal_ring(hit->point, 30.0f, 10.0f), cam);
    const glm::ivec2 c = to_pixel(cam, hit->point);
    ASSERT_TRUE(c.x >= 1 && c.y >= 1 && c.x < kSize - 1 && c.y < kSize - 1);
    const std::uint8_t* before = pixel(undamaged, c.x, c.y);
    const std::uint8_t* after = pixel(torn, c.x, c.y);
    std::fprintf(stderr, "[PlatingRender] centre (%d,%d) hull=(%d,%d,%d) torn=(%d,%d,%d)\n",
                 c.x, c.y, before[0], before[1], before[2], after[0], after[1], after[2]);
    ASSERT_GT(before[0] + before[1] + before[2], 30) << "hull not lit at the centre";
    EXPECT_GT(rgb_diff(before, after), 30) << "the hull still shows at the torn centre";
}

// Far from the record (beyond reach + the early-out margin) the plating
// program draws the undamaged hull's exact pixels.
TEST_F(PlatingRenderTest, FarFromDamagePixelMatchesStock) {
    auto m = ambassador();
    ASSERT_TRUE(m) << "BC asset not available at " << ambassador_nif()
                   << " -- set DAUNTLESS_GAME_DIR";
    const renderer::Aabb box = renderer::compute_model_aabb(*m);
    const auto cam = top_down(box);
    dauntless_plating::g_params[0] = 1.0f;
    const float* g = dauntless_plating::g_params;
    const auto hit = saucer_top_point(*m, box);
    ASSERT_TRUE(hit);

    const float reach = 30.0f;
    const float margin = g[5] + g[6] + g[15] + g[2];
    const auto undamaged = render(*m, scenegraph::DamageDecalRing{}, cam);
    const auto torn = render(*m, internal_ring(hit->point, reach, 10.0f), cam);

    int compared = 0, mismatched = 0, near_changed = 0;
    for (int y = 0; y < kSize; y += 3) {
        for (int x = 0; x < kSize; x += 3) {
            const auto h = trace_pixel(*m, cam, x, y);
            if (!h) continue;
            const float d = glm::length(h->point - hit->point);
            const int diff = rgb_diff(pixel(undamaged, x, y), pixel(torn, x, y));
            if (d > reach + margin + 1.0f) {
                ++compared;
                if (diff != 0) ++mismatched;
            } else if (d < reach * 0.5f && diff > 30) {
                ++near_changed;
            }
        }
    }
    std::fprintf(stderr, "[PlatingRender] far compared=%d mismatched=%d near_changed=%d\n",
                 compared, mismatched, near_changed);
    ASSERT_GT(compared, 500);
    EXPECT_GT(near_changed, 0) << "the damage drew nothing near the record";
    EXPECT_EQ(mismatched, 0);
}

// The program choice itself, read back from GL: an undamaged hull and a
// HeatGlow-only hull draw through the stock program, a torn hull through
// plating_shader(). draw_model's use() is the last program bind in the pass
// for a far_fade-0 instance, so GL_CURRENT_PROGRAM after the render is the
// program the draw took.
TEST_F(PlatingRenderTest, ProgramChoiceIsReadBackFromGL) {
    auto m = ambassador();
    ASSERT_TRUE(m) << "BC asset not available at " << ambassador_nif()
                   << " -- set DAUNTLESS_GAME_DIR";
    const renderer::Aabb box = renderer::compute_model_aabb(*m);
    const auto cam = top_down(box);
    dauntless_plating::g_params[0] = 1.0f;
    const auto hit = saucer_top_point(*m, box);
    ASSERT_TRUE(hit);
    const GLint stock = static_cast<GLint>(p->opaque_shader().program());
    const GLint plating = static_cast<GLint>(p->plating_shader().program());
    ASSERT_NE(stock, plating);
    auto current = [] { GLint prog = 0; glGetIntegerv(GL_CURRENT_PROGRAM, &prog); return prog; };

    render(*m, scenegraph::DamageDecalRing{}, cam);
    EXPECT_EQ(current(), stock) << "undamaged hull";

    scenegraph::DamageDecalRing glow;
    glow.add(hit->point, hit->normal, 30.0f, 1.0f,
             scenegraph::WeaponClass::HeatGlow, 0.0f);
    render(*m, glow, cam);
    EXPECT_EQ(current(), stock) << "HeatGlow-only hull";

    render(*m, internal_ring(hit->point, 30.0f, 10.0f), cam);
    EXPECT_EQ(current(), plating) << "torn hull";
}

// The plating draw is front faces only: a back-facing far skin is culled, so
// the torn centre shows the clear colour, not an inside wall.
TEST_F(PlatingRenderTest, PlatingDrawCullsBackFaces) {
    dauntless_plating::g_params[0] = 1.0f;
    const auto cam = quad_cam();
    const auto ring = internal_ring({0.0f, 0.0f, 0.0f}, 30.0f, 10.0f);
    ASSERT_TRUE(renderer::plating::build_damage_list(
                    ring, dauntless_plating::g_params).torn_possible);
    const glm::ivec2 c = to_pixel(cam, glm::vec3(0.0f));
    auto two = build_quad(20.0f, /*facing_camera=*/true);
    add_quad(*two, 20.0f, -35.0f, /*facing_camera=*/false);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    const auto px = render(*two, ring, cam);
    ASSERT_GT(count_non_black(px), 1000) << "the near skin does not render";
    const std::uint8_t* q = pixel(px, c.x, c.y);
    EXPECT_LE(q[0] + q[1] + q[2], 6) << "a back face showed through the tear";
}

TEST_F(PlatingRenderTest, MarkingStampsOnlyTornPixels) {
    dauntless_plating::g_params[0] = 1.0f;
    GLint sbits = 0;
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glGetFramebufferAttachmentParameteriv(GL_FRAMEBUFFER, GL_STENCIL,
                                          GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE, &sbits);
    ASSERT_GE(sbits, 8) << "test window has no stencil buffer";
    const float* g = dauntless_plating::g_params;
    const float reach = 30.0f;
    const float margin = g[5] + g[6] + g[15] + g[2];
    const auto cam = quad_cam();
    auto quad = build_quad(150.0f, true);
    const auto r = render_marked(*quad, internal_ring({0, 0, 0}, reach, 10.0f), cam);
    EXPECT_EQ(r.marks, 1);
    auto st = [&](glm::ivec2 c) { return r.stencil[static_cast<std::size_t>(c.y) * kSize + c.x]; };
    EXPECT_EQ(st(to_pixel(cam, glm::vec3(0.0f))), 2);
    EXPECT_EQ(st(to_pixel(cam, glm::vec3(reach + margin + 5.0f, 0.0f, 0.0f))), 0);
    EXPECT_EQ(st(glm::ivec2(1, 1)), 0) << "a pixel off the quad";
}

TEST_F(PlatingRenderTest, NoMarkWithoutPossibleTear) {
    dauntless_plating::g_params[0] = 1.0f;
    GLint sbits = 0;
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glGetFramebufferAttachmentParameteriv(GL_FRAMEBUFFER, GL_STENCIL,
                                          GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE, &sbits);
    ASSERT_GE(sbits, 8) << "test window has no stencil buffer";
    const auto cam = quad_cam();
    auto quad = build_quad(150.0f, true);
    const auto r = render_marked(*quad, internal_ring({0, 0, 0}, 30.0f, 0.3f), cam);
    EXPECT_EQ(r.marks, 0);
    EXPECT_EQ(*std::max_element(r.stencil.begin(), r.stencil.end()), 0);
}

// A skinned model's program has no plating layer, so a marking draw of it
// would stamp its whole hull. It must be skipped.
TEST_F(PlatingRenderTest, SkinnedModelIsNeverMarked) {
    dauntless_plating::g_params[0] = 1.0f;
    GLint sbits = 0;
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glGetFramebufferAttachmentParameteriv(GL_FRAMEBUFFER, GL_STENCIL,
                                          GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE, &sbits);
    ASSERT_GE(sbits, 8) << "test window has no stencil buffer";
    auto quad = build_quad(150.0f, true);
    quad->skeleton.bones.push_back(assets::Bone{});
    const auto r = render_marked(*quad, internal_ring({0, 0, 0}, 30.0f, 10.0f), quad_cam());
    EXPECT_EQ(r.marks, 0);
    EXPECT_EQ(*std::max_element(r.stencil.begin(), r.stencil.end()), 0);
}

TEST_F(PlatingRenderTest, PlatingDrawsLeaveStockGlState) {
    dauntless_plating::g_params[0] = 1.0f;
    const auto cam = quad_cam();
    auto quad = build_quad(150.0f, true);
    render_marked(*quad, internal_ring({0, 0, 0}, 30.0f, 10.0f), cam);
    GLint v = 0;
    EXPECT_EQ(glIsEnabled(GL_CULL_FACE), GL_TRUE);
    glGetIntegerv(GL_CULL_FACE_MODE, &v);
    EXPECT_EQ(v, GL_BACK);
    EXPECT_EQ(glIsEnabled(GL_STENCIL_TEST), GL_FALSE);
    glGetIntegerv(GL_STENCIL_WRITEMASK, &v);
    EXPECT_EQ(v & 0xFF, 0xFF);
    GLboolean cm[4];
    glGetBooleanv(GL_COLOR_WRITEMASK, cm);
    EXPECT_TRUE(cm[0] && cm[1] && cm[2] && cm[3]);
    GLboolean dm = GL_FALSE;
    glGetBooleanv(GL_DEPTH_WRITEMASK, &dm);
    EXPECT_TRUE(dm);
    glGetIntegerv(GL_DEPTH_FUNC, &v);
    EXPECT_EQ(v, GL_LESS) << "render_marked sets GL_LESS before the calls";
}

// ---- Uneven breach (Task 1): toughness per panel + hole-scale lumps. ------
namespace {

// 32 pixels evenly round a ring of radius 15 mu about the origin, after an
// Internal record (reach 30) whose wear on that ring is breach_wear + delta.
// Returns how many are cut (clear colour).
struct RingCut { int cut = 0; int kept = 0; };

}  // namespace

class UnevenBreach : public PlatingRenderTest {
protected:
    RingCut ring_cut(float delta) {
        dauntless_plating::g_params[0] = 1.0f;
        dauntless_plating::g_params[4] = 0.0f;    // member_width
        dauntless_plating::g_params[19] = 0.0f;   // tear_noise
        const float* g = dauntless_plating::g_params;
        const float R = 30.0f, r = 15.0f;
        const float fall = (1.0f - r * r / (R * R));
        const float W = (g[16] + delta) / (fall * fall);
        scenegraph::Camera cam;
        cam.eye = glm::vec3(0.0f, 0.0f, 120.0f);
        cam.target = glm::vec3(0.0f);
        cam.up = glm::vec3(0.0f, 1.0f, 0.0f);
        cam.aspect = 1.0f;
        auto quad = build_quad(40.0f, /*facing_camera=*/true);
        const auto px = render(*quad, internal_ring({0, 0, 0}, R, W), cam);
        RingCut out;
        for (int i = 0; i < 32; ++i) {
            const float a = 6.2831853f * static_cast<float>(i) / 32.0f;
            const glm::ivec2 c = to_pixel(
                cam, glm::vec3(r * std::cos(a), r * std::sin(a), 0.0f));
            const std::uint8_t* q = pixel(px, c.x, c.y);
            if (q[0] + q[1] + q[2] <= 6) ++out.cut; else ++out.kept;
        }
        std::fprintf(stderr, "[UnevenBreach] delta %+.2f cut %d kept %d\n",
                     delta, out.cut, out.kept);
        return out;
    }
};

TEST_F(UnevenBreach, BreachOutlineIsUnevenAtEqualWear) {
    const RingCut r = ring_cut(+0.2f);
    EXPECT_GE(r.cut, 4);
    EXPECT_GE(r.kept, 4);
}

TEST_F(UnevenBreach, ZeroSpreadAndLumpsKeepTheEvenOutline) {
    dauntless_plating::g_params[22] = 0.0f;
    dauntless_plating::g_params[23] = 0.0f;
    EXPECT_EQ(ring_cut(+0.2f).cut, 32);
    EXPECT_EQ(ring_cut(-0.2f).cut, 0);
}
