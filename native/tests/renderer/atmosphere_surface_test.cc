// native/tests/renderer/atmosphere_surface_test.cc
//
// Planet surface atmosphere (spec docs/superpowers/specs/2026-10-07-planet-atmosphere-design.md
// §6): opaque.frag's geosphere branch hazes the surface toward the air colour
// at grazing view angles (Fresnel limb) and tints the sun-grazing band with the
// sunset colour (terminator). Fed per draw from Instance::atmosphere through
// submit_opaque_in_pass -> draw_model; off (u_atmo_enabled == 0) on every other
// draw, byte-identically.
#include <gtest/gtest.h>

#include <renderer/frame.h>
#include <renderer/hdr_target.h>
#include <renderer/nonfinite_probe.h>
#include <renderer/pipeline.h>
#include <renderer/scuff_texture.h>
#include <renderer/shader.h>
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
#include <vector>

#include "support/content_root.h"

namespace {

using test_support::game_root;

const std::filesystem::path kGalaxyNif =
    game_root() / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif";
const std::filesystem::path kGalaxyTex =
    game_root() / "data" / "Models" / "SharedTextures" / "FedShips" / "High";
const std::filesystem::path kEnvDir =
    game_root() / "data" / "Models" / "Environment";
const std::filesystem::path kIcePlanetNif = kEnvDir / "IcePlanet.NIF";

constexpr int kSize = 256;

renderer::FrameSubmitter::ModelLookup handle_lookup() {
    return [](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h);
    };
}

class AtmosphereSurfaceTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<assets::AssetCache> cache;

    void SetUp() override {
        if (!std::filesystem::is_regular_file(kIcePlanetNif)) {
            GTEST_SKIP() << "BC asset not available at " << kIcePlanetNif;
        }
        if (!std::filesystem::is_regular_file(kGalaxyNif)) {
            GTEST_SKIP() << "BC asset not available at " << kGalaxyNif;
        }
        try {
            w = std::make_unique<renderer::Window>(kSize, kSize, "atmo-surface-test", false);
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

    assets::ModelHandle load_planet() {
        return cache->load(kIcePlanetNif, std::vector<std::filesystem::path>{kEnvDir},
                           {}, {}, 1.0f, /*geosphere=*/true);
    }

    static scenegraph::InstanceId add(scenegraph::World& world,
                                      const assets::ModelHandle& model,
                                      const glm::mat4& world_m) {
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model.get()));
        world.set_world_transform(iid, world_m);
        return iid;
    }

    static renderer::Lighting sun_lighting(glm::vec3 sun_dir, float ambient) {
        renderer::Lighting l;
        l.ambient = glm::vec3(ambient);
        l.directional_count = 1;
        l.directional_dir_ws[0] = glm::normalize(sun_dir);
        l.directional_color[0] = glm::vec3(1.0f);
        return l;
    }

    // Camera on +Z at 400 units from a 90-unit sphere: the whole disc, with
    // black space around its silhouette, is in view.
    static scenegraph::Camera planet_camera(const assets::Model& geo) {
        const glm::vec3 c = geo.sphere_map->center_body;
        scenegraph::Camera cam;
        cam.eye = c + glm::vec3(0.0f, 0.0f, 400.0f);
        cam.target = c;
        cam.aspect = 1.0f;
        return cam;
    }

    void draw(const scenegraph::World& world, const scenegraph::Camera& cam,
              const renderer::Lighting& lighting, renderer::HdrTarget& hdr,
              const std::vector<renderer::SunDescriptor>* suns = nullptr) {
        hdr.bind();
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        renderer::FrameSubmitter submitter;
        submitter.submit_opaque_in_pass(world, cam, *p, handle_lookup(), lighting,
                                        scenegraph::Pass::Space, 0.0f, nullptr, 1.0f,
                                        nullptr, nullptr, suns);
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

    // Last centre-row column with luminance > 0 (the +X silhouette edge).
    static int last_lit_column(const std::vector<float>& px) {
        int last = -1;
        for (int x = 0; x < kSize; ++x)
            if (lum(px, x, kSize / 2) > 0.0f) last = x;
        return last;
    }

    // First centre-row column (scanning from -X) with luminance > 0.
    static int first_lit_column(const std::vector<float>& px) {
        for (int x = 0; x < kSize; ++x)
            if (lum(px, x, kSize / 2) > 0.0f) return x;
        return -1;
    }

    static scenegraph::Instance::Atmosphere limb_atmo(bool enabled) {
        scenegraph::Instance::Atmosphere a;
        a.enabled = enabled;
        a.color = glm::vec3(0.0f, 0.0f, 1.0f);
        a.sunset_color = glm::vec3(1.0f);
        a.thickness = 0.06f;
        a.density = 1.4f;
        a.limb = 4.0f;
        return a;
    }

    static scenegraph::Instance::Atmosphere sunset_atmo(bool enabled) {
        scenegraph::Instance::Atmosphere a;
        a.enabled = enabled;
        a.color = glm::vec3(1.0f);
        a.sunset_color = glm::vec3(1.0f, 0.0f, 0.0f);
        a.thickness = 0.06f;
        a.density = 1.4f;
        a.limb = 0.0f;   // isolate the terminator from the limb haze
        return a;
    }

    // Limb frame: sun from the camera side, blue air, limb 4.
    std::vector<float> limb_frame(bool enabled, renderer::HdrTarget& hdr) {
        auto geo = load_planet();
        EXPECT_TRUE(geo->sphere_map.has_value());
        scenegraph::World world;
        auto iid = add(world, geo, glm::mat4(1.0f));
        world.set_atmosphere(iid, limb_atmo(enabled));
        draw(world, planet_camera(*geo), sun_lighting({0, 0, 1}, 0.1f), hdr);
        return read_rgba(hdr);
    }

    // Terminator frame: sun along +X, camera on +Z, no ambient (so the first
    // lit column from -X is where the sun's direct term starts).
    std::vector<float> terminator_frame(bool enabled, renderer::HdrTarget& hdr,
                                        glm::vec3 fallback_dir = {1, 0, 0},
                                        const std::vector<renderer::SunDescriptor>* suns
                                            = nullptr) {
        auto geo = load_planet();
        EXPECT_TRUE(geo->sphere_map.has_value());
        scenegraph::World world;
        auto iid = add(world, geo, glm::mat4(1.0f));
        world.set_atmosphere(iid, sunset_atmo(enabled));
        draw(world, planet_camera(*geo), sun_lighting(fallback_dir, 0.0f), hdr, suns);
        return read_rgba(hdr);
    }
};

