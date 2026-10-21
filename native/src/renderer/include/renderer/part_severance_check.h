// native/src/renderer/include/renderer/part_severance_check.h
//
// Which detected structure parts have come away from the main body: a part is
// severed when the damage has blown through everything joining it to the main
// body. Pure CPU; no GL. The caller (throttled, ~0.5 s) owns the per-ship
// bookkeeping of parts already severed.
#pragma once
#include <cstdint>
#include <vector>

#include <glm/glm.hpp>

#include "renderer/plating_damage.h"
#include "scenegraph/instance.h"
#include "voxel/structure_parts.h"

namespace renderer {

struct SeveredPart {
    int part = -1;
    int voxels = 0;                 // surviving voxels of the part
    glm::vec3 centroid_body{0};
    glm::vec3 min_body{0}, max_body{0};
};

constexpr float kReachedFraction = 0.05f;
constexpr int kMinPartVoxels = 64;

// A voxel survives when the interior wear at its centre (all records, no
// facing; the same sum hull_interior.frag's interior_wear uses, a.w as
// uploaded) is below deck_break. Main body = the part with the most surviving
// voxels. Flood 6-connected surviving voxels from it; a part is severed when
// fewer than kReachedFraction of its surviving voxels were reached and it has
// at least kMinPartVoxels surviving. Bit i of already_severed skips part i.
// Parts with index >= 32 are beyond the mask and never sever.
std::vector<SeveredPart> find_severed_parts(const voxel::StructureSegmentation&,
                                            const plating::DamageList&, float deck_break,
                                            std::uint32_t already_severed);

// Articulated instances (any node override) are never structure-checked.
bool can_structure_sever(const scenegraph::Instance& inst);

}  // namespace renderer
