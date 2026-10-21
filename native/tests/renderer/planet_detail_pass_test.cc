// native/tests/renderer/planet_detail_pass_test.cc
//
// PlanetDetailPass (spec docs/superpowers/specs/2026-10-08-planet-surface-
// detail-design.md §5.1, §5.3, §5.5): once per frame it picks ONE target
// planet, anchors the clipmap at the camera's nadir in the planet's BODY
// frame, bakes under a fixed budget, and exposes the target's sampling
// uniforms. FrameSubmitter draws only that target through planet_.
#include <gtest/gtest.h>

#include <renderer/frame.h>
#include <renderer/hdr_target.h>
#include <renderer/pipeline.h>
#include <renderer/planet_clipmap_schedule.h>
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
#include <filesystem>
#include <memory>
#include <optional>
#include <vector>

#include "support/content_root.h"

namespace {

namespace pd = renderer::planet_detail;
using test_support::game_root;

// ---------------------------------------------------------------- pick_target

pd::Candidate cand(std::uint32_t idx, glm::vec3 c, float R, int w = 256) {
    return pd::Candidate{scenegraph::InstanceId{idx, 1}, c, R, w};
}

constexpr float kFocal = 935.0f;   // 1080-px viewport, 60 deg fov

TEST(PlanetDetailPick, NoneVisibleFarAway) {
    const std::vector<pd::Candidate> c{cand(0, {0, 0, 0}, 1000.0f)};
    EXPECT_EQ(pd::pick_target(c, {0, 0, 100.0f * 1000.0f}, kFocal, std::nullopt), -1);
}

TEST(PlanetDetailPick, EmptyListIsMinusOne) {
    EXPECT_EQ(pd::pick_target({}, {0, 0, 0}, kFocal, std::nullopt), -1);
}

TEST(PlanetDetailPick, NearestBySurfaceDistanceWins) {
    // A: big planet, centre far but surface 300 away; B: small, centre nearer
    // (1300) but surface 1200 away. Surface distance, not centre distance.
    const std::vector<pd::Candidate> c{
        cand(0, {0, 0, 0}, 1100.0f),       // camera at z=1300: surface 200 away
        cand(1, {0, 0, 1700.0f}, 100.0f),  // surface 300 away
    };
    EXPECT_EQ(pd::pick_target(c, {0, 0, 1300.0f}, kFocal, std::nullopt), 0);
    const std::vector<pd::Candidate> d{
        cand(0, {0, 0, 0}, 1000.0f),       // surface 300 away
        cand(1, {0, 0, 1500.0f}, 100.0f),  // surface 100 away
    };
    EXPECT_EQ(pd::pick_target(d, {0, 0, 1300.0f}, kFocal, std::nullopt), 1);
}

TEST(PlanetDetailPick, HysteresisKeepsCurrentUntilTenPercentNearer) {
    const glm::vec3 cam{0, 0, 0};
    // Current (index 0) at surface distance 200.
    auto two = [&](float other_alt) {
        return std::vector<pd::Candidate>{
            cand(0, {0, 0, -(1000.0f + 200.0f)}, 1000.0f),
            cand(1, {0, 0, 1000.0f + other_alt}, 1000.0f),
        };
    };
    const auto cur = std::optional<scenegraph::InstanceId>(scenegraph::InstanceId{0, 1});
    EXPECT_EQ(pd::pick_target(two(190.0f), cam, kFocal, cur), 0) << "5% nearer: keep";
    EXPECT_EQ(pd::pick_target(two(170.0f), cam, kFocal, cur), 1) << "15% nearer: switch";
    // Without a current target the nearest simply wins.
    EXPECT_EQ(pd::pick_target(two(190.0f), cam, kFocal, std::nullopt), 1);
}

TEST(PlanetDetailPick, MoonAt150IsVisible) {
    const std::vector<pd::Candidate> c{cand(0, {0, 0, 0}, 140.0f)};
    EXPECT_EQ(pd::pick_target(c, {0, 0, 140.0f + 150.0f}, kFocal, std::nullopt), 0);
}

TEST(PlanetDetailPick, CurrentThatIsNoLongerVisibleIsDropped) {
    const std::vector<pd::Candidate> c{cand(0, {0, 0, 0}, 1000.0f)};
    const auto cur = std::optional<scenegraph::InstanceId>(scenegraph::InstanceId{0, 1});
    EXPECT_EQ(pd::pick_target(c, {0, 0, 1.0e6f}, kFocal, cur), -1);
}

// ------------------------------------------------------------ the GL pass

const std::filesystem::path kEnvDir = game_root() / "data" / "Models" / "Environment";
const std::filesystem::path kIcePlanetNif = kEnvDir / "IcePlanet.NIF";

constexpr int kSize = 256;
constexpr int kViewportH = 1080;

renderer::FrameSubmitter::ModelLookup handle_lookup() {
    return [](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h);
    };
}

