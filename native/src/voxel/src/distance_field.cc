// native/src/voxel/src/distance_field.cc
#include <voxel/distance_field.h>

#include <cmath>
#include <cstdint>
#include <unordered_map>

namespace voxel {

// Closest point on a triangle (Ericson, Real-Time Collision Detection, 5.1.5).
// Region-by-region: the three vertices, the three edges, then the interior.
float point_triangle_distance(const glm::vec3& p, const Tri& t) {
    const glm::vec3 ab = t.b - t.a;
    const glm::vec3 ac = t.c - t.a;
    const glm::vec3 ap = p - t.a;

    const float d1 = glm::dot(ab, ap);
    const float d2 = glm::dot(ac, ap);
    if (d1 <= 0.0f && d2 <= 0.0f) return glm::length(ap);          // vertex a

    const glm::vec3 bp = p - t.b;
    const float d3 = glm::dot(ab, bp);
    const float d4 = glm::dot(ac, bp);
    if (d3 >= 0.0f && d4 <= d3) return glm::length(bp);            // vertex b

    const float vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0f && d1 >= 0.0f && d3 <= 0.0f) {                  // edge ab
        const float denom = d1 - d3;
        const float v = (std::abs(denom) > 1e-20f) ? d1 / denom : 0.0f;
        return glm::length(p - (t.a + v * ab));
    }

    const glm::vec3 cp = p - t.c;
    const float d5 = glm::dot(ab, cp);
    const float d6 = glm::dot(ac, cp);
    if (d6 >= 0.0f && d5 <= d6) return glm::length(cp);            // vertex c

    const float vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0f && d2 >= 0.0f && d6 <= 0.0f) {                  // edge ac
        const float denom = d2 - d6;
        const float w = (std::abs(denom) > 1e-20f) ? d2 / denom : 0.0f;
        return glm::length(p - (t.a + w * ac));
    }

    const float va = d3 * d6 - d5 * d4;
    if (va <= 0.0f && (d4 - d3) >= 0.0f && (d5 - d6) >= 0.0f) {    // edge bc
        const float denom = (d4 - d3) + (d5 - d6);
        const float w = (std::abs(denom) > 1e-20f) ? (d4 - d3) / denom : 0.0f;
        return glm::length(p - (t.b + w * (t.c - t.b)));
    }

    const float sum = va + vb + vc;                                 // interior
    // Guard: sum = |ab×ac|² = (2*Area)². Independent of p, depends on triangle alone.
    // Exactly-degenerate triangles (area=0) cannot reach here. Ultra-thin slivers
    // (area~1e-11) can: their interior region is real, but sum shrinks below 1e-20
    // epsilon due to quadratic scaling. Returns distance to vertex a: finite, safe, approximate.
    if (!(std::abs(sum) > 1e-20f)) return glm::length(ap);
    const float inv = 1.0f / sum;
    return glm::length(p - (t.a + ab * (vb * inv) + ac * (vc * inv)));
}

namespace {

// Hash key for a triangle bin.
struct BinKey {
    int x, y, z;
    bool operator==(const BinKey& o) const { return x == o.x && y == o.y && z == o.z; }
};
struct BinHash {
    std::size_t operator()(const BinKey& k) const {
        // Cheap mix; bins are few relative to cells.
        return (static_cast<std::size_t>(k.x) * 73856093u)
             ^ (static_cast<std::size_t>(k.y) * 19349663u)
             ^ (static_cast<std::size_t>(k.z) * 83492791u);
    }
};

}  // namespace

DistanceField distance_field_from_tris(const std::vector<Tri>& tris,
                                       glm::vec3 cell,
                                       float band_cells) {
    DistanceField f;
    if (tris.empty()) return f;
    if (!(cell.x > 0.0f) || !(cell.y > 0.0f) || !(cell.z > 0.0f)) return f;
    if (!(band_cells > 0.0f)) return f;

    glm::vec3 mn(1e30f), mx(-1e30f);
    for (const auto& t : tris) {
        mn = glm::min(mn, glm::min(t.a, glm::min(t.b, t.c)));
        mx = glm::max(mx, glm::max(t.a, glm::max(t.b, t.c)));
    }

    // Two-cell margin so the outside band is representable all the way round.
    f.cell   = cell;
    f.origin = mn - cell * 2.0f;
    const glm::vec3 span = (mx - mn) / cell;
    f.dims = glm::ivec3(static_cast<int>(std::ceil(span.x)) + 5,
                        static_cast<int>(std::ceil(span.y)) + 5,
                        static_cast<int>(std::ceil(span.z)) + 5);

    const float band = band_cells * std::max(cell.x, std::max(cell.y, cell.z));
    f.scale = band / 127.0f;

    // Sign: the flood-filled occupancy of the SAME lattice.
    const VoxelVolume occ = voxelize_into(tris, f.dims, f.origin, f.cell);

    // Bin triangles by band-sized cells, each inserted into every bin its
    // band-expanded bbox touches. A voxel then need only consult its OWN bin:
    // any triangle within `band` of it is guaranteed to be there.
    std::unordered_map<BinKey, std::vector<std::uint32_t>, BinHash> bins;
    auto bin_of = [&](const glm::vec3& p) {
        return BinKey{static_cast<int>(std::floor(p.x / band)),
                      static_cast<int>(std::floor(p.y / band)),
                      static_cast<int>(std::floor(p.z / band))};
    };
    for (std::uint32_t i = 0; i < tris.size(); ++i) {
        const Tri& t = tris[i];
        const glm::vec3 tlo = glm::min(t.a, glm::min(t.b, t.c)) - band;
        const glm::vec3 thi = glm::max(t.a, glm::max(t.b, t.c)) + band;
        const BinKey lo = bin_of(tlo), hi = bin_of(thi);
        for (int z = lo.z; z <= hi.z; ++z)
        for (int y = lo.y; y <= hi.y; ++y)
        for (int x = lo.x; x <= hi.x; ++x)
            bins[BinKey{x, y, z}].push_back(i);
    }

    f.dist.assign(static_cast<std::size_t>(f.dims.x)
                * static_cast<std::size_t>(f.dims.y)
                * static_cast<std::size_t>(f.dims.z), 0);

    for (int z = 0; z < f.dims.z; ++z)
    for (int y = 0; y < f.dims.y; ++y)
    for (int x = 0; x < f.dims.x; ++x) {
        const glm::vec3 p = f.origin
                          + (glm::vec3(x, y, z) + 0.5f) * f.cell;
        float best = band;
        auto it = bins.find(bin_of(p));
        if (it != bins.end())
            for (std::uint32_t ti : it->second)
                best = std::min(best, point_triangle_distance(p, tris[ti]));

        const float sign = occ.solid(x, y, z) ? -1.0f : 1.0f;
        float q = std::round(sign * best / f.scale);
        q = std::max(-127.0f, std::min(127.0f, q));
        f.dist[f.index(x, y, z)] = static_cast<std::int8_t>(q);
    }
    return f;
}

}  // namespace voxel
