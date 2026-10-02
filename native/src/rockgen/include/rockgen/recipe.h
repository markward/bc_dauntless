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

/// One "rock collection" density variant: how many rocks a collection holds.
struct CollectionVariant {
    std::string name;
    int rocks_min = 0, rocks_max = 0;
};

/// recipe.json "collections" (optional; absent == no collections):
///   {"count": 16, "family": "silicate", "view_size": 128,
///    "variants": [{"name": "sparse", "rocks": [20, 30]}, ...],
///    "size": [0.03, 0.15], "exponent": 2.5}
/// `count` collections per variant; part radii are a power law (exponent)
/// over `size`, as fractions of the collection radius.
struct CollectionParams {
    int count = 0;
    std::string family;
    int view_size = 128;
    std::vector<CollectionVariant> variants;
    float size_min = 0.03f, size_max = 0.15f;
    float exponent = 2.5f;
};

struct Recipe {
    int tool_version = 1; std::uint64_t seed = 0; float bound_radius_m = 100.0f;
    int impostor_view_size = 128; int volume_dims = 48;
    KindParams major, fragment;
    std::vector<FamilyParams> families;          // order as in the JSON array
    CollectionParams collections;                // count 0 when the recipe has none
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

struct CollectionSpec {
    std::string id;          // "collections/dense_00"
    std::string variant;     // "dense"
    std::uint64_t seed = 0;  // fnv1a64(to_string(recipe.seed) + ":" + id)
    int rocks = 0;           // in the variant's [min, max], drawn from `seed`
};

/// Variants in recipe order; within a variant, nn from 00 to count-1.
std::vector<CollectionSpec> expand_collections(const Recipe& r);

/// Standard FNV-1a 64.
std::uint64_t fnv1a64(const std::string& s);

}  // namespace rockgen
