// native/tests/renderer/atmosphere_pass_test.cc
//
// Planet atmosphere shell pass (spec docs/superpowers/specs/2026-10-07-planet-atmosphere-design.md
// §5; plan deviation D1: drawn in render phase 2 with depth test off, the
// march ending at the scene's opaque depth). The planet is drawn first through
// the production opaque path so the depth texture is populated, then the
// AtmospherePass adds its in-scatter on top.
#include <gtest/gtest.h>

#include <renderer/atmosphere_math.h>
#include <renderer/atmosphere_pass.h>
#include <renderer/frame.h>
#include <renderer/hdr_target.h>
#include <renderer/nonfinite_probe.h>
#include <renderer/pipeline.h>
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
#include <iostream>
#include <limits>
#include <vector>

#include "support/content_root.h"

namespace {

using test_support::game_root;

const std::filesystem::path kEnvDir =
    game_root() / "data" / "Models" / "Environment";
const std::filesystem::path kIcePlanetNif = kEnvDir / "IcePlanet.NIF";

constexpr int   kSize       = 256;
constexpr float kScale      = 20.0f;      // planet instance scale (R ~ 1800)
constexpr float kThickness  = 0.06f;
constexpr float kDensity    = 1.4f;

glm::mat4 scaled(float s) { return glm::scale(glm::mat4(1.0f), glm::vec3(s)); }

renderer::FrameSubmitter::ModelLookup handle_lookup() {
    return [](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h);
    };
}

class AtmospherePassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<assets::AssetCache> cache;

    void SetUp() override {
        if (!std::filesystem::is_regular_file(kIcePlanetNif)) {
            GTEST_SKIP() << "BC asset not available at " << kIcePlanetNif;
        }
        try {
            w = std::make_unique<renderer::Window>(kSize, kSize, "atmosphere-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        // keep_cpu_data, as the production host cache: apply_geosphere's
        // sphere gate reads the source MeshCpu (see geosphere_draw_test.cc).
        assets::AssetCache::Config cfg;
        cfg.keep_cpu_data = true;
        cache = std::make_unique<assets::AssetCache>(cfg);
    }

    void TearDown() override {
        if (!w) return;
        renderer::reset_damage_decal_texture();
        renderer::reset_scuff_normal_texture();
        renderer::reset_decal_mask_sampler();
        renderer::reset_model_radius_cache();
    }

    assets::ModelHandle load_planet(bool geosphere) {
        return cache->load(kIcePlanetNif, std::vector<std::filesystem::path>{kEnvDir},
                           {}, {}, 1.0f, geosphere);
    }

    static scenegraph::Instance::Atmosphere atmo(bool enabled) {
        scenegraph::Instance::Atmosphere a;
        a.enabled = enabled;
        a.color = glm::vec3(1.0f);
        a.thickness = kThickness;
        a.density = kDensity;
        return a;
    }

    static scenegraph::InstanceId add(scenegraph::World& world,
                                      const assets::ModelHandle& model,
                                      const glm::mat4& world_m) {
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model.get()));
        world.set_world_transform(iid, world_m);
        return iid;
    }

    // Sun on +X, far away; directional 0 points at it.
    static renderer::Lighting sun_lighting(glm::vec3 sun_dir, glm::vec3 color) {
        renderer::Lighting l;
        l.directional_count = 1;
        l.directional_dir_ws[0] = glm::normalize(sun_dir);
        l.directional_color[0] = color;
        return l;
    }

    static std::vector<renderer::SunDescriptor> suns_at(glm::vec3 pos) {
        renderer::SunDescriptor s;
        s.position = pos;
        s.radius = 1000.0f;
        return {s};
    }

    // Phase 1: the scene's opaque geometry through the production submit path.
    void draw_opaque(const scenegraph::World& world, const scenegraph::Camera& cam,
                     const renderer::Lighting& lighting, renderer::HdrTarget& hdr) {
        hdr.bind();
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        renderer::FrameSubmitter submitter;
        submitter.submit_opaque_in_pass(world, cam, *p, handle_lookup(), lighting,
                                        scenegraph::Pass::Space);
    }

    // Phase 2: the atmosphere pass into the same (still bound) target.
    void draw_atmosphere(renderer::AtmospherePass& pass, const scenegraph::World& world,
                         const scenegraph::Camera& cam, const renderer::Lighting& lighting,
                         const std::vector<renderer::SunDescriptor>& suns,
                         renderer::HdrTarget& hdr) {
        hdr.bind();
        pass.render(world, cam, *p, handle_lookup(), lighting, suns,
                    hdr.depth_texture(), hdr.width(), hdr.height());
    }

    static std::vector<float> read_rgba(const renderer::HdrTarget& hdr) {
        std::vector<float> px(static_cast<std::size_t>(hdr.width() * hdr.height() * 4), 0.0f);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, hdr.fbo());
        glReadPixels(0, 0, hdr.width(), hdr.height(), GL_RGBA, GL_FLOAT, px.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        return px;
    }

    static glm::vec3 rgb(const std::vector<float>& px, int x, int y) {
        const std::size_t i = static_cast<std::size_t>((y * kSize + x) * 4);
        return {px[i], px[i + 1], px[i + 2]};
    }

    static float lum(const std::vector<float>& px, int x, int y) {
        const glm::vec3 c = rgb(px, x, y);
        return 0.2126f * c.r + 0.7152f * c.g + 0.0722f * c.b;
    }

    // First / last centre-row column with luminance > 0 (the silhouette).
    static void silhouette(const std::vector<float>& px, int& first, int& last) {
        first = -1; last = -1;
        const int row = kSize / 2;
        for (int x = 0; x < kSize; ++x) {
            if (lum(px, x, row) > 0.0f) {
                if (first < 0) first = x;
                last = x;
            }
        }
    }

    // World-space unit ray through the centre of pixel (x, y). Built in view
    // space from the frustum slopes rather than by unprojecting an NDC point:
    // inverse(proj*view) at ndc.z = 0 lands ~0.2 units from a 9000-unit eye,
    // where float rounding alone moves the direction by about a pixel.
    static glm::vec3 pixel_ray(const scenegraph::Camera& cam, int x, int y) {
        const float t = std::tan(0.5f * cam.fov_y_rad);
        const float ndc_x = (x + 0.5f) / kSize * 2.0f - 1.0f;
        const float ndc_y = (y + 0.5f) / kSize * 2.0f - 1.0f;
        const glm::vec3 d_view(ndc_x * t * cam.aspect, ndc_y * t, -1.0f);
        const glm::mat3 cam_to_world = glm::mat3(glm::inverse(cam.view_matrix()));
        return glm::normalize(cam_to_world * d_view);
    }

    static scenegraph::Camera far_camera() {
        scenegraph::Camera cam;
        cam.eye = {0.0f, 0.0f, 9000.0f};
        cam.target = {0.0f, 0.0f, 0.0f};
        cam.aspect = 1.0f;
        return cam;
    }
};

TEST_F(AtmospherePassTest, LitLimbIsBrighterThanFarLimb) {
    auto geo = load_planet(true);
    ASSERT_TRUE(geo->sphere_map.has_value());
    scenegraph::World world;
    auto iid = add(world, geo, scaled(kScale));
    world.set_atmosphere(iid, atmo(true));
    const auto cam = far_camera();
    const auto lighting = sun_lighting({1, 0, 0}, glm::vec3(1.0f));
    const auto suns = suns_at({1e6f, 0, 0});

    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    draw_opaque(world, cam, lighting, hdr);
    const auto before = read_rgba(hdr);
    int first = 0, last = 0;
    silhouette(before, first, last);
    ASSERT_GT(first, 2);
    ASSERT_LT(last, kSize - 3);

    renderer::AtmospherePass pass;
    draw_atmosphere(pass, world, cam, lighting, suns, hdr);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_EQ(pass.last_draw_count(), 1);
    const auto after = read_rgba(hdr);

    const int row = kSize / 2;
    const float lit = lum(after, last + 1, row);
    const float dark = lum(after, first - 1, row);
    EXPECT_GT(lit, 0.0f) << "no halo on the sun side";
    EXPECT_GT(lit, 4.0f * dark) << "lit " << lit << " vs far " << dark;
}

