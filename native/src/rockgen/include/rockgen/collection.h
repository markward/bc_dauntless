// native/src/rockgen/include/rockgen/collection.h
#pragma once

#include <rockgen/recipe.h>

#include <glm/glm.hpp>

#include <cstddef>
#include <vector>

// A "rock collection": a deterministic cluster of catalogue rocks, baked into
// one impostor (the rock-fields mid band draws one per tile).
namespace rockgen {

struct CollectionPart {
    std::size_t rock = 0;          // index into expand_recipe(recipe)
    glm::vec3 centre{0.0f};        // collection frame: |centre| + radius <= 1
    float radius = 0.0f;           // the part's bound radius in the collection frame
    glm::mat3 rotation{1.0f};      // part -> collection orientation (proper rotation)
};

/// Deterministic from `c.seed`: `c.rocks` parts, centres uniform in the unit
/// ball (rejection), radii a power law over the recipe's `size` range,
/// uniform random orientation; meshes from the recipe's collection family --
/// fragments for radius < 0.08, majors otherwise. Then uniformly rescaled so
/// max(|centre| + radius) over the parts is exactly 1.
std::vector<CollectionPart> arrange_collection(const Recipe& r,
                                               const std::vector<RockSpec>& rocks,
                                               const CollectionSpec& c);

/// The part's mesh -> collection transform for a rock mesh whose bounding
/// radius is `bound_radius_m`: translate(centre) * rotation * scale(radius / bound).
glm::mat4 part_xform(const CollectionPart& p, float bound_radius_m);

}  // namespace rockgen
