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
#include <renderer/cloak_pass.h>
#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/node_anim.h>
#include <renderer/plating_damage.h>
#include <renderer/ray_trace.h>
#include <renderer/scuff_texture.h>
#include <renderer/structure_parts_cache.h>
#include <renderer/window.h>

#include <scenegraph/camera.h>
#include <scenegraph/damage_decals.h>
#include <scenegraph/hull_damage.h>
#include <scenegraph/world.h>

#include <assets/cache.h>
#include <assets/mesh.h>
#include <assets/model.h>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "embedded_opaque_fs.h"
#include "embedded_shadow_parts_fs.h"
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
    // FrameSubmitter::set_plating_record_culling for every render: off = the
    // whole list on every mesh and the whole list as the deck-break set.
    bool record_culling = true;
    // FrameSubmitter::set_plating_skip_record_free_meshes for every render.
    bool skip_record_free = true;

    // Every uniform the lean mark must set or neutralise, set to a value that
    // changes which fragments survive (or what p_body is).
    void poison_plating_program() {
        renderer::Shader& s = p->plating_shader();
        s.use();
        s.set_int("u_coverage_cutout", 1);
        s.set_int("u_impostor_blend", 1);
        s.set_int("u_plating_far", 1);
        s.set_mat4("u_ship_world_inv",
                   glm::inverse(glm::translate(glm::mat4(1.0f), glm::vec3(500.0f, 0.0f, 0.0f))));
    }

    // u_dmg_count as the last draw through the plating program left it.
    int plating_dmg_count() const {
        const GLuint prog = p->plating_shader().program();
        const GLint loc = glGetUniformLocation(prog, "u_dmg_count");
        GLint v = -1;
        if (loc >= 0) glGetUniformiv(prog, loc, &v);
        return v;
    }

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
                                     const scenegraph::HullDamageStore& ring,
                                     const scenegraph::Camera& cam,
                                     bool stock_submit = false,
                                     const scenegraph::DamageDecalRing* decals = nullptr,
                                     const std::unordered_map<int, glm::mat4>* overrides =
                                         nullptr,
                                     const std::function<void(scenegraph::Instance&)>&
                                         configure = {}) {
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(&model));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.get(iid)->hull_damage = ring;
        if (decals != nullptr) world.get(iid)->decals = *decals;
        if (overrides != nullptr) world.get(iid)->node_overrides = *overrides;
        if (configure) configure(*world.get(iid));
        // far_fade 0: no u_dither_fade use() after draw_model, so the program
        // bound after a render is the one the draw chose (program-choice test).
        EXPECT_EQ(world.get(iid)->far_fade, 0.0f);

        glViewport(0, 0, kSize, kSize);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        renderer::reset_model_radius_cache();

        renderer::FrameSubmitter submitter;
        // These tests pin the near (cut) look; their cameras are past 20 GU.
        submitter.set_interior_policy(all_near_policy());
        submitter.set_plating_record_culling(record_culling);
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
    // returns the stencil plane (row 0 = bottom), the colour buffer read after
    // both (RGBA, row 0 = bottom) and the mark count.
    struct Marked {
        std::vector<std::uint8_t> stencil;
        std::vector<std::uint8_t> color;
        int marks = -1;
        int cull = 0;
        int mark_mesh_draws = -1;
        int interior_mesh_draws = -1;
    };
    struct Placed {
        glm::mat4 world;
        scenegraph::HullDamageStore ring;
        std::uint32_t severed_parts = 0;   // Instance::severed_parts
        std::uint32_t shown_parts = 0;     // Instance::shown_parts
        std::unordered_map<int, glm::mat4> overrides{};   // Instance::node_overrides
        scenegraph::BreachEventRing breach{};             // Instance::breach_events
    };
    Marked render_marked(const assets::Model& model, const scenegraph::HullDamageStore& ring,
                         const scenegraph::Camera& cam,
                         const glm::vec3& clear = glm::vec3(0.0f),
                         const std::function<void()>& before_mark = {}) {
        return render_marked_many(model, {Placed{glm::mat4(1.0f), ring}}, cam, clear,
                                  before_mark);
    }
    // Every `placed` instance of `model`; `before_mark` runs between the
    // opaque pass and submit_plating_interior.
    Marked render_marked_many(const assets::Model& model, const std::vector<Placed>& placed,
                              const scenegraph::Camera& cam,
                              const glm::vec3& clear = glm::vec3(0.0f),
                              const std::function<void()>& before_mark = {}) {
        scenegraph::World world;
        for (const Placed& pl : placed) {
            auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(&model));
            world.set_world_transform(iid, pl.world);
            world.get(iid)->hull_damage = pl.ring;
            world.get(iid)->severed_parts = pl.severed_parts;
            world.get(iid)->shown_parts = pl.shown_parts;
            world.get(iid)->node_overrides = pl.overrides;
            world.get(iid)->breach_events = pl.breach;
        }
        glViewport(0, 0, kSize, kSize);
        glClearColor(clear.r, clear.g, clear.b, 1.0f);
        glStencilMask(0xFF);
        glClearStencil(0);
        glEnable(GL_CULL_FACE);
        glCullFace(GL_BACK);
        glDepthFunc(GL_LESS);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        renderer::reset_model_radius_cache();
        renderer::FrameSubmitter submitter;
        submitter.set_interior_policy(all_near_policy());
        submitter.set_plating_record_culling(record_culling);
        submitter.set_plating_skip_record_free_meshes(skip_record_free);
        const auto lookup = [](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        };
        submitter.submit_opaque_in_pass(world, cam, *p, lookup, test_lighting(),
                                        scenegraph::Pass::Space, kDecalTime);
        if (before_mark) before_mark();
        submitter.submit_plating_interior(world, cam, *p, lookup, nullptr, test_lighting(),
                                          1.0f, kDecalTime);
        Marked out;
        out.marks = submitter.plating_marks_last_frame();
        out.mark_mesh_draws = submitter.plating_mark_mesh_draws_last_frame();
        out.interior_mesh_draws = submitter.plating_interior_mesh_draws_last_frame();
        out.stencil.assign(static_cast<std::size_t>(kSize) * kSize, 0);
        glReadPixels(0, 0, kSize, kSize, GL_STENCIL_INDEX, GL_UNSIGNED_BYTE, out.stencil.data());
        out.color.assign(static_cast<std::size_t>(kSize) * kSize * 4, 0);
        glReadPixels(0, 0, kSize, kSize, GL_RGBA, GL_UNSIGNED_BYTE, out.color.data());
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
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
    const scenegraph::HullDamageStore none;
    EXPECT_FALSE(renderer::plating::wants_plating(
        renderer::plating::build_damage_list(none, params.data()), params.data()));
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

    const scenegraph::HullDamageStore empty;
    const auto stock_empty = render(*m, empty, cam, /*stock_submit=*/true);
    const auto in_pass_empty = render(*m, empty, cam);
    ASSERT_GT(count_non_black(stock_empty), 2000) << "hull not in view";
    EXPECT_EQ(in_pass_empty, stock_empty);

    const auto hit = saucer_top_point(*m, box);
    ASSERT_TRUE(hit);
    scenegraph::DamageDecalRing glow;
    glow.add(hit->point, hit->normal, 30.0f, 1.0f,
             scenegraph::WeaponClass::HeatGlow, 0.0f);
    const auto stock_glow = render(*m, empty, cam, /*stock_submit=*/true, &glow);
    const auto in_pass_glow = render(*m, empty, cam, false, &glow);
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

    const auto undamaged = render(*m, scenegraph::HullDamageStore{}, cam);
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
    const auto undamaged = render(*m, scenegraph::HullDamageStore{}, cam);
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

    render(*m, scenegraph::HullDamageStore{}, cam);
    EXPECT_EQ(current(), stock) << "undamaged hull";

    scenegraph::DamageDecalRing glow;
    glow.add(hit->point, hit->normal, 30.0f, 1.0f,
             scenegraph::WeaponClass::HeatGlow, 0.0f);
    render(*m, scenegraph::HullDamageStore{}, cam, false, &glow);
    EXPECT_EQ(current(), stock) << "HeatGlow-only hull";

    render(*m, internal_ring(hit->point, 30.0f, 10.0f), cam);
    EXPECT_EQ(current(), plating) << "torn hull";
}

// Perf probe (params[26]): an undamaged hull is forced through the plating
// program with an empty list; its pixels stay the stock draw's.
TEST_F(PlatingRenderTest, ForceProgramDrawsUndamagedHullWithPlatingProgram) {
    auto m = ambassador();
    ASSERT_TRUE(m) << "BC asset not available at " << ambassador_nif()
                   << " -- set DAUNTLESS_GAME_DIR";
    const renderer::Aabb box = renderer::compute_model_aabb(*m);
    const auto cam = top_down(box);
    dauntless_plating::g_params[0] = 1.0f;
    const GLint stock = static_cast<GLint>(p->opaque_shader().program());
    const GLint plating = static_cast<GLint>(p->plating_shader().program());
    auto current = [] { GLint prog = 0; glGetIntegerv(GL_CURRENT_PROGRAM, &prog); return prog; };
    const scenegraph::HullDamageStore empty;

    const auto stock_px = render(*m, empty, cam, /*stock_submit=*/true);
    ASSERT_GT(count_non_black(stock_px), 2000) << "hull not in view";
    dauntless_plating::g_params[26] = 1.0f;
    const auto forced_px = render(*m, empty, cam);
    const GLint used = current();
    dauntless_plating::g_params[26] = 0.0f;
    EXPECT_EQ(used, plating) << "forced undamaged hull";
    ASSERT_EQ(forced_px.size(), stock_px.size());
    int worst = 0;
    for (std::size_t i = 0; i < stock_px.size(); ++i)
        worst = std::max(worst, std::abs(int(forced_px[i]) - int(stock_px[i])));
    EXPECT_LE(worst, 1);
    render(*m, empty, cam);
    EXPECT_EQ(current(), stock) << "force off restores the stock program";
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

// The lean marking draw (draw_plating_mark) stamps exactly the pixels the
// plating draw cuts, on the real Ambassador: the cut set is every pixel inside
// the undamaged hull's silhouette that shows the background after the plating
// draw, and the stencil equals it pixel for pixel. Interior off (params[25]),
// so the colour read back is the plating draw's alone.
TEST_F(PlatingRenderTest, LeanMarkStampsExactlyTheCutPixels) {
    auto m = ambassador();
    ASSERT_TRUE(m) << "BC asset not available at " << ambassador_nif()
                   << " -- set DAUNTLESS_GAME_DIR";
    GLint sbits = 0;
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glGetFramebufferAttachmentParameteriv(GL_FRAMEBUFFER, GL_STENCIL,
                                          GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE, &sbits);
    ASSERT_GE(sbits, 8) << "test window has no stencil buffer";
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 0.0f;
    const renderer::Aabb box = renderer::compute_model_aabb(*m);
    const auto cam = top_down(box);
    const auto hit = saucer_top_point(*m, box);
    ASSERT_TRUE(hit);
    // Structure parts are detected on a worker; wait for them, so the plating
    // draw and the mark both see them (and the mark's part upload is pinned)
    // instead of one landing between the two draws.
    const auto t0 = std::chrono::steady_clock::now();
    while (renderer::structure_parts_for(m->source) == nullptr &&
           std::chrono::steady_clock::now() - t0 < std::chrono::seconds(20))
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    ASSERT_NE(renderer::structure_parts_for(m->source), nullptr) << "parts never landed";
    ASSERT_FALSE(renderer::structure_parts_for(m->source)->empty());
    // A background no lit hull pixel lands on exactly.
    const std::uint8_t bg[3] = {13, 251, 7};
    const glm::vec3 clear(bg[0] / 255.0f, bg[1] / 255.0f, bg[2] / 255.0f);

    const auto undamaged = render_marked(*m, scenegraph::HullDamageStore{}, cam, clear);
    EXPECT_EQ(undamaged.marks, 0);
    // The plating program is poisoned between the opaque pass and the mark
    // with every switch that would change which fragments survive: the mark
    // must set (or neutralise) each one itself.
    const auto torn = render_marked(*m, internal_ring(hit->point, 30.0f, 10.0f), cam, clear,
                                    [this] { poison_plating_program(); });
    EXPECT_EQ(torn.marks, 1);

    auto is_bg = [&](const std::vector<std::uint8_t>& px, int x, int y) {
        const std::uint8_t* q = pixel(px, x, y);
        return q[0] == bg[0] && q[1] == bg[1] && q[2] == bg[2];
    };
    int silhouette = 0, cut = 0, stamped = 0, missed = 0, extra = 0, wrong_value = 0;
    for (int y = 0; y < kSize; ++y) {
        for (int x = 0; x < kSize; ++x) {
            const bool in_hull = !is_bg(undamaged.color, x, y);
            const bool is_cut = in_hull && is_bg(torn.color, x, y);
            const std::uint8_t s = torn.stencil[static_cast<std::size_t>(y) * kSize + x];
            silhouette += in_hull ? 1 : 0;
            cut += is_cut ? 1 : 0;
            stamped += s != 0 ? 1 : 0;
            if (is_cut && s == 0) ++missed;
            if (!is_cut && s != 0) ++extra;
            if (s != 0 && s != 2) ++wrong_value;
        }
    }
    std::fprintf(stderr,
                 "[PlatingRender] lean mark: silhouette=%d cut=%d stamped=%d missed=%d "
                 "extra=%d\n", silhouette, cut, stamped, missed, extra);
    ASSERT_GT(silhouette, 2000) << "hull not in view";
    ASSERT_GT(cut, 50) << "the record cut too little to compare";
    EXPECT_EQ(missed, 0) << "cut pixels the mark did not stamp";
    EXPECT_EQ(extra, 0) << "stamped pixels the plating draw did not cut";
    EXPECT_EQ(wrong_value, 0) << "the first marked hull stamps 2";
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

// The damage list is built once per change (store revision or plating params),
// not once per draw: two frames of opaque + interior draws share one build.
TEST_F(PlatingRenderTest, PlatingListIsBuiltOncePerChange) {
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 1.0f;
    auto quad = build_quad(150.0f, true);
    ASSERT_TRUE(quad);
    scenegraph::World world;
    auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(quad.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));
    world.get(iid)->hull_damage = internal_ring({0, 0, 0}, 30.0f, 10.0f);
    const auto cam = quad_cam();
    renderer::reset_model_radius_cache();
    renderer::FrameSubmitter submitter;
    const auto lookup = [](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h);
    };
    auto frame = [&] {
        glViewport(0, 0, kSize, kSize);
        glStencilMask(0xFF);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        submitter.submit_opaque_in_pass(world, cam, *p, lookup, test_lighting(),
                                        scenegraph::Pass::Space, kDecalTime);
        submitter.submit_plating_interior(world, cam, *p, lookup, nullptr, test_lighting(),
                                          1.0f, kDecalTime);
    };
    const int b0 = submitter.plating_list_builds();
    frame();
    frame();
    EXPECT_EQ(submitter.plating_list_builds() - b0, 1);
    world.get(iid)->hull_damage.add({5, 0, 0}, glm::vec3(0.0f), 30.0f, 2.0f,
                                    scenegraph::HullDamageKind::Internal);
    frame();
    EXPECT_EQ(submitter.plating_list_builds() - b0, 2);
}