TEST_F(AtmospherePassTest, ShaderMatchesCpuTwin) {
    auto geo = load_planet(true);
    ASSERT_TRUE(geo->sphere_map.has_value());
    scenegraph::World world;
    const glm::mat4 world_m = scaled(kScale);
    auto iid = add(world, geo, world_m);
    world.set_atmosphere(iid, atmo(true));
    const auto cam = far_camera();
    const glm::vec3 sun_color(1.5f, 1.2f, 0.8f);
    const auto lighting = sun_lighting({1, 0, 0}, sun_color);
    const auto suns = suns_at({1e6f, 0, 0});

    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    draw_opaque(world, cam, lighting, hdr);
    const auto before = read_rgba(hdr);
    int first = 0, last = 0;
    silhouette(before, first, last);
    ASSERT_GT(first, 2);
    ASSERT_LT(last, kSize - 3);

    renderer::AtmospherePass pass;
    draw_atmosphere(pass, world, cam, lighting, suns, hdr);
    const auto after = read_rgba(hdr);

    const int px_x = last + 1;
    const int px_y = kSize / 2;
    const glm::vec3 added = rgb(after, px_x, px_y) - rgb(before, px_x, px_y);

    // The CPU twin along the same pixel-centre ray.
    const glm::vec3 dir = pixel_ray(cam, px_x, px_y);
    const glm::vec3 center =
        glm::vec3(world_m * glm::vec4(geo->sphere_map->center_body, 1.0f));
    const float r = geo->sphere_map->radius * kScale;
    const renderer::planet_atmo::Shell shell{center, r, r * (1.0f + kThickness)};
    const renderer::planet_atmo::Params params{glm::vec3(1.0f), kThickness, kDensity};
    const glm::vec3 sun_dir = renderer::planet_atmo::sun_dir_for(center, suns, {1, 0, 0});
    // atmo() leaves intensity at the struct default (6.0) -- the twin must
    // multiply by the same factor the shader's u_intensity applies.
    const glm::vec3 expected =
        renderer::planet_atmo::in_scatter(shell, params, cam.eye, dir,
                                          std::numeric_limits<float>::infinity(), sun_dir)
        * sun_color * scenegraph::Instance::Atmosphere{}.intensity;

    ASSERT_GT(expected.r, 0.0f) << "twin pixel is outside the shell";
    for (int c = 0; c < 3; ++c) {
        EXPECT_NEAR(added[c], expected[c], 0.02f * expected[c])
            << "channel " << c << " gpu " << added[c] << " cpu " << expected[c];
    }
}

// The root-cause bug: the raw in-scatter peaks at ~0.06 against a sun colour
// of ~1, roughly a sixth of the lit surface, so the halo vanishes after
// tonemapping. The sun is placed ALONG the camera's view axis (rather than
// off to the side, as LitLimbIsBrighterThanFarLimb does) so the disc centre
// is itself directly lit and the limb ring is the brightest halo band --
// giving a clean "lit surface" vs "halo" comparison on one frame.
TEST_F(AtmospherePassTest, DefaultIntensityHaloIsVisible) {
    auto geo = load_planet(true);
    ASSERT_TRUE(geo->sphere_map.has_value());
    scenegraph::World world;
    auto iid = add(world, geo, scaled(kScale));
    world.set_atmosphere(iid, atmo(true));   // default intensity == 6.0
    scenegraph::Camera cam;
    cam.eye = {0.0f, 0.0f, 9000.0f};
    cam.target = {0.0f, 0.0f, 0.0f};
    cam.aspect = 1.0f;
    const auto lighting = sun_lighting({0, 0, 1}, glm::vec3(1.0f));
    const auto suns = suns_at({0, 0, 1e6f});

    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    draw_opaque(world, cam, lighting, hdr);
    const auto before = read_rgba(hdr);
    int first = 0, last = 0;
    silhouette(before, first, last);
    ASSERT_GT(first, 2);
    ASSERT_LT(last, kSize - 3);
    const float surface_centre = lum(before, kSize / 2, kSize / 2);
    ASSERT_GT(surface_centre, 0.0f) << "disc centre was black -- sun/camera setup is wrong";

    renderer::AtmospherePass pass;
    draw_atmosphere(pass, world, cam, lighting, suns, hdr);
    const auto after = read_rgba(hdr);

    const int row = kSize / 2;
    float peak = 0.0f;
    for (int x = std::max(0, first - 4); x <= std::min(kSize - 1, last + 4); ++x) {
        peak = std::max(peak, lum(after, x, row) - lum(before, x, row));
    }

    std::cerr << "[atmosphere] DefaultIntensityHaloIsVisible: halo peak=" << peak
              << " lit-surface centre=" << surface_centre
              << " ratio=" << (peak / surface_centre) << "\n";

    EXPECT_GT(peak, 0.0f) << "no halo at all";
    EXPECT_GE(peak, 0.25f * surface_centre)
        << "halo peak " << peak << " is under 25% of the lit surface " << surface_centre;
}

