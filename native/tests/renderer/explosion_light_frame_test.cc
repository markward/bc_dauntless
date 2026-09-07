// Does an explosion light of the SHIPPED parameters actually put light on a
// neighbouring hull?
//
// The fireball lights were reported invisible in game. Three fixes reasoned
// from the attenuation formula did not change that, so this measures the
// rendered pixels instead of arguing about the maths.
#include <gtest/gtest.h>
#include <glad/glad.h>

#include <assets/mesh.h>
#include <assets/model.h>
#include <renderer/dynamic_lights.h>
#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>
#include <scenegraph/world.h>

#include <glm/glm.hpp>

#include <cstdio>
#include <memory>
#include <vector>

namespace {

// A plane standing in for a hull surface, `half` GU to a side, facing +Z.
assets::Model make_plane_model(float half) {
    assets::MeshCpu cpu;
    cpu.vertices.resize(4);
    cpu.vertices[0].position = {-half, -half, 0.0f};
    cpu.vertices[1].position = { half, -half, 0.0f};
    cpu.vertices[2].position = { half,  half, 0.0f};
    cpu.vertices[3].position = {-half,  half, 0.0f};
    // Normals face the camera and the light, so nl > 0 and the dynamic-light
    // term is actually exercised.
    for (auto& v : cpu.vertices) v.normal = glm::vec3(0.0f, 0.0f, 1.0f);
    cpu.indices = {0, 1, 2, 0, 2, 3};

    assets::Model m;
    assets::Mesh mesh = assets::upload_mesh(cpu);
    mesh.set_cpu_data(cpu);
    m.meshes.push_back(std::move(mesh));

    assets::Node root;
    root.name = "root";
    root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    root.meshes = {0};
    m.nodes.push_back(std::move(root));
    m.root_node = 0;
    return m;
}

int read_center_total(int size) {
    unsigned char px[4] = {0, 0, 0, 0};
    glReadPixels(size / 2, size / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    return px[0] + px[1] + px[2];
}

constexpr int kSize = 128;

class ExplosionLightFrameTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kSize, kSize,
                                                   "explosion-light-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        renderer::reset_model_radius_cache();
        renderer::reset_damage_decal_texture();
    }

    /// Render a hull plane and return the centre pixel's summed brightness.
    /// `dist` is how far the explosion light sits from the surface, in GU.
    /// A negative `dist` means "no explosion light at all" (the baseline).
    int render(float dist, float intensity, float radius, float ambient) {
        assets::Model plane = make_plane_model(60.0f);
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(&plane));
        world.set_world_transform(iid, glm::mat4(1.0f));

        scenegraph::Camera cam;
        cam.eye    = glm::vec3(0.0f, 0.0f, 300.0f);
        cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
        cam.aspect = 1.0f;

        std::vector<renderer::DynamicLightDescriptor> lights;
        if (dist >= 0.0f) {
            renderer::DynamicLightDescriptor l;
            l.pos_a = l.pos_b = glm::vec3(0.0f, 0.0f, dist);
            l.color = glm::vec3(1.0f, 0.62f, 0.28f);   // explosion_lights.COLOR
            l.radius = radius;
            l.intensity = intensity;
            l.spot_tan_x = -1.0f;                      // point light, not a cone
            l.spot_tan_y = -1.0f;
            lights.push_back(l);
        }

        glViewport(0, 0, kSize, kSize);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        renderer::FrameSubmitter submitter;
        renderer::Lighting lighting;
        lighting.ambient = glm::vec3(ambient);
        lighting.directional_count = 0;
        submitter.submit_opaque(world, cam, *p,
            [](scenegraph::ModelHandle h) -> const assets::Model* {
                return reinterpret_cast<const assets::Model*>(h);
            }, lighting, /*decal_time=*/0.0f, /*carve_cache=*/nullptr, &lights);
        EXPECT_EQ(glGetError(), GL_NO_ERROR);
        return read_center_total(kSize);
    }
};