// A plating param change alone (no store change) rebuilds the cached list:
// params[7] scales Surface reach inside build_damage_list, so a stale list
// would draw the old reach.
TEST_F(PlatingRenderTest, PlatingListRebuildsWhenAParamChanges) {
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 1.0f;
    auto quad = build_quad(150.0f, true);
    ASSERT_TRUE(quad);
    scenegraph::World world;
    auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(quad.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));
    world.get(iid)->hull_damage = internal_ring({0, 0, 0}, 30.0f, 10.0f);
    const auto cam = quad_cam();
    renderer::reset_model_radius_cache();
    renderer::FrameSubmitter submitter;
    const auto lookup = [](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h);
    };
    auto frame = [&] {
        glViewport(0, 0, kSize, kSize);
        glStencilMask(0xFF);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        submitter.submit_opaque_in_pass(world, cam, *p, lookup, test_lighting(),
                                        scenegraph::Pass::Space, kDecalTime);
    };
    const int b0 = submitter.plating_list_builds();
    frame();
    EXPECT_EQ(submitter.plating_list_builds() - b0, 1);
    const float saved = dauntless_plating::g_params[7];
    dauntless_plating::g_params[7] = saved + 0.25f;
    frame();
    EXPECT_EQ(submitter.plating_list_builds() - b0, 2) << "a param change must rebuild";
    frame();
    EXPECT_EQ(submitter.plating_list_builds() - b0, 2) << "and only once";
    dauntless_plating::g_params[7] = saved;
}

// The lean mark on two hulls (each damaged at its own centre), the program
// poisoned before the mark: hull 2's mark must use hull 2's world->body, never
// the matrix hull 1's mark (or the poison) left behind. The stencil equals the
// cut set pixel for pixel, each hull under its own value.
TEST_F(PlatingRenderTest, LeanMarkOnTwoHullsStampsEachHullsCut) {
    GLint sbits = 0;
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glGetFramebufferAttachmentParameteriv(GL_FRAMEBUFFER, GL_STENCIL,
                                          GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE, &sbits);
    ASSERT_GE(sbits, 8) << "test window has no stencil buffer";
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 0.0f;
    const auto cam = quad_cam();
    auto quad = build_quad(25.0f, true);
    const glm::mat4 left = glm::translate(glm::mat4(1.0f), glm::vec3(-32.0f, 0.0f, 0.0f));
    const glm::mat4 right = glm::translate(glm::mat4(1.0f), glm::vec3(32.0f, 0.0f, 0.0f));
    const auto ring = internal_ring(glm::vec3(0.0f), 12.0f, 10.0f);
    const std::uint8_t bg[3] = {13, 251, 7};
    const glm::vec3 clear(bg[0] / 255.0f, bg[1] / 255.0f, bg[2] / 255.0f);

    const auto undamaged = render_marked_many(
        *quad, {Placed{left, {}}, Placed{right, {}}}, cam, clear);
    const auto torn = render_marked_many(*quad, {Placed{left, ring}, Placed{right, ring}}, cam,
                                         clear, [this] { poison_plating_program(); });
    EXPECT_EQ(torn.marks, 2);
    auto is_bg = [&](const std::vector<std::uint8_t>& px, int x, int y) {
        const std::uint8_t* q = pixel(px, x, y);
        return q[0] == bg[0] && q[1] == bg[1] && q[2] == bg[2];
    };
    const int mid = to_pixel(cam, glm::vec3(0.0f)).x;
    int cut[2] = {0, 0}, missed = 0, extra = 0, wrong_value = 0;
    for (int y = 0; y < kSize; ++y) {
        for (int x = 0; x < kSize; ++x) {
            const bool is_cut = !is_bg(undamaged.color, x, y) && is_bg(torn.color, x, y);
            const std::uint8_t s = torn.stencil[static_cast<std::size_t>(y) * kSize + x];
            const int side = x < mid ? 0 : 1;
            if (is_cut) ++cut[side];
            if (is_cut && s == 0) ++missed;
            if (!is_cut && s != 0) ++extra;
            if (s != 0 && s != 2 + side) ++wrong_value;
        }
    }
    std::fprintf(stderr, "[PlatingRender] two hulls: cut=%d,%d missed=%d extra=%d wrong=%d\n",
                 cut[0], cut[1], missed, extra, wrong_value);
    ASSERT_GT(cut[0], 50) << "the left hull cut too little to compare";
    ASSERT_GT(cut[1], 50) << "the right hull cut too little to compare";
    EXPECT_EQ(missed, 0);
    EXPECT_EQ(extra, 0);
    EXPECT_EQ(wrong_value, 0) << "the first hull stamps 2, the second 3";
}

// ---- Phase 2 Task 3: records near each mesh. --------------------------------
namespace {

// Two quads of one node: mesh 0 at x = first_x, mesh 1 at x = -first_x.
std::unique_ptr<assets::Model> two_quads(float first_x) {
    auto model = std::make_unique<assets::Model>();
    const glm::vec3 X(1, 0, 0), Y(0, 1, 0);
    add_face(*model, glm::vec3(first_x, 0.0f, 0.0f), X, Y, 15.0f);
    add_face(*model, glm::vec3(-first_x, 0.0f, 0.0f), X, Y, 15.0f);
    return model;
}

// Two records on the quad at x = -40 (reach 10 and 4, 7 mu apart: not merged),
// on `node` (-1 the body).
scenegraph::HullDamageStore left_quad_ring(int node = -1) {
    scenegraph::HullDamageStore s;
    s.add({-40.0f, 0.0f, 0.0f}, glm::vec3(0.0f), 10.0f, 10.0f,
          scenegraph::HullDamageKind::Internal, node);
    s.add({-45.0f, 5.0f, 0.0f}, glm::vec3(0.0f), 4.0f, 2.0f,
          scenegraph::HullDamageKind::Internal, node);
    return s;
}

}  // namespace

// One body-frame box per mesh, at the rest pose (node transforms composed).
TEST_F(PlatingRenderTest, MeshBodyAabbsAreOnePerMeshInTheBodyFrame) {
    auto model = two_quads(-40.0f);
    model->nodes[0].local_transform =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, 5.0f));
    const auto boxes = renderer::mesh_body_aabbs(*model);
    ASSERT_EQ(boxes.size(), 2u);
    EXPECT_FLOAT_EQ(boxes[0].center.x, -40.0f);
    EXPECT_FLOAT_EQ(boxes[0].center.z, 5.0f);
    EXPECT_FLOAT_EQ(boxes[0].half_extents.x, 15.0f);
    EXPECT_FLOAT_EQ(boxes[0].half_extents.z, 0.0f);
    EXPECT_FLOAT_EQ(boxes[1].center.x, 40.0f);
}

// Per mesh, only the records near that mesh are uploaded: the damaged quad
// gets both records. Read back from GL after the draw, so the LAST plating
// mesh drawn is the one observed. The quad far from every record draws
// through the stock program (phase 2b Task 2), so whichever order the quads
// come in, the plating program is left with the damaged quad's 2. The marking
// draw, with record-free meshes drawn, uploads u_dmg_count 0 for the far quad;
// by default it skips the far quad altogether (I2), leaving the damaged
// quad's upload.
TEST_F(PlatingRenderTest, MeshWithoutNearbyDamageUploadsNothing) {
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 0.0f;
    const auto cam = quad_cam();
    const auto ring = left_quad_ring();
    ASSERT_EQ(renderer::plating::build_damage_list(ring, dauntless_plating::g_params).count, 2);

    auto damaged_last = two_quads(40.0f);    // mesh 1 = the damaged quad
    render(*damaged_last, ring, cam);
    EXPECT_EQ(plating_dmg_count(), 2) << "the damaged quad lost a record";

    auto undamaged_last = two_quads(-40.0f); // mesh 1 = the far quad
    const auto px = render(*undamaged_last, ring, cam);
    EXPECT_EQ(plating_dmg_count(), 2) << "the far quad drew through the plating program";
    const auto stock = render(*undamaged_last, scenegraph::HullDamageStore{}, cam, true);
    const glm::ivec2 far_c = to_pixel(cam, glm::vec3(40.0f, 0.0f, 0.0f));
    EXPECT_EQ(rgb_diff(pixel(px, far_c.x, far_c.y), pixel(stock, far_c.x, far_c.y)), 0);

    skip_record_free = false;
    const auto r = render_marked(*undamaged_last, ring, cam);
    skip_record_free = true;
    EXPECT_EQ(r.marks, 1);
    EXPECT_EQ(r.mark_mesh_draws, 2);
    EXPECT_EQ(plating_dmg_count(), 0) << "the mark uploaded records the far quad never reaches";

    const auto skipped = render_marked(*undamaged_last, ring, cam);
    EXPECT_EQ(skipped.marks, 1);
    EXPECT_EQ(skipped.mark_mesh_draws, 1) << "the far quad has no record: no mark draw";
    EXPECT_EQ(plating_dmg_count(), 2) << "the last mark upload is the damaged quad's";
}

// With node overrides (an articulated hull) records and per-mesh boxes are
// both REST-frame data, so the per-mesh subsets still hold: the mark skips the
// quad no record reaches, exactly as for an unposed hull.
TEST_F(PlatingRenderTest, ArticulatedDrawKeepsPerMeshSubsets) {
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 0.0f;
    const auto cam = quad_cam();
    auto model = two_quads(-40.0f);          // mesh 1 = the far quad
    // An override that leaves the node where it was; the records are on that
    // node, so they stay in its frame (ArticulatedRecordsStayInTheirOwnFrame
    // covers a real move and the body's records).
    Placed pl{glm::mat4(1.0f), left_quad_ring(/*node=*/0)};
    pl.overrides[0] = model->nodes[0].local_transform;
    const auto r = render_marked_many(*model, {pl}, cam);
    EXPECT_EQ(r.marks, 1);
    EXPECT_EQ(r.mark_mesh_draws, 1) << "the far quad has no record: no mark draw";
    EXPECT_EQ(plating_dmg_count(), 2) << "the last mark upload is the damaged quad's";
}

