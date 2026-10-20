// native/src/renderer/include/renderer/plating_damage.h
//
// SPIKE (damage redesign): the compact per-draw list of damage records that
// actually carry plating wear, so the layered-damage shader only pays for the
// records that matter. Pure CPU; no GL.
#pragma once
#include <glm/glm.hpp>

#include "scenegraph/damage_decals.h"

namespace renderer::plating {

constexpr int kMaxDamage = 24;

struct DamageList {
    int count = 0;
    glm::vec4 a[kMaxDamage];   // centre_body.xyz, reach (model units)
    glm::vec4 b[kMaxDamage];   // normal_body.xyz (zero for Internal), wear
    glm::vec4 c[kMaxDamage];   // kind (1 = Scorch, 3 = Internal), 0, 0, 0
    bool torn_possible = false;
};

// params = dauntless_plating::g_params (24 floats). Only active Scorch with
// wear > 0 and Internal records enter. torn_possible: summed wear reaches the
// breach wear (params[16]) minus the largest tear-noise lift (0.75 * params[19]).
DamageList build_damage_list(const scenegraph::DamageDecalRing& ring,
                             const float* params);

}  // namespace renderer::plating