// Two otherwise-identical draws differing only in `intensity`: the shell
// pass's output must scale LINEARLY with it (it is a flat multiplier on the
// final colour, applied before the clamp/NaN guard).
TEST_F(AtmospherePassTest, IntensityScalesTheHaloLinearly) {
    auto geo = load_planet(true);
    ASSERT_TRUE(geo->sphere_map.has_value());
    const auto cam = far_camera();
    const auto lighting = sun_lighting({1, 0, 0}, glm::vec3(1.0f));
    const auto suns = suns_at({1e6f, 0, 0});

    auto measure = [&](float intensity) {
        scenegraph::World world;
        auto iid = add(world, geo, scaled(kScale));
        auto a = atmo(true);
        a.intensity = intensity;
        world.set_atmosphere(iid, a);

        renderer::HdrTarget hdr;
        hdr.resize(kSize, kSize);
        draw_opaque(world, cam, lighting, hdr);
        const auto before = read_rgba(hdr);
        int first = 0, last = 0;
        silhouette(before, first, last);

        renderer::AtmospherePass pass;
        draw_atmosphere(pass, world, cam, lighting, suns, hdr);
        const auto after = read_rgba(hdr);
        const int hx = last + 1;
        const int hy = kSize / 2;
        return lum(after, hx, hy) - lum(before, hx, hy);
    };

    const float at2 = measure(2.0f);
    const float at4 = measure(4.0f);
    ASSERT_GT(at2, 0.0f);
    EXPECT_NEAR(at4, 2.0f * at2, 0.02f * 2.0f * at2)
        << "intensity 4 (" << at4 << ") is not 2x intensity 2 (" << at2 << ")";
}

TEST_F(AtmospherePassTest, NoNanAnywhereOutside) {
    auto geo = load_planet(true);
    scenegraph::World world;
    auto iid = add(world, geo, scaled(kScale));
    world.set_atmosphere(iid, atmo(true));
    const auto cam = far_camera();
    const auto lighting = sun_lighting({1, 0, 0}, glm::vec3(1.0f));
    const auto suns = suns_at({1e6f, 0, 0});

    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    draw_opaque(world, cam, lighting, hdr);
    renderer::AtmospherePass pass;
    draw_atmosphere(pass, world, cam, lighting, suns, hdr);
    EXPECT_EQ(pass.last_draw_count(), 1);

    renderer::NonfiniteProbe probe;
    const auto& res = probe.run(hdr.color_texture(), kSize, kSize);
    EXPECT_FALSE(res.any) << res.flagged_cells << " cell(s) hold NaN/Inf";
    const auto px = read_rgba(hdr);
    int nonfinite = 0;
    for (float v : px) if (!std::isfinite(v)) ++nonfinite;
    EXPECT_EQ(nonfinite, 0);
}

