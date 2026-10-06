// native/src/assets/src/geosphere.cc
#include <assets/geosphere.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <unordered_map>

#include <glm/gtc/constants.hpp>

namespace assets {
namespace {

struct Builder {
    std::vector<glm::vec3> dirs;
    std::vector<std::uint32_t> tris;
    std::unordered_map<std::uint64_t, std::uint32_t> mid;

    std::uint32_t midpoint(std::uint32_t a, std::uint32_t b) {
        const std::uint64_t key = a < b ? (std::uint64_t(a) << 32) | b
                                        : (std::uint64_t(b) << 32) | a;
        auto it = mid.find(key);
        if (it != mid.end()) return it->second;
        dirs.push_back(glm::normalize(dirs[a] + dirs[b]));
        const auto i = static_cast<std::uint32_t>(dirs.size() - 1);
        mid.emplace(key, i);
        return i;
    }
};

}  // namespace

glm::vec2 sphere_uv(glm::vec3 d) {
    const float two_pi = glm::two_pi<float>();
    const float lon = (std::abs(d.x) < 1e-12f && std::abs(d.y) < 1e-12f)
                          ? 0.0f : std::atan2(d.y, d.x);
    float u = lon / two_pi + 0.75f;
    u -= std::floor(u);
    const float v = 0.5f - std::asin(std::clamp(d.z, -1.0f, 1.0f)) / glm::pi<float>();
    return {u, v};
}

MeshCpu build_geosphere(int level, float radius, glm::vec3 center) {
    const float t = (1.0f + std::sqrt(5.0f)) * 0.5f;
    Builder b;
    for (glm::vec3 p : {glm::vec3(-1, t, 0), glm::vec3(1, t, 0), glm::vec3(-1, -t, 0),
                        glm::vec3(1, -t, 0), glm::vec3(0, -1, t), glm::vec3(0, 1, t),
                        glm::vec3(0, -1, -t), glm::vec3(0, 1, -t), glm::vec3(t, 0, -1),
                        glm::vec3(t, 0, 1), glm::vec3(-t, 0, -1), glm::vec3(-t, 0, 1)})
        b.dirs.push_back(glm::normalize(p));
    b.tris = {0, 11, 5, 0, 5, 1, 0, 1, 7, 0, 7, 10, 0, 10, 11, 1, 5, 9, 5, 11, 4,
              11, 10, 2, 10, 7, 6, 7, 1, 8, 3, 9, 4, 3, 4, 2, 3, 2, 6, 3, 6, 8,
              3, 8, 9, 4, 9, 5, 2, 4, 11, 6, 2, 10, 8, 6, 7, 9, 8, 1};
    for (int l = 0; l < level; ++l) {
        std::vector<std::uint32_t> next;
        next.reserve(b.tris.size() * 4);
        for (std::size_t i = 0; i < b.tris.size(); i += 3) {
            const auto a = b.tris[i], c = b.tris[i + 1], e = b.tris[i + 2];
            const auto ab = b.midpoint(a, c), bc = b.midpoint(c, e), ca = b.midpoint(e, a);
            next.insert(next.end(), {a, ab, ca, c, bc, ab, e, ca, bc, ab, bc, ca});
        }
        b.tris = std::move(next);
    }
    // Enforce CCW-outward per triangle (the seed table's winding is not
    // trusted; the test pins the result, not the table).
    for (std::size_t i = 0; i < b.tris.size(); i += 3) {
        const glm::vec3 p0 = b.dirs[b.tris[i]], p1 = b.dirs[b.tris[i + 1]], p2 = b.dirs[b.tris[i + 2]];
        if (glm::dot(glm::cross(p1 - p0, p2 - p0), p0 + p1 + p2) < 0.0f)
            std::swap(b.tris[i + 1], b.tris[i + 2]);
    }
    MeshCpu m;
    m.vertices.reserve(b.dirs.size());
    for (const glm::vec3& d : b.dirs) {
        MeshCpu::Vertex v;
        v.position = center + d * radius;
        v.normal = d;
        // Compute uv from the same expression the geometric-consistency test
        // uses (normalize(position - center)), not the pre-scale direction
        // `d`: near the poles, asin() amplifies the tiny FP divergence
        // between the two into a visible v error.
        v.uv = sphere_uv(glm::normalize(v.position - center));
        m.vertices.push_back(v);
    }
    m.indices = std::move(b.tris);
    return m;
}

bool apply_geosphere(Model& model, const std::function<Mesh(MeshCpu)>& upload,
                     bool keep_cpu_data) {
    if (model.meshes.size() != 1) return false;
    const Mesh& src = model.meshes[0];
    if (!src.cpu_data() || src.cpu_data()->vertices.empty()) return false;
    const MeshCpu& cpu = *src.cpu_data();

    // Gate (spec §4.2): a UV set, and every vertex within 0.5% of the mean
    // distance from the SHAPE'S OWN LOCAL ORIGIN -- not the vertex-position
    // arithmetic mean. build_mesh_cpu bakes the NiTriShape's own (T,R,S) into
    // the vertices but leaves them in the owning NODE's local space; BC's
    // stock sphere primitives are authored with their geometric centre AT
    // that node-local origin (measured: IcePlanet's 673-vertex lat/long
    // sphere has a 9e-6 relative radius spread about (0,0,0), vs. ~2.25%
    // about its vertex-position mean). The vertex mean is skewed by the
    // mesh's DUPLICATE vertices -- the seam-column copies (u = 0 and u = 1
    // at the same point) and the pole-fan copies -- which are not spread
    // evenly round the sphere, so averaging pulls the estimate off the true
    // centre. Measuring from the local origin needs no averaging and
    // matches the asset exactly.
    bool has_uv = false;
    for (const auto& v : cpu.vertices) has_uv = has_uv || v.uv != glm::vec2(0.0f);
    if (!has_uv) return false;
    float mean = 0.0f;
    for (const auto& v : cpu.vertices) mean += glm::length(v.position);
    mean /= static_cast<float>(cpu.vertices.size());
    if (!(mean > 0.0f)) return false;
    for (const auto& v : cpu.vertices)
        if (std::abs(glm::length(v.position) - mean) > 0.005f * mean) return false;

    // Compose the node chain down to the mesh's node (node-local -> body).
    glm::mat4 node_world(1.0f);
    for (int n = src.node_index(); n >= 0; n = model.nodes[n].parent_index)
        node_world = model.nodes[n].local_transform * node_world;

    // Its linear part must be a pure rotation: the icosphere is built with
    // the node-local radius, and opaque.frag derives the mapping direction
    // in the body frame, so a scale or shear would make both wrong.
    const glm::mat3 rot(node_world);
    for (int c = 0; c < 3; ++c) {
        if (std::abs(glm::length(rot[c]) - 1.0f) > 1e-4f) return false;
        if (std::abs(glm::dot(rot[c], rot[(c + 1) % 3])) > 1e-4f) return false;
    }

    // The stored UVs must be BC's mapping of the BODY-frame direction -- the
    // mapping opaque.frag reproduces. Skipped where the stored value is not
    // the formula's by construction: near the poles (BC's fan u leaves
    // [0, 1]) and on the seam column (u = 0 or 1, either is right).
    for (const auto& v : cpu.vertices) {
        const glm::vec3 dir = rot * glm::normalize(v.position);
        if (std::abs(dir.z) > 0.98f) continue;
        if (v.uv.x < 1e-3f || v.uv.x > 1.0f - 1e-3f) continue;
        const glm::vec2 want = sphere_uv(dir);
        if (std::abs(v.uv.x - want.x) > 1e-3f || std::abs(v.uv.y - want.y) > 1e-3f)
            return false;
    }

    SphereMap sm;
    sm.mesh_index = 0;
    sm.center_body = glm::vec3(node_world * glm::vec4(0.0f, 0.0f, 0.0f, 1.0f));
    sm.radius = mean;
    for (std::size_t i = 0; i < kGeosphereLevels.size(); ++i) {
        MeshCpu lod = build_geosphere(kGeosphereLevels[i], mean, glm::vec3(0.0f));
        lod.material_index = cpu.material_index;
        lod.node_index = cpu.node_index;
        Mesh m = upload(lod);
        if (keep_cpu_data) m.set_cpu_data(std::move(lod));
        sm.lods[i] = std::move(m);
    }
    model.sphere_map = std::move(sm);
    return true;
}

int pick_geosphere_level(float R, float d, float focal_px, float max_err_px) {
    constexpr int kFinest = static_cast<int>(kGeosphereLevels.size()) - 1;
    if (!(d > R) || !(R > 0.0f) || !(focal_px > 0.0f)) return kFinest;
    const float sil = std::max(std::sqrt(d * d - R * R), 1e-3f);
    const float base = glm::radians(63.435f);
    for (int i = 0; i <= kFinest; ++i) {
        const float theta = base / static_cast<float>(1 << kGeosphereLevels[i]);
        const float err_px = R * theta * theta / 8.0f / sil * focal_px;
        if (err_px < max_err_px) return i;
    }
    return kFinest;
}

}  // namespace assets
