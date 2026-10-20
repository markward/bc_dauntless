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

#include "support/content_root.h"

namespace dauntless_plating { extern float g_params[24]; }

namespace fs = std::filesystem;

namespace {

constexpr int kSize = 256;
// Past every flicker (FLICKER_DUR_MAX 60 s) and ember (tau ~3.1 s) of a
// record born at 0, so the stock decal loop adds nothing outside a record's
// own radius and the far-pixel comparison isolates the plating layer.
constexpr float kDecalTime = 1000.0f;

fs::path ambassador_dir() {
    return test_support::game_root() / "data/Models/Ships/Ambassador";
}
fs::path ambassador_nif() { return ambassador_dir() / "Ambassador.nif"; }
std::vector<fs::path> ambassador_search() {
    return {ambassador_dir() / "High",
            test_support::game_root() / "data/Models/SharedTextures/FedShips/High"};
}

renderer::Lighting test_lighting() {
    renderer::Lighting l;
    l.ambient = glm::vec3(0.6f);
    l.directional_count = 1;
    l.directional_dir_ws[0] = glm::normalize(glm::vec3(0.3f, 0.2f, -1.0f));
    l.directional_color[0] = glm::vec3(0.8f);
    return l;
}

const std::uint8_t* pixel(const std::vector<std::uint8_t>& px, int x, int y) {
    return &px[(static_cast<std::size_t>(y) * kSize + x) * 4];
}

int rgb_diff(const std::uint8_t* a, const std::uint8_t* b) {
    return std::abs(a[0] - b[0]) + std::abs(a[1] - b[1]) + std::abs(a[2] - b[2]);
}

int count_non_black(const std::vector<std::uint8_t>& px) {
    int n = 0;
    for (std::size_t i = 0; i + 3 < px.size(); i += 4)
        if (px[i] + px[i + 1] + px[i + 2] > 6) ++n;
    return n;
}

// A flat quad in the z = 0 plane, half size `half`, with no textures (the
// draw binds the white fallback). `facing_camera` winds it CCW seen from +z
// (front-facing for a camera above it); otherwise CW (a back face).
std::unique_ptr<assets::Model> build_quad(float half, bool facing_camera) {
    auto model = std::make_unique<assets::Model>();
    assets::MeshCpu cpu;
    cpu.material_index = 0;
    cpu.node_index = 0;
    const glm::vec3 n(0.0f, 0.0f, facing_camera ? 1.0f : -1.0f);
    auto push = [&](float x, float y, float u, float v) {
        assets::MeshCpu::Vertex vt;
        vt.position = glm::vec3(x, y, 0.0f);
        vt.normal = n;
        vt.uv = glm::vec2(u, v);
        cpu.vertices.push_back(vt);
    };
    push(-half, -half, 0.0f, 0.0f);
    push( half, -half, 1.0f, 0.0f);
    push( half,  half, 1.0f, 1.0f);
    push(-half,  half, 0.0f, 1.0f);
    if (facing_camera) cpu.indices = {0, 1, 2, 0, 2, 3};
    else               cpu.indices = {0, 2, 1, 0, 3, 2};
    assets::Mesh mesh = assets::upload_mesh(cpu);
    mesh.set_cpu_data(cpu);
    model->meshes.push_back(std::move(mesh));

    assets::Material mat;
    mat.diffuse = glm::vec3(1.0f);
    mat.specular = glm::vec3(0.0f);
    mat.emissive = glm::vec3(0.0f);
    model->materials.push_back(mat);

    assets::Node node;
    node.name = "plating_probe_quad";
    node.meshes = {0};
    model->nodes.push_back(node);
    model->root_node = 0;
    return model;
}

class PlatingRenderTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<assets::AssetCache> cache;
    std::array<float, 24> saved_params{};

    void SetUp() override {
        std::copy(dauntless_plating::g_params, dauntless_plating::g_params + 24,
                  saved_params.begin());
        try {
            w = std::make_unique<renderer::Window>(kSize, kSize, "plating-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        assets::AssetCache::Config cfg;
        cfg.keep_cpu_data = true;  // compute_model_aabb + ray_trace read CPU data
        cfg.mesh_fix_dir = [] {
            return fs::path(OPEN_STBC_PROJECT_ROOT) / "native/assets/mesh_fixes";
        };
        cache = std::make_unique<assets::AssetCache>(cfg);
    }

    void TearDown() override {
        std::copy(saved_params.begin(), saved_params.end(), dauntless_plating::g_params);
        if (!w) return;
        cache.reset();
        renderer::reset_damage_decal_texture();
        renderer::reset_scuff_normal_texture();
        renderer::reset_decal_mask_sampler();
        renderer::reset_model_radius_cache();
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

    // Window pixel (row 0 = bottom) of a world point.
    static glm::ivec2 to_pixel(const scenegraph::Camera& cam, const glm::vec3& p) {
        const glm::vec4 c = cam.proj_matrix() * cam.view_matrix() * glm::vec4(p, 1.0f);
        const glm::vec2 ndc = glm::vec2(c) / c.w;
        return glm::ivec2(static_cast<int>(std::floor((ndc.x * 0.5f + 0.5f) * kSize)),
                          static_cast<int>(std::floor((ndc.y * 0.5f + 0.5f) * kSize)));
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

    static scenegraph::DamageDecalRing internal_ring(const glm::vec3& at, float radius,
                                                    float wear) {
        scenegraph::DamageDecalRing ring;
        ring.add(at, glm::vec3(0.0f, 0.0f, 1.0f), radius, 1.0f,
                 scenegraph::WeaponClass::Internal, 0.0f, glm::vec3(0.0f), wear);
        return ring;
    }
};

}  // namespace

// The selection rule itself: plating enabled AND at least one listed record.
TEST_F(PlatingRenderTest, WantsPlatingNeedsEnabledAndAListedRecord) {
    std::array<float, 24> params{};
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

// A back face far from every listed record is dropped even though the
// damaged (torn-possible) draw is double-sided; and a front face there still
// draws. The record sits 500 mu away, so it reaches no quad pixel.
TEST_F(PlatingRenderTest, FarBackFaceIsDiscarded) {
    dauntless_plating::g_params[0] = 1.0f;
    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 0.0f, 120.0f);
    cam.target = glm::vec3(0.0f);
    cam.up = glm::vec3(0.0f, 1.0f, 0.0f);
    cam.aspect = 1.0f;
    const auto ring = internal_ring({500.0f, 0.0f, 0.0f}, 30.0f, 10.0f);
    ASSERT_TRUE(renderer::plating::build_damage_list(
                    ring, dauntless_plating::g_params).torn_possible);

    auto front = build_quad(20.0f, /*facing_camera=*/true);
    const int front_px = count_non_black(render(*front, ring, cam));
    auto back = build_quad(20.0f, /*facing_camera=*/false);
    const int back_px = count_non_black(render(*back, ring, cam));
    std::fprintf(stderr, "[PlatingRender] quad front=%d back=%d lit pixels\n",
                 front_px, back_px);
    ASSERT_GT(front_px, 1000) << "the probe quad does not render at all";
    EXPECT_EQ(back_px, 0) << "a far back face drew in a double-sided draw";
}
