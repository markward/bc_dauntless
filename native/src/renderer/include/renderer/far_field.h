// native/src/renderer/include/renderer/far_field.h
// Far tier (docs/superpowers/specs/2026-10-01-far-tier-design.md, §2-3).
#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include <glm/glm.hpp>
#include <glm/gtc/type_precision.hpp>
#include <renderer/far_math.h>

namespace renderer::far {

struct Population {
    int kind = 0;                 // 0 = minor (catalogue fragment), 1 = major
    float density_at_1 = 0.0f;    // rocks / GU^3 at a == 1
    float a_lo = 0.0f, a_hi = 1.0f;   // n = density_at_1 * clamp((a-a_lo)/(a_hi-a_lo))
    PowerLaw size;
    std::vector<int> rocks;       // catalogue indices
    std::vector<float> weights;   // parallel to rocks
    glm::vec3 albedo{0.4f};       // mean avg_albedo of `rocks` (haze colour)
};

struct DiscSource {
    std::uint32_t id = 0;
    std::string frame;            // system name; active only when it is the viewed frame
    glm::dvec3 centre{0.0};       // system coordinates
    glm::vec3 normal{0.0f, 0.0f, 1.0f};
    std::vector<glm::vec2> table; // (r_gu, a), sorted by r
    float outer_fade_gu = 20000.0f;
    float scale_height_frac = 0.03f, scale_height_min_gu = 1000.0f;
    std::uint32_t seed = 0;
    std::vector<glm::dvec4> explicit_regions;   // xyz centre (system), w radius
    std::vector<Population> pops;
};

float table_a(const DiscSource& s, float rho);
float scale_height(const DiscSource& s, float rho);
float density_a(const DiscSource& s, const glm::dvec3& x_sys);
float pop_density(const Population& p, float a);

struct GenParams { float k_ref = 1713.0f, p_min = 0.25f; int size_classes = 4, cells_per_range = 4; };

struct ClassBin { float r_lo = 0, r_hi = 0, share = 0, cell_gu = 1; };
std::vector<ClassBin> size_classes(const Population& p, const GenParams& g);

struct FarRock {
    glm::dvec3 pos_sys{0.0};
    float radius = 0.0f;
    int rock = 0;                 // catalogue index
    glm::vec3 tumble_axis{0.0f, 0.0f, 1.0f};
    float tumble_rate = 0.0f;     // rad/s
    float phase = 0.0f;           // rad
};

std::vector<FarRock> generate_cell(const DiscSource& s, int pop, int cls,
                                   const glm::i64vec3& ijk, const GenParams& g);

}  // namespace renderer::far
