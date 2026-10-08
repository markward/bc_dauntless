// native/tests/renderer/planet_detail_bench_test.cc
//
// Performance bench for planet surface detail (spec docs/superpowers/specs/
// 2026-10-08-planet-surface-detail-design.md §8 "Performance"). Drives the
// REAL PlanetDetailPass::update (the bake) and a REAL draw of the target
// through the planet_ program, at full screen resolution, over a scripted
// camera path that mirrors the throwaway GPU spike this bench productionises
// (cold start, steady state, three speeds, and a hard re-anchor).
//
// Bake and draw cannot share one GL_TIME_ELAPSED query (only one may be
// active at a time), so each gets its own query, read back with a blocking
// glGetQueryObjectui64v -- fine for a bench, wrong for the production
// profiler (see frame_timer.h).
//
// Gating mirrors rock_near_bench_test.cc: this REPORTS unconditionally, and
// asserts budgets only when the driver actually has a GL_TIME_ELAPSED
// counter (Apple's GL-over-Metal: GL_TIMESTAMP is 0 bits, GL_TIME_ELAPSED is
// 32 -- see frame_timer.h). With 0 bits every query reads back 0 ns and a
// budget assert would pass vacuously, which is worse than not asserting.
#include <gtest/gtest.h>

#include <renderer/frame.h>
#include <renderer/hdr_target.h>
#include <renderer/pipeline.h>
#include <renderer/planet_detail_noise.h>
#include <renderer/planet_detail_pass.h>
#include <renderer/planet_detail_uniforms.h>
#include <renderer/scuff_texture.h>
#include <renderer/window.h>

#include <glad/glad.h>

#include <glm/gtc/matrix_transform.hpp>

#include <scenegraph/camera.h>
#include <scenegraph/world.h>

#include <assets/cache.h>
#include <assets/model.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

#include "support/content_root.h"

namespace {

namespace pd = renderer::planet_detail;
using test_support::game_root;

const std::filesystem::path kEnvDir = game_root() / "data" / "Models" / "Environment";
const std::filesystem::path kIcePlanetNif = kEnvDir / "IcePlanet.NIF";

constexpr int kWinSize = 64;      // GL context only -- real draws go to hdr_
constexpr int kFbW = 3840, kFbH = 1200;
constexpr float kScale = 40.0f;   // IcePlanet r 90.0099 -> R ~3600 GU
constexpr float kAlt = 270.0f, kTiltDeg = 15.0f;
constexpr double kHz = 60.0;

renderer::FrameSubmitter::ModelLookup handle_lookup() {
    return [](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h);
    };
}

glm::vec3 dir_for_lon_lat(float lon_deg, float lat_deg) {
    const float lo = glm::radians(lon_deg), la = glm::radians(lat_deg);
    return glm::vec3(std::cos(la) * std::cos(lo), std::cos(la) * std::sin(lo), std::sin(la));
}

// Camera `alt` GU above the surface point at anchor-plane coords (cx, cy),
// tilted `tilt_deg` off the local vertical toward the plane's north -- the
// spike's camera path (clip.cc), not a pure nadir look.
scenegraph::Camera cam_for(const pd::Anchor& anchor, float cx, float cy, float R, float alt,
                          float tilt_deg) {
    const glm::vec3 dir = glm::normalize(pd::from_plane(anchor, glm::vec2(cx, cy)));
    const glm::vec3 world_z(0.0f, 0.0f, 1.0f);
    glm::vec3 east = glm::cross(world_z, dir);
    east = glm::length(east) > 1e-3f ? glm::normalize(east)
                                      : glm::normalize(glm::cross(dir, glm::vec3(0, 1, 0)));
    const glm::vec3 north = glm::cross(dir, east);
    const float tilt = glm::radians(tilt_deg);
    const glm::vec3 fwd = -dir * std::cos(tilt) + north * std::sin(tilt);
    const glm::vec3 camup = north * std::cos(tilt) + dir * std::sin(tilt);

    scenegraph::Camera cam;
    cam.eye = dir * (R + alt);
    cam.target = cam.eye + fwd;
    cam.up = camup;
    cam.fov_y_rad = glm::radians(30.0f);   // matches the spike's tan(15 deg) half-angle
    cam.aspect = static_cast<float>(kFbW) / static_cast<float>(kFbH);
    cam.near = 1.0f;
    cam.far = 1.0e6f;
    return cam;
}