TEST_F(AtmospherePassTest, CameraInsideShellIsFiniteAndHazesTheDisc) {
    auto geo = load_planet(true);
    ASSERT_TRUE(geo->sphere_map.has_value());
    scenegraph::World world;
    const glm::mat4 world_m = scaled(kScale);
    auto iid = add(world, geo, world_m);
    world.set_atmosphere(iid, atmo(true));
    const glm::vec3 center =
        glm::vec3(world_m * glm::vec4(geo->sphere_map->center_body, 1.0f));
    const float r = geo->sphere_map->radius * kScale;
    scenegraph::Camera cam;
    cam.eye = center + glm::vec3(0.0f, 0.0f, r + 0.5f * kThickness * r);
    cam.target = center;
    cam.aspect = 1.0f;
    const auto lighting = sun_lighting({0, 0, 1}, glm::vec3(1.0f));
    const auto suns = suns_at({0, 0, 1e6f});

    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    draw_opaque(world, cam, lighting, hdr);
    const auto before = read_rgba(hdr);
    renderer::AtmospherePass pass;
    draw_atmosphere(pass, world, cam, lighting, suns, hdr);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    const auto after = read_rgba(hdr);

    renderer::NonfiniteProbe probe;
    const auto& res = probe.run(hdr.color_texture(), kSize, kSize);
    EXPECT_FALSE(res.any) << res.flagged_cells << " cell(s) hold NaN/Inf";
    int nonfinite = 0;
    for (float v : after) if (!std::isfinite(v)) ++nonfinite;
    EXPECT_EQ(nonfinite, 0);
    EXPECT_GT(lum(before, kSize / 2, kSize / 2), 0.0f) << "disc centre was black";
    EXPECT_GT(lum(after, kSize / 2, kSize / 2), lum(before, kSize / 2, kSize / 2))
        << "atmosphere did not haze the disc from inside the shell";
}

TEST_F(AtmospherePassTest, OpaqueDepthEndsTheMarch) {
    auto geo = load_planet(true);
    auto occ_model = load_planet(false);   // plain IcePlanet, small, as an occluder
    ASSERT_TRUE(geo->sphere_map.has_value());
    const auto cam = far_camera();
    const auto lighting = sun_lighting({1, 0, 0}, glm::vec3(1.0f));
    const auto suns = suns_at({1e6f, 0, 0});

    // Reference: planet alone, find the +X halo pixel and its added light.
    scenegraph::World world;
    auto iid = add(world, geo, scaled(kScale));
    world.set_atmosphere(iid, atmo(true));
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    draw_opaque(world, cam, lighting, hdr);
    const auto before = read_rgba(hdr);
    int first = 0, last = 0;
    silhouette(before, first, last);
    const int hx = last + 1;
    const int hy = kSize / 2;
    renderer::AtmospherePass pass;
    draw_atmosphere(pass, world, cam, lighting, suns, hdr);
    const auto after = read_rgba(hdr);
    const float added_clear = lum(after, hx, hy) - lum(before, hx, hy);
    ASSERT_GT(added_clear, 0.0f);

    // Same scene plus a small opaque occluder halfway along the halo pixel's ray.
    const glm::vec3 dir = pixel_ray(cam, hx, hy);
    const glm::vec3 occ_pos = cam.eye + dir * 4500.0f;
    // Plain IcePlanet ~90 units; x2 => ~180 units radius = ~9 px at 4500.
    const glm::mat4 occ_m = glm::translate(glm::mat4(1.0f), occ_pos)
        * glm::scale(glm::mat4(1.0f), glm::vec3(2.0f));
    add(world, occ_model, occ_m);
    draw_opaque(world, cam, lighting, hdr);
    const auto before_occ = read_rgba(hdr);
    ASSERT_GT(lum(before_occ, hx, hy), 0.0f) << "occluder does not cover the halo pixel";
    draw_atmosphere(pass, world, cam, lighting, suns, hdr);
    const auto after_occ = read_rgba(hdr);
    const float added_occ = lum(after_occ, hx, hy) - lum(before_occ, hx, hy);
    // The occluder sits ~4300 units in front of the shell, so the march span
    // is empty: nothing is added. A bare `<` would pass on fp16 rounding of
    // the brighter occluder pixel alone (measured: it survives a shader that
    // ignores the depth texture), so demand the halo is essentially gone.
    EXPECT_LT(added_occ, 0.1f * added_clear)
        << "opaque depth did not end the march: " << added_occ << " vs " << added_clear;
}

