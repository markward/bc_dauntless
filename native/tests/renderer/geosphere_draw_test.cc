// native/tests/renderer/geosphere_draw_test.cc
//
// Planet geosphere draw (spec docs/superpowers/specs/2026-10-06-planet-geosphere-design.md
// §4.3-4.4): the per-camera LOD pick, draw_model's LOD substitution, and the
// sphere-mapped normal + UV in opaque.frag.
#include <gtest/gtest.h>

#include <renderer/frame.h>
#include <renderer/scuff_texture.h>
#include <renderer/hdr_target.h>
#include <renderer/nonfinite_probe.h>
#include <renderer/pipeline.h>
#include <renderer/shader.h>
#include <renderer/window.h>

#include <glad/glad.h>

#include <glm/gtc/matrix_transform.hpp>

#include <scenegraph/world.h>
#include <scenegraph/camera.h>

#include <assets/cache.h>
#include <assets/geosphere.h>
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

constexpr float kIceRadius = 90.0099f;   // IcePlanet.NIF sphere radius, model units

// Instance-world helper: uniform scale s at the origin.
glm::mat4 scaled(float s) { return glm::scale(glm::mat4(1.0f), glm::vec3(s)); }

class GeosphereDrawTest : public ::testing::Test {
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
            w = std::make_unique<renderer::Window>(256, 256, "geosphere-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        // Real GL upload, with CPU data retained exactly as the production
        // host cache does (host_bindings.cc): apply_geosphere's sphere gate
        // reads the source mesh's MeshCpu, so a default (keep_cpu_data =
        // false) cache never builds a sphere_map.
        assets::AssetCache::Config cfg;
        cfg.keep_cpu_data = true;
        cache = std::make_unique<assets::AssetCache>(cfg);
    }

    // Same session-scoped resets as FrameTest (frame_test.cc).
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

    // Draw one instance of `model` at `world_m` into `hdr` through the real
    // production submit path: the host (host_bindings.cc) only ever calls
    // submit_opaque_in_pass, never submit_opaque.
    void draw_one(const assets::ModelHandle& model, const glm::mat4& world_m,
                  const scenegraph::Camera& cam, renderer::HdrTarget& hdr) {
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model.get()));
        world.set_world_transform(iid, world_m);
        hdr.bind();
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        renderer::FrameSubmitter submitter;
        renderer::Lighting lighting;
        submitter.submit_opaque_in_pass(world, cam, *p,
            [](scenegraph::ModelHandle h) -> const assets::Model* {
                return reinterpret_cast<const assets::Model*>(h);
            }, lighting, scenegraph::Pass::Space);
    }

    // Primitives the production draw of `model` emits, counted by a
    // GL_PRIMITIVES_GENERATED query (core in GL 4.1).
    GLuint primitives_drawn(const assets::ModelHandle& model, const glm::mat4& world_m,
                            const scenegraph::Camera& cam, renderer::HdrTarget& hdr) {
        GLuint q = 0;
        glGenQueries(1, &q);
        glBeginQuery(GL_PRIMITIVES_GENERATED, q);
        draw_one(model, world_m, cam, hdr);
        glEndQuery(GL_PRIMITIVES_GENERATED);
        GLuint n = 0;
        glGetQueryObjectuiv(q, GL_QUERY_RESULT, &n);
        glDeleteQueries(1, &q);
        return n;
    }

    // 20*4^L triangles for the geosphere LOD at index `idx`.
    static GLuint lod_triangles(int idx) {
        const int level = assets::kGeosphereLevels[static_cast<std::size_t>(idx)];
        return 20u * (1u << (2 * level));
    }

    // RGBA float readback of the whole target.
    static std::vector<float> read_rgba(const renderer::HdrTarget& hdr) {
        std::vector<float> px(static_cast<std::size_t>(hdr.width() * hdr.height() * 4), 0.0f);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, hdr.fbo());
        glReadPixels(0, 0, hdr.width(), hdr.height(), GL_RGBA, GL_FLOAT, px.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        return px;
    }

    static float lum(const std::vector<float>& px, int width, int x, int y) {
        const std::size_t i = static_cast<std::size_t>((y * width + x) * 4);
        return 0.2126f * px[i] + 0.7152f * px[i + 1] + 0.0722f * px[i + 2];
    }
};

TEST_F(GeosphereDrawTest, NonSphereModelHasNoLevel) {
    auto galaxy = cache->load(kGalaxyNif, kGalaxyTex);
    scenegraph::Camera cam;
    cam.eye = {0, 0, 1500}; cam.target = {0, 0, 0}; cam.aspect = 1.0f;
    EXPECT_EQ(renderer::geosphere_level_for(*galaxy, glm::mat4(1.0f), cam), -1);
}

