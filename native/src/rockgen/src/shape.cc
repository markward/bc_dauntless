// native/src/rockgen/src/shape.cc
//
// Deterministic rock shapes for the rock catalogue: a noise-displaced,
// axis-stretched icosphere with craters (majors), additionally flattened by
// plane cuts (fragments). The icosphere builder, fbm field, smooth-normal
// recompute and UV seam split are ported from feat/procedural-asteroids
// (asteroid_gen.cc); the variant-pool API and fixed model-unit scale are not.
//
// Every LOD samples the SAME field: the displacement is a function of the
// unit icosphere direction alone, and the per-rock parameters (axes, craters,
// cuts) are drawn once and shared by all LODs.
#include <rockgen/shape.h>

#include "noise.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <map>
#include <random>
#include <utility>
#include <vector>

namespace rockgen {
namespace {

constexpr double kPi = 3.14159265358979323846;

// --- randomness -----------------------------------------------------------
// std::mt19937_64 is fully specified by the standard; the *_distribution
// classes are not, so [0,1) is mapped by hand from the top 53 bits.
struct Rng {
    std::mt19937_64 eng;
    explicit Rng(std::uint64_t seed) : eng(seed) {}
    double unit() { return static_cast<double>(eng() >> 11) * 0x1.0p-53; }
    double range(double lo, double hi) { return lo + (hi - lo) * unit(); }
    /// Uniform integer in [lo, hi] (inclusive).
    int pick(int lo, int hi) {
        if (hi <= lo) { unit(); return lo; }   // still consume one draw: fixed order
        const int n = lo + static_cast<int>(unit() * static_cast<double>(hi - lo + 1));
        return std::min(n, hi);
    }
    /// Uniform direction on the unit sphere (two draws).
    glm::vec3 direction() {
        const double z = 2.0 * unit() - 1.0;
        const double phi = 2.0 * kPi * unit();
        const double r = std::sqrt(std::max(0.0, 1.0 - z * z));
        return glm::vec3(static_cast<float>(r * std::cos(phi)),
                         static_cast<float>(r * std::sin(phi)),
                         static_cast<float>(z));
    }
};

struct Crater { glm::vec3 centre; float radius; };   // radius: angular, radians
struct Cut    { glm::vec3 normal; float fraction; }; // dist = fraction * support along normal (LOD0, pre-cut)

struct RockParams {
    std::uint32_t noise_seed = 0;
    glm::vec3 axes{1.0f};
    std::vector<Crater> craters;
    std::vector<Cut> cuts;
};

/// Draw order is fixed and load-bearing (the catalogue is committed):
/// axes, then craters, then cuts.
RockParams draw_params(const RockSpec& spec) {
    const FamilyParams& f = *spec.family;
    const KindParams& k = *spec.kind;
    RockParams p;
    // The value-noise hash is 32-bit; fold the 64-bit rock seed into it.
    p.noise_seed = static_cast<std::uint32_t>(spec.seed) ^
                   static_cast<std::uint32_t>(spec.seed >> 32);
    Rng rng(spec.seed);
    for (int a = 0; a < 3; ++a)
        p.axes[a] = static_cast<float>(rng.range(f.axis_min, f.axis_max));
    const int n_craters = rng.pick(f.craters_min, f.craters_max);
    for (int i = 0; i < n_craters; ++i) {
        Crater c;
        c.centre = rng.direction();
        c.radius = static_cast<float>(rng.range(f.crater_radius_min, f.crater_radius_max));
        p.craters.push_back(c);
    }
    if (spec.fragment) {
        const int n_cuts = rng.pick(k.cuts_min, k.cuts_max);
        for (int i = 0; i < n_cuts; ++i) {
            Cut c;
            c.normal = rng.direction();
            c.fraction = static_cast<float>(rng.range(0.45, 0.70));
            p.cuts.push_back(c);
        }
    }
    return p;
}

// --- icosphere (ported) ---------------------------------------------------
struct Builder {
    std::vector<glm::vec3> pos;
    std::vector<std::uint32_t> idx;
    std::map<std::pair<std::uint32_t, std::uint32_t>, std::uint32_t> midpoints;

