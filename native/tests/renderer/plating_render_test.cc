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
#include <thread>
#include <unordered_map>
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
    // FrameSubmitter::set_plating_record_culling for every render: off = the
    // whole list on every mesh and the whole list as the deck-break set.
    bool record_culling = true;

    // Every uniform the lean mark must set or neutralise, set to a value that
    // changes which fragments survive (or what p_body is).
    void poison_plating_program() {
        renderer::Shader& s = p->plating_shader();
        s.use();
        s.set_int("u_coverage_cutout", 1);
        s.set_int("u_carve_invert", 1);
        s.set_int("u_carve_enabled", 1);
        s.set_int("u_carve_count", 3);
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
                                         nullptr) {
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(&model));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.get(iid)->hull_damage = ring;
        if (decals != nullptr) world.get(iid)->decals = *decals;
        if (overrides != nullptr) world.get(iid)->node_overrides = *overrides;
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
    };
    struct Placed {
        glm::mat4 world;
        scenegraph::HullDamageStore ring;
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

// Two records on the quad at x = -40 (reach 10 and 4, 7 mu apart: not merged).
scenegraph::HullDamageStore left_quad_ring() {
    scenegraph::HullDamageStore s;
    s.add({-40.0f, 0.0f, 0.0f}, glm::vec3(0.0f), 10.0f, 10.0f,
          scenegraph::HullDamageKind::Internal);
    s.add({-45.0f, 5.0f, 0.0f}, glm::vec3(0.0f), 4.0f, 2.0f,
          scenegraph::HullDamageKind::Internal);
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

// Per mesh, only the records near that mesh are uploaded: the quad far from
// every record gets u_dmg_count 0, the damaged one both records. Read back
// from GL after the draw, so the LAST mesh drawn is the one observed. The
// marking draw does the same.
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
    EXPECT_EQ(plating_dmg_count(), 0) << "the far quad uploaded records it never reaches";
    const auto stock = render(*undamaged_last, scenegraph::HullDamageStore{}, cam, true);
    const glm::ivec2 far_c = to_pixel(cam, glm::vec3(40.0f, 0.0f, 0.0f));
    EXPECT_EQ(rgb_diff(pixel(px, far_c.x, far_c.y), pixel(stock, far_c.x, far_c.y)), 0);

    const auto r = render_marked(*undamaged_last, ring, cam);
    EXPECT_EQ(r.marks, 1);
    EXPECT_EQ(plating_dmg_count(), 0) << "the mark uploaded records the far quad never reaches";
}

// With node overrides (an articulated hull) the rest-pose boxes no longer
// bound the posed meshes: every mesh gets the whole list.
TEST_F(PlatingRenderTest, ArticulatedDrawUsesFullList) {
    dauntless_plating::g_params[0] = 1.0f;
    const auto cam = quad_cam();
    auto model = two_quads(-40.0f);          // mesh 1 = the far quad
    const std::unordered_map<int, glm::mat4> overrides{{0, model->nodes[0].local_transform}};
    render(*model, left_quad_ring(), cam, false, nullptr, &overrides);
    EXPECT_EQ(plating_dmg_count(), 2);
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
        for (std::size_t k = 0; k < boxes.size(); ++k)
            std::fprintf(stderr, "[PlatingRender] mesh %zu half=(%.0f,%.0f,%.0f) records %d/%d\n",
                         k, boxes[k].half_extents.x, boxes[k].half_extents.y,
                         boxes[k].half_extents.z,
                         renderer::plating::records_near(
                             list, boxes[k],
                             renderer::plating::plating_margin(dauntless_plating::g_params), idx),
                         list.count);
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
