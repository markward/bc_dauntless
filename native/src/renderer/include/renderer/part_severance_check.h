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
#include "scenegraph/world.h"
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
// Parts with index >= 32 are beyond the mask and never sever, and the main body is chosen among parts < 32.
std::vector<SeveredPart> find_severed_parts(const voxel::StructureSegmentation&,
                                            const plating::DamageList&, float deck_break,
                                            std::uint32_t already_severed);

// Per-voxel interior wear (same sum as the shader's interior_wear), each record
// accumulated over its sphere's voxel box only. Exposed for tests.
std::vector<float> interior_wear_field(const voxel::VoxelVolume& vol,
                                       const plating::DamageList& dmg);

// Articulated instances (any node override) are never structure-checked.
bool can_structure_sever(const scenegraph::Instance& inst);

// The plating draw can hide parts 0..kMaxHideableParts-1 only (opaque.frag
// MAX_PARTS: upload_plating uploads that many). A part past it never
// severs: it could not leave the parent's draw.
constexpr int kMaxHideableParts = 12;

struct SeveredSplit {
    SeveredPart part;               // body frame, model units
    scenegraph::InstanceId chunk;   // the new instance drawing only the part
    int total_voxels = 0;           // every solid voxel of the hull
};

// Break off every part of `parent` that find_severed_parts reports (parts it
// already lost skipped): ORs the part's bit into parent.severed_parts and
// creates a chunk instance of the same model on a copy of the parent's pose
// and render state (as hull_split_detached does) and its damage records,
// drawing only that part (only_part). Rocks, articulated hulls and stale ids
// never sever.
std::vector<SeveredSplit> split_severed_parts(scenegraph::World& world,
                                              scenegraph::InstanceId parent,
                                              const voxel::StructureSegmentation& seg,
                                              const plating::DamageList& dmg,
                                              float deck_break);

}  // namespace renderer