    std::uint32_t add(const glm::vec3& p) {
        pos.push_back(glm::normalize(p));
        return static_cast<std::uint32_t>(pos.size() - 1);
    }
    std::uint32_t midpoint(std::uint32_t a, std::uint32_t b) {
        const std::pair<std::uint32_t, std::uint32_t> key(std::min(a, b), std::max(a, b));
        auto it = midpoints.find(key);
        if (it != midpoints.end()) return it->second;
        const std::uint32_t m = add((pos[a] + pos[b]) * 0.5f);
        midpoints[key] = m;
        return m;
    }
};

/// Unit icosphere, 20 * 4^subdivisions triangles, CCW outward. The vertex
/// list at subdivision s is a prefix of the list at s+1.
Builder icosphere(int subdivisions) {
    Builder b;
    const float t = (1.0f + std::sqrt(5.0f)) * 0.5f;
    for (glm::vec3 v : {glm::vec3(-1, t, 0), glm::vec3(1, t, 0), glm::vec3(-1,-t, 0), glm::vec3(1,-t, 0),
                        glm::vec3(0,-1, t), glm::vec3(0, 1, t), glm::vec3(0,-1,-t), glm::vec3(0, 1,-t),
                        glm::vec3(t, 0,-1), glm::vec3(t, 0, 1), glm::vec3(-t, 0,-1), glm::vec3(-t, 0, 1)})
        b.add(v);
    b.idx = {0,11,5, 0,5,1, 0,1,7, 0,7,10, 0,10,11,
             1,5,9, 5,11,4, 11,10,2, 10,7,6, 7,1,8,
             3,9,4, 3,4,2, 3,2,6, 3,6,8, 3,8,9,
             4,9,5, 2,4,11, 6,2,10, 8,6,7, 9,8,1};
    for (int s = 0; s < subdivisions; ++s) {
        std::vector<std::uint32_t> next;
        next.reserve(b.idx.size() * 4);
        for (size_t i = 0; i < b.idx.size(); i += 3) {
            const std::uint32_t a = b.idx[i], c = b.idx[i+1], d = b.idx[i+2];
            const std::uint32_t ab = b.midpoint(a, c);
            const std::uint32_t bc = b.midpoint(c, d);
            const std::uint32_t ca = b.midpoint(d, a);
            for (std::uint32_t v : {a, ab, ca, c, bc, ab, d, ca, bc, ab, bc, ca})
                next.push_back(v);
        }
        b.idx.swap(next);
    }
    return b;
}

// --- the displacement field -----------------------------------------------
/// Crater term to SUBTRACT from the radius at unit direction d: a parabolic
/// bowl of depth 0.35*a inside angular radius a, minus a gaussian rim bump.
float crater_term(const glm::vec3& d, const std::vector<Crater>& craters) {
    float sum = 0.0f;
    for (const Crater& c : craters) {
        const float cosang = glm::clamp(glm::dot(d, c.centre), -1.0f, 1.0f);
        const float t = std::acos(cosang) / c.radius;
        const float depth = 0.35f * c.radius;
        if (t < 1.0f) sum += depth * (1.0f - t * t);
        const float r = (t - 1.0f) / 0.15f;
        sum -= 0.15f * depth * std::exp(-r * r);
    }
    return sum;
}

/// Radius of the rock (before axes) along unit direction d.
float radius_at(const glm::vec3& d, const FamilyParams& f, const RockParams& p) {
    const float n = detail::fbm(d * f.noise_scale, p.noise_seed, f.octaves);
    return 1.0f + f.displace * (n - 0.5f) * 2.0f - crater_term(d, p.craters);
}

// --- normals and UVs (ported) ---------------------------------------------
void recompute_smooth_normals(assets::MeshCpu& cpu) {
    for (auto& v : cpu.vertices) v.normal = glm::vec3(0.0f);
    for (size_t i = 0; i < cpu.indices.size(); i += 3) {
        auto& v0 = cpu.vertices[cpu.indices[i]];
        auto& v1 = cpu.vertices[cpu.indices[i+1]];
        auto& v2 = cpu.vertices[cpu.indices[i+2]];
        // Unnormalised cross product: area-weighted accumulation.
        const glm::vec3 fn = glm::cross(v1.position - v0.position,
                                        v2.position - v0.position);
        v0.normal += fn; v1.normal += fn; v2.normal += fn;
    }
    for (auto& v : cpu.vertices) {
        const float len = glm::length(v.normal);
        v.normal = (len > 1e-12f) ? v.normal / len : glm::vec3(0.0f, 1.0f, 0.0f);
    }
}

glm::vec2 spherical_uv(const glm::vec3& n) {
    return glm::vec2(std::atan2(n.z, n.x) / (2.0f * 3.14159265f) + 0.5f,
                     std::asin(glm::clamp(n.y, -1.0f, 1.0f)) / 3.14159265f + 0.5f);
}

/// A triangle whose vertices straddle the u=0/u=1 meridian would otherwise
/// interpolate BACKWARDS through the whole texture. For each triangle spanning
/// more than half the u range, duplicate its low-u (<= 0.5) vertices with
/// u += 1.0 (textures sample GL_REPEAT) and rewrite the index. Duplicates are
/// cached per source index, so a shared vertex is duplicated once and the
/// result is deterministic.
///
/// "<=", not "<": the icosahedron's mirror-pair seed vertices put first-level
/// midpoints exactly on the poles, where atan2(0,0)=0 gives u=0.5; a strict
/// "<" leaves such a vertex un-shifted inside a triangle that still straddles.
/// See the branch's asteroid_gen.cc for the full derivation.
void split_uv_seam(assets::MeshCpu& cpu) {
    std::map<std::uint32_t, std::uint32_t> seam_duplicates;
    for (size_t i = 0; i < cpu.indices.size(); i += 3) {
        const float u0 = cpu.vertices[cpu.indices[i]].uv.x;
        const float u1 = cpu.vertices[cpu.indices[i + 1]].uv.x;
        const float u2 = cpu.vertices[cpu.indices[i + 2]].uv.x;
        const float umin = std::min({u0, u1, u2});
        const float umax = std::max({u0, u1, u2});
        if (umax - umin <= 0.5f) continue;
        for (int k = 0; k < 3; ++k) {
            const std::uint32_t orig = cpu.indices[i + k];
            if (cpu.vertices[orig].uv.x > 0.5f) continue;
            auto it = seam_duplicates.find(orig);
            std::uint32_t dup;
            if (it != seam_duplicates.end()) {
                dup = it->second;
            } else {
                assets::MeshCpu::Vertex v = cpu.vertices[orig];
                v.uv.x += 1.0f;
                dup = static_cast<std::uint32_t>(cpu.vertices.size());
                cpu.vertices.push_back(v);
                seam_duplicates[orig] = dup;
            }
            cpu.indices[i + k] = dup;
        }
    }
}

}  // namespace

std::vector<assets::MeshCpu> generate_rock_lods(const RockSpec& spec) {
    const FamilyParams& f = *spec.family;
    const RockParams params = draw_params(spec);
    const std::vector<int>& subdivs = spec.kind->lod_subdivisions;

    // Pass 1: the displaced, stretched, uncut surface of every LOD.
    std::vector<Builder> spheres;
    std::vector<std::vector<glm::vec3>> positions;
    for (int s : subdivs) {
        spheres.push_back(icosphere(s));
        std::vector<glm::vec3> ps;
        ps.reserve(spheres.back().pos.size());
        for (const glm::vec3& d : spheres.back().pos)
            ps.push_back(d * radius_at(d, f, params) * params.axes);
        positions.push_back(std::move(ps));
    }

    // Each cut's distance is a fraction of the rock's SUPPORT along the cut
    // normal (max dot(p, n) over LOD0's pre-cut vertices), so every cut bites
    // regardless of the rock's elongation. A fraction of max|p| instead let
    // ~7% of cuts miss a stretched rock outright and left most of the rest
    // too shallow to form a fracture face. Measured on LOD0 so every LOD is
    // cut by the SAME planes.
    std::vector<float> cut_dist;
    for (const Cut& c : params.cuts) {
        float support = -std::numeric_limits<float>::infinity();
        for (const glm::vec3& q : positions[0]) support = std::max(support, glm::dot(q, c.normal));
        cut_dist.push_back(c.fraction * support);
    }

    // Plane cuts: pull everything beyond each plane onto it by CENTRAL
    // projection toward the origin (q *= dist / dot(q, n)). Orthogonal
    // flattening along n folded every cap triangle that faced away from n
    // back over the fracture face with reversed winding; scaling along the
    // ray keeps the surface star-shaped about the origin, so no face can
    // turn inward. Scaling toward the origin never pushes a point back past
    // an earlier plane (dist > 0), so the cuts do not undo one another. The
    // same planes are applied identically to every LOD, preserving the
    // shared-direction positions.
    for (std::vector<glm::vec3>& ps : positions)
        for (size_t k = 0; k < params.cuts.size(); ++k)
            for (glm::vec3& q : ps) {
                const float along = glm::dot(q, params.cuts[k].normal);
                if (along > cut_dist[k]) q *= cut_dist[k] / along;
            }

    // LOD0 is recentred on its AABB midpoint and scaled so its max|p| is
    // exactly the bound radius. Every lower LOD reuses LOD0's centre AND
    // scale: a shared direction lands at the same position in every LOD (no
    // popping), and a lower LOD's radius is <= the bound -- slightly short
    // where it lacks LOD0's extreme vertex. Normalising each LOD to its own
    // max|p| instead rescaled a coarse fragment LOD by up to ~10%.
    glm::vec3 lo(positions[0][0]), hi(positions[0][0]);
    for (const glm::vec3& q : positions[0]) { lo = glm::min(lo, q); hi = glm::max(hi, q); }
    const glm::vec3 centre = (lo + hi) * 0.5f;
    float lod0_max = 0.0f;
    for (const glm::vec3& q : positions[0]) lod0_max = std::max(lod0_max, glm::length(q - centre));
    const float scale = spec.bound_radius_m / lod0_max;

    std::vector<assets::MeshCpu> lods;
    for (size_t l = 0; l < subdivs.size(); ++l) {
        std::vector<glm::vec3>& ps = positions[l];
        for (glm::vec3& q : ps) q -= centre;
        for (glm::vec3& q : ps) q *= scale;

        assets::MeshCpu cpu;
        cpu.material_index = 0;
        cpu.node_index = 0;
        cpu.vertices.resize(ps.size());
        for (size_t i = 0; i < ps.size(); ++i) {
            cpu.vertices[i].position = ps[i];
            cpu.vertices[i].uv = spherical_uv(spheres[l].pos[i]);   // pre-cut direction
        }
        cpu.indices = spheres[l].idx;
        recompute_smooth_normals(cpu);
        split_uv_seam(cpu);
        lods.push_back(std::move(cpu));
    }
    return lods;
}

float bounding_radius(const assets::MeshCpu& m) {
    float r = 0.0f;
    for (const auto& v : m.vertices) r = std::max(r, glm::length(v.position));
    return r;
}

}  // namespace rockgen
