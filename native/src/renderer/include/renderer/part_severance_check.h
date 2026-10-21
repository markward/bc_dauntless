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

// One piece cut off the hull: the structure parts that leave together.
struct SeveredPiece {
    std::uint32_t parts = 0;        // bit i: structure part i leaves with it
    int voxels = 0;                 // surviving voxels of the piece
    glm::vec3 centroid_body{0};
    glm::vec3 min_body{0}, max_body{0};
};

constexpr int kMinPartVoxels = 64;

// What the severance check actually did (tests): `floods` counts
// find_severed_parts calls that reached the alive/flood passes, `checks`
// split_severed_parts calls that ran find_severed_parts at all.
struct SeveranceStats {
    int floods = 0;
    int checks = 0;
};

// A voxel survives when the interior wear at its centre (all records, no
// facing; the same sum hull_interior.frag's interior_wear uses, a.w as
// uploaded) is below deck_break. Main body = the part with the most surviving
// voxels. Flood 6-connected surviving voxels from it. What the flood did not
// reach falls into 6-connected components; a part belongs to a component when
// the MAJORITY of its surviving voxels lie in it (unreached), and a component
// of at least kMinPartVoxels voxels holding at least one part is one piece
// (Ruling 4: a cut-off assembly leaves in one piece). Bit i of
// already_severed keeps part i out of every piece.
// Parts with index >= 32 are beyond the mask and never sever, and the main body is chosen among parts < 32.
// Bit i of `gone` marks part i as already LEFT the hull: its voxels are not
// survivors (never the main body, never a bridge for the flood) and it is
// not reported. `already_severed` only stops a part being reported.
std::vector<SeveredPiece> find_severed_parts(const voxel::StructureSegmentation&,
                                            const plating::DamageList&, float deck_break,
                                            std::uint32_t already_severed,
                                            std::uint32_t gone = 0,
                                            SeveranceStats* stats = nullptr);

// Per-voxel interior wear (same sum as the shader's interior_wear), each record
// accumulated over its sphere's voxel box only. Exposed for tests.
std::vector<float> interior_wear_field(const voxel::VoxelVolume& vol,
                                       const plating::DamageList& dmg);

// The structure part whose voxel holds `body_point` (body frame, model
// units); -1 outside the grid, in an empty voxel or with no segmentation.
int structure_part_at(const voxel::StructureSegmentation&, const glm::vec3& body_point);

// Articulated instances (any node override) are never structure-checked.
bool can_structure_sever(const scenegraph::Instance& inst);

// The plating draw can hide parts 0..kMaxHideableParts-1 only (opaque.frag
// MAX_PARTS: upload_plating uploads that many). A part past it never
// severs: it could not leave the parent's draw.
constexpr int kMaxHideableParts = 12;

struct SeveredSplit {
    SeveredPiece piece;             // body frame, model units
    scenegraph::InstanceId chunk;   // the new instance drawing only its parts
    int total_voxels = 0;           // every solid voxel of the hull
};

// Break off every part of `parent` that find_severed_parts reports (parts it
// already lost are `gone`; parts past kMaxHideableParts are never reported):
// ORs the piece's parts into parent.severed_parts and
// creates a chunk instance of the same model on a copy of the parent's pose
// and render state (as hull_split_detached does) and its damage records,
// drawing only those parts (shown_parts), with its damage decals, and dead
// (emissive_scale 0: no window glow). Rocks,
// chunks, articulated hulls, skinned models (`skinned`: the draw cannot hide
// their parts) and stale ids never sever.
std::vector<SeveredSplit> split_severed_parts(scenegraph::World& world,
                                              scenegraph::InstanceId parent,
                                              const voxel::StructureSegmentation& seg,
                                              const plating::DamageList& dmg,
                                              float deck_break,
                                              SeveranceStats* stats = nullptr,
                                              bool skinned = false);

}  // namespace renderer