// The subsets never change a pixel: the torn Ambassador, damaged all over,
// draws and marks byte-identically with record culling on and off.
TEST_F(PlatingRenderTest, RecordCullingNeverChangesAPixel) {
    auto m = ambassador();
    ASSERT_TRUE(m) << "BC asset not available at " << ambassador_nif()
                   << " -- set DAUNTLESS_GAME_DIR";
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 0.0f;
    const renderer::Aabb box = renderer::compute_model_aabb(*m);
    const auto cam = top_down(box);
    // Wait for the structure parts, so the disc and cylinder charts (the
    // largest panel-centre offsets) are compared, not only the box fallback.
    const auto t0 = std::chrono::steady_clock::now();
    while (renderer::structure_parts_for(m->source) == nullptr &&
           std::chrono::steady_clock::now() - t0 < std::chrono::seconds(20))
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    const auto* parts = renderer::structure_parts_for(m->source);
    ASSERT_NE(parts, nullptr) << "parts never landed";
    int discs = 0, cylinders = 0;
    for (const auto& sp : *parts) {
        discs += sp.kind == voxel::PartKind::Disc ? 1 : 0;
        cylinders += sp.kind == voxel::PartKind::Cylinder ? 1 : 0;
    }
    std::fprintf(stderr, "[PlatingRender] parts %zu (discs %d, cylinders %d)\n", parts->size(),
                 discs, cylinders);
    ASSERT_GT(discs + cylinders, 0) << "only box charts: the A/B misses the large offsets";
    // Records where a 5 x 5 grid of downward rays meets the hull.
    scenegraph::HullDamageStore ring;
    const float top = box.center.z + box.half_extents.z + 10.0f;
    for (int i = 0; i < 5; ++i) {
        for (int j = 0; j < 5; ++j) {
            const glm::vec3 o(box.center.x + box.half_extents.x * (-0.8f + 0.4f * i),
                              box.center.y + box.half_extents.y * (-0.8f + 0.4f * j), top);
            const auto h = renderer::ray_trace_instance(*m, glm::mat4(1.0f), o,
                                                        glm::vec3(0.0f, 0.0f, -1.0f), 1.0e5f);
            if (!h) continue;
            ring.add(h->point, h->normal, 18.0f, ((i + j) % 3 == 0) ? 10.0f : 2.0f,
                     (i + j) % 2 == 0 ? scenegraph::HullDamageKind::Internal
                                      : scenegraph::HullDamageKind::Surface);
        }
    }
    ASSERT_GT(ring.count(), 8u);
    {   // How much the subsets cull on this hull (reported, not asserted).
        const auto list = renderer::plating::build_damage_list(ring, dauntless_plating::g_params);
        const auto boxes = renderer::mesh_body_aabbs(*m);
        std::array<std::uint8_t, renderer::plating::kMaxDamage> idx{};
        for (std::size_t k = 0; k < boxes.size(); ++k) {
            const float cull = renderer::plating::plating_cull_margin(
                dauntless_plating::g_params, parts, boxes[k]);
            std::fprintf(stderr,
                         "[PlatingRender] mesh %zu half=(%.0f,%.0f,%.0f) cull margin %.1f "
                         "records %d/%d\n",
                         k, boxes[k].half_extents.x, boxes[k].half_extents.y,
                         boxes[k].half_extents.z, cull,
                         renderer::plating::records_near(list, boxes[k], cull, idx), list.count);
        }
    }

    record_culling = true;
    const auto on = render(*m, ring, cam);
    const auto on_marked = render_marked(*m, ring, cam);
    record_culling = false;
    const auto off = render(*m, ring, cam);
    const auto off_marked = render_marked(*m, ring, cam);
    record_culling = true;
    ASSERT_GT(count_non_black(on), 2000) << "hull not in view";
    int diff = 0;
    for (std::size_t i = 0; i < on.size(); ++i) diff += on[i] != off[i] ? 1 : 0;
    int stencil_diff = 0;
    for (std::size_t i = 0; i < on_marked.stencil.size(); ++i)
        stencil_diff += on_marked.stencil[i] != off_marked.stencil[i] ? 1 : 0;
    std::fprintf(stderr, "[PlatingRender] culling on/off: colour bytes differ %d, stencil %d\n",
                 diff, stencil_diff);
    EXPECT_EQ(diff, 0);
    EXPECT_EQ(stencil_diff, 0);
}

// The cache follows the world: an instance destroyed is dropped by the next
// submit_opaque_in_pass.
TEST_F(PlatingRenderTest, ListCachePrunesDestroyedInstances) {
    dauntless_plating::g_params[0] = 1.0f;
    auto quad = build_quad(20.0f, true);
    scenegraph::World world;
    const auto ring = internal_ring({0, 0, 0}, 10.0f, 10.0f);
    const auto a = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(quad.get()));
    const auto b = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(quad.get()));
    world.set_world_transform(a, glm::mat4(1.0f));
    world.set_world_transform(b, glm::translate(glm::mat4(1.0f), glm::vec3(45.0f, 0.0f, 0.0f)));
    world.get(a)->hull_damage = ring;
    world.get(b)->hull_damage = ring;
    renderer::reset_model_radius_cache();
    renderer::FrameSubmitter submitter;
    const auto lookup = [](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h);
    };
    const auto cam = quad_cam();
    auto frame = [&] {
        glViewport(0, 0, kSize, kSize);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        submitter.submit_opaque_in_pass(world, cam, *p, lookup, test_lighting(),
                                        scenegraph::Pass::Space, kDecalTime);
    };
    frame();
    EXPECT_EQ(submitter.plating_list_cache_size(), 2u);
    world.destroy_instance(b);
    frame();
    EXPECT_EQ(submitter.plating_list_cache_size(), 1u);
}

// Why the subsets take the margin: a pixel further than reach from a record
// can still belong to a panel whose centre (where its wear is sampled) is
// inside reach. Two coplanar quads meet at x = 4.5; the body-axis chart's
// stringer cells run every 5 mu along x, so B's pixels at x in [4.5, 5) sit in
// the cell [0, 5), centred at x = 2.5 on A's side. A record at x = -4 (reach
// 8) misses B's box by 0.5 mu, yet strips that sliver of B. B's subset keeps
// it, and culling on draws what culling off draws.
TEST_F(PlatingRenderTest, RecordCullingKeepsRecordsWithinTheMarginOfAMesh) {
    dauntless_plating::g_params[0] = 1.0f;
    auto model = std::make_unique<assets::Model>();
    const glm::vec3 X(1, 0, 0), Y(0, 1, 0);
    add_face(*model, glm::vec3(-15.5f, 0.0f, 0.0f), X, Y, 20.0f);   // A: x in [-35.5, 4.5]
    add_face(*model, glm::vec3(24.5f, 0.0f, 0.0f), X, Y, 20.0f);    // B: x in [4.5, 44.5]
    scenegraph::Camera cam;
    cam.eye = glm::vec3(5.0f, 0.0f, 40.0f);
    cam.target = glm::vec3(5.0f, 0.0f, 0.0f);
    cam.up = glm::vec3(0.0f, 1.0f, 0.0f);
    cam.aspect = 1.0f;
    const auto ring = internal_ring({-4.0f, 0.0f, 0.0f}, 8.0f, 200.0f);
    const auto list = renderer::plating::build_damage_list(ring, dauntless_plating::g_params);
    const auto boxes = renderer::mesh_body_aabbs(*model);
    ASSERT_EQ(boxes.size(), 2u);
    std::array<std::uint8_t, renderer::plating::kMaxDamage> idx{};
    ASSERT_EQ(renderer::plating::records_near(list, boxes[1], 0.0f, idx), 0)
        << "the record's own sphere must miss B";
    EXPECT_EQ(renderer::plating::records_near(
                  list, boxes[1], renderer::plating::plating_margin(dauntless_plating::g_params),
                  idx), 1) << "B's subset drops a record that reaches its panels";

    const auto undamaged = render(*model, scenegraph::HullDamageStore{}, cam);
    record_culling = true;
    const auto on = render(*model, ring, cam);
    record_culling = false;
    const auto off = render(*model, ring, cam);
    record_culling = true;
    const int b_from = to_pixel(cam, glm::vec3(4.6f, 0.0f, 0.0f)).x;
    int b_changed = 0, diff = 0;
    for (int y = 0; y < kSize; ++y) {
        for (int x = 0; x < kSize; ++x) {
            if (x >= b_from && rgb_diff(pixel(on, x, y), pixel(undamaged, x, y)) != 0)
                ++b_changed;
            if (rgb_diff(pixel(on, x, y), pixel(off, x, y)) != 0) ++diff;
        }
    }
    std::fprintf(stderr, "[PlatingRender] margin sliver: B pixels changed %d, on/off differ %d\n",
                 b_changed, diff);
    EXPECT_GT(b_changed, 0) << "the record no longer reaches B's panels: the test lost its point";
    EXPECT_EQ(diff, 0);
}

// Fix round 1: the cull margin must cover every wear sample the shader takes
// for a pixel (plating::plating_cull_margin), not just the shader's own
// near-test margin. Big panels (secondary spacing = panel size = 60, member
// bend 0, both legal dial settings) put a pixel's panel centre up to 30 mu
// from it along x: B's pixels at x in [55, 60) judge their panel at x = 30.
// A strong record at x = 22 (reach 20) strips that panel, yet sits 33 mu from
// B's box, past reach + the shader's margin (29.8). A weak record at x = 57
// makes those pixels near. B's subset must keep the strong record.
TEST_F(PlatingRenderTest, RecordCullingCoversLargePanelOffsets) {
    float* g = dauntless_plating::g_params;
    g[0] = 1.0f;
    g[1] = 60.0f;    // panel size
    g[3] = 60.0f;    // secondary spacing
    g[15] = 0.0f;    // member bend
    auto model = std::make_unique<assets::Model>();
    const glm::vec3 X(1, 0, 0), Y(0, 1, 0);
    add_face(*model, glm::vec3(10.0f, 0.0f, 0.0f), X, Y, 45.0f);   // A: x in [-35, 55]
    add_face(*model, glm::vec3(75.0f, 0.0f, 0.0f), X, Y, 20.0f);   // B: x in [55, 95]
    scenegraph::Camera cam;
    cam.eye = glm::vec3(57.0f, 0.0f, 40.0f);
    cam.target = glm::vec3(57.0f, 0.0f, 0.0f);
    cam.up = glm::vec3(0.0f, 1.0f, 0.0f);
    cam.aspect = 1.0f;
    scenegraph::HullDamageStore weak;
    weak.add({57.0f, 0.0f, 0.0f}, glm::vec3(0.0f), 2.0f, 0.05f,
             scenegraph::HullDamageKind::Internal);
    scenegraph::HullDamageStore ring = weak;
    ring.add({22.0f, 0.0f, 0.0f}, glm::vec3(0.0f), 20.0f, 200.0f,
             scenegraph::HullDamageKind::Internal);
    const auto list = renderer::plating::build_damage_list(ring, g);
    ASSERT_EQ(list.count, 2);
    const auto boxes = renderer::mesh_body_aabbs(*model);
    ASSERT_EQ(boxes.size(), 2u);
    std::array<std::uint8_t, renderer::plating::kMaxDamage> idx{};
    EXPECT_EQ(renderer::plating::records_near(list, boxes[1],
                                              renderer::plating::plating_margin(g), idx), 1)
        << "the shader's own margin already keeps the strong record: no test";
    EXPECT_EQ(renderer::plating::records_near(
                  list, boxes[1], renderer::plating::plating_cull_margin(g, nullptr, boxes[1]),
                  idx), 2) << "B's subset drops the record that strips its panel";

    const auto weak_only = render(*model, weak, cam);
    record_culling = true;
    const auto on = render(*model, ring, cam);
    record_culling = false;
    const auto off = render(*model, ring, cam);
    record_culling = true;
    const int b_from = to_pixel(cam, glm::vec3(55.1f, 0.0f, 0.0f)).x;
    const int b_to = to_pixel(cam, glm::vec3(59.9f, 0.0f, 0.0f)).x;
    int b_stripped = 0, diff = 0;
    for (int y = 0; y < kSize; ++y) {
        for (int x = 0; x < kSize; ++x) {
            if (x >= b_from && x <= b_to &&
                rgb_diff(pixel(off, x, y), pixel(weak_only, x, y)) != 0)
                ++b_stripped;
            if (rgb_diff(pixel(on, x, y), pixel(off, x, y)) != 0) ++diff;
        }
    }
    std::fprintf(stderr, "[PlatingRender] large panels: B pixels changed %d, on/off differ %d\n",
                 b_stripped, diff);
    EXPECT_GT(b_stripped, 0) << "the strong record no longer reaches B's panel: no test";
    EXPECT_EQ(diff, 0);
}

// ---- Final fix wave I1: per-mesh subsets cached on the list entry. ----------

// The per-mesh record subsets (cull margin + records_near per mesh) are
// computed once per change of what they depend on -- the list (store revision
// + params), the hull's structure parts (they land on a worker, so the
// pointer changes from null to the parts) and the model -- not once per draw:
// two frames of opaque + mark + interior, and a viewscreen render between
// them, share one computation.
TEST_F(PlatingRenderTest, PerMeshSubsetsComputedOncePerChange) {
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 1.0f;
    auto model = two_quads(40.0f);
    // A source of its own, so the parts job is this test's: it fails to find
    // the file and lands an empty parts list, a pointer change all the same.
    static int unique = 0;
    model->source = fs::path("/nonexistent/plating-subset-cache-" +
                             std::to_string(++unique) + ".nif");
    auto other = two_quads(40.0f);
    scenegraph::World world;
    auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));
    world.get(iid)->hull_damage = left_quad_ring();
    const auto cam = quad_cam();
    renderer::reset_model_radius_cache();
    renderer::FrameSubmitter submitter;
    const auto lookup = [](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h);
    };
    auto frame = [&](const renderer::InteriorPolicy& policy) {
        submitter.set_interior_policy(policy);
        glViewport(0, 0, kSize, kSize);
        glStencilMask(0xFF);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        submitter.submit_opaque_in_pass(world, cam, *p, lookup, test_lighting(),
                                        scenegraph::Pass::Space, kDecalTime);
        submitter.submit_plating_interior(world, cam, *p, lookup, nullptr, test_lighting(),
                                          1.0f, kDecalTime);
    };
    renderer::InteriorPolicy viewscreen = all_near_policy();
    viewscreen.viewscreen = true;
    viewscreen.viewscreen_target = iid;

    const int c0 = renderer::plating_mesh_subset_computations();
    frame(all_near_policy());
    EXPECT_EQ(submitter.plating_marks_last_frame(), 1);
    EXPECT_EQ(submitter.plating_interiors_last_frame(), 1);
    // The parts job started on the first read; it may land between draws.
    const auto t0 = std::chrono::steady_clock::now();
    while (renderer::structure_parts_for(model->source) == nullptr &&
           std::chrono::steady_clock::now() - t0 < std::chrono::seconds(20))
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    ASSERT_NE(renderer::structure_parts_for(model->source), nullptr) << "parts never landed";
    frame(all_near_policy());   // parts pointer changed (or changed in frame 1)
    const int c1 = renderer::plating_mesh_subset_computations();
    EXPECT_GE(c1 - c0, 1);
    EXPECT_LE(c1 - c0, 2) << "one computation per parts pointer, not one per draw";

    frame(all_near_policy());
    frame(viewscreen);
    frame(all_near_policy());
    EXPECT_EQ(renderer::plating_mesh_subset_computations() - c1, 0)
        << "nothing changed: the subsets must be reused by every draw and pass";

    world.get(iid)->hull_damage.add({40.0f, 0.0f, 0.0f}, glm::vec3(0.0f), 6.0f, 2.0f,
                                    scenegraph::HullDamageKind::Internal);
    frame(all_near_policy());
    frame(all_near_policy());
    EXPECT_EQ(renderer::plating_mesh_subset_computations() - c1, 1) << "a store change";

    world.get(iid)->model_handle = reinterpret_cast<scenegraph::ModelHandle>(other.get());
    frame(all_near_policy());
    frame(all_near_policy());
    EXPECT_EQ(renderer::plating_mesh_subset_computations() - c1, 2) << "a model change";
}