// Eye-to-surface distance of the opaque geometry at pixel (x, y), read back
// from the depth buffer and linearised in double precision: exactly the
// (quantised) depth the shader's scene_t() sees, so the CPU twin can be
// handed the same march end.
static float depth_distance(const renderer::HdrTarget& hdr, const scenegraph::Camera& cam,
                            int x, int y, glm::vec3 dir) {
    float d = 1.0f;
    glBindFramebuffer(GL_READ_FRAMEBUFFER, hdr.fbo());
    glReadPixels(x, y, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, &d);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    const double n = cam.near, f = cam.far;
    // The projection is glm's zero-to-one (GLM_FORCE_DEPTH_ZERO_TO_ONE) under
    // GL's [-1,1] clip volume, so ndc = 2d - 1 lies in [0,1] -- the same
    // reconstruction scene_t() does through inverse(proj * view).
    const double ndc = 2.0 * d - 1.0;
    const double z_eye = f * n / (f - ndc * (f - n));
    const glm::vec3 fwd = glm::normalize(cam.target - cam.eye);
    return static_cast<float>(z_eye / static_cast<double>(glm::dot(dir, fwd)));
}

// An opaque occluder INSIDE the halo ray's shell span on the lit limb: the
// march must end exactly at it, so the added light is the twin's in-scatter
// truncated at the occluder's distance (not zero, not the full chord).
TEST_F(AtmospherePassTest, OccluderInsideTheShellEndsTheMarchAtItsDistance) {
    auto geo = load_planet(true);
    auto occ_model = load_planet(false);
    ASSERT_TRUE(geo->sphere_map.has_value());
    const auto cam = far_camera();
    const auto lighting = sun_lighting({1, 0, 0}, glm::vec3(1.0f));
    const auto suns = suns_at({1e6f, 0, 0});
    const glm::mat4 world_m = scaled(kScale);

    scenegraph::World world;
    auto iid = add(world, geo, world_m);
    world.set_atmosphere(iid, atmo(true));
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    draw_opaque(world, cam, lighting, hdr);
    int first = 0, last = 0;
    silhouette(read_rgba(hdr), first, last);
    const int hx = last + 1;
    const int hy = kSize / 2;

    const glm::vec3 center =
        glm::vec3(world_m * glm::vec4(geo->sphere_map->center_body, 1.0f));
    const float r = geo->sphere_map->radius * kScale;
    const renderer::planet_atmo::Shell shell{center, r, r * (1.0f + kThickness)};
    const renderer::planet_atmo::Params params{glm::vec3(1.0f), kThickness, kDensity};
    const glm::vec3 dir = pixel_ray(cam, hx, hy);
    const auto span = renderer::planet_atmo::air_span(
        shell, cam.eye, dir, std::numeric_limits<float>::infinity());
    ASSERT_TRUE(span.hit);

    // Occluder centred just past the span midpoint, so its front surface
    // lands inside the span.
    const glm::vec3 occ_pos = cam.eye + dir * (0.5f * (span.t0 + span.t1) + 150.0f);
    const glm::mat4 occ_m = glm::translate(glm::mat4(1.0f), occ_pos)
        * glm::scale(glm::mat4(1.0f), glm::vec3(2.0f));
    add(world, occ_model, occ_m);
    draw_opaque(world, cam, lighting, hdr);
    const auto before = read_rgba(hdr);
    const float t_occ = depth_distance(hdr, cam, hx, hy, dir);
    ASSERT_GT(t_occ, span.t0 + 0.1f * (span.t1 - span.t0)) << "occluder not inside the span";
    ASSERT_LT(t_occ, span.t1 - 0.1f * (span.t1 - span.t0)) << "occluder not inside the span";

    renderer::AtmospherePass pass;
    draw_atmosphere(pass, world, cam, lighting, suns, hdr);
    const auto after = read_rgba(hdr);
    const glm::vec3 added = rgb(after, hx, hy) - rgb(before, hx, hy);

    const glm::vec3 sun_dir = renderer::planet_atmo::sun_dir_for(center, suns, {1, 0, 0});
    const float intensity = scenegraph::Instance::Atmosphere{}.intensity;
    const glm::vec3 expected =
        renderer::planet_atmo::in_scatter(shell, params, cam.eye, dir, t_occ, sun_dir)
        * intensity;
    const glm::vec3 full = renderer::planet_atmo::in_scatter(
        shell, params, cam.eye, dir, std::numeric_limits<float>::infinity(), sun_dir)
        * intensity;
    ASSERT_GT(expected.r, 0.0f);
    ASSERT_LT(expected.r, 0.95f * full.r) << "occluder does not truncate the march";
    for (int c = 0; c < 3; ++c) {
        EXPECT_NEAR(added[c], expected[c], 0.05f * expected[c])
            << "channel " << c << " gpu " << added[c] << " cpu " << expected[c];
    }
}

