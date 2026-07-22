// native/src/renderer/include/renderer/bone_palette.h
#pragma once
#include <cstddef>
#include <vector>
#include <glm/glm.hpp>
#include <assets/skeleton.h>

namespace assets { struct Model; }

namespace renderer {

/// Maximum bones in the skinning palette (matches u_bones[128] in skinned.vert).
inline constexpr std::size_t kMaxBones = 128;

// ── Officer jaw drive (SP3 lip-sync) ────────────────────────────────────────
// BC has no dedicated jaw bone: every bridge-character head skins its mouth/chin
// cluster to the repurposed biped bone "Bip01 Ponytail1". These constants are
// the MEASURED values from the Task-8 probes (task-8-report.md,
// project_lipsync_re_findings) — NOT the design brief's 7° estimate.
//
// The bone's rest LOCAL already holds ~111.481° about bone-local +Z; the three
// global mouth-viseme clips (MouthClosed/MouthOpenPartly/MouthOpen) hold it at
// rest / rest+5° / rest+10°, a 10° jaw-drop. The rotation axis is unanimous
// (bone-local +Z) across every mouth clip quaternion and the head bind.
inline constexpr char       kJawBoneName[] = "Bip01 Ponytail1";
inline constexpr glm::vec3  kJawAxis       = {0.0f, 0.0f, 1.0f};   // bone-local +Z
inline constexpr float      kJawMaxDropRad = 0.17453f;             // 10° (Task 8)

/// Build the skinning palette: palette[b] = world_pose(b) * inverse_bind_pose(b).
/// `local_pose`, if non-null, supplies a local transform per bone (same order as
/// skeleton.bones); when null, each bone's bind local_transform is used (so the
/// palette is identity per bone). Result clamped to kMaxBones with a warning.
///
/// Precondition: each bone's parent_index must be acyclic and in range (-1 or a
/// valid bone index). The world-transform chain-walk traverses the full ancestry
/// to the root (mirroring assets::detail::compute_inverse_bind_poses); a malformed
/// chain would loop forever or read out of bounds. The kMaxBones clamp limits how
/// many palette entries are produced, NOT how far the chain-walk traverses, so an
/// in-range bone may legitimately have an ancestor with index >= kMaxBones.
std::vector<glm::mat4> build_bone_palette(
    const assets::Skeleton& skeleton,
    const std::vector<glm::mat4>* local_pose);

/// Compose an ADDITIONAL jaw-drop rotation onto the "Bip01 Ponytail1" bone's
/// local transform, IN PLACE, before the palette is built. `openness` is
/// clamped to [0,1]; angle = openness * kJawMaxDropRad about kJawAxis
/// (bone-local +Z). At openness==0 the composed rotation is identity, so the
/// mouth returns to REST — callers re-pose every frame while a jaw is active so
/// a settled officer's palette does not stay stuck open. No-op (leaves `locals`
/// untouched) if the bone is absent or its index is out of range for `locals`.
void apply_jaw_rotation(const assets::Model& model,
                        std::vector<glm::mat4>& locals, float openness);

}  // namespace renderer