// Uploads of u_dmg_* skip a mesh whose subset equals the last one uploaded in
// the same draw: two quads that both see every record upload the list once
// per draw (the opaque draw and the mark), not once per mesh.
TEST_F(PlatingRenderTest, IdenticalMeshSubsetsUploadOncePerDraw) {
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 0.0f;
    auto model = std::make_unique<assets::Model>();
    const glm::vec3 X(1, 0, 0), Y(0, 1, 0);
    add_face(*model, glm::vec3(-10.0f, 0.0f, 0.0f), X, Y, 10.0f);
    add_face(*model, glm::vec3(10.0f, 0.0f, 0.0f), X, Y, 10.0f);
    const auto ring = internal_ring(glm::vec3(0.0f), 12.0f, 10.0f);
    const auto cam = quad_cam();
    const int u0 = renderer::plating_record_uploads();
    render(*model, ring, cam);
    EXPECT_EQ(renderer::plating_record_uploads() - u0, 1) << "opaque draw";
    const int u1 = renderer::plating_record_uploads();
    const auto r = render_marked(*model, ring, cam);
    EXPECT_EQ(r.marks, 1);
    EXPECT_EQ(renderer::plating_record_uploads() - u1, 2) << "opaque draw + mark";
}

// ---- Final fix wave I2: record-free meshes skipped in the mark + interior. --

// A mesh whose record subset is empty is not drawn by the mark (every one of
// its fragments would be discarded) nor by the interior (it cannot pass the
// stencil and depth there). The torn Ambassador, its structure parts loaded,
// rooms on: colour and stencil byte-identical with the skip on and off, and
// both passes issue fewer mesh draws with it on.
TEST_F(PlatingRenderTest, SkippingRecordFreeMeshesIsByteIdentical) {
    auto m = ambassador();
    ASSERT_TRUE(m) << "BC asset not available at " << ambassador_nif()
                   << " -- set DAUNTLESS_GAME_DIR";
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 1.0f;
    const renderer::Aabb box = renderer::compute_model_aabb(*m);
    const auto cam = top_down(box);
    const auto t0 = std::chrono::steady_clock::now();
    while (renderer::structure_parts_for(m->source) == nullptr &&
           std::chrono::steady_clock::now() - t0 < std::chrono::seconds(20))
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    ASSERT_NE(renderer::structure_parts_for(m->source), nullptr) << "parts never landed";
    ASSERT_FALSE(renderer::structure_parts_for(m->source)->empty());
    // Holes on the saucer: one torn, one blown clear through.
    scenegraph::HullDamageStore ring;
    const float top = box.center.z + box.half_extents.z + 10.0f;
    const glm::vec2 at[3] = {{0.0f, 170.0f}, {35.0f, 140.0f}, {-35.0f, 140.0f}};
    for (int k = 0; k < 3; ++k) {
        const auto h = renderer::ray_trace_instance(*m, glm::mat4(1.0f),
                                                    glm::vec3(at[k], top),
                                                    glm::vec3(0.0f, 0.0f, -1.0f), 1.0e5f);
        ASSERT_TRUE(h) << "no hull under saucer point " << k;
        ring.add(h->point, h->normal, 25.0f, k == 0 ? 60.0f : 10.0f,
                 scenegraph::HullDamageKind::Internal);
    }
    const std::uint8_t bg[3] = {13, 251, 7};
    const glm::vec3 clear(bg[0] / 255.0f, bg[1] / 255.0f, bg[2] / 255.0f);

    skip_record_free = true;
    const auto on = render_marked(*m, ring, cam, clear);
    skip_record_free = false;
    const auto off = render_marked(*m, ring, cam, clear);
    skip_record_free = true;

    int stamped = 0;
    for (std::uint8_t v : on.stencil) stamped += v != 0 ? 1 : 0;
    int colour_diff = 0, stencil_diff = 0;
    for (std::size_t i = 0; i < on.color.size(); ++i) colour_diff += on.color[i] != off.color[i];
    for (std::size_t i = 0; i < on.stencil.size(); ++i)
        stencil_diff += on.stencil[i] != off.stencil[i];
    std::fprintf(stderr,
                 "[PlatingRender] skip record-free meshes: meshes=%zu stamped=%d mark draws "
                 "%d->%d interior draws %d->%d colour diff %d stencil diff %d\n",
                 m->meshes.size(), stamped, off.mark_mesh_draws, on.mark_mesh_draws,
                 off.interior_mesh_draws, on.interior_mesh_draws, colour_diff, stencil_diff);
    ASSERT_EQ(on.marks, 1);
    ASSERT_GT(stamped, 200) << "the holes cut too little to compare";
    EXPECT_EQ(colour_diff, 0);
    EXPECT_EQ(stencil_diff, 0);
    EXPECT_EQ(off.mark_mesh_draws, static_cast<int>(m->meshes.size()));
    EXPECT_EQ(off.interior_mesh_draws, static_cast<int>(m->meshes.size()));
    EXPECT_GT(on.mark_mesh_draws, 0);
    EXPECT_LT(on.mark_mesh_draws, off.mark_mesh_draws);
    EXPECT_EQ(on.interior_mesh_draws, on.mark_mesh_draws)
        << "the interior draws exactly the meshes the mark drew";
}

// ---- Phase 2b Task 2: record-free meshes take the stock program. -----------

// Within a plated instance, a mesh whose record subset is empty draws through
// the stock program: forcing the plating program costs GPU time (C-118/C-119)
// for a mesh it can change nothing on. Two quads, damage on the one at
// x = -40: only that quad draws through plating (counted), the plating
// program is the last one bound (stock first, then plating), and the far
// quad's pixels are the stock draw's.
TEST_F(PlatingRenderTest, RecordFreeMeshesDrawWithStockProgram) {
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 0.0f;
    const auto cam = quad_cam();
    auto model = two_quads(40.0f);   // mesh 0 far (x = 40), mesh 1 damaged (x = -40)
    const GLint plating = static_cast<GLint>(p->plating_shader().program());
    auto current = [] { GLint prog = 0; glGetIntegerv(GL_CURRENT_PROGRAM, &prog); return prog; };

    const int d0 = renderer::draw_model_plating_mesh_draws();
    const auto px = render(*model, left_quad_ring(), cam);
    EXPECT_EQ(renderer::draw_model_plating_mesh_draws() - d0, 1)
        << "only the damaged quad draws through the plating program";
    EXPECT_EQ(current(), plating) << "the plating meshes draw last";

    const auto stock = render(*model, scenegraph::HullDamageStore{}, cam, /*stock_submit=*/true);
    int compared = 0, mismatched = 0;
    const glm::ivec2 lo = to_pixel(cam, glm::vec3(28.0f, -12.0f, 0.0f));
    const glm::ivec2 hi = to_pixel(cam, glm::vec3(52.0f, 12.0f, 0.0f));
    for (int y = lo.y; y <= hi.y; ++y) {
        for (int x = lo.x; x <= hi.x; ++x) {
            ++compared;
            if (rgb_diff(pixel(px, x, y), pixel(stock, x, y)) != 0) ++mismatched;
        }
    }
    ASSERT_GT(compared, 500);
    EXPECT_EQ(mismatched, 0) << "the far quad is not the stock draw";
}

// The soot ruling: outside the near-damage zone a scorch deposit is full
// strength, as on an undamaged hull; the plating soot scale applies only
// where plating_near. Two quads meet at x = 0; a weak record sits on the left
// quad at x = -36, far from the seam (beyond reach + margin, and outside the
// right quad's subset), so the right quad draws stock and the left plating.
// A scorch decal centred on the seam: the pixels either side match each other
// and the undamaged hull's soot.
TEST_F(PlatingRenderTest, SootIsContinuousAcrossTheProgramSplit) {
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 0.0f;
    const float* g = dauntless_plating::g_params;
    ASSERT_LT(g[13], 0.9f) << "soot dial at 1: the test cannot see the scale";
    auto model = std::make_unique<assets::Model>();
    const glm::vec3 X(1, 0, 0), Y(0, 1, 0);
    add_face(*model, glm::vec3(-20.0f, 0.0f, 0.0f), X, Y, 20.0f);   // A: x in [-40, 0]
    add_face(*model, glm::vec3(20.0f, 0.0f, 0.0f), X, Y, 20.0f);    // B: x in [0, 40]
    scenegraph::HullDamageStore ring;
    ring.add({-36.0f, 0.0f, 0.0f}, glm::vec3(0.0f), 2.0f, 1.0f,
             scenegraph::HullDamageKind::Internal);
    const auto list = renderer::plating::build_damage_list(ring, g);
    ASSERT_EQ(list.count, 1);
    const auto boxes = renderer::mesh_body_aabbs(*model);
    std::array<std::uint8_t, renderer::plating::kMaxDamage> idx{};
    ASSERT_EQ(renderer::plating::records_near(
                  list, boxes[1], renderer::plating::plating_cull_margin(g, nullptr, boxes[1]),
                  idx), 0) << "the record reaches B: no program split";
    ASSERT_GT(36.0f - 1.0f, 2.0f + renderer::plating::plating_margin(g))
        << "the seam is near the record";

    scenegraph::DamageDecalRing decals;
    decals.add(glm::vec3(0.0f), glm::vec3(0.0f, 0.0f, 1.0f), 12.0f, 1.0f,
               scenegraph::WeaponClass::Scorch, 0.0f);
    const auto cam = quad_cam();
    const auto damaged = render(*model, ring, cam, false, &decals);
    const auto undamaged = render(*model, scenegraph::HullDamageStore{}, cam, false, &decals);
    const auto clean = render(*model, scenegraph::HullDamageStore{}, cam);

    const glm::ivec2 seam = to_pixel(cam, glm::vec3(0.0f));
    int worst_seam = 0, worst_stock = 0, sooted = 0;
    for (int dy = -12; dy <= 12; ++dy) {
        const int y = seam.y + dy;
        const std::uint8_t* left = pixel(damaged, seam.x - 1, y);
        const std::uint8_t* right = pixel(damaged, seam.x, y);
        for (int c = 0; c < 3; ++c) worst_seam = std::max(worst_seam, std::abs(left[c] - right[c]));
        for (int x : {seam.x - 1, seam.x}) {
            const std::uint8_t* a = pixel(damaged, x, y);
            const std::uint8_t* b = pixel(undamaged, x, y);
            for (int c = 0; c < 3; ++c) worst_stock = std::max(worst_stock, std::abs(a[c] - b[c]));
            if (rgb_diff(pixel(clean, x, y), b) > 30) ++sooted;
        }
    }
    std::fprintf(stderr, "[PlatingRender] soot seam: worst across %d, worst vs undamaged %d, "
                 "sooted %d\n", worst_seam, worst_stock, sooted);
    ASSERT_GT(sooted, 20) << "the decal laid too little soot at the seam to compare";
    EXPECT_LE(worst_seam, 2) << "soot steps at the program split";
    EXPECT_LE(worst_stock, 2) << "away from damage the soot is not the undamaged hull's";
}