// With the PRODUCTION near/far (engine/cameras: 1 / 1.8e6 GU) the 24-bit
// depth of the planet's own disc is quantised to tens of GU at this range --
// coarser than the shell's scale height. Read as the march end it would cut
// off the dense bottom of the haze (contours/speckle across the disc); the
// analytic surface must win unless the scene is nearer by more than a quantum.
TEST_F(AtmospherePassTest, DiscHazeIgnoresDepthQuantisationAtProductionPlanes) {
    auto geo = load_planet(true);
    ASSERT_TRUE(geo->sphere_map.has_value());
    scenegraph::World world;
    const glm::mat4 world_m = scaled(kScale);
    auto iid = add(world, geo, world_m);
    world.set_atmosphere(iid, atmo(true));
    const glm::vec3 center =
        glm::vec3(world_m * glm::vec4(geo->sphere_map->center_body, 1.0f));
    const float r = geo->sphere_map->radius * kScale;
    scenegraph::Camera cam;
    cam.eye = center + glm::vec3(0.0f, 0.0f, 15.0f * r);
    cam.target = center;
    cam.aspect = 1.0f;
    cam.near = 1.0f;
    cam.far = 1.8e6f;
    const glm::vec3 sun_dir_ws = glm::normalize(glm::vec3(1.0f, 0.0f, 1.0f));
    const glm::vec3 sun_color(1.5f, 1.2f, 0.8f);
    const auto lighting = sun_lighting(sun_dir_ws, sun_color);
    const auto suns = suns_at(center + sun_dir_ws * 1e6f);

    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    draw_opaque(world, cam, lighting, hdr);
    const auto before = read_rgba(hdr);
    int first = 0, last = 0;
    silhouette(before, first, last);
    ASSERT_GT(last - first, 16) << "disc too small to sample";
    renderer::AtmospherePass pass;
    draw_atmosphere(pass, world, cam, lighting, suns, hdr);
    const auto after = read_rgba(hdr);

    const renderer::planet_atmo::Shell shell{center, r, r * (1.0f + kThickness)};
    const renderer::planet_atmo::Params params{glm::vec3(1.0f), kThickness, kDensity};
    const glm::vec3 sun_dir = renderer::planet_atmo::sun_dir_for(center, suns, sun_dir_ws);
    const float intensity = scenegraph::Instance::Atmosphere{}.intensity;
    const int row = kSize / 2;
    int checked = 0, bad = 0;
    float worst = 0.0f;
    // Interior disc pixels only (stay a few px inside the silhouette).
    for (int x = first + 4; x <= last - 4; ++x) {
        const glm::vec3 added = rgb(after, x, row) - rgb(before, x, row);
        const glm::vec3 expected = renderer::planet_atmo::in_scatter(
            shell, params, cam.eye, pixel_ray(cam, x, row),
            std::numeric_limits<float>::infinity(), sun_dir) * sun_color * intensity;
        if (!(expected.g > 0.0f)) continue;
        ++checked;
        const float err = std::abs(added.g - expected.g) / expected.g;
        worst = std::max(worst, err);
        if (err > 0.05f) ++bad;
    }
    ASSERT_GT(checked, 8);
    EXPECT_EQ(bad, 0) << bad << "/" << checked << " disc pixels off by >5%; worst "
                      << worst;
}