double percentile(std::vector<double> v, double pct) {
    std::sort(v.begin(), v.end());
    const std::size_t idx =
        std::min(v.size() - 1, static_cast<std::size_t>(static_cast<double>(v.size()) * pct / 100.0));
    return v[idx];
}

std::string stat_string(std::vector<double> v) {
    std::sort(v.begin(), v.end());
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%6.3f/%6.3f/%6.3f", v[v.size() / 2], v[v.size() * 95 / 100],
                  v.back());
    return std::string(buf);
}

class PlanetDetailBenchTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<assets::AssetCache> cache;
    assets::ModelHandle geo;

    void SetUp() override {
        if (!std::filesystem::is_regular_file(kIcePlanetNif)) {
            GTEST_SKIP() << "BC asset not available at " << kIcePlanetNif;
        }
        try {
            w = std::make_unique<renderer::Window>(kWinSize, kWinSize, "planet-detail-bench", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        assets::AssetCache::Config cfg;
        cfg.keep_cpu_data = true;
        cache = std::make_unique<assets::AssetCache>(cfg);
        geo = cache->load(kIcePlanetNif, std::vector<std::filesystem::path>{kEnvDir}, {}, {}, 1.0f,
                          /*geosphere=*/true);
        ASSERT_TRUE(geo->sphere_map.has_value());
        pd::reset_live_params();
    }

    void TearDown() override {
        pd::reset_live_params();
        if (!w) return;
        renderer::reset_damage_decal_texture();
        renderer::reset_scuff_normal_texture();
        renderer::reset_decal_mask_sampler();
        renderer::reset_model_radius_cache();
    }
};

// Spec §8: full-screen bake and sampling cost over a scripted camera path
// (cold start, steady state, orbit/fast/dash speeds, and a hard re-anchor).
// REPORTS the table unconditionally; ASSERTS the budgets only when the
// driver exposes a real GL_TIME_ELAPSED counter.
TEST_F(PlanetDetailBenchTest, FullScreenBakeAndSamplingBudget) {
    scenegraph::World world;
    const float R = geo->sphere_map->radius * kScale;
    const auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(geo.get()));
    world.set_world_transform(iid, glm::scale(glm::mat4(1.0f), glm::vec3(kScale)));
    scenegraph::Instance::Surface surf;
    surf.type = static_cast<int>(pd::SurfaceType::Rocky);
    surf.seed = 7;
    world.set_surface(iid, surf);

    pd::PlanetDetailPass pass;

    renderer::HdrTarget hdr;
    hdr.resize(kFbW, kFbH);

    renderer::Lighting lighting;
    lighting.ambient = glm::vec3(0.05f);
    lighting.directional_count = 1;
    lighting.directional_dir_ws[0] = glm::normalize(glm::vec3(0.4f, 0.3f, 0.85f));
    lighting.directional_color[0] = glm::vec3(1.0f);

    const auto lookup = handle_lookup();
    renderer::FrameSubmitter submitter;

    auto draw_once = [&](const scenegraph::Camera& cam, const pd::PlanetDetailPass* detail) {
        hdr.bind();
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        submitter.submit_opaque_in_pass(world, cam, *p, lookup, lighting, scenegraph::Pass::Space,
                                        0.0f, nullptr, 1.0f, nullptr, nullptr, nullptr, detail);
    };

    GLuint q_bake = 0, q_draw = 0;
    glGenQueries(1, &q_bake);
    glGenQueries(1, &q_draw);
    auto gpu_ms = [](GLuint q) {
        GLuint64 ns = 0;
        glGetQueryObjectui64v(q, GL_QUERY_RESULT, &ns);
        return static_cast<double>(ns) / 1.0e6;
    };

    GLint te_bits = 0;
    glGetQueryiv(GL_TIME_ELAPSED, GL_QUERY_COUNTER_BITS, &te_bits);
    const bool can_assert_timing = te_bits > 0;

    pd::Anchor anchor = pd::make_anchor(dir_for_lon_lat(30.0f, 20.0f), R);
    float cx = 0.0f, cy = 0.0f;

    // Baseline: the same draw with detail disabled (sampling off, no bake)
    // at a static camera -- the "sampling delta" budget's reference point.
    std::vector<double> baseline_draw;
    {
        const auto cam = cam_for(anchor, cx, cy, R, kAlt, kTiltDeg);
        for (int i = 0; i < 120; ++i) {
            glBeginQuery(GL_TIME_ELAPSED, q_draw);
            draw_once(cam, nullptr);
            glEndQuery(GL_TIME_ELAPSED);
            baseline_draw.push_back(gpu_ms(q_draw));
        }
    }

    struct Seg {
        const char* name;
        int frames;
        double speed_gups;
        bool cut;
    };
    const Seg segs[] = {
        {"cold", 120, 0.0, false},     {"still", 240, 0.0, false},
        {"orbit6", 300, 6.0, false},   {"fast60", 300, 60.0, false},
        {"dash400", 300, 400.0, false}, {"cut", 120, 0.0, true},
    };

    std::vector<double> all_bake, all_draw;
    std::printf("[planet detail bench] %dx%d, alt=%.0f tilt=%.0fdeg R=%.1f GU\n", kFbW, kFbH, kAlt,
               kTiltDeg, static_cast<double>(R));
    std::printf("baseline draw (no detail): p50 %.3f ms over %d frames\n",
               percentile(baseline_draw, 50), static_cast<int>(baseline_draw.size()));
    std::printf("%-10s %6s | %-24s | %-24s\n", "segment", "frames", "bake ms p50/p95/max",
               "draw ms p50/p95/max");

    for (const auto& seg : segs) {
        if (seg.cut) {
            // A hard cut to the opposite side of the planet: forces the pass
            // to re-anchor mid-segment, same as the spike's "cut" segment.
            anchor = pd::make_anchor(dir_for_lon_lat(-60.0f, -10.0f), R);
            cx = cy = 0.0f;
        }
        std::vector<double> bake_v, draw_v;
        bake_v.reserve(static_cast<std::size_t>(seg.frames));
        draw_v.reserve(static_cast<std::size_t>(seg.frames));
        for (int i = 0; i < seg.frames; ++i) {
            cx += static_cast<float>(seg.speed_gups / kHz);
            const auto cam = cam_for(anchor, cx, cy, R, kAlt, kTiltDeg);

            glBeginQuery(GL_TIME_ELAPSED, q_bake);
            pass.update(world, cam, kFbH, lookup);
            glEndQuery(GL_TIME_ELAPSED);
            bake_v.push_back(gpu_ms(q_bake));

            glBeginQuery(GL_TIME_ELAPSED, q_draw);
            draw_once(cam, &pass);
            glEndQuery(GL_TIME_ELAPSED);
            draw_v.push_back(gpu_ms(q_draw));
        }
        std::printf("%-10s %6d | %-24s | %-24s\n", seg.name, seg.frames, stat_string(bake_v).c_str(),
                   stat_string(draw_v).c_str());
        std::fflush(stdout);
        all_bake.insert(all_bake.end(), bake_v.begin(), bake_v.end());
        all_draw.insert(all_draw.end(), draw_v.begin(), draw_v.end());
    }

    const double bake_p95 = percentile(all_bake, 95);
    const double bake_max = *std::max_element(all_bake.begin(), all_bake.end());
    const double draw_p50 = percentile(all_draw, 50);
    const double baseline_p50 = percentile(baseline_draw, 50);
    const double sampling_delta = draw_p50 - baseline_p50;

    std::printf(
        "overall: bake p95=%.3f ms max=%.3f ms; draw p50=%.3f ms; baseline p50=%.3f ms; "
        "sampling delta=%.3f ms; GL_TIME_ELAPSED bits=%d\n",
        bake_p95, bake_max, draw_p50, baseline_p50, sampling_delta, te_bits);

    glDeleteQueries(1, &q_bake);
    glDeleteQueries(1, &q_draw);

    EXPECT_GT(all_bake.size(), 0u);
    if (!can_assert_timing) {
        std::printf(
            "GL_TIME_ELAPSED has 0 query-counter bits on this driver: timing asserts skipped "
            "(table above still measured and printed)\n");
        return;
    }
    EXPECT_LE(bake_p95, 0.35) << "bake p95 " << bake_p95 << " ms over the 0.35 ms budget";
    EXPECT_LE(bake_max, 0.6) << "bake max " << bake_max << " ms over the 0.6 ms budget";
    EXPECT_LE(sampling_delta, 0.35)
        << "sampling delta " << sampling_delta << " ms (draw p50 " << draw_p50 << " - baseline p50 "
        << baseline_p50 << ") over the 0.35 ms budget";
}

}  // namespace