// The soot scale fades in over one margin around each record, so a scorch
// decal much larger than the near zone shows no ring at the zone's edge.
TEST_F(PlatingRenderTest, SootHasNoRingAtTheNearZoneEdge) {
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 0.0f;
    const float* g = dauntless_plating::g_params;
    ASSERT_LT(g[13], 0.9f) << "soot dial at 1: the test cannot see the scale";
    auto model = std::make_unique<assets::Model>();
    add_face(*model, glm::vec3(0.0f), glm::vec3(1, 0, 0), glm::vec3(0, 1, 0), 45.0f);
    const float reach = 2.0f;
    const float margin = renderer::plating::plating_margin(g);
    ASSERT_GT(margin, 4.0f);
    scenegraph::HullDamageStore ring;
    ring.add({0.0f, 0.0f, 0.0f}, glm::vec3(0.0f), reach, 1.0f,
             scenegraph::HullDamageKind::Internal);
    scenegraph::DamageDecalRing decals;
    decals.add(glm::vec3(0.0f), glm::vec3(0.0f, 0.0f, 1.0f), 44.0f, 1.0f,
               scenegraph::WeaponClass::Scorch, 0.0f);
    const auto cam = quad_cam();
    const auto damaged = render(*model, ring, cam, false, &decals);
    const auto undamaged = render(*model, scenegraph::HullDamageStore{}, cam, false, &decals);

    const int y = to_pixel(cam, glm::vec3(0.0f, 0.0f, 0.0f)).y;
    const int x0 = to_pixel(cam, glm::vec3(reach + 1.0f, 0.0f, 0.0f)).x;
    const int x1 = to_pixel(cam, glm::vec3(32.0f, 0.0f, 0.0f)).x;
    const int xe = to_pixel(cam, glm::vec3(reach + margin + 5.0f, 0.0f, 0.0f)).x;
    int worst_step = 0, worst_far = 0;
    for (int x = x0; x < x1; ++x) {
        const std::uint8_t* a = pixel(damaged, x, y);
        const std::uint8_t* b = pixel(damaged, x + 1, y);
        for (int c = 0; c < 3; ++c) worst_step = std::max(worst_step, std::abs(a[c] - b[c]));
        if (x >= xe) {
            const std::uint8_t* u = pixel(undamaged, x, y);
            for (int c = 0; c < 3; ++c) worst_far = std::max(worst_far, std::abs(a[c] - u[c]));
        }
    }
    std::fprintf(stderr, "[PlatingRender] soot ring: worst step %d, far vs stock %d\n",
                 worst_step, worst_far);
    // Measured 3 with the smoothed weight; the old ringing shader gave 28.
    EXPECT_LE(worst_step, 6) << "soot steps along the line out of the near zone";
    EXPECT_LE(worst_far, 2) << "far from damage the soot is not the stock draw's";
}

// With node overrides the per-mesh split still applies: the record-free quad
// draws through the stock program and the damaged one through plating, one
// switch.
TEST_F(PlatingRenderTest, ArticulatedPlatedDrawSplitsLikeAnUnposedOne) {
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 0.0f;
    const auto cam = quad_cam();
    auto model = two_quads(-40.0f);
    const std::unordered_map<int, glm::mat4> overrides{
        {0, glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 2.0f, 0.0f))}};
    const int d0 = renderer::draw_model_plating_mesh_draws();
    const int b0 = renderer::draw_model_program_binds();
    render(*model, left_quad_ring(), cam, false, nullptr, &overrides);
    EXPECT_EQ(renderer::draw_model_plating_mesh_draws() - d0, 1) << "only the damaged quad";
    EXPECT_EQ(renderer::draw_model_program_binds() - b0, 2) << "stock once, plating once";
}

// Record-free and damaged meshes interleaved in the model's mesh order: the
// instance binds the stock program once and the plating program once (one
// switch), never per mesh.
TEST_F(PlatingRenderTest, PlatedInstanceSwitchesProgramAtMostOnce) {
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 0.0f;
    auto model = std::make_unique<assets::Model>();
    const glm::vec3 X(1, 0, 0), Y(0, 1, 0);
    for (float cx : {-60.0f, -20.0f, 20.0f, 60.0f})   // damaged, free, damaged, free
        add_face(*model, glm::vec3(cx, 0.0f, 0.0f), X, Y, 15.0f);
    scenegraph::HullDamageStore ring;
    ring.add({-60.0f, 0.0f, 0.0f}, glm::vec3(0.0f), 2.0f, 1.0f,
             scenegraph::HullDamageKind::Internal);
    ring.add({20.0f, 0.0f, 0.0f}, glm::vec3(0.0f), 2.0f, 1.0f,
             scenegraph::HullDamageKind::Internal);
    const int d0 = renderer::draw_model_plating_mesh_draws();
    const int b0 = renderer::draw_model_program_binds();
    render(*model, ring, quad_cam());
    EXPECT_EQ(renderer::draw_model_plating_mesh_draws() - d0, 2) << "the two damaged quads";
    EXPECT_EQ(renderer::draw_model_program_binds() - b0, 2) << "stock once, plating once";
}

// ── Severed structure parts (phase 3 Task 4) ───────────────────────────────
// Two plates side by side in z = 0, each its own structure part: part 0 on
// the left (x < 0), part 1 on the right. The segmentation is injected, so the
// plating draw's plating_part sees exactly these two boxes.
namespace {
std::unique_ptr<assets::Model> two_part_plate(const char* tag) {
    auto model = std::make_unique<assets::Model>();
    const glm::vec3 X(1, 0, 0), Y(0, 1, 0);
    add_face(*model, glm::vec3(-32.0f, 0.0f, 0.0f), X, Y, 30.0f);
    add_face(*model, glm::vec3(32.0f, 0.0f, 0.0f), X, Y, 30.0f);
    model->source = std::string("test://two-part-plate/") + tag;
    voxel::StructureSegmentation seg;
    for (const float cx : {-32.0f, 32.0f}) {
        voxel::StructurePart part;
        part.kind = voxel::PartKind::Box;
        part.centre = glm::vec3(cx, 0.0f, 0.0f);
        part.half_extent = glm::vec3(30.0f, 30.0f, 5.0f);
        seg.parts.push_back(part);
    }
    renderer::set_structure_segmentation_for_test(model->source, std::move(seg));
    return model;
}

// Every pixel of `px` whose window x is on `right` side of `mid_x`.
int count_lit_on_side(const std::vector<std::uint8_t>& px, int mid_x, bool right) {
    int n = 0;
    for (int y = 0; y < kSize; ++y)
        for (int x = right ? mid_x + 2 : 0; x < (right ? kSize : mid_x - 2); ++x) {
            const std::uint8_t* q = pixel(px, x, y);
            if (q[0] + q[1] + q[2] > 6) ++n;
        }
    return n;
}

// Largest channel difference over the pixels on `right` side of `mid_x`.
int worst_on_side(const std::vector<std::uint8_t>& a, const std::vector<std::uint8_t>& b,
                  int mid_x, bool right) {
    int worst = 0;
    for (int y = 0; y < kSize; ++y)
        for (int x = right ? mid_x + 2 : 0; x < (right ? kSize : mid_x - 2); ++x)
            for (int c = 0; c < 3; ++c)
                worst = std::max(worst, std::abs(int(pixel(a, x, y)[c]) - int(pixel(b, x, y)[c])));
    return worst;
}
}  // namespace

// A part the hull has lost is not drawn on the parent: its pixels show the
// clear colour, and the part still attached draws exactly as before.
TEST_F(PlatingRenderTest, SeveredPartIsHiddenOnTheParent) {
    dauntless_plating::g_params[0] = 1.0f;
    const auto cam = quad_cam();
    auto plate = two_part_plate("severed-parent");
    const int mid = to_pixel(cam, glm::vec3(0.0f)).x;
    const auto whole = render(*plate, scenegraph::HullDamageStore{}, cam);
    ASSERT_GT(count_lit_on_side(whole, mid, false), 2000) << "part 0 not in view";
    ASSERT_GT(count_lit_on_side(whole, mid, true), 2000) << "part 1 not in view";

    const auto severed = render(*plate, scenegraph::HullDamageStore{}, cam, false, nullptr,
                                nullptr, [](scenegraph::Instance& i) { i.severed_parts = 1u << 1; });
    EXPECT_EQ(count_lit_on_side(severed, mid, true), 0) << "the severed part still draws";
    EXPECT_LE(worst_on_side(whole, severed, mid, false), 1) << "the attached part changed";
}

// A chunk (shown_parts) draws its own parts and nothing else of the model.
TEST_F(PlatingRenderTest, ChunkDrawsOnlyItsPart) {
    dauntless_plating::g_params[0] = 1.0f;
    const auto cam = quad_cam();
    auto plate = two_part_plate("chunk");
    const int mid = to_pixel(cam, glm::vec3(0.0f)).x;
    const auto whole = render(*plate, scenegraph::HullDamageStore{}, cam);
    const auto chunk = render(*plate, scenegraph::HullDamageStore{}, cam, false, nullptr,
                              nullptr, [](scenegraph::Instance& i) { i.shown_parts = 1u << 1; });
    EXPECT_EQ(count_lit_on_side(chunk, mid, false), 0) << "the chunk drew another part";
    ASSERT_GT(count_lit_on_side(whole, mid, true), 2000) << "part 1 not in view";
    EXPECT_LE(worst_on_side(whole, chunk, mid, true), 1) << "the chunk's own part changed";
}

// A chunk that is a whole assembly (Ruling 4) draws every part in its mask,
// exactly as the whole hull draws them.
TEST_F(PlatingRenderTest, ChunkDrawsEveryPartInItsMask) {
    dauntless_plating::g_params[0] = 1.0f;
    const auto cam = quad_cam();
    auto plate = two_part_plate("chunk-mask");
    const int mid = to_pixel(cam, glm::vec3(0.0f)).x;
    const auto whole = render(*plate, scenegraph::HullDamageStore{}, cam);
    const auto chunk =
        render(*plate, scenegraph::HullDamageStore{}, cam, false, nullptr, nullptr,
               [](scenegraph::Instance& i) { i.shown_parts = (1u << 0) | (1u << 1); });
    ASSERT_GT(count_lit_on_side(whole, mid, false), 2000) << "part 0 not in view";
    ASSERT_GT(count_lit_on_side(whole, mid, true), 2000) << "part 1 not in view";
    EXPECT_LE(worst_on_side(whole, chunk, mid, false), 1) << "part 0 of the assembly changed";
    EXPECT_LE(worst_on_side(whole, chunk, mid, true), 1) << "part 1 of the assembly changed";
    const auto other =
        render(*plate, scenegraph::HullDamageStore{}, cam, false, nullptr, nullptr,
               [](scenegraph::Instance& i) { i.shown_parts = 1u << 0; });
    EXPECT_EQ(count_lit_on_side(other, mid, true), 0) << "a part outside the mask drew";
    EXPECT_LE(worst_on_side(whole, other, mid, false), 1) << "the chunk's own part changed";
}

// The mark never stamps a hidden part: a tear spanning both parts stamps
// only the attached one.
TEST_F(PlatingRenderTest, MarkSkipsHiddenParts) {
    dauntless_plating::g_params[0] = 1.0f;
    GLint sbits = 0;
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glGetFramebufferAttachmentParameteriv(GL_FRAMEBUFFER, GL_STENCIL,
                                          GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE, &sbits);
    ASSERT_GE(sbits, 8) << "test window has no stencil buffer";
    const auto cam = quad_cam();
    auto plate = two_part_plate("mark");
    const auto ring = internal_ring(glm::vec3(0.0f), 30.0f, 10.0f);
    const glm::ivec2 left = to_pixel(cam, glm::vec3(-12.0f, 0.0f, 0.0f));
    const glm::ivec2 right = to_pixel(cam, glm::vec3(12.0f, 0.0f, 0.0f));
    auto st = [](const Marked& r, glm::ivec2 c) {
        return r.stencil[static_cast<std::size_t>(c.y) * kSize + c.x];
    };
    const auto whole = render_marked_many(*plate, {Placed{glm::mat4(1.0f), ring}}, cam);
    ASSERT_EQ(st(whole, left), 2) << "the tear does not cut part 0";
    ASSERT_EQ(st(whole, right), 2) << "the tear does not cut part 1";

    const auto severed =
        render_marked_many(*plate, {Placed{glm::mat4(1.0f), ring, 1u << 1, 0u}}, cam);
    EXPECT_EQ(st(severed, left), 2) << "the attached part lost its mark";
    int stamped_right = 0;
    const int mid = to_pixel(cam, glm::vec3(0.0f)).x;
    for (int y = 0; y < kSize; ++y)
        for (int x = mid + 2; x < kSize; ++x)
            if (severed.stencil[static_cast<std::size_t>(y) * kSize + x] != 0) ++stamped_right;
    EXPECT_EQ(stamped_right, 0) << "the hidden part was stamped";
}