class PlanetDetailPassTest : public ::testing::Test {
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
            w = std::make_unique<renderer::Window>(kSize, kSize, "planet-detail-pass", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        assets::AssetCache::Config cfg;
        cfg.keep_cpu_data = true;
        cache = std::make_unique<assets::AssetCache>(cfg);
        geo = cache->load(kIcePlanetNif, std::vector<std::filesystem::path>{kEnvDir},
                          {}, {}, 1.0f, /*geosphere=*/true);
        ASSERT_TRUE(geo->sphere_map.has_value());
        pd::reset_live_params();
    }

    void TearDown() override {
        pd::reset_live_params();
        if (!w) return;
        renderer::reset_scuff_normal_texture();
        renderer::reset_decal_mask_sampler();
        renderer::reset_model_radius_cache();
    }

    float R(float scale) const { return geo->sphere_map->radius * scale; }

    static scenegraph::Instance::Surface rocky(std::uint32_t seed = 7) {
        scenegraph::Instance::Surface s;
        s.type = static_cast<int>(pd::SurfaceType::Rocky);
        s.seed = seed;
        return s;
    }

    // A planet of world scale `scale` whose sphere centre lands at `centre`.
    scenegraph::InstanceId add_planet(scenegraph::World& world, float scale, glm::vec3 centre,
                                      const glm::mat4& rot = glm::mat4(1.0f)) {
        auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(geo.get()));
        world.set_world_transform(iid, planet_world(scale, centre, rot));
        world.set_surface(iid, rocky());
        return iid;
    }

    glm::mat4 planet_world(float scale, glm::vec3 centre, const glm::mat4& rot) const {
        // world * center_body == centre
        const glm::mat4 lin = rot * glm::scale(glm::mat4(1.0f), glm::vec3(scale));
        const glm::vec3 off = glm::vec3(lin * glm::vec4(geo->sphere_map->center_body, 1.0f));
        return glm::translate(glm::mat4(1.0f), centre - off) * lin;
    }

    static scenegraph::Camera cam_above(glm::vec3 centre, glm::vec3 dir, float R, float alt) {
        dir = glm::normalize(dir);
        scenegraph::Camera cam;
        cam.eye = centre + dir * (R + alt);
        cam.target = centre;
        cam.up = std::abs(dir.z) > 0.9f ? glm::vec3(0, 1, 0) : glm::vec3(0, 0, 1);
        cam.aspect = 1.0f;
        cam.near = 1.0f;
        cam.far = 1.0e6f;
        return cam;
    }

    void run(pd::PlanetDetailPass& pass, const scenegraph::World& world,
             const scenegraph::Camera& cam, int frames = 1) {
        for (int i = 0; i < frames; ++i) pass.update(world, cam, kViewportH, handle_lookup());
    }
};