TEST_F(AtmospherePassTest, DisabledAtmosphereDrawsNothing) {
    auto geo = load_planet(true);
    scenegraph::World world;
    auto iid = add(world, geo, scaled(kScale));
    world.set_atmosphere(iid, atmo(false));
    const auto cam = far_camera();
    const auto lighting = sun_lighting({1, 0, 0}, glm::vec3(1.0f));
    const auto suns = suns_at({1e6f, 0, 0});

    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    draw_opaque(world, cam, lighting, hdr);
    const auto before = read_rgba(hdr);

    hdr.bind();
    GLboolean depth_test = glIsEnabled(GL_DEPTH_TEST);
    GLboolean blend = glIsEnabled(GL_BLEND);
    GLboolean cull = glIsEnabled(GL_CULL_FACE);
    GLboolean depth_mask = GL_FALSE;
    glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_mask);

    renderer::AtmospherePass pass;
    draw_atmosphere(pass, world, cam, lighting, suns, hdr);
    EXPECT_EQ(pass.last_draw_count(), 0);
    EXPECT_EQ(glIsEnabled(GL_DEPTH_TEST), depth_test);
    EXPECT_EQ(glIsEnabled(GL_BLEND), blend);
    EXPECT_EQ(glIsEnabled(GL_CULL_FACE), cull);
    GLboolean depth_mask_after = GL_FALSE;
    glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_mask_after);
    EXPECT_EQ(depth_mask_after, depth_mask);

    const auto after = read_rgba(hdr);
    EXPECT_EQ(before, after);
}

// The pass detaches the depth texture from the bound framebuffer while it
// samples it (a same-FBO feedback loop is undefined), so it must re-attach it
// and hand the following phase-2 passes their expected state: depth test and
// writes on, blend off, back-face culling.
TEST_F(AtmospherePassTest, DrawLeavesDepthAttachedAndStateRestored) {
    auto geo = load_planet(true);
    scenegraph::World world;
    auto iid = add(world, geo, scaled(kScale));
    world.set_atmosphere(iid, atmo(true));
    const auto cam = far_camera();
    const auto lighting = sun_lighting({1, 0, 0}, glm::vec3(1.0f));
    const auto suns = suns_at({1e6f, 0, 0});

    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    draw_opaque(world, cam, lighting, hdr);
    renderer::AtmospherePass pass;
    draw_atmosphere(pass, world, cam, lighting, suns, hdr);
    ASSERT_EQ(pass.last_draw_count(), 1);

    GLint fbo = 0;
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &fbo);
    EXPECT_EQ(static_cast<std::uint32_t>(fbo), hdr.fbo());
    GLint name = 0;
    glGetFramebufferAttachmentParameteriv(GL_DRAW_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT,
                                          GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME, &name);
    EXPECT_EQ(static_cast<std::uint32_t>(name), hdr.depth_texture());
    EXPECT_EQ(glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER),
              static_cast<GLenum>(GL_FRAMEBUFFER_COMPLETE));

    EXPECT_TRUE(glIsEnabled(GL_DEPTH_TEST));
    EXPECT_FALSE(glIsEnabled(GL_BLEND));
    EXPECT_TRUE(glIsEnabled(GL_CULL_FACE));
    GLint cull = 0;
    glGetIntegerv(GL_CULL_FACE_MODE, &cull);
    EXPECT_EQ(cull, GL_BACK);
    GLboolean depth_mask = GL_FALSE;
    glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_mask);
    EXPECT_EQ(depth_mask, GL_TRUE);
    GLint vao = -1;
    glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao);
    EXPECT_EQ(vao, 0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(AtmospherePassTest, NonGeosphereModelIsSkipped) {
    auto plain = load_planet(false);
    ASSERT_FALSE(plain->sphere_map.has_value());
    scenegraph::World world;
    auto iid = add(world, plain, scaled(kScale));
    world.set_atmosphere(iid, atmo(true));
    const auto cam = far_camera();
    const auto lighting = sun_lighting({1, 0, 0}, glm::vec3(1.0f));
    const auto suns = suns_at({1e6f, 0, 0});

    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    draw_opaque(world, cam, lighting, hdr);
    const auto before = read_rgba(hdr);
    renderer::AtmospherePass pass;
    draw_atmosphere(pass, world, cam, lighting, suns, hdr);
    EXPECT_EQ(pass.last_draw_count(), 0);
    EXPECT_EQ(before, read_rgba(hdr));
}

}  // namespace
