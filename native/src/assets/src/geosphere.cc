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
