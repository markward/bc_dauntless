// native/tests/renderer/plating_gl_fixture.h
//
// SPIKE (damage redesign): the window, pipeline and synthetic-geometry setup
// shared by the plating GL tests (plating_render_test.cc,
// hull_interior_test.cc). One copy, so the two suites cannot drift apart in
// how they build a probe hull or restore the plating params.
#pragma once

#include <gtest/gtest.h>

#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/plating_damage.h>
#include <renderer/scuff_texture.h>
#include <renderer/window.h>

#include <scenegraph/camera.h>
#include <scenegraph/damage_decals.h>

#include <assets/mesh.h>
#include <assets/model.h>

#include <glm/glm.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <memory>
#include <stdexcept>
#include <vector>

namespace dauntless_plating { extern float g_params[renderer::plating::kParamCount]; }

namespace plating_gl {

constexpr int kSize = 256;
// Past every flicker (FLICKER_DUR_MAX 60 s) and ember (tau ~3.1 s) of a
// record born at 0, so the stock decal loop adds nothing outside a record's
// own radius and the far-pixel comparison isolates the plating layer.
constexpr float kDecalTime = 1000.0f;

inline renderer::Lighting test_lighting() {
    renderer::Lighting l;
    l.ambient = glm::vec3(0.6f);
    l.directional_count = 1;
    l.directional_dir_ws[0] = glm::normalize(glm::vec3(0.3f, 0.2f, -1.0f));
    l.directional_color[0] = glm::vec3(0.8f);
    return l;
}

inline const std::uint8_t* pixel(const std::vector<std::uint8_t>& px, int x, int y) {
    return &px[(static_cast<std::size_t>(y) * kSize + x) * 4];
}

inline int rgb_diff(const std::uint8_t* a, const std::uint8_t* b) {
    return std::abs(a[0] - b[0]) + std::abs(a[1] - b[1]) + std::abs(a[2] - b[2]);
}

inline int count_non_black(const std::vector<std::uint8_t>& px) {
    int n = 0;
    for (std::size_t i = 0; i + 3 < px.size(); i += 4)
        if (px[i] + px[i + 1] + px[i + 2] > 6) ++n;
    return n;
}

// A flat square face centred on `centre`, half size `half`, spanned by the
// unit axes `u` and `v`; its front face looks along u x v. No textures (the
// draw binds the white fallback). Appended to `model` as one more mesh of
// node 0.
inline void add_face(assets::Model& model, const glm::vec3& centre, const glm::vec3& u,
                     const glm::vec3& v, float half) {
    assets::MeshCpu cpu;
    cpu.material_index = 0;
    cpu.node_index = 0;
    const glm::vec3 n = glm::normalize(glm::cross(u, v));
    auto push = [&](float a, float b, float s, float t) {
        assets::MeshCpu::Vertex vt;
        vt.position = centre + u * (a * half) + v * (b * half);
        vt.normal = n;
        vt.uv = glm::vec2(s, t);
        cpu.vertices.push_back(vt);
    };
    push(-1.0f, -1.0f, 0.0f, 0.0f);
    push( 1.0f, -1.0f, 1.0f, 0.0f);
    push( 1.0f,  1.0f, 1.0f, 1.0f);
    push(-1.0f,  1.0f, 0.0f, 1.0f);
    cpu.indices = {0, 1, 2, 0, 2, 3};
    assets::Mesh mesh = assets::upload_mesh(cpu);
    mesh.set_cpu_data(cpu);
    if (model.materials.empty()) {
        assets::Material mat;
        mat.diffuse = glm::vec3(1.0f);
        mat.specular = glm::vec3(0.0f);
        mat.emissive = glm::vec3(0.0f);
        model.materials.push_back(mat);
    }
    if (model.nodes.empty()) {
        assets::Node node;
        node.name = "plating_probe_quad";
        model.nodes.push_back(node);
        model.root_node = 0;
    }
    model.nodes[0].meshes.push_back(static_cast<int>(model.meshes.size()));
    model.meshes.push_back(std::move(mesh));
}

// A flat quad in the z = `z` plane. `facing_camera` winds it CCW seen from
// +z (front-facing for a camera above it); otherwise CW (a back face, as the
// inside of a hull's far skin is from inside the hull).
inline void add_quad(assets::Model& model, float half, float z, bool facing_camera) {
    const glm::vec3 x(1.0f, 0.0f, 0.0f), y(0.0f, 1.0f, 0.0f);
    add_face(model, glm::vec3(0.0f, 0.0f, z), facing_camera ? x : y,
             facing_camera ? y : x, half);
}

inline std::unique_ptr<assets::Model> build_quad(float half, bool facing_camera) {
    auto model = std::make_unique<assets::Model>();
    add_quad(*model, half, 0.0f, facing_camera);
    return model;
}

// A closed cube of half size `half` centred on the origin: six outward-facing
// faces.
inline std::unique_ptr<assets::Model> build_box(float half) {
    auto model = std::make_unique<assets::Model>();
    const glm::vec3 X(1, 0, 0), Y(0, 1, 0), Z(0, 0, 1);
    add_face(*model,  Z * half, X, Y, half);   // +z
    add_face(*model, -Z * half, Y, X, half);   // -z
    add_face(*model,  X * half, Y, Z, half);   // +x
    add_face(*model, -X * half, Z, Y, half);   // -x
    add_face(*model,  Y * half, Z, X, half);   // +y
    add_face(*model, -Y * half, X, Z, half);   // -y
    return model;
}

// Window + pipeline, and the plating params restored after every test.
class PlatingGLFixture : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::array<float, renderer::plating::kParamCount> saved_params{};

    void SetUp() override {
        std::copy(dauntless_plating::g_params,
                  dauntless_plating::g_params + renderer::plating::kParamCount,
                  saved_params.begin());
        try {
            w = std::make_unique<renderer::Window>(kSize, kSize, "plating-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
    }

    void TearDown() override {
        std::copy(saved_params.begin(), saved_params.end(), dauntless_plating::g_params);
        if (!w) return;
        renderer::reset_damage_decal_texture();
        renderer::reset_scuff_normal_texture();
        renderer::reset_decal_mask_sampler();
        renderer::reset_model_radius_cache();
    }

    // Window pixel (row 0 = bottom) of a world point.
    static glm::ivec2 to_pixel(const scenegraph::Camera& cam, const glm::vec3& p) {
        const glm::vec4 c = cam.proj_matrix() * cam.view_matrix() * glm::vec4(p, 1.0f);
        const glm::vec2 ndc = glm::vec2(c) / c.w;
        return glm::ivec2(static_cast<int>(std::floor((ndc.x * 0.5f + 0.5f) * kSize)),
                          static_cast<int>(std::floor((ndc.y * 0.5f + 0.5f) * kSize)));
    }

    static scenegraph::Camera quad_cam() {
        scenegraph::Camera cam;
        cam.eye = glm::vec3(0.0f, 0.0f, 120.0f);
        cam.target = glm::vec3(0.0f);
        cam.up = glm::vec3(0.0f, 1.0f, 0.0f);
        cam.aspect = 1.0f;
        return cam;
    }

    static scenegraph::DamageDecalRing internal_ring(const glm::vec3& at, float radius,
                                                    float wear) {
        scenegraph::DamageDecalRing ring;
        ring.add(at, glm::vec3(0.0f, 0.0f, 1.0f), radius, 1.0f,
                 scenegraph::WeaponClass::Internal, 0.0f, glm::vec3(0.0f), wear);
        return ring;
    }
};

}  // namespace plating_gl