// Phase 4, Task 5: the shadow depth pass hides what the colour draw hides. A
// parent casts no depth from a part it has lost, and a chunk casts depth from
// its own parts only -- not the whole model, and not nothing. Every kept
// texel's depth is exactly the whole hull's.
TEST_F(PlatingRenderTest, ShadowHonoursThePartMask) {
    // The light looks UP at the plates (+z): the pass culls FRONT faces and
    // the plates face +z, so seen from below their back faces are the casters.
    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 0.0f, -120.0f);
    cam.target = glm::vec3(0.0f);
    cam.up = glm::vec3(0.0f, 1.0f, 0.0f);
    cam.aspect = 1.0f;
    auto plate = two_part_plate("shadow");
    renderer::ShadowLight light;
    light.view_proj = cam.proj_matrix() * cam.view_matrix();
    const int mid = to_pixel(cam, glm::vec3(0.0f)).x;
    // Which window side each part lands on (the view from below mirrors x).
    const bool part1_right = to_pixel(cam, glm::vec3(32.0f, 0.0f, 0.0f)).x > mid;
    const auto lookup = [](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h);
    };
    auto depth = [&](std::uint32_t severed, std::uint32_t shown) {
        scenegraph::World world;
        auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(plate.get()));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.get(iid)->rim_eligible = true;
        world.get(iid)->severed_parts = severed;
        world.get(iid)->shown_parts = shown;
        glViewport(0, 0, kSize, kSize);
        glDepthMask(GL_TRUE);
        glClearDepth(1.0);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        renderer::submit_shadow_depth(world, light, *p, lookup);
        std::vector<float> d(static_cast<std::size_t>(kSize) * kSize, -1.0f);
        glReadPixels(0, 0, kSize, kSize, GL_DEPTH_COMPONENT, GL_FLOAT, d.data());
        return d;
    };
    // Texels with depth on part `part`'s side of the window.
    auto cast = [&](const std::vector<float>& d, int part) {
        const bool right = (part == 1) == part1_right;
        int n = 0;
        for (int y = 0; y < kSize; ++y)
            for (int x = right ? mid + 2 : 0; x < (right ? kSize : mid - 2); ++x)
                if (d[static_cast<std::size_t>(y) * kSize + x] < 1.0f) ++n;
        return n;
    };
    // Largest depth difference on part `part`'s side.
    auto worst = [&](const std::vector<float>& a, const std::vector<float>& b, int part) {
        const bool right = (part == 1) == part1_right;
        float w = 0.0f;
        for (int y = 0; y < kSize; ++y)
            for (int x = right ? mid + 2 : 0; x < (right ? kSize : mid - 2); ++x) {
                const std::size_t i = static_cast<std::size_t>(y) * kSize + x;
                w = std::max(w, std::abs(a[i] - b[i]));
            }
        return w;
    };

    const auto whole = depth(0u, 0u);
    ASSERT_GT(cast(whole, 0), 2000) << "part 0 casts no depth";
    ASSERT_GT(cast(whole, 1), 2000) << "part 1 casts no depth";

    const auto parent = depth(1u << 1, 0u);
    EXPECT_EQ(cast(parent, 1), 0) << "the parent still shadows its lost part";
    EXPECT_EQ(worst(whole, parent, 0), 0.0f) << "the parent's attached part changed";

    const auto chunk = depth(0u, 1u << 1);
    EXPECT_EQ(cast(chunk, 0), 0) << "the chunk shadows a part it does not have";
    EXPECT_EQ(worst(whole, chunk, 1), 0.0f) << "the chunk's own part lost its shadow";
}

// Ruling 8 drift guard: shadow_parts.frag's plating_part is a COPY of
// opaque.frag's (shader sources are embedded whole), and so is the MAX_PARTS
// it loops to. Compared on the embedded sources -- the texts the programs are
// actually built from.
namespace {
std::string glsl_function(const std::string& src, const std::string& signature) {
    const std::size_t at = src.find(signature);
    if (at == std::string::npos) return {};
    const std::size_t end = src.find("\n}\n", at);
    if (end == std::string::npos) return {};
    return src.substr(at, end + 3 - at);
}
std::string glsl_line_with(const std::string& src, const std::string& needle) {
    const std::size_t at = src.find(needle);
    if (at == std::string::npos) return {};
    const std::size_t start = src.rfind('\n', at) + 1;
    return src.substr(start, src.find('\n', at) - start);
}
}  // namespace

TEST(ShadowPartsShader, PlatingPartIsTheTwinOfOpaque) {
    const std::string opaque = renderer::shader_src::opaque_fs;
    const std::string shadow = renderer::shader_src::shadow_parts_fs;
    const std::string sig = "int plating_part(vec3 p) {";
    const std::string a = glsl_function(opaque, sig), b = glsl_function(shadow, sig);
    ASSERT_FALSE(a.empty()) << "opaque.frag has no plating_part";
    ASSERT_FALSE(b.empty()) << "shadow_parts.frag has no plating_part";
    EXPECT_EQ(a, b) << "shadow_parts.frag's plating_part drifted from opaque.frag's";
    const std::string ma = glsl_line_with(opaque, "const int  MAX_PARTS");
    ASSERT_FALSE(ma.empty()) << "opaque.frag has no MAX_PARTS";
    EXPECT_EQ(ma, glsl_line_with(shadow, "const int  MAX_PARTS"))
        << "the two MAX_PARTS differ";
}

// Phase 4, Task 5: a chunk never draws a cloak shell (a cloaking parent's
// shell is the whole model; a chunk's would be too).
TEST_F(PlatingRenderTest, CloakSkipsChunks) {
    const auto cam = quad_cam();
    auto plate = two_part_plate("cloak");
    const auto lookup = [](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h);
    };
    auto shell = [&](std::uint32_t shown) {
        scenegraph::World world;
        auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(plate.get()));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.get(iid)->shown_parts = shown;
        glViewport(0, 0, kSize, kSize);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        renderer::CloakRefractionPass pass;
        pass.render({renderer::CloakShipDescriptor{iid, 0.5f}}, world, cam, *p, lookup, 0.0f,
                    test_lighting(), 1.0f, kDecalTime);
        std::vector<std::uint8_t> px(static_cast<std::size_t>(kSize) * kSize * 4);
        glReadPixels(0, 0, kSize, kSize, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        return count_non_black(px);
    };
    ASSERT_GT(shell(0u), 2000) << "a cloaking hull drew no shell";
    EXPECT_EQ(shell(1u << 1), 0) << "a chunk drew a cloak shell";
}

// Phase 4, Task 2 (removing the old voxel carve): the carve clip, its
// uniforms and its 3D field sampler leave the STOCK program, and the frame
// stops binding carve state. None of that may change how an undamaged hull
// looks. The read-back (raw RGBA8, kSize x kSize, row 0 = bottom: the
// Ambassador undamaged through submit_opaque_in_pass, a fixed three-quarter
// camera and test_lighting()) is pinned by its 64-bit FNV-1a hash, taken from
// the build BEFORE the removal. The pixels themselves are BC-derived, so they
// are never committed (Ruling 3). The hash is exact to the byte and tied to
// this machine's GL driver, like the reference bytes it replaces.
//
// Re-baseline ONLY for a deliberate look change: the failure message prints
// the new hash. DAUNTLESS_DUMP_UNDAMAGED_PIXELS=1 additionally writes the
// raw buffer to the system TEMP directory (never the project tree) so two
// builds can be diffed by eye.
TEST_F(PlatingRenderTest, UndamagedHullUnchangedByCarveRemoval) {
    constexpr std::uint64_t kUndamagedAmbassadorHash = 0xfd47abf2c15863fdull;

    auto m = ambassador();
    ASSERT_TRUE(m) << "BC asset not available at " << ambassador_nif()
                   << " -- set DAUNTLESS_GAME_DIR";
    const renderer::Aabb box = renderer::compute_model_aabb(*m);
    scenegraph::Camera cam;
    const float radius = glm::length(box.half_extents);
    const float dist = 1.15f * radius / std::tan(cam.fov_y_rad * 0.5f);
    cam.target = box.center;
    cam.eye = box.center + glm::normalize(glm::vec3(0.55f, -0.7f, 0.45f)) * dist;
    cam.up = glm::vec3(0.0f, 0.0f, 1.0f);
    cam.aspect = 1.0f;

    const auto px = render(*m, scenegraph::HullDamageStore{}, cam);
    ASSERT_GT(count_non_black(px), 4000) << "hull not in view";
    ASSERT_EQ(px.size(), static_cast<std::size_t>(kSize) * kSize * 4);

    if (std::getenv("DAUNTLESS_DUMP_UNDAMAGED_PIXELS") != nullptr) {
        const fs::path dump = fs::temp_directory_path() / "dauntless_undamaged_ambassador.rgba";
        std::FILE* f = std::fopen(dump.string().c_str(), "wb");
        ASSERT_NE(f, nullptr) << "cannot write " << dump;
        std::fwrite(px.data(), 1, px.size(), f);
        std::fclose(f);
        std::fprintf(stderr, "[PlatingRender] dumped undamaged pixels to %s\n",
                     dump.string().c_str());
    }

    std::uint64_t h = 0xcbf29ce484222325ull;  // FNV-1a 64 offset basis
    for (const std::uint8_t b : px) {
        h ^= b;
        h *= 0x100000001b3ull;  // FNV-1a 64 prime
    }
    char got[24];
    std::snprintf(got, sizeof got, "0x%016llx", static_cast<unsigned long long>(h));
    EXPECT_EQ(h, kUndamagedAmbassadorHash)
        << "undamaged hull changed: read-back hash " << got
        << " (set DAUNTLESS_DUMP_UNDAMAGED_PIXELS=1 to dump the pixels to TEMP)";
}

// ── Damage moves with articulated parts (layered damage phase 4 §2.1) ─────
namespace {

// Two plates facing +z: node 0 (the body, root) at x = -40 and node 1 (a
// part, child of the root, identity local) at x = +40. Half size 15.
std::unique_ptr<assets::Model> body_and_part() {
    auto model = std::make_unique<assets::Model>();
    const glm::vec3 X(1, 0, 0), Y(0, 1, 0);
    add_face(*model, glm::vec3(-40.0f, 0.0f, 0.0f), X, Y, 15.0f);
    add_face(*model, glm::vec3(40.0f, 0.0f, 0.0f), X, Y, 15.0f);
    model->nodes[0].name = "body";
    assets::Node part;
    part.name = "part";
    part.parent_index = 0;
    part.meshes.push_back(model->nodes[0].meshes.back());
    model->nodes[0].meshes.pop_back();
    model->nodes[0].children.push_back(1);
    model->nodes.push_back(part);
    return model;
}

}  // namespace

// A hit on a part is recorded on that part's node, in its REST frame. When
// the part is then posed (rotated 30 degrees about its own centre and
// translated), the cut hole and the interior behind it go with it: the part's
// pixels -- cut stencil and colour -- match a render of the same record with
// the WHOLE instance moved by the same transform (the frame the damage was
// always right in), and the unposed body draws exactly as before.
TEST_F(PlatingRenderTest, DamageFollowsAnArticulatedNode) {
    dauntless_plating::g_params[0] = 1.0f;
    const auto cam = quad_cam();
    auto model = body_and_part();
    const glm::vec3 clear(0.8f, 0.2f, 0.8f);

    // Hit node 1 at rest, off its plate's centre so the rotation moves it.
    const glm::vec3 hit_rest(48.0f, 6.0f, 0.0f);
    scenegraph::HullDamageStore ring;
    ASSERT_GE(ring.add(hit_rest, glm::vec3(0.0f), 8.0f, 10.0f,
                       scenegraph::HullDamageKind::Internal, /*node=*/1).index, 0);

    // The pose: 30 degrees about z through the plate's centre, then up 10.
    const glm::mat4 pose =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 10.0f, 0.0f)) *
        glm::translate(glm::mat4(1.0f), glm::vec3(40.0f, 0.0f, 0.0f)) *
        glm::rotate(glm::mat4(1.0f), glm::radians(30.0f), glm::vec3(0.0f, 0.0f, 1.0f)) *
        glm::translate(glm::mat4(1.0f), glm::vec3(-40.0f, 0.0f, 0.0f));
    const glm::vec3 hit_posed = glm::vec3(pose * glm::vec4(hit_rest, 1.0f));

    const Marked rest = render_marked_many(*model, {Placed{glm::mat4(1.0f), ring}}, cam, clear);
    Placed posed_pl{glm::mat4(1.0f), ring};
    posed_pl.overrides[1] = pose;
    const Marked posed = render_marked_many(*model, {posed_pl}, cam, clear);
    // The reference: no override, the whole instance moved by `pose`.
    const Marked moved = render_marked_many(*model, {Placed{pose, ring}}, cam, clear);

    const glm::ivec2 at_rest = to_pixel(cam, hit_rest);
    const glm::ivec2 at_posed = to_pixel(cam, hit_posed);
    auto stencil_at = [](const Marked& m, glm::ivec2 c) {
        return m.stencil[static_cast<std::size_t>(c.y) * kSize + c.x];
    };
    auto is_clear = [](const std::uint8_t* q) {
        return std::abs(q[0] - 204) <= 1 && std::abs(q[1] - 51) <= 1 &&
               std::abs(q[2] - 204) <= 1;
    };
    ASSERT_NE(stencil_at(rest, at_rest), 0) << "no cut at the hit at rest";
    ASSERT_FALSE(is_clear(pixel(rest.color, at_rest.x, at_rest.y))) << "no interior at rest";
    ASSERT_NE(stencil_at(moved, at_posed), 0) << "the reference has no cut at the posed hit";

    // The hole and its interior moved with the node.
    EXPECT_NE(stencil_at(posed, at_posed), 0) << "no cut where the posed hit is";
    EXPECT_FALSE(is_clear(pixel(posed.color, at_posed.x, at_posed.y)))
        << "no interior behind the posed cut";
    EXPECT_EQ(stencil_at(posed, at_rest), 0) << "the cut stayed at the rest position";

    // The part's pixels match the rigidly moved instance (x > 0 in view).
    const int mid_x = to_pixel(cam, glm::vec3(0.0f)).x;
    int stencil_diff = 0;
    for (int y = 0; y < kSize; ++y)
        for (int x = mid_x + 2; x < kSize; ++x)
            if ((posed.stencil[static_cast<std::size_t>(y) * kSize + x] != 0) !=
                (moved.stencil[static_cast<std::size_t>(y) * kSize + x] != 0))
                ++stencil_diff;
    const int worst_part = worst_on_side(posed.color, moved.color, mid_x, /*right=*/true);
    std::fprintf(stderr, "[PlatingRender] articulated: stencil diff %d, worst colour %d\n",
                 stencil_diff, worst_part);
    EXPECT_LE(stencil_diff, 4) << "the posed cut is not the moved instance's cut";
    EXPECT_LE(worst_part, 8) << "the posed part's damage differs from the moved instance's";

    // The unposed body is unchanged.
    EXPECT_EQ(worst_on_side(rest.color, posed.color, mid_x, /*right=*/false), 0);
}

