// native/src/rockgen/include/rockgen/recipe.h
#pragma once

#include <glm/glm.hpp>

#include <cstdint>
#include <string>
#include <vector>

// The rock-catalogue recipe: the committed JSON that drives the catalogue
// tool. Parsing is strict -- every key is required and a missing or
// mistyped key throws std::runtime_error naming it.
namespace rockgen {

struct FamilyParams {
    std::string name;
    int majors = 0, fragments = 0;
    glm::vec3 color_a{0.4f}, color_b{0.5f};   // palette endpoints (linear RGB)
    float gloss = 0.12f;
    float displace = 0.35f; int octaves = 5; float noise_scale = 2.3f;
    float axis_min = 0.7f, axis_max = 1.3f;
    int craters_min = 0, craters_max = 0; float crater_radius_min = 0.1f, crater_radius_max = 0.25f;
    int detail_octaves = 3; float detail_scale = 7.0f; float normal_strength = 2.5f;
};

struct KindParams {
    std::vector<int> lod_subdivisions;
    int texture_size = 256;
    int cuts_min = 0, cuts_max = 0;
};

struct Recipe {
    int tool_version = 1; std::uint64_t seed = 0; float bound_radius_m = 100.0f;
    int impostor_view_size = 128; int volume_dims = 48;
    KindParams major, fragment;
    std::vector<FamilyParams> families;          // order as in the JSON array
};

struct RockSpec {
    std::string id;                               // "majors/silicate_01" | "fragments/icy_03"
    bool fragment = false;
    const FamilyParams* family = nullptr;         // points into the Recipe -- keep it alive
    const KindParams* kind = nullptr;
    std::uint64_t seed = 0;                       // fnv1a64(to_string(recipe.seed) + ":" + id)
    float bound_radius_m = 100.0f;
};

/// Throws std::runtime_error naming the offending key.
Recipe parse_recipe(const std::string& json_text);

/// Families in recipe order; within a family, majors then fragments; nn from 01.
std::vector<RockSpec> expand_recipe(const Recipe& r);
/// RockSpec points into the Recipe; expanding a temporary would dangle.
std::vector<RockSpec> expand_recipe(Recipe&&) = delete;

/// Standard FNV-1a 64.
std::uint64_t fnv1a64(const std::string& s);

}  // namespace rockgen
