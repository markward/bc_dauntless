#include "mesh_build.h"

#include <algorithm>

namespace assets::detail {

namespace {

inline std::uint8_t to_u8(float f) {
    f = std::clamp(f, 0.0f, 1.0f);
    return static_cast<std::uint8_t>(f * 255.0f + 0.5f);
}

// Apply a NIF 3x3 rotation to a vector. Storage is row-major with
// column-vector math (v' = M * v), so v'.x = m[0]*v.x + m[1]*v.y +
// m[2]*v.z, etc.
inline glm::vec3 apply_rotation(const nif::Mat3x3& r, const glm::vec3& v) noexcept {
    return {
        r.m[0] * v.x + r.m[1] * v.y + r.m[2] * v.z,
        r.m[3] * v.x + r.m[4] * v.y + r.m[5] * v.z,
        r.m[6] * v.x + r.m[7] * v.y + r.m[8] * v.z,
    };
}

}  // namespace

// NiTriShape carries an `av` block with a local translation/rotation/
// scale that composes parent_world * (T * R * S) on top of the parent
// NiNode's world transform. We bake (T, R, S) into the vertex positions
// (and R into the normals) at build time, so the renderer only sees
// node-local geometry and applies the node's world transform.
//
// This is equivalent to what the stock engine's geometry-data
// ApplyTransform path does at export — BC's content authoring tools
// often emit non-identity shape transforms (per a corpus scan: 366 of
// 549 NiTriShapes had non-identity translations, 75 had non-identity
// rotations, 0 had non-unit scale), and ignoring them would render
// chunks like the Warbird's two halves (at +/-470 along X) collapsed
// to the parent node's origin.
//
// Cost: O(vertex count) on load, zero at render time. Scale is uniform
// per the NIF transform model, so normals only need the rotation.
MeshCpu build_mesh_cpu(
    const nif::NiTriShape& shape,
    const nif::NiTriShapeData& data,
    int material_index,
    int node_index,
    const glm::mat4& extra_model_transform)
{
    MeshCpu mesh;
    mesh.material_index = material_index;
    mesh.node_index     = node_index;

    mesh.vertices.resize(data.num_vertices);

    const auto& t = shape.av.translation;
    const auto& r = shape.av.rotation;
    const float s = shape.av.scale;
    const glm::vec3 trans{t.x, t.y, t.z};

    if (data.has_vertices) {
        for (std::size_t i = 0; i < data.vertices.size(); ++i) {
            const auto& v = data.vertices[i];
            glm::vec3 p{v.x * s, v.y * s, v.z * s};
            mesh.vertices[i].position = apply_rotation(r, p) + trans;
        }
    }
    if (data.has_normals) {
        for (std::size_t i = 0; i < data.normals.size(); ++i) {
            const auto& n = data.normals[i];
            mesh.vertices[i].normal = apply_rotation(r, {n.x, n.y, n.z});
        }
    }

    // SP2: for rigid character shapes the caller passes the parent node's
    // bind-world transform so verts move from node-local into BIND-MODEL space
    // (the space the GPU palette poses). Identity for everything else, so ships
    // and bridges are byte-identical.
    if (extra_model_transform != glm::mat4(1.0f)) {
        const glm::mat3 nm = glm::mat3(extra_model_transform);  // BC scale is uniform/1
        for (auto& v : mesh.vertices) {
            v.position = glm::vec3(extra_model_transform * glm::vec4(v.position, 1.0f));
            v.normal   = glm::normalize(nm * v.normal);
        }
    }
    if (data.has_uv && !data.uv_sets.empty()) {
        const auto& primary = data.uv_sets[0];
        for (std::size_t i = 0; i < primary.size(); ++i) {
            mesh.vertices[i].uv = {primary[i].u, primary[i].v};
        }
        if (data.uv_sets.size() > 1) {
            const auto& secondary = data.uv_sets[1];
            for (std::size_t i = 0; i < secondary.size() && i < mesh.vertices.size(); ++i) {
                mesh.vertices[i].uv1 = {secondary[i].u, secondary[i].v};
            }
        }
        for (std::size_t set = 1; set < data.uv_sets.size(); ++set) {
            std::vector<glm::vec2> extra;
            extra.reserve(data.uv_sets[set].size());
            for (auto& tc : data.uv_sets[set]) extra.push_back({tc.u, tc.v});
            mesh.extra_uvs.push_back(std::move(extra));
        }
    }
    if (data.has_vertex_colors) {
        for (std::size_t i = 0; i < data.vertex_colors.size(); ++i) {
            const auto& c = data.vertex_colors[i];
            mesh.vertices[i].color = glm::u8vec4(
                to_u8(c.r), to_u8(c.g), to_u8(c.b), to_u8(c.a));
        }
    }

    mesh.indices.reserve(data.triangles.size() * 3);
    for (auto& tri : data.triangles) {
        mesh.indices.push_back(tri[0]);
        mesh.indices.push_back(tri[1]);
        mesh.indices.push_back(tri[2]);
    }
    return mesh;
}

}  // namespace assets::detail