TEST_F(PlanetDetailPassTest, TargetsTheNearPlanetOnly) {
    scenegraph::World world;
    const float s = 40.0f;
    const auto a = add_planet(world, s, {0, 0, 0});
    const auto b = add_planet(world, s, {100000.0f, 0, 0});
    pd::PlanetDetailPass pass;
    run(pass, world, cam_above({0, 0, 0}, {0, 0, 1}, R(s), 200.0f));
    ASSERT_TRUE(pass.target().has_value());
    EXPECT_EQ(*pass.target(), a);
    const pd::SampleUniforms ua = pass.uniforms_for(a);
    EXPECT_TRUE(ua.enabled);
    EXPECT_FALSE(pass.uniforms_for(b).enabled);
    EXPECT_EQ(ua.levels, 5);
    EXPECT_NE(ua.atlas, 0u);
    EXPECT_NEAR(ua.R, R(s), 1e-2f);
    EXPECT_NEAR(ua.scale_local, s, 1e-4f);
    EXPECT_EQ(ua.type, static_cast<int>(pd::SurfaceType::Rocky));
    // Anchored at the nadir: the camera is straight up body +Z.
    EXPECT_NEAR(ua.A.z, 1.0f, 1e-4f);
    EXPECT_GT(pass.last_cost(), 0);
    EXPECT_GT(pass.debug_valid_area(), 0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(PlanetDetailPassTest, SwitchingTargetResetsTheSchedule) {
    scenegraph::World world;
    const float s = 40.0f;
    add_planet(world, s, {0, 0, 0});
    const auto b = add_planet(world, s, {100000.0f, 0, 0});
    pd::PlanetDetailPass pass;
    run(pass, world, cam_above({0, 0, 0}, {0, 0, 1}, R(s), 200.0f), 20);
    const long long area_a = pass.debug_valid_area();
    run(pass, world, cam_above({100000.0f, 0, 0}, {0, 0, 1}, R(s), 200.0f));
    ASSERT_TRUE(pass.target().has_value());
    EXPECT_EQ(*pass.target(), b);
    EXPECT_LT(pass.debug_valid_area(), area_a) << "the clipmap restarted on B";
}

TEST_F(PlanetDetailPassTest, DestroyedTargetIsDropped) {
    scenegraph::World world;
    const float s = 40.0f;
    const auto a = add_planet(world, s, {0, 0, 0});
    pd::PlanetDetailPass pass;
    const auto cam = cam_above({0, 0, 0}, {0, 0, 1}, R(s), 200.0f);
    run(pass, world, cam, 3);
    ASSERT_TRUE(pass.target().has_value());
    world.destroy_instance(a);
    run(pass, world, cam);
    EXPECT_FALSE(pass.target().has_value());
    EXPECT_FALSE(pass.uniforms_for(a).enabled);
    EXPECT_EQ(pass.last_cost(), 0);
    // A new instance recycling the slot is a different id: not the old target.
    const auto c = add_planet(world, s, {0, 0, 0});
    EXPECT_FALSE(pass.uniforms_for(c).enabled);
    run(pass, world, cam);
    ASSERT_TRUE(pass.target().has_value());
    EXPECT_EQ(*pass.target(), c);
}

TEST_F(PlanetDetailPassTest, CostStaysWithinBudgetOverMotion) {
    scenegraph::World world;
    const float s = 40.0f;
    add_planet(world, s, {0, 0, 0});
    pd::PlanetDetailPass pass;
    const long long budget = 65536;
    pass.set_budget(budget);
    // One strip: a full band column/row times the most octaves any level has.
    const auto& tp = pd::live_params(pd::SurfaceType::Rocky);
    const long long strip = static_cast<long long>(pd::kBandRows) * std::max(tp.max_octaves, 1);
    int baked_frames = 0;
    for (int f = 0; f < 120; ++f) {
        // Sweep along the surface fast enough to re-anchor (0.5 R ~ 1800 GU).
        const float ang = f * (25.0f / R(s));
        const glm::vec3 dir{std::sin(ang), 0.0f, std::cos(ang)};
        run(pass, world, cam_above({0, 0, 0}, dir, R(s), 200.0f));
        // Cold start (any level incomplete) doubles the cap.
        EXPECT_LE(pass.last_cost(), 2 * budget + strip) << "frame " << f;
        if (pass.last_cost() > 0) ++baked_frames;
    }
    EXPECT_GT(baked_frames, 60);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(PlanetDetailPassTest, MoonGetsTwoLevels) {
    scenegraph::World world;
    const float s = 140.0f / geo->sphere_map->radius;
    const auto m = add_planet(world, s, {0, 0, 0});
    pd::PlanetDetailPass pass;
    run(pass, world, cam_above({0, 0, 0}, {0, 0, 1}, R(s), 150.0f));
    ASSERT_TRUE(pass.target().has_value());
    EXPECT_EQ(pass.uniforms_for(m).levels, 2);
}

TEST_F(PlanetDetailPassTest, NoCandidateDoesNoGlWork) {
    scenegraph::World world;
    const float s = 40.0f;
    add_planet(world, s, {0, 0, 0});
    pd::PlanetDetailPass pass;
    const auto far = cam_above({0, 0, 0}, {0, 0, 1}, R(s), 100.0f * R(s));
    run(pass, world, far);
    EXPECT_FALSE(pass.target().has_value());
    EXPECT_EQ(pass.debug_atlas_texture(), 0u) << "no atlas created without a target";
    EXPECT_EQ(pass.last_cost(), 0);
    // Target, then leave: no bake, and the atlas is neither freed nor remade.
    run(pass, world, cam_above({0, 0, 0}, {0, 0, 1}, R(s), 200.0f), 2);
    const unsigned tex = pass.debug_atlas_texture();
    ASSERT_NE(tex, 0u);
    run(pass, world, far);
    EXPECT_FALSE(pass.target().has_value());
    EXPECT_EQ(pass.last_cost(), 0);
    EXPECT_EQ(pass.debug_atlas_texture(), tex);
}

TEST_F(PlanetDetailPassTest, SurfaceShapeChangeResetsTheClipmap) {
    scenegraph::World world;
    const float s = 40.0f;
    const auto a = add_planet(world, s, {0, 0, 0});
    pd::PlanetDetailPass pass;
    const auto cam = cam_above({0, 0, 0}, {0, 0, 1}, R(s), 200.0f);
    run(pass, world, cam, 20);
    const long long full = pass.debug_valid_area();
    world.set_surface(a, rocky(/*seed=*/99));
    run(pass, world, cam);
    EXPECT_LT(pass.debug_valid_area(), full) << "seed change resets";

    run(pass, world, cam, 20);
    const long long full2 = pass.debug_valid_area();
    pd::live_params(pd::SurfaceType::Rocky).amplitude *= 2.0f;
    run(pass, world, cam);
    EXPECT_LT(pass.debug_valid_area(), full2) << "shape-hash change resets";

    run(pass, world, cam, 20);
    const long long full3 = pass.debug_valid_area();
    pd::live_params(pd::SurfaceType::Rocky).bump *= 2.0f;   // display-only
    run(pass, world, cam);
    EXPECT_GE(pass.debug_valid_area(), full3) << "a display-only dial does not reset";
}

// The anchor and nadir are in the planet's BODY frame: rotating the planet
// together with the camera leaves every sampling uniform where it was, so the
// detail stays attached to the surface.
TEST_F(PlanetDetailPassTest, RotatedPlanetKeepsBodyFrameAnchor) {
    const float s = 40.0f;
    const glm::vec3 c{500.0f, -300.0f, 200.0f};
    const glm::vec3 dir_body = glm::normalize(glm::vec3(0.3f, -0.2f, 1.0f));
    const glm::mat4 rot =
        glm::rotate(glm::mat4(1.0f), 1.2f, glm::normalize(glm::vec3(1.0f, 2.0f, 0.5f)));

    scenegraph::World w0;
    const auto a0 = add_planet(w0, s, c);
    pd::PlanetDetailPass p0;
    run(p0, w0, cam_above(c, dir_body, R(s), 200.0f), 4);
    const pd::SampleUniforms u0 = p0.uniforms_for(a0);

    scenegraph::World w1;
    const auto a1 = add_planet(w1, s, c, rot);
    pd::PlanetDetailPass p1;
    const glm::vec3 dir_ws = glm::vec3(rot * glm::vec4(dir_body, 0.0f));
    run(p1, w1, cam_above(c, dir_ws, R(s), 200.0f), 4);
    const pd::SampleUniforms u1 = p1.uniforms_for(a1);

    ASSERT_TRUE(u0.enabled);
    ASSERT_TRUE(u1.enabled);
    EXPECT_NEAR(glm::length(u0.A - glm::normalize(dir_body)), 0.0f, 1e-3f);
    EXPECT_NEAR(glm::length(u1.A - u0.A), 0.0f, 1e-3f);
    EXPECT_NEAR(glm::length(u1.E - u0.E), 0.0f, 1e-3f);
    EXPECT_NEAR(glm::length(u1.N - u0.N), 0.0f, 1e-3f);
    // The nadir sits on the anchor (plane origin), a texel corner: float
    // rounding may land it either side, so rects agree to one texel.
    for (int L = 0; L < u0.levels; ++L)
        for (int k = 0; k < 4; ++k)
            EXPECT_NEAR(u1.valid[static_cast<std::size_t>(L)][k],
                        u0.valid[static_cast<std::size_t>(L)][k], 1.0f)
                << "level " << L << " component " << k;

    // Spinning the planet under a fixed camera moves the nadir across the
    // body: a large spin forces a re-anchor at the new body-frame nadir.
    w0.set_world_transform(a0, planet_world(s, c, rot));
    run(p0, w0, cam_above(c, dir_body, R(s), 200.0f));
    const glm::vec3 nadir_body =
        glm::normalize(glm::vec3(glm::inverse(rot) * glm::vec4(dir_body, 0.0f)));
    EXPECT_NEAR(glm::length(p0.uniforms_for(a0).A - nadir_body), 0.0f, 1e-3f);
}

// Review Focus #1: only the target goes through planet_. Every other draw is
// byte-identical to a render with no detail pass at all.
TEST_F(PlanetDetailPassTest, OnlyTheTargetDrawsThroughPlanetProgram) {
    scenegraph::World world;
    const float s = 40.0f;
    const auto a = add_planet(world, s, {0, 0, 0});
    // B: far beyond A's horizon, above the view centre.
    const auto b = add_planet(world, s, {25000.0f, 0.0f, 3600.0f + 2000.0f});
    (void)b;

    scenegraph::Camera cam;
    cam.eye = glm::vec3(0, 0, R(s) + 200.0f);
    cam.target = cam.eye + glm::vec3(1.0f, 0.0f, -0.15f);
    cam.up = glm::vec3(0, 0, 1);
    cam.aspect = 1.0f;
    cam.near = 1.0f;
    cam.far = 1.0e6f;

    renderer::Lighting l;
    l.ambient = glm::vec3(0.05f);
    l.directional_count = 1;
    l.directional_dir_ws[0] = glm::normalize(glm::vec3(0.6f, 0.3f, 0.75f));
    l.directional_color[0] = glm::vec3(1.0f);

    pd::PlanetDetailPass pass;
    pass.set_budget(1LL << 40);   // bake everything this frame
    pass.update(world, cam, kSize, handle_lookup());
    pass.update(world, cam, kSize, handle_lookup());
    ASSERT_TRUE(pass.target().has_value());
    ASSERT_EQ(*pass.target(), a);

    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    auto draw = [&](const scenegraph::World& wld, const pd::PlanetDetailPass* d) {
        hdr.bind();
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        renderer::FrameSubmitter submitter;
        submitter.submit_opaque_in_pass(wld, cam, *p, handle_lookup(), l,
                                        scenegraph::Pass::Space, 0.0f, 1.0f,
                                        nullptr, nullptr, d);
        std::vector<float> px(static_cast<std::size_t>(kSize * kSize * 4), 0.0f);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, hdr.fbo());
        glReadPixels(0, 0, kSize, kSize, GL_RGBA, GL_FLOAT, px.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        return px;
    };
    const auto plain = draw(world, nullptr);
    const auto detail = draw(world, &pass);

    // B's own pixels: B drawn alone.
    world.set_visible(a, false);
    const auto b_only = draw(world, nullptr);
    world.set_visible(a, true);

    int b_px = 0, a_px = 0, a_diff = 0;
    for (int i = 0; i < kSize * kSize; ++i) {
        const std::size_t k = static_cast<std::size_t>(i) * 4;
        const bool is_b = b_only[k] + b_only[k + 1] + b_only[k + 2] > 0.0f;
        const bool lit = plain[k] + plain[k + 1] + plain[k + 2] > 0.0f;
        bool same = true;
        for (int ch = 0; ch < 4; ++ch) same = same && plain[k + ch] == detail[k + ch];
        if (is_b) {
            ++b_px;
            EXPECT_TRUE(same) << "B pixel " << i << " changed";
        } else if (lit) {
            ++a_px;
            if (!same) ++a_diff;
        }
    }
    EXPECT_GT(b_px, 200) << "B must be in view";
    EXPECT_GT(a_px, 2000) << "A must be in view";
    EXPECT_GT(a_diff, 100) << "the target drew through planet_ with detail";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Gas flow (spec §6) is seeded per planet: uniforms_for carries the seed.
TEST_F(PlanetDetailPassTest, UniformsCarryTheSurfaceSeed) {
    scenegraph::World world;
    const float s = 40.0f;
    const auto a = add_planet(world, s, {0, 0, 0});
    world.set_surface(a, rocky(/*seed=*/4242u));
    pd::PlanetDetailPass pass;
    run(pass, world, cam_above({0, 0, 0}, {0, 0, 1}, R(s), 200.0f));
    ASSERT_TRUE(pass.target().has_value());
    EXPECT_EQ(pass.uniforms_for(a).seed, 4242u);
}

}  // namespace
