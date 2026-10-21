// native/src/renderer/include/renderer/plating_damage.h
//
// SPIKE (damage redesign): the compact per-draw list of damage records that
// actually carry plating wear, so the layered-damage shader only pays for the
// records that matter. Pure CPU; no GL.
#pragma once
#include <cstddef>

#include <glm/glm.hpp>

#include "scenegraph/hull_damage.h"

namespace renderer::plating {

constexpr int kMaxDamage = 64;
static_assert(kMaxDamage >= static_cast<int>(scenegraph::HullDamageStore::kCapacity),
              "the plating damage list must hold every store slot");
// Floats in dauntless_plating::g_params / the u_plating upload / the binding.
constexpr int kParamCount = 32;

struct DamageList {
    int count = 0;
    glm::vec4 a[kMaxDamage];   // centre_body.xyz, reach (model units)
    glm::vec4 b[kMaxDamage];   // normal_body.xyz (zero for Internal), wear
    glm::vec4 c[kMaxDamage];   // kind (1 = Surface, 3 = Internal), 0, 0, 0
    bool torn_possible = false;
};

// params = dauntless_plating::g_params (kParamCount floats). Only ACTIVE records
// with wear > 0 enter. Surface reach is scaled by params[7]; Internal reach and
// facing are kept as stored. torn_possible: summed wear reaches the lowest
// breach the shader can return, params[16] * (1 - 0.4 * params[22]) - params[23]
// (toughness spread, lumps), minus the largest tear-noise lift (0.75 * params[19]).
DamageList build_damage_list(const scenegraph::HullDamageStore& store,
                             const float* params);

// Whether a draw takes the PLATING program: the layer is enabled (params[0])
// and the list holds at least one record. Everything else draws through the
// stock program and uploads nothing for plating. frame.cc's
// submit_opaque_in_pass and the GL tests share this one rule.
bool wants_plating(const DamageList& list, const float* params);

}  // namespace renderer::plating
