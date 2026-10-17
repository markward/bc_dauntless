// native/tests/renderer/bridge_test_room.h
// Test-only: the synthetic bridge room the GL bridge tests draw -- quads from
// corners, 1x1 solid textures, the two-mesh corner (floor + wall), and the
// model lookup that treats a handle as the Model pointer. Shared by
// bridge_pbr_frame_test.cc and bridge_probe_content_test.cc. Needs a current
// GL context (uploads). Not an installed header.
#pragma once

#include <glad/glad.h>

#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/model.h>
#include <assets/texture.h>

#include <glm/glm.hpp>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <utility>

namespace bridge_test_room {

// One quad from four corners with an authored normal `n`, wound
// counter-clockwise as seen from the side the normal faces. `uv_axes` picks
// which two position components (scaled by 1/100) become the UV; {-1, -1}
// leaves the UVs at zero (a UV-less mesh).
inline void append_quad(assets::MeshCpu& cpu, const glm::vec3 (&c)[4], const glm::vec3& n,
                        glm::ivec2 uv_axes) {
    const auto base = static_cast<std::uint32_t>(cpu.vertices.size());
    for (const auto& p : c) {
        assets::MeshCpu::Vertex v;
        v.position = p;
        v.normal = n;
        if (uv_axes.x >= 0) v.uv = glm::vec2(p[uv_axes.x], p[uv_axes.y]) / 100.0f;
        cpu.vertices.push_back(v);
    }
    if (glm::dot(glm::cross(c[1] - c[0], c[2] - c[0]), n) >= 0.0f)
        cpu.indices.insert(cpu.indices.end(), {base, base + 1, base + 2, base, base + 2, base + 3});
    else
        cpu.indices.insert(cpu.indices.end(), {base, base + 2, base + 1, base, base + 3, base + 2});
}

// A 1x1 RGBA8 texture of `rgba` (0..1 per channel), owned by the returned
// assets::Texture (same upload as bridge_lighting_test.cc's red_1x1()).
inline assets::Texture solid_1x1(glm::vec4 rgba) {
    GLuint t = 0;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    unsigned char px[4];
    for (int i = 0; i < 4; ++i)
        px[i] = static_cast<unsigned char>(std::lround(std::clamp(rgba[i], 0.0f, 1.0f) * 255.0f));
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glBindTexture(GL_TEXTURE_2D, 0);
    return assets::Texture(t, 1, 1, false);
}

// The corner as TWO meshes so a reflection is identifiable by hue: mesh 0 the
// floor z = 0 (x >= 0, normal +Z; material 0, `floor_rgb`), mesh 1 the wall
// x = 0 (z >= 0, normal +X; material 1, `wall_rgb`). Texture i is material
// i's Base.
inline std::unique_ptr<assets::Model> make_two_mesh_corner(glm::vec3 floor_rgb,
                                                           glm::vec3 wall_rgb) {
    auto m = std::make_unique<assets::Model>();
    constexpr float L = 300.0f;
    const glm::vec3 floor_c[4] = {{0, -L, 0}, {L, -L, 0}, {L, L, 0}, {0, L, 0}};
    const glm::vec3 wall_c[4]  = {{0, -L, 0}, {0, L, 0}, {0, L, L}, {0, -L, L}};
    assets::MeshCpu floor_cpu, wall_cpu;
    append_quad(floor_cpu, floor_c, {0, 0, 1}, glm::ivec2(0, 1));
    append_quad(wall_cpu, wall_c, {1, 0, 0}, glm::ivec2(1, 2));
    floor_cpu.material_index = 0;
    floor_cpu.node_index = 0;
    wall_cpu.material_index = 1;
    wall_cpu.node_index = 0;
    // CPU data retained, as an interior load keeps it: the probe box is the
    // model's AABB from it.
    m->meshes.push_back(assets::upload_mesh(floor_cpu));
    m->meshes.back().set_cpu_data(floor_cpu);
    m->meshes.push_back(assets::upload_mesh(wall_cpu));
    m->meshes.back().set_cpu_data(wall_cpu);
    const glm::vec3 cols[2] = {floor_rgb, wall_rgb};
    for (int i = 0; i < 2; ++i) {
        m->textures.push_back(solid_1x1(glm::vec4(cols[i], 1.0f)));
        assets::Material mat;
        mat.stages[static_cast<std::size_t>(assets::Material::StageSlot::Base)].texture_index = i;
        m->materials.push_back(mat);
    }
    assets::Node root;
    root.name = "root";
    root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    root.meshes = {0, 1};
    m->nodes.push_back(std::move(root));
    m->root_node = 0;
    return m;
}

inline const assets::Model* lookup_fn(unsigned long long h) {
    return reinterpret_cast<const assets::Model*>(h);
}

}  // namespace bridge_test_room
