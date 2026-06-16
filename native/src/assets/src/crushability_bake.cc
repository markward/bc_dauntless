// native/src/assets/src/crushability_bake.cc
//
// Per-vertex hull "crushability" bake for hull-damage deformation (spec §2).
// PER-MESH approximation: each vertex's inward ray is cast against the vertex's
// own NiTriShape triangles, not the whole ship. Thin single-shape extremities
// (bow tip, saucer rim) crush; thick hull resists. Cross-mesh thickness would
// be large anyway (-> low crushability), so per-mesh is adequate and far
// cheaper than a whole-model cast.
#include "assets/crushability_bake.h"

#include <algorithm>
#include <cmath>
#include <limits>

namespace assets {

float crushability_from_thickness(float thickness, float ref) {
    if (ref <= 0.0f) return 0.0f;
    return std::clamp(1.0f - thickness / ref, 0.0f, 1.0f);
}

}  // namespace assets