TEST_F(GeosphereDrawTest, ScaledInstanceUsesWorldRadius) {
    auto geo = load_planet(/*geosphere=*/true);
    ASSERT_TRUE(geo->sphere_map.has_value());
    glViewport(0, 0, 256, 256);
    scenegraph::Camera cam; cam.aspect = 1.0f;
    cam.eye = {0, 0, kIceRadius * 20.0f + 100.0f}; cam.target = {0, 0, 0};

    const glm::mat4 world_m = scaled(20.0f);
    const float focal = cam.proj_matrix()[1][1] * 128.0f;
    const glm::vec3 c =
        glm::vec3(world_m * glm::vec4(geo->sphere_map->center_body, 1.0f));
    const float d = glm::length(cam.eye - c);

    const int at_scale = renderer::geosphere_level_for(*geo, world_m, cam);
    const int expected = assets::pick_geosphere_level(kIceRadius * 20.0f, d, focal);
    const int ignoring_scale = assets::pick_geosphere_level(kIceRadius, d, focal);
    EXPECT_EQ(at_scale, expected);
    EXPECT_GT(at_scale, ignoring_scale);
}

TEST_F(GeosphereDrawTest, PickUsesBoundViewportHeight) {
    auto geo = load_planet(true);
    scenegraph::Camera cam; cam.aspect = 1.0f;
    cam.eye = {0, 0, kIceRadius * 20.0f + 150.0f}; cam.target = {0, 0, 0};
    glViewport(0, 0, 64, 64);
    const int small = renderer::geosphere_level_for(*geo, scaled(20.0f), cam);
    glViewport(0, 0, 4096, 4096);
    const int big = renderer::geosphere_level_for(*geo, scaled(20.0f), cam);
    glViewport(0, 0, 256, 256);
    EXPECT_GT(big, small);
}