TEST_F(AtmosphereSurfaceTest, LimbHazeTintsTheEdge) {
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    const auto off = limb_frame(false, hdr);
    const auto on = limb_frame(true, hdr);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    const int last = last_lit_column(off);
    ASSERT_GT(last, kSize / 2);
    ASSERT_LT(last, kSize - 3) << "silhouette must be in view";
    const int x = last - 1;   // just inside the silhouette, lit side
    const int y = kSize / 2;
    const glm::vec3 a = rgb(off, x, y);
    const glm::vec3 b = rgb(on, x, y);
    ASSERT_GT(a.r, 0.0f);
    ASSERT_GT(b.r + b.b, 0.0f);
    const float ratio_off = a.b / a.r;
    const float ratio_on = b.b / std::max(b.r, 1e-6f);
    EXPECT_GT(ratio_on, ratio_off)
        << "limb b/r on " << ratio_on << " vs off " << ratio_off;
}

TEST_F(AtmosphereSurfaceTest, TerminatorTakesTheSunsetTint) {
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    const auto off = terminator_frame(false, hdr);
    const auto on = terminator_frame(true, hdr);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    const int x = first_lit_column(off);
    ASSERT_GT(x, 0);
    const int y = kSize / 2;
    const glm::vec3 a = rgb(off, x, y);
    const glm::vec3 b = rgb(on, x, y);
    ASSERT_GT(a.g, 0.0f);
    const float rg_off = a.r / a.g;
    const float rg_on = b.r / std::max(b.g, 1e-6f);
    EXPECT_GT(rg_on, rg_off) << "terminator r/g on " << rg_on << " vs off " << rg_off
                             << " at column " << x;
}

// The submitter's sun direction comes from the system's suns when given, not
// from directional 0. The diffuse light stays on +X in both frames (so the
// terminator column is fixed); only the sun LIST moves: on +X it grazes that
// column and tints it, on +Z (behind the camera) it is overhead there and
// does not. A submitter that ignored the list would draw both frames alike.
TEST_F(AtmosphereSurfaceTest, TerminatorFollowsTheSunList) {
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    const auto off = terminator_frame(false, hdr);
    const int x = first_lit_column(off);
    ASSERT_GT(x, 0);

    renderer::SunDescriptor s;
    s.radius = 1000.0f;
    s.position = glm::vec3(1e6f, 0.0f, 0.0f);
    const std::vector<renderer::SunDescriptor> grazing{s};
    s.position = glm::vec3(0.0f, 0.0f, 1e6f);
    const std::vector<renderer::SunDescriptor> overhead{s};
    const auto with_grazing = terminator_frame(true, hdr, {1, 0, 0}, &grazing);
    const auto with_overhead = terminator_frame(true, hdr, {1, 0, 0}, &overhead);

    const int y = kSize / 2;
    const glm::vec3 a = rgb(with_grazing, x, y);
    const glm::vec3 b = rgb(with_overhead, x, y);
    ASSERT_GT(a.g, 0.0f);
    ASSERT_GT(b.g, 0.0f);
    EXPECT_GT(a.r / a.g, b.r / b.g)
        << "a grazing sun in the list should tint the terminator more than an overhead one";
}