// ── Fix round 1: geometric attribution, frame-compatible records ───────────
namespace {

// One mesh of `quads` (centre, u, v, half), all facing u x v, on `node`.
struct QuadSpec { glm::vec3 centre, u, v; float half; };
void add_mesh_of_quads(assets::Model& model, int node, const std::vector<QuadSpec>& quads) {
    assets::MeshCpu cpu;
    cpu.material_index = 0;
    cpu.node_index = node;
    for (const QuadSpec& q : quads) {
        const glm::vec3 n = glm::normalize(glm::cross(q.u, q.v));
        const auto base = static_cast<std::uint32_t>(cpu.vertices.size());
        for (const auto& ab : {glm::vec2(-1, -1), glm::vec2(1, -1), glm::vec2(1, 1),
                               glm::vec2(-1, 1)}) {
            assets::MeshCpu::Vertex vt;
            vt.position = q.centre + q.u * (ab.x * q.half) + q.v * (ab.y * q.half);
            vt.normal = n;
            vt.uv = 0.5f * (ab + 1.0f);
            cpu.vertices.push_back(vt);
        }
        for (std::uint32_t k : {0u, 1u, 2u, 0u, 2u, 3u}) cpu.indices.push_back(base + k);
    }
    assets::Mesh mesh = assets::upload_mesh(cpu);
    mesh.set_cpu_data(cpu);
    if (model.materials.empty()) {
        assets::Material mat;
        mat.diffuse = glm::vec3(1.0f);
        mat.specular = glm::vec3(0.0f);
        mat.emissive = glm::vec3(0.0f);
        model.materials.push_back(mat);
    }
    model.nodes[static_cast<std::size_t>(node)].meshes.push_back(
        static_cast<int>(model.meshes.size()));
    model.meshes.push_back(std::move(mesh));
}

// Root "body" (0) and a child "part" (1), no meshes yet.
std::unique_ptr<assets::Model> body_and_part_nodes() {
    auto model = std::make_unique<assets::Model>();
    assets::Node body;
    body.name = "body";
    body.children.push_back(1);
    assets::Node part;
    part.name = "part";
    part.parent_index = 0;
    model->nodes.push_back(body);
    model->nodes.push_back(part);
    model->root_node = 0;
    return model;
}

// 30 degrees about z through (40, 0, 0), then up 10: the part's pose.
glm::mat4 part_pose() {
    return glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 10.0f, 0.0f)) *
           glm::translate(glm::mat4(1.0f), glm::vec3(40.0f, 0.0f, 0.0f)) *
           glm::rotate(glm::mat4(1.0f), glm::radians(30.0f), glm::vec3(0.0f, 0.0f, 1.0f)) *
           glm::translate(glm::mat4(1.0f), glm::vec3(-40.0f, 0.0f, 0.0f));
}

// Largest channel difference over the square of half size `r` about `c`.
int worst_in_window(const std::vector<std::uint8_t>& a, const std::vector<std::uint8_t>& b,
                    glm::ivec2 c, int r) {
    int worst = 0;
    for (int y = std::max(0, c.y - r); y <= std::min(kSize - 1, c.y + r); ++y)
        for (int x = std::max(0, c.x - r); x <= std::min(kSize - 1, c.x + r); ++x)
            for (int k = 0; k < 3; ++k)
                worst = std::max(worst, std::abs(int(pixel(a, x, y)[k]) - int(pixel(b, x, y)[k])));
    return worst;
}

}  // namespace

// The LC Intrepid shape: the hull mesh's box ENCLOSES the posed part's mesh,
// so no box rule can find the part. The geometry can: a hit on the posed
// part's surface is the part's (node 1, rest frame), a hit on the hull is the
// body's, and the record drawn from that answer cuts the posed part there.
TEST_F(PlatingRenderTest, PosedHitInsideTheBodyBoxIsAttributedByGeometry) {
    dauntless_plating::g_params[0] = 1.0f;
    auto model = body_and_part_nodes();
    const glm::vec3 X(1, 0, 0), Y(0, 1, 0);
    add_mesh_of_quads(*model, 0, {{glm::vec3(0.0f, 0.0f, -20.0f), X, Y, 70.0f},
                                  {glm::vec3(-65.0f, -65.0f, 20.0f), X, Y, 3.0f}});
    add_mesh_of_quads(*model, 1, {{glm::vec3(40.0f, 0.0f, 0.0f), X, Y, 15.0f}});
    const auto boxes = renderer::mesh_body_aabbs(*model);
    ASSERT_EQ(boxes.size(), 2u);
    for (int a = 0; a < 3; ++a) {
        ASSERT_LE(boxes[0].center[a] - boxes[0].half_extents[a],
                  boxes[1].center[a] - boxes[1].half_extents[a]) << "axis " << a;
        ASSERT_GE(boxes[0].center[a] + boxes[0].half_extents[a],
                  boxes[1].center[a] + boxes[1].half_extents[a]) << "axis " << a;
    }

    const std::unordered_map<int, glm::mat4> overrides{{1, part_pose()}};
    const glm::vec3 hit_rest(48.0f, 6.0f, 0.0f);
    const glm::vec3 hit_posed = glm::vec3(part_pose() * glm::vec4(hit_rest, 1.0f));
    const auto on_part = renderer::attribute_to_rest_frame(*model, overrides, hit_posed);
    EXPECT_EQ(on_part.node, 1);
    EXPECT_LT(on_part.distance, 1e-3f);
    const glm::vec3 rest = glm::vec3(on_part.to_rest * glm::vec4(hit_posed, 1.0f));
    EXPECT_NEAR(glm::length(rest - hit_rest), 0.0f, 1e-3f);

    const glm::vec3 on_hull(-30.0f, -40.0f, -20.0f);
    const auto on_body = renderer::attribute_to_rest_frame(*model, overrides, on_hull);
    EXPECT_EQ(on_body.node, -1);
    EXPECT_EQ(on_body.to_rest, glm::mat4(1.0f));
    EXPECT_EQ(renderer::attribute_to_rest_frame(*model, {}, hit_posed).node, -1)
        << "no overrides: the body, no work";

    scenegraph::HullDamageStore ring;
    ring.add(rest, glm::vec3(0.0f), 8.0f, 10.0f, scenegraph::HullDamageKind::Internal,
             on_part.node);
    Placed pl{glm::mat4(1.0f), ring};
    pl.overrides = overrides;
    const auto cam = quad_cam();
    const Marked r = render_marked_many(*model, {pl}, cam, glm::vec3(0.8f, 0.2f, 0.8f));
    const glm::ivec2 c = to_pixel(cam, hit_posed);
    EXPECT_NE(r.stencil[static_cast<std::size_t>(c.y) * kSize + c.x], 0)
        << "the attributed hit does not cut the posed part";
}

// Once a part is posed, a record is only kept for meshes in its own frame
// (same rest correction): the part's record leaves no ghost on the hull under
// the part's rest spot, and a hull record there does not ride on the part.
TEST_F(PlatingRenderTest, ArticulatedRecordsStayInTheirOwnFrame) {
    dauntless_plating::g_params[0] = 1.0f;
    auto model = body_and_part_nodes();
    const glm::vec3 X(1, 0, 0), Y(0, 1, 0);
    add_mesh_of_quads(*model, 0, {{glm::vec3(40.0f, 0.0f, -1.0f), X, Y, 20.0f}});
    add_mesh_of_quads(*model, 0, {{glm::vec3(-40.0f, 0.0f, -1.0f), X, Y, 20.0f}});
    add_mesh_of_quads(*model, 1, {{glm::vec3(40.0f, 0.0f, 0.0f), X, Y, 15.0f}});
    // The part moves off its rest spot to sit over the other hull plate.
    Placed undamaged{glm::mat4(1.0f), scenegraph::HullDamageStore{}};
    undamaged.overrides[1] = glm::translate(glm::mat4(1.0f), glm::vec3(-80.0f, 0.0f, 1.0f));
    const auto cam = quad_cam();
    const glm::vec3 clear(0.8f, 0.2f, 0.8f);
    const Marked base = render_marked_many(*model, {undamaged}, cam, clear);
    const glm::ivec2 rest_spot = to_pixel(cam, glm::vec3(40.0f, 0.0f, -1.0f));
    const glm::ivec2 part_now = to_pixel(cam, glm::vec3(-40.0f, 0.0f, 1.0f));
    auto stencil_at = [](const Marked& m, glm::ivec2 c) {
        return m.stencil[static_cast<std::size_t>(c.y) * kSize + c.x];
    };

    // The part's record: cuts the part where it is, nothing on the hull.
    Placed part_hit = undamaged;
    part_hit.ring.add({40.0f, 0.0f, 0.0f}, glm::vec3(0.0f), 8.0f, 10.0f,
                      scenegraph::HullDamageKind::Internal, 1);
    const Marked a = render_marked_many(*model, {part_hit}, cam, clear);
    EXPECT_NE(stencil_at(a, part_now), 0) << "the part's record does not cut the part";
    EXPECT_EQ(stencil_at(a, rest_spot), 0) << "the part's record cut the hull";
    EXPECT_LE(worst_in_window(a.color, base.color, rest_spot, 12), 2)
        << "the part's record damaged the hull under its rest spot";

    // A hull record at the part's rest spot: cuts the hull, not the part.
    Placed hull_hit = undamaged;
    hull_hit.ring.add({40.0f, 0.0f, -1.0f}, glm::vec3(0.0f), 8.0f, 10.0f,
                      scenegraph::HullDamageKind::Internal, -1);
    const Marked b = render_marked_many(*model, {hull_hit}, cam, clear);
    EXPECT_NE(stencil_at(b, rest_spot), 0) << "the hull record does not cut the hull";
    EXPECT_EQ(stencil_at(b, part_now), 0) << "the hull record rides on the posed part";
    EXPECT_LE(worst_in_window(b.color, base.color, part_now, 12), 2)
        << "the hull record damaged the posed part";

    // The interior behind the part's hole reads only the part's records: with
    // a deck break neither record reaches alone, the hull record at the part's
    // rest spot must not add its wear and blow the part's hole through.
    dauntless_plating::g_params[24] = 15.0f;
    Placed both = part_hit;
    both.ring.add({40.0f, 0.0f, -1.0f}, glm::vec3(0.0f), 8.0f, 10.0f,
                  scenegraph::HullDamageKind::Internal, -1);
    const Marked c = render_marked_many(*model, {both}, cam, clear);
    const std::uint8_t* q = pixel(c.color, part_now.x, part_now.y);
    std::fprintf(stderr, "[PlatingRender] part hole interior (%d,%d,%d)\n", q[0], q[1], q[2]);
    ASSERT_NE(stencil_at(c, part_now), 0);
    EXPECT_FALSE(std::abs(q[0] - 204) <= 1 && std::abs(q[1] - 51) <= 1 &&
                 std::abs(q[2] - 204) <= 1)
        << "the hull record's wear blew the part's hole through";
    const Marked solo = render_marked_many(*model, {part_hit}, cam, clear);
    EXPECT_LE(worst_in_window(c.color, solo.color, part_now, 6), 2)
        << "the part's hole interior changed with a hull record in another frame";
}

// Fix round 2: an AUTHORED (rest-frame) volume is attributed in REST space
// -- the nearest rest triangle, no posed correction -- to that triangle's own
// node. Added at rest (no overrides, as at mission init), it keeps its part:
// once the part is posed the damage shows on the part where it is drawn and
// not on the hull under its rest spot.
TEST_F(PlatingRenderTest, AuthoredRecordOnAPartFollowsItWhenPosed) {
    dauntless_plating::g_params[0] = 1.0f;
    auto model = body_and_part_nodes();
    const glm::vec3 X(1, 0, 0), Y(0, 1, 0);
    add_mesh_of_quads(*model, 0, {{glm::vec3(40.0f, 0.0f, -1.0f), X, Y, 20.0f}});
    add_mesh_of_quads(*model, 0, {{glm::vec3(-40.0f, 0.0f, -1.0f), X, Y, 20.0f}});
    add_mesh_of_quads(*model, 1, {{glm::vec3(40.0f, 0.0f, 0.0f), X, Y, 15.0f}});

    // Authored just above the part (nearer it than the hull plate under it).
    const glm::vec3 authored(44.0f, 3.0f, 0.2f);
    const auto at_rest = renderer::attribute_rest_point(*model, {}, authored);
    EXPECT_EQ(at_rest.node, 1) << "no overrides yet: still the part's own node";
    EXPECT_EQ(at_rest.to_rest, glm::mat4(1.0f)) << "already rest-frame: no conversion";
    const std::unordered_map<int, glm::mat4> moved{
        {1, glm::translate(glm::mat4(1.0f), glm::vec3(-80.0f, 0.0f, 1.0f))}};
    EXPECT_EQ(renderer::attribute_rest_point(*model, moved, authored).node, 1)
        << "a posed part does not change a rest-space answer";
    EXPECT_EQ(renderer::attribute_rest_point(*model, {}, glm::vec3(-40.0f, 5.0f, -1.0f)).node, 0)
        << "on the hull plate: the hull's node";

    Placed pl{glm::mat4(1.0f), scenegraph::HullDamageStore{}};
    pl.ring.add(authored, glm::vec3(0.0f), 8.0f, 10.0f, scenegraph::HullDamageKind::Internal,
                at_rest.node);
    pl.overrides = moved;
    Placed undamaged{glm::mat4(1.0f), scenegraph::HullDamageStore{}};
    undamaged.overrides = moved;
    const auto cam = quad_cam();
    const glm::vec3 clear(0.8f, 0.2f, 0.8f);
    const Marked r = render_marked_many(*model, {pl}, cam, clear);
    const Marked base = render_marked_many(*model, {undamaged}, cam, clear);
    const glm::ivec2 part_now = to_pixel(cam, authored + glm::vec3(-80.0f, 0.0f, 1.0f));
    const glm::ivec2 rest_spot = to_pixel(cam, glm::vec3(44.0f, 3.0f, -1.0f));
    EXPECT_NE(r.stencil[static_cast<std::size_t>(part_now.y) * kSize + part_now.x], 0)
        << "the authored damage left the posed part";
    EXPECT_EQ(r.stencil[static_cast<std::size_t>(rest_spot.y) * kSize + rest_spot.x], 0)
        << "the authored damage stayed on the hull under the part's rest spot";
    EXPECT_LE(worst_in_window(r.color, base.color, rest_spot, 12), 2);
}