// Diagnostic: prints the numbers rather than asserting a threshold, so the
// shipped parameters can be read off directly.
TEST_F(ExplosionLightFrameTest, DiagnosticSweepOfShippedParameters) {
    const float kShippedIntensity = 6.0f;    // explosion_lights.PEAK_INTENSITY
    const float kWarbirdRadius   = 110.0f;   // 11 GU fireball x RADIUS_FACTOR 10
    const float kOldRadius       = 33.0f;    // what originally shipped

    std::printf("\n  baseline, no explosion light, ambient 0.0 : %d\n",
                render(-1.0f, 0.0f, 0.0f, 0.0f));
    std::printf("  shipped light at  5 GU (r=110, i=6)       : %d\n",
                render(5.0f, kShippedIntensity, kWarbirdRadius, 0.0f));
    std::printf("  shipped light at 20 GU (r=110, i=6)       : %d\n",
                render(20.0f, kShippedIntensity, kWarbirdRadius, 0.0f));
    std::printf("  shipped light at 40 GU (r=110, i=6)       : %d\n",
                render(40.0f, kShippedIntensity, kWarbirdRadius, 0.0f));
    std::printf("  OLD radius   at 20 GU (r=33,  i=6)        : %d\n",
                render(20.0f, kShippedIntensity, kOldRadius, 0.0f));
    std::printf("  shipped light at 20 GU, ambient 0.04      : %d\n",
                render(20.0f, kShippedIntensity, kWarbirdRadius, 0.04f));
    std::printf("  baseline      at ambient 0.04, no light   : %d\n",
                render(-1.0f, 0.0f, 0.0f, 0.04f));

    // Intensity sweep at a close-quarters separation, to pick a peak that
    // reads bright without blowing out. 765 is fully saturated white.
    std::printf("\n  intensity sweep, r=110, ambient 0.04:\n");
    for (float i : {0.5f, 1.0f, 1.5f, 2.0f, 3.0f, 4.0f, 6.0f}) {
        std::printf("    i=%-4.1f  d=10GU: %-4d  d=20GU: %-4d  d=40GU: %-4d\n",
                    i, render(10.0f, i, kWarbirdRadius, 0.04f),
                    render(20.0f, i, kWarbirdRadius, 0.04f),
                    render(40.0f, i, kWarbirdRadius, 0.04f));
    }
    SUCCEED();
}

// The claim the feature rests on: at a realistic separation the light is
// measurably brighter than the same frame without it.
// Pins the RENDERER's behaviour, not the Python tuning: an explosion-scale
// light must measurably brighten a hull at a realistic separation, and a
// hull-scale one must not. The Python side owns the shipped values and guards
// them separately (tests/unit/test_dynamic_light_scope.py) -- duplicating them
// here would just create two homes for one number.
TEST_F(ExplosionLightFrameTest, ExplosionScaleLightBrightensAHullAt20GU) {
    const int dark = render(-1.0f, 0.0f, 0.0f, 0.04f);
    const int lit  = render(20.0f, 1.5f, 110.0f, 0.04f);
    EXPECT_GT(lit, dark + 100)
        << "an explosion-scale light barely changed a hull 20 GU away ("
        << dark << " -> " << lit << ")";
}

// The fault that made the feature invisible: a radius under the renderer's
// 40 GU ship-scale ceiling falls back to the hull-local 1/(d^2+1) curve and
// delivers essentially nothing at inter-ship range. Pinning it here means the
// arithmetic argument is backed by a measurement.
TEST_F(ExplosionLightFrameTest, HullScaleRadiusCannotReachANeighbouringHull) {
    const int dark  = render(-1.0f, 0.0f, 0.0f, 0.04f);
    const int under = render(20.0f, 1.5f, 33.0f, 0.04f);   // under the ceiling
    EXPECT_LT(under, dark + 10)
        << "a sub-ceiling radius unexpectedly carried 20 GU (" << dark
        << " -> " << under << "); if the falloff changed, the explosion "
           "radius floor should be revisited";
}

}  // namespace
