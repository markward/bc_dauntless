// native/src/rockgen/src/collection.cc
//
// Deterministic arrangement of a rock collection. The catalogue is
// committed, so the draw order below is load-bearing: per part, a centre
// (rejection, 3 draws per try), a radius (1 draw), a mesh pick (1 draw),
// an orientation (3 draws).
#include <rockgen/collection.h>

#include <glm/gtc/quaternion.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <random>
#include <stdexcept>

namespace rockgen {
namespace {

constexpr double kPi = 3.14159265358979323846;

/// Parts smaller than this (fraction of the collection radius) use the
/// family's fragments; larger ones its majors.
constexpr float kFragmentBelow = 0.08f;

// std::mt19937_64 is fully specified by the standard; the *_distribution
// classes are not, so [0,1) is mapped by hand from the top 53 bits (as in
// shape.cc).
struct Rng {
    std::mt19937_64 eng;
    explicit Rng(std::uint64_t seed) : eng(seed) {}
    double unit() { return static_cast<double>(eng() >> 11) * 0x1.0p-53; }
};

/// Inverse-CDF draw from p(r) ~ r^-k on [lo, hi].
double power_law(double u, double lo, double hi, double k) {
    if (std::abs(k - 1.0) < 1e-9) return lo * std::pow(hi / lo, u);
    const double e = 1.0 - k;
    const double a = std::pow(lo, e), b = std::pow(hi, e);
    return std::pow(a + u * (b - a), 1.0 / e);
}

}  // namespace

std::vector<CollectionPart> arrange_collection(const Recipe& r,
                                               const std::vector<RockSpec>& rocks,
                                               const CollectionSpec& c) {
    const CollectionParams& cp = r.collections;
    std::vector<std::size_t> fragments, majors;
    for (std::size_t i = 0; i < rocks.size(); ++i) {
        if (rocks[i].family == nullptr || rocks[i].family->name != cp.family) continue;
        (rocks[i].fragment ? fragments : majors).push_back(i);
    }
    if (fragments.empty() && majors.empty())
        throw std::runtime_error("collection " + c.id + ": family has no rocks: " + cp.family);
    if (fragments.empty()) fragments = majors;
    if (majors.empty()) majors = fragments;

    Rng rng(c.seed);
    std::vector<CollectionPart> parts;
    parts.reserve(static_cast<std::size_t>(std::max(0, c.rocks)));
    for (int n = 0; n < c.rocks; ++n) {
        CollectionPart p;
        glm::dvec3 q;
        do {
            q = glm::dvec3(2.0 * rng.unit() - 1.0, 2.0 * rng.unit() - 1.0, 2.0 * rng.unit() - 1.0);
        } while (glm::dot(q, q) > 1.0);
        p.centre = glm::vec3(q);
        p.radius = static_cast<float>(power_law(rng.unit(), cp.size_min, cp.size_max, cp.exponent));
        const std::vector<std::size_t>& pool = (p.radius < kFragmentBelow) ? fragments : majors;
        p.rock = pool[std::min(pool.size() - 1,
                               static_cast<std::size_t>(rng.unit() * static_cast<double>(pool.size())))];
        // Shoemake's uniform random unit quaternion.
        const double u1 = rng.unit(), u2 = rng.unit(), u3 = rng.unit();
        const double s1 = std::sqrt(1.0 - u1), s2 = std::sqrt(u1);
        const glm::dquat rot(s2 * std::cos(2.0 * kPi * u3),   // w
                             s1 * std::sin(2.0 * kPi * u2),   // x
                             s1 * std::cos(2.0 * kPi * u2),   // y
                             s2 * std::sin(2.0 * kPi * u3));  // z
        p.rotation = glm::mat3(glm::mat3_cast(rot));
        parts.push_back(p);
    }

    // Frame on the unit ball: max(|centre| + radius) == 1.
    float reach = 0.0f;
    for (const CollectionPart& p : parts) reach = std::max(reach, glm::length(p.centre) + p.radius);
    if (reach > 0.0f) {
        for (CollectionPart& p : parts) {
            p.centre /= reach;
            p.radius /= reach;
        }
    }
    return parts;
}

glm::mat4 part_xform(const CollectionPart& p, float bound_radius_m) {
    const float s = p.radius / bound_radius_m;
    glm::mat4 m(1.0f);
    for (int col = 0; col < 3; ++col) m[col] = glm::vec4(p.rotation[col] * s, 0.0f);
    m[3] = glm::vec4(p.centre, 1.0f);
    return m;
}

}  // namespace rockgen