TEST_F(AtmosphereSurfaceTest, DisabledAtmosphereIsByteIdentical) {
    auto geo = load_planet();
    ASSERT_TRUE(geo->sphere_map.has_value());
    const auto cam = planet_camera(*geo);
    const auto lighting = sun_lighting({0.6f, 0.0f, 0.8f}, 0.1f);
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);

    // SP1 path: an instance that never had an atmosphere set.
    scenegraph::World plain;
    add(plain, geo, glm::mat4(1.0f));
    draw(plain, cam, lighting, hdr);
    const auto ref = read_rgba(hdr);

    // Dirty the program: an enabled planet leaves limb 4 / blue air / a sun
    // direction in the atmo uniforms. A gate that keyed on anything but
    // u_atmo_enabled would apply those stale values to the next frame.
    limb_frame(true, hdr);

    // Same frame with a fully-populated but disabled atmosphere.
    scenegraph::World off;
    auto iid = add(off, geo, glm::mat4(1.0f));
    auto a = limb_atmo(false);
    a.sunset_color = glm::vec3(1.0f, 0.0f, 0.0f);
    off.set_atmosphere(iid, a);
    draw(off, cam, lighting, hdr);
    const auto got = read_rgba(hdr);

    ASSERT_EQ(ref.size(), got.size());
    std::size_t diffs = 0;
    for (std::size_t i = 0; i < ref.size(); ++i)
        if (ref[i] != got[i]) ++diffs;
    EXPECT_EQ(diffs, 0u) << "disabled atmosphere changed " << diffs << " channel(s)";
    EXPECT_GT(lum(ref, kSize / 2, kSize / 2), 0.0f);
}

TEST_F(AtmosphereSurfaceTest, FlagDoesNotLeakToNextDraw) {
    auto geo = load_planet();
    ASSERT_TRUE(geo->sphere_map.has_value());
    auto galaxy = cache->load(kGalaxyNif, kGalaxyTex);
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    const GLuint prog = p->opaque_shader().program();
    const GLint loc = glGetUniformLocation(prog, "u_atmo_enabled");
    ASSERT_GE(loc, 0) << "opaque program has no u_atmo_enabled uniform";

    // Planet alone first: it sets u_atmo_enabled = 1 on the program.
    {
        scenegraph::World world;
        auto iid = add(world, geo, glm::mat4(1.0f));
        world.set_atmosphere(iid, limb_atmo(true));
        draw(world, planet_camera(*geo), sun_lighting({0, 0, 1}, 0.1f), hdr);
        GLint v = -1;
        glGetUniformiv(prog, loc, &v);
        EXPECT_EQ(v, 1) << "the atmosphere planet draw did not set u_atmo_enabled";
    }

    // Planet then Galaxy in ONE submit (creation order = draw order): the
    // Galaxy draw must reset the flag -- uniforms persist between draws.
    scenegraph::World world;
    auto iid = add(world, geo, glm::mat4(1.0f));
    world.set_atmosphere(iid, limb_atmo(true));
    add(world, galaxy, glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, 200.0f)));
    draw(world, planet_camera(*geo), sun_lighting({0, 0, 1}, 0.1f), hdr);
    GLint v = -1;
    glGetUniformiv(prog, loc, &v);
    EXPECT_EQ(v, 0) << "u_atmo_enabled leaked from the planet onto the Galaxy";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(AtmosphereSurfaceTest, NoNan) {
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    const auto px = limb_frame(true, hdr);
    renderer::NonfiniteProbe probe;
    const auto& r = probe.run(hdr.color_texture(), kSize, kSize);
    EXPECT_FALSE(r.any) << r.flagged_cells << " cell(s) hold NaN/Inf (cause code "
                        << r.max_code << ")";
    int nonfinite = 0;
    for (float v : px) if (!std::isfinite(v)) ++nonfinite;
    EXPECT_EQ(nonfinite, 0);
}

}  // namespace
