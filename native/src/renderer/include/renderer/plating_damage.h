// native/src/renderer/include/renderer/plating_damage.h
//
// SPIKE (damage redesign): the compact per-draw list of damage records that
// actually carry plating wear, so the layered-damage shader only pays for the
// records that matter. Pure CPU; no GL.
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

#include <glm/glm.hpp>

#include "renderer/aabb.h"
#include "scenegraph/hull_damage.h"
#include "voxel/structure_parts.h"

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

// opaque.frag's near-damage margin (plating_margin): nothing in the plating
// layer reaches further from a record than its reach plus this.
// params[5] + params[6] + params[15] + params[2].
float plating_margin(const float* params);

// The records whose sphere grown by `margin` (a.w + margin) touches
// `body_box` (body frame), in list order, as indices into `list`. Returns how
// many. A mesh draw uploads only these: a pixel of the mesh lies in its box,
// so a record left out is further than reach + margin from every pixel and
// adds nothing to it (opaque.frag's near test, wear sums and gradients all
// skip it there). The test is grown by a small slack, so float rounding of
// p_body can only ever keep an extra record, never drop a needed one.
// The margin a mesh's record subset is culled with (records_near): it bounds
// the distance from a pixel to every point where opaque.frag reads a record
// for it (the plate-edge march and the panel centres of the pixel's part
// chart), and is never below plating_margin. `parts` = the hull's structure
// parts as the draw uploads them (nullptr = not detected yet: the box chart);
// a cylinder part's bound grows with the distance from its axis, taken over
// `body_box`. Derivation in plating_damage.cc.
float plating_cull_margin(const float* params,
                          const std::vector<voxel::StructurePart>* parts,
                          const Aabb& body_box);

int records_near(const DamageList& list, const Aabb& body_box, float margin,
                 std::array<std::uint8_t, kMaxDamage>& out);

// The records that can break an interior plate (hull_interior.frag's blown
// tests: wear plus at most 1.25 x tear noise past deck break). Record i is
// kept when the summed wear of every record whose sphere overlaps i's (i
// included) is at least params[24] - 1.25 * |params[19]|. Exact: if a left-out
// record k covers a point, every record covering that point overlaps k, so the
// point's wear is at most k's overlap sum, below the threshold, and the point
// cannot be blown with or without k. Where only kept records cover a point
// the subset's wear is the full list's, summed in the same order. Indices
// ascend.
struct DeckBreakSet {
    int count = 0;
    std::array<int, kMaxDamage> idx{};
};
DeckBreakSet deck_break_subset(const DamageList& list, const float* params);

// Every record of `list`, in order (record culling off).
DeckBreakSet full_deck_break_set(const DamageList& list);

}  // namespace renderer::plating
