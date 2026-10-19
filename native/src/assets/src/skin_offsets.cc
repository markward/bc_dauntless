// native/src/assets/src/skin_offsets.cc
#include "skin_offsets.h"

#include <algorithm>
#include <cmath>

namespace assets::detail {

namespace {

// Least-squares affine fit dst ≈ M·src (M 4x4, last row 0 0 0 1). Returns
// nullopt when the points do not span 3D (fewer than four non-coplanar).
std::optional<glm::mat4> fit_affine(const std::vector<glm::vec3>& src,
                                    const std::vector<glm::vec3>& dst) {
    // Normal equations: (AᵀA) X = Aᵀ B, A rows = [x y z 1], B rows = dst.
    double m[4][7] = {};
    for (std::size_t k = 0; k < src.size(); ++k) {
        const double a[4] = {src[k].x, src[k].y, src[k].z, 1.0};
        for (int p = 0; p < 4; ++p) {
            for (int q = 0; q < 4; ++q) m[p][q] += a[p] * a[q];
            for (int q = 0; q < 3; ++q) m[p][4 + q] += a[p] * dst[k][q];
        }
    }
    for (int col = 0; col < 4; ++col) {
        int piv = col;
        for (int r = col + 1; r < 4; ++r)
            if (std::fabs(m[r][col]) > std::fabs(m[piv][col])) piv = r;
        if (std::fabs(m[piv][col]) < 1e-9) return std::nullopt;
        for (int q = 0; q < 7; ++q) std::swap(m[col][q], m[piv][q]);
        const double d = m[col][col];
        for (int q = 0; q < 7; ++q) m[col][q] /= d;
        for (int r = 0; r < 4; ++r) {
            if (r == col) continue;
            const double f = m[r][col];
            for (int q = 0; q < 7; ++q) m[r][q] -= f * m[col][q];
        }
    }
    // Row p of X holds d(dst)/d(src_p): column p of the glm matrix.
    glm::mat4 out(1.0f);
    for (int p = 0; p < 4; ++p)
        out[p] = glm::vec4(static_cast<float>(m[p][4]), static_cast<float>(m[p][5]),
                           static_cast<float>(m[p][6]), p == 3 ? 1.0f : 0.0f);
    return out;
}

}  // namespace

bool seat_from_skin_offsets(
    MeshCpu& cpu,
    const nif::NiTriShapeSkinController& skin,
    const std::vector<std::optional<glm::mat4>>& skin_bone_bind_world) {
    const std::size_t n = cpu.vertices.size();
    std::vector<glm::vec3> seated(n, glm::vec3(0.0f));
    std::vector<float> weight(n, 0.0f);

    for (std::size_t b = 0; b < skin.bone_weights.size(); ++b) {
        if (skin.bone_weights[b].empty()) continue;
        if (b >= skin_bone_bind_world.size() || !skin_bone_bind_world[b])
            return false;  // can't evaluate this bone's offsets: trust the verts
        const glm::mat4& bone = *skin_bone_bind_world[b];
        for (const auto& w : skin.bone_weights[b]) {
            if (w.vertex_index >= n || w.weight <= 0.0f) continue;
            const glm::vec4 o(w.unknown_vector.x, w.unknown_vector.y,
                              w.unknown_vector.z, 1.0f);
            seated[w.vertex_index] += w.weight * glm::vec3(bone * o);
            weight[w.vertex_index] += w.weight;
        }
    }

    std::vector<glm::vec3> from, to;
    float worst = 0.0f;
    for (std::size_t k = 0; k < n; ++k) {
        if (weight[k] <= 0.0f) continue;
        seated[k] /= weight[k];
        from.push_back(cpu.vertices[k].position);
        to.push_back(seated[k]);
        worst = std::max(worst, glm::length(seated[k] - cpu.vertices[k].position));
    }
    if (worst <= kSkinOffsetTolerance) return false;

    const std::optional<glm::mat4> fit = fit_affine(from, to);
    const glm::mat3 normal_xform =
        fit ? glm::transpose(glm::inverse(glm::mat3(*fit))) : glm::mat3(1.0f);
    for (std::size_t k = 0; k < n; ++k) {
        auto& v = cpu.vertices[k];
        if (weight[k] > 0.0f)
            v.position = seated[k];
        else if (fit)
            v.position = glm::vec3(*fit * glm::vec4(v.position, 1.0f));
        if (fit) {
            const glm::vec3 nrm = normal_xform * v.normal;
            const float len = glm::length(nrm);
            if (len > 0.0f) v.normal = nrm / len;
        }
    }
    return true;
}

}  // namespace assets::detail