TEST_F(GeosphereDrawTest, SphereMappedPlanetDrawsLitAndFinite) {
    auto geo = load_planet(true);
    ASSERT_TRUE(geo->sphere_map.has_value());

    // Eye on +Z, 160 units from the centre of a 90-unit sphere: its angular
    // radius (34 deg) exceeds the 30-deg half-FOV, so the planet covers every
    // pixel of the 256x256 view.
    const glm::vec3 c = geo->sphere_map->center_body;
    scenegraph::Camera cam;
    cam.eye = c + glm::vec3(0.0f, 0.0f, 160.0f);
    cam.target = c;
    cam.aspect = 1.0f;

    // A float target: an 8-bit backbuffer cannot hold a NaN.
    renderer::HdrTarget hdr;
    hdr.resize(256, 256);
    draw_one(geo, glm::mat4(1.0f), cam, hdr);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    renderer::NonfiniteProbe probe;
    const auto& r = probe.run(hdr.color_texture(), 256, 256);
    EXPECT_FALSE(r.any)
        << r.flagged_cells << " cell(s) of the sphere-mapped planet hold NaN/Inf"
        << " (cause code " << r.max_code << ")";

    const auto px = read_rgba(hdr);
    int nonfinite = 0;
    for (float v : px) if (!std::isfinite(v)) ++nonfinite;
    EXPECT_EQ(nonfinite, 0);
    EXPECT_GT(lum(px, 256, 128, 128), 0.0f) << "planet centre was black";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(GeosphereDrawTest, NoSeamDiscontinuityAcrossThePlusYMeridian) {
    auto geo = load_planet(true);
    ASSERT_TRUE(geo->sphere_map.has_value());

    // BC's seam (u = 0/1) is the +Y half of the x = 0 plane, body frame. Eye
    // on +Y with Z up: the seam meridian projects to a vertical line near the
    // screen centre. 160 units from a 90-unit sphere fills the centre row.
    //
    // The camera is slid ONE PIXEL sideways (pixel footprint at the 70-unit
    // surface depth: 2*70*tan(30deg)/256 = 0.3157). Dead centre, the seam
    // falls on the x = 128 boundary between two 2x2 derivative quads, so no
    // quad straddles it and even an implicit-derivative fetch shows no
    // stripe -- measured: the test then passes with textureGrad replaced by
    // texture(). One pixel over, the seam splits a quad.
    const glm::vec3 c = geo->sphere_map->center_body;
    const glm::vec3 slide(0.3157f, 0.0f, 0.0f);
    scenegraph::Camera cam;
    cam.eye = c + slide + glm::vec3(0.0f, 160.0f, 0.0f);
    cam.target = c + slide;
    cam.up = glm::vec3(0.0f, 0.0f, 1.0f);
    cam.aspect = 1.0f;

    renderer::HdrTarget hdr;
    hdr.resize(256, 256);
    draw_one(geo, glm::mat4(1.0f), cam, hdr);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    const auto px = read_rgba(hdr);
    const int row = 128;
    float seam_max = 0.0f;
    float other_max = 0.0f;
    // Interior of the row only: away from the viewport edges.
    for (int x = 32; x < 224; ++x) {
        const float dl = std::fabs(lum(px, 256, x + 1, row) - lum(px, 256, x, row));
        if (x >= 124 && x <= 131) seam_max = std::max(seam_max, dl);
        else                      other_max = std::max(other_max, dl);
    }
    EXPECT_GT(lum(px, 256, 128, row), 0.0f) << "seam row was black";
    EXPECT_GT(other_max, 0.0f) << "row has no texture variation to compare against";
    EXPECT_LE(seam_max, other_max * 1.5f)
        << "seam column jump " << seam_max << " vs largest elsewhere " << other_max;
}

TEST_F(GeosphereDrawTest, SphereMapFlagOffMatchesThePlainNif) {
    auto geo = load_planet(true);
    auto plain = load_planet(false);
    ASSERT_TRUE(geo->sphere_map.has_value());
    ASSERT_FALSE(plain->sphere_map.has_value());

    const glm::vec3 c = geo->sphere_map->center_body;
    scenegraph::Camera cam;
    cam.eye = c + glm::vec3(0.0f, 0.0f, 160.0f);
    cam.target = c;
    cam.aspect = 1.0f;

    renderer::HdrTarget hdr;
    hdr.resize(256, 256);
    const GLuint prog = p->opaque_shader().program();
    const GLint loc = glGetUniformLocation(prog, "u_sphere_map");
    ASSERT_GE(loc, 0) << "opaque program has no u_sphere_map uniform";

    // Draw the geosphere first: it sets u_sphere_map = 1 on the program.
    draw_one(geo, glm::mat4(1.0f), cam, hdr);
    GLint v = -1;
    glGetUniformiv(prog, loc, &v);
    EXPECT_EQ(v, 1) << "the geosphere draw did not set u_sphere_map";

    // The plain draw must reset it -- uniforms persist between draws.
    draw_one(plain, glm::mat4(1.0f), cam, hdr);
    v = -1;
    glGetUniformiv(prog, loc, &v);
    EXPECT_EQ(v, 0) << "u_sphere_map leaked from the previous draw";

    const auto px = read_rgba(hdr);
    EXPECT_GT(lum(px, 256, 128, 128), 0.0f) << "plain planet centre was black";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// --- LOD substitution through the production path (submit_opaque_in_pass) ---

TEST_F(GeosphereDrawTest, InPassDrawsTheCameraLevelLod) {
    auto geo = load_planet(true);
    ASSERT_TRUE(geo->sphere_map.has_value());
    renderer::HdrTarget hdr;
    hdr.resize(256, 256);   // binds a 256x256 viewport in draw_one
    hdr.bind();
    const glm::vec3 c = geo->sphere_map->center_body;
    scenegraph::Camera cam;
    cam.eye = c + glm::vec3(0.0f, 0.0f, 120.0f);
    cam.target = c;
    cam.aspect = 1.0f;
    const int idx = renderer::geosphere_level_for(*geo, glm::mat4(1.0f), cam);
    // Index 0 is level 3 = 1,280 triangles, the same count as BC's own mesh:
    // a camera picking it could not tell the LOD from the source mesh.
    ASSERT_GT(idx, 0);
    EXPECT_EQ(primitives_drawn(geo, glm::mat4(1.0f), cam, hdr), lod_triangles(idx))
        << "level index " << idx;
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(GeosphereDrawTest, InPassPlainLoadDrawsBcsOwnMesh) {
    auto plain = load_planet(false);
    ASSERT_FALSE(plain->sphere_map.has_value());
    renderer::HdrTarget hdr;
    hdr.resize(256, 256);
    hdr.bind();
    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 0.0f, 400.0f);
    cam.target = glm::vec3(0.0f);
    cam.aspect = 1.0f;
    EXPECT_EQ(primitives_drawn(plain, glm::mat4(1.0f), cam, hdr), 1280u);
}

TEST_F(GeosphereDrawTest, InPassDifferentDistancesDrawDifferentLods) {
    auto geo = load_planet(true);
    ASSERT_TRUE(geo->sphere_map.has_value());
    renderer::HdrTarget hdr;
    hdr.resize(256, 256);
    hdr.bind();
    const glm::vec3 c = geo->sphere_map->center_body;
    scenegraph::Camera near_cam, far_cam;
    near_cam.eye = c + glm::vec3(0.0f, 0.0f, 120.0f);
    far_cam.eye = c + glm::vec3(0.0f, 0.0f, 4000.0f);
    near_cam.target = far_cam.target = c;
    near_cam.aspect = far_cam.aspect = 1.0f;
    const int near_idx = renderer::geosphere_level_for(*geo, glm::mat4(1.0f), near_cam);
    const int far_idx = renderer::geosphere_level_for(*geo, glm::mat4(1.0f), far_cam);
    ASSERT_NE(near_idx, far_idx) << "cameras must pick different levels";
    const GLuint near_n = primitives_drawn(geo, glm::mat4(1.0f), near_cam, hdr);
    const GLuint far_n = primitives_drawn(geo, glm::mat4(1.0f), far_cam, hdr);
    EXPECT_EQ(near_n, lod_triangles(near_idx));
    EXPECT_EQ(far_n, lod_triangles(far_idx));
    EXPECT_NE(near_n, far_n);
}

}  // namespace