// Fix round 3: the frame filter compares POSED OWNERS, not correction
// matrices. The part's mesh hangs under a CHILD node with a non-identity
// local, whose rest correction is computed separately from its posed owner's
// and differs from it in the low bits. A record attributed while posed (on
// the owner, node 1) and one attributed at the identity pose of a rigged
// ship (on the triangle's own node, 2) both stay on the part once it is
// posed.
TEST_F(PlatingRenderTest, DamageOnAChildOfAPosedPartStaysOnThePart) {
    dauntless_plating::g_params[0] = 1.0f;
    auto model = body_and_part_nodes();
    assets::Node child;
    child.name = "part mesh";
    child.parent_index = 1;
    child.local_transform =
        glm::translate(glm::mat4(1.0f), glm::vec3(40.0f, 0.0f, 0.0f)) *
        glm::rotate(glm::mat4(1.0f), glm::radians(23.0f), glm::vec3(0.0f, 0.0f, 1.0f));
    model->nodes[1].children.push_back(2);
    model->nodes.push_back(child);
    const glm::vec3 X(1, 0, 0), Y(0, 1, 0);
    add_mesh_of_quads(*model, 0, {{glm::vec3(-40.0f, 0.0f, -1.0f), X, Y, 20.0f}});
    add_mesh_of_quads(*model, 2, {{glm::vec3(0.0f), X, Y, 15.0f}});

    const glm::mat4 pose =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 10.0f, 0.0f)) *
        glm::translate(glm::mat4(1.0f), glm::vec3(40.0f, 0.0f, 0.0f)) *
        glm::rotate(glm::mat4(1.0f), glm::radians(37.0f), glm::vec3(0.0f, 0.0f, 1.0f)) *
        glm::translate(glm::mat4(1.0f), glm::vec3(-40.0f, 0.0f, 0.0f));
    const std::unordered_map<int, glm::mat4> overrides{{1, pose}};
    const auto fix = renderer::rest_corrections(*model, overrides);
    std::fprintf(stderr, "[PlatingRender] child fix == owner fix: %d\n", fix[2] == fix[1] ? 1 : 0);

    const glm::mat4 child_rest = child.local_transform;
    const glm::vec3 hit_a_rest = glm::vec3(child_rest * glm::vec4(6.0f, 5.0f, 0.0f, 1.0f));
    const glm::vec3 hit_b_rest = glm::vec3(child_rest * glm::vec4(-7.0f, -6.0f, 0.0f, 1.0f));
    const glm::vec3 hit_a_posed = glm::vec3(pose * glm::vec4(hit_a_rest, 1.0f));
    const glm::vec3 hit_b_posed = glm::vec3(pose * glm::vec4(hit_b_rest, 1.0f));

    // (a) hit while posed: the owner (1), converted to rest.
    const auto a = renderer::attribute_to_rest_frame(*model, overrides, hit_a_posed);
    ASSERT_EQ(a.node, 1);
    // (b) hit at the identity pose of a rigged ship: the triangle's node (2).
    const auto b = renderer::attribute_rest_point(*model, {}, hit_b_rest);
    ASSERT_EQ(b.node, 2);

    scenegraph::HullDamageStore ring;
    ring.add(glm::vec3(a.to_rest * glm::vec4(hit_a_posed, 1.0f)), glm::vec3(0.0f), 4.0f, 10.0f,
             scenegraph::HullDamageKind::Internal, a.node);
    ring.add(hit_b_rest, glm::vec3(0.0f), 4.0f, 10.0f, scenegraph::HullDamageKind::Internal,
             b.node);
    Placed pl{glm::mat4(1.0f), ring};
    pl.overrides = overrides;
    const auto cam = quad_cam();
    const Marked r = render_marked_many(*model, {pl}, cam, glm::vec3(0.8f, 0.2f, 0.8f));
    auto stencil_at = [&](const glm::vec3& p) {
        const glm::ivec2 c = to_pixel(cam, p);
        return r.stencil[static_cast<std::size_t>(c.y) * kSize + c.x];
    };
    EXPECT_NE(stencil_at(hit_a_posed), 0) << "the posed-time record left its part";
    EXPECT_NE(stencil_at(hit_b_posed), 0) << "the identity-pose record left its part";
}

// ── Molten rims on fresh tears (layered damage phase 4 §2.3) ───────────────
namespace {

// Redness (red minus blue) gained from `cold` to `hot`, the largest over the
// square of half size `r` about `c`, and where.
struct RednessGain { int gain = -1000; glm::ivec2 at{-1}; };
RednessGain redness_gain(const std::vector<std::uint8_t>& hot,
                         const std::vector<std::uint8_t>& cold, glm::ivec2 c, int r) {
    RednessGain g;
    for (int y = std::max(0, c.y - r); y <= std::min(kSize - 1, c.y + r); ++y)
        for (int x = std::max(0, c.x - r); x <= std::min(kSize - 1, c.x + r); ++x) {
            const std::uint8_t* h = pixel(hot, x, y);
            const std::uint8_t* k = pixel(cold, x, y);
            const int d = (int(h[0]) - int(h[2])) - (int(k[0]) - int(k[2]));
            if (d > g.gain) { g.gain = d; g.at = glm::ivec2(x, y); }
        }
    return g;
}

// A breach event at `centre` (rest frame of `node`, posed body `posed`),
// radius `r`, born `age` seconds before kDecalTime.
scenegraph::BreachEventRing breach_at(const glm::vec3& centre, float r, float age,
                                      int node = -1,
                                      std::optional<glm::vec3> posed = std::nullopt) {
    scenegraph::BreachEventRing ring;
    ring.push(posed.value_or(centre), r, glm::vec3(0.0f, 0.0f, 1.0f), kDecalTime - age, 1u,
              node, centre);
    return ring;
}

}  // namespace

// A tear just made glows molten at its rim; the same tear kRimLife + 1 s
// later does not. Same pixels, same damage: only the event's age differs.
// The interior is off, so the glow is the plating draw's torn rim
// (HullInteriorTest.FreshTearHeatsTheCharEdge covers the interior's).
TEST_F(PlatingRenderTest, FreshTearRimGlows) {
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 0.0f;   // no interior
    auto model = build_quad(30.0f, /*facing_camera=*/true);
    const auto cam = quad_cam();
    const glm::vec3 hit(0.0f, 0.0f, 0.0f);
    const float reach = 8.0f, r = 0.5f * reach;
    Placed pl{glm::mat4(1.0f), internal_ring(hit, reach, 10.0f)};
    pl.breach = breach_at(hit, r, 0.0f);
    const Marked fresh = render_marked_many(*model, {pl}, cam);
    pl.breach = breach_at(hit, r, scenegraph::kRimLife + 1.0f);
    const Marked old = render_marked_many(*model, {pl}, cam);

    const glm::ivec2 c = to_pixel(cam, hit);
    // 3r (the heat's outer edge) plus a model unit, in pixels.
    const int reach_px = to_pixel(cam, hit + glm::vec3(3.0f * r + 1.0f, 0.0f, 0.0f)).x - c.x;
    const auto g = redness_gain(fresh.color, old.color, c, kSize / 2);
    std::fprintf(stderr, "[PlatingRender] fresh rim: redness gain %d at (%d,%d), centre (%d,%d), "
                 "3r = %d px\n", g.gain, g.at.x, g.at.y, c.x, c.y, reach_px);
    EXPECT_GE(g.gain, 40) << "a fresh tear's rim is not molten";
    EXPECT_LE(glm::length(glm::vec2(g.at - c)), float(reach_px) * 1.415f)
        << "the glow is not at the tear";
}

// A tear older than kRimLife is cold: its frame is the frame with no event.
TEST_F(PlatingRenderTest, OldTearsStayCold) {
    dauntless_plating::g_params[0] = 1.0f;
    auto model = build_quad(30.0f, /*facing_camera=*/true);
    const auto cam = quad_cam();
    const glm::vec3 hit(0.0f, 0.0f, 0.0f);
    Placed pl{glm::mat4(1.0f), internal_ring(hit, 8.0f, 10.0f)};
    const Marked none = render_marked_many(*model, {pl}, cam);
    pl.breach = breach_at(hit, 4.0f, scenegraph::kRimLife + 0.01f);
    const Marked old = render_marked_many(*model, {pl}, cam);
    int worst = 0;
    for (std::size_t i = 0; i < none.color.size(); ++i)
        worst = std::max(worst, std::abs(int(none.color[i]) - int(old.color[i])));
    EXPECT_LE(worst, 1) << "a cold tear still changes the frame";
}

// A rim on a POSED part glows on the part where it is drawn: the event is
// uploaded in the part's rest frame and only to the part's meshes. The part
// (node 1, rest at x = +40) is moved over the other hull plate (x = -40);
// the hull also has a tear of its own under the part's rest spot, which the
// part's rim must not heat. Interior off, as in FreshTearRimGlows.
TEST_F(PlatingRenderTest, FreshRimOnAPosedPartGlowsOnThePart) {
    dauntless_plating::g_params[0] = 1.0f;
    dauntless_plating::g_params[25] = 0.0f;   // no interior: the plating draw's rim
    auto model = body_and_part_nodes();
    const glm::vec3 X(1, 0, 0), Y(0, 1, 0);
    add_mesh_of_quads(*model, 0, {{glm::vec3(40.0f, 0.0f, -1.0f), X, Y, 20.0f}});
    add_mesh_of_quads(*model, 0, {{glm::vec3(-40.0f, 0.0f, -1.0f), X, Y, 20.0f}});
    add_mesh_of_quads(*model, 1, {{glm::vec3(40.0f, 0.0f, 0.0f), X, Y, 15.0f}});
    const glm::mat4 pose = glm::translate(glm::mat4(1.0f), glm::vec3(-80.0f, 0.0f, 1.0f));
    const glm::vec3 part_rest(40.0f, 0.0f, 0.0f), hull_tear(40.0f, 0.0f, -1.0f);
    const glm::vec3 part_posed = glm::vec3(pose * glm::vec4(part_rest, 1.0f));
    const float reach = 8.0f, r = 0.5f * reach;

    Placed pl{glm::mat4(1.0f), scenegraph::HullDamageStore{}};
    pl.overrides[1] = pose;
    pl.ring.add(part_rest, glm::vec3(0.0f), reach, 10.0f, scenegraph::HullDamageKind::Internal, 1);
    pl.ring.add(hull_tear, glm::vec3(0.0f), reach, 10.0f, scenegraph::HullDamageKind::Internal, -1);
    const auto cam = quad_cam();
    const glm::vec3 clear(0.8f, 0.2f, 0.8f);
    pl.breach = breach_at(part_rest, r, 0.0f, /*node=*/1, part_posed);
    const Marked fresh = render_marked_many(*model, {pl}, cam, clear);
    pl.breach = breach_at(part_rest, r, scenegraph::kRimLife + 1.0f, 1, part_posed);
    const Marked old = render_marked_many(*model, {pl}, cam, clear);

    const glm::ivec2 on_part = to_pixel(cam, part_posed);
    const glm::ivec2 rest_spot = to_pixel(cam, hull_tear);
    const int win = to_pixel(cam, part_posed + glm::vec3(3.0f * r + 1.0f, 0.0f, 0.0f)).x - on_part.x;
    const auto part = redness_gain(fresh.color, old.color, on_part, win);
    const auto hull = redness_gain(fresh.color, old.color, rest_spot, win);
    std::fprintf(stderr, "[PlatingRender] posed rim: part gain %d, hull (rest spot) gain %d\n",
                 part.gain, hull.gain);
    EXPECT_GE(part.gain, 40) << "the posed part's fresh tear does not glow on the part";
    EXPECT_LE(worst_in_window(fresh.color, old.color, rest_spot, win), 1)
        << "the part's rim heated the hull under its rest spot";
}
