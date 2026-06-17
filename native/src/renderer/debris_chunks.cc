#include "debris_chunks.h"
#include <cmath>
#include <glm/gtc/matrix_transform.hpp>

namespace renderer {

namespace {

// 64-bit splitmix hash for deterministic per-chunk randomness.
inline std::uint64_t smix(std::uint64_t x) {
    x += 0x9e3779b97f4a7c15ull;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ull;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebull;
    return x ^ (x >> 31);
}

// Float in [0, 1) from a hash value.
inline float h01(std::uint64_t h) {
    return static_cast<float>(h >> 11) * (1.f / static_cast<float>(1ull << 53));
}

} // namespace

std::vector<glm::vec3> sample_chunk_origins(
    const voxel::VoxelVolume& fill,
    const glm::vec3& center_body,
    float radius,
    std::uint64_t seed,
    int max_chunks) {

    std::vector<glm::vec3> candidates;
    candidates.reserve(64);

    // TODO(perf): iterates the full voxel grid; could clamp loop bounds to the
    // carve sphere's voxel bbox to skip empty regions if fill grids ever grow large.
    // Enumerate solid voxels inside the carve sphere.
    for (int iz = 0; iz < fill.dims.z; ++iz) {
        for (int iy = 0; iy < fill.dims.y; ++iy) {
            for (int ix = 0; ix < fill.dims.x; ++ix) {
                const std::size_t idx =
                    static_cast<std::size_t>(iz * fill.dims.y * fill.dims.x
                                           + iy * fill.dims.x + ix);
                if (fill.occ[idx] == 0) continue;
                // Voxel center in body frame.
                const glm::vec3 vc = fill.origin
                    + fill.cell * glm::vec3(ix + 0.5f, iy + 0.5f, iz + 0.5f);
                if (glm::length(vc - center_body) <= radius) {
                    candidates.push_back(vc);
                }
            }
        }
    }
    if (candidates.empty()) return {};

    // Deterministic subsample to max_chunks using Fisher-Yates-style shuffle.
    const int n = static_cast<int>(candidates.size());
    const int take = std::min(max_chunks, n);
    std::vector<int> idx(static_cast<std::size_t>(n));
    for (int i = 0; i < n; ++i) idx[static_cast<std::size_t>(i)] = i;

    std::uint64_t rng = smix(seed ^ 0xdeadbeefcafeull);
    for (int i = 0; i < take; ++i) {
        rng = smix(rng);
        const int j = i + static_cast<int>(rng % static_cast<std::uint64_t>(n - i));
        std::swap(idx[static_cast<std::size_t>(i)], idx[static_cast<std::size_t>(j)]);
    }

    std::vector<glm::vec3> result;
    result.reserve(static_cast<std::size_t>(take));
    for (int i = 0; i < take; ++i) {
        result.push_back(candidates[static_cast<std::size_t>(idx[static_cast<std::size_t>(i)])]);
    }
    return result;
}

ChunkTransform chunk_transform(
    const glm::vec3& origin,
    const glm::vec3& breach_center,
    float age,
    std::uint64_t seed,
    int i) {

    // Per-chunk deterministic parameters.
    const std::uint64_t h0 = smix(seed ^ (static_cast<std::uint64_t>(i) * 2654435761ull));
    const std::uint64_t h1 = smix(h0 + 1);
    const std::uint64_t h2 = smix(h0 + 2);
    const std::uint64_t h3 = smix(h0 + 3);
    const std::uint64_t h4 = smix(h0 + 4);

    // Outward direction from breach center with small random spread.
    const glm::vec3 radial = (glm::length(origin - breach_center) > 1e-4f)
        ? glm::normalize(origin - breach_center)
        : glm::vec3(0.f, 1.f, 0.f);
    // Random tangential kick ±30 % of radial length to spread chunks.
    const float kick_x = (h01(h1) * 2.f - 1.f) * 0.3f;
    const float kick_y = (h01(h2) * 2.f - 1.f) * 0.3f;
    // Build a simple orthonormal frame around radial.
    const glm::vec3 up   = (std::abs(radial.y) < 0.99f)
                           ? glm::vec3(0.f, 1.f, 0.f)
                           : glm::vec3(1.f, 0.f, 0.f);
    const glm::vec3 tang = glm::normalize(glm::cross(up, radial));
    const glm::vec3 btan = glm::cross(radial, tang);
    const glm::vec3 dir  = glm::normalize(radial + tang * kick_x + btan * kick_y);

    // Speed in [20, 60] body-units (model units) / second. The breach gap is
    // ~25-100 model units wide and the hull ~350, so the old [1.5,4.5] barely
    // crept out of the hole; this ejects chunks clear of the gap in ~1s, then
    // they coast + tumble + fade over kDebrisLife. Eyeball-tunable.
    const float speed = 20.0f + h01(h3) * 40.0f;

    // Alpha: linear fade 1 → 0 over kDebrisLife; clamp to [0,1].
    const float t    = age / scenegraph::kDebrisLife;
    const float alpha = std::max(0.f, 1.f - t);

    const glm::vec3 pos_body = origin + dir * (speed * age);

    // Rotation: constant angular velocity around a random axis, angle = spin * age.
    const float spin_deg = 90.f + h01(h4) * 270.f;  // 90..360 deg/s
    const float angle    = glm::radians(spin_deg * age);
    const glm::vec3 rot_axis = glm::normalize(
        glm::vec3(h01(smix(h4 + 1)) * 2.f - 1.f,
                  h01(smix(h4 + 2)) * 2.f - 1.f,
                  h01(smix(h4 + 3)) * 2.f - 1.f + 1e-4f));
    const glm::mat3 rot = glm::mat3(
        glm::rotate(glm::mat4(1.f), angle, rot_axis));

    return ChunkTransform{pos_body, rot, alpha};
}

} // namespace renderer
