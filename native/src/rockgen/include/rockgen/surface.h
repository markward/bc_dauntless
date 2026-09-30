// native/src/rockgen/include/rockgen/surface.h
#pragma once

#include <assets/texture.h>
#include <rockgen/recipe.h>

#include <glm/glm.hpp>

namespace rockgen {

/// A baked per-family surface: base colour and a tangent-space normal map,
/// both RGB8, `spec.kind->texture_size` square, plus the sphere-area-weighted
/// mean of the base colour (linear, 0..1). Deterministic: byte-identical
/// output for the same spec, regardless of thread scheduling.
struct RockSurface {
    assets::Image base_color;
    assets::Image normal;
    glm::vec3 avg_albedo{0.0f};
};

/// Inverts the SAME spherical UV mapping shape.cc's mesh UVs use (shared via
/// src/uv_sphere.h), so the bake and the mesh can never disagree.
RockSurface generate_rock_surface(const RockSpec& spec);

}  // namespace rockgen
