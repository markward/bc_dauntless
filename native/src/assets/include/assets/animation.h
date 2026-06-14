// native/src/assets/include/assets/animation.h
#pragma once

#include <filesystem>
#include <string>
#include <unordered_map>
#include <vector>

#include <glm/glm.hpp>
#include <glm/gtc/quaternion.hpp>

namespace assets {

struct AnimationClip {
    std::string name;
    float duration_seconds = 0.0f;

    struct TranslationKey { float time; glm::vec3 value; };
    struct RotationKey    { float time; glm::quat value; };
    struct ScaleKey       { float time; float     value; };
    struct VisibilityKey  { float time; bool      value; };
    struct FloatKey       { float time; float     value; };

    struct NodeTrack {
        std::string                  target_node_name;
        std::vector<TranslationKey>  translation;
        std::vector<RotationKey>     rotation;
        std::vector<ScaleKey>        scale;
        std::vector<VisibilityKey>   visibility;
        std::vector<FloatKey>        floats;
    };

    std::vector<NodeTrack> tracks;
};

/// Parse a NIF and extract its animation clips WITHOUT building a model.
/// Placement/animation NIFs (e.g. data/animations/db_stand_t_l.nif) carry only
/// keyframe controllers and no NiTriShape geometry, so the full model build
/// rejects them ("no NiTriShape in NIF file"). This loads just the clips.
/// Returns empty on parse failure or if the NIF has no animation.
std::vector<AnimationClip> load_animation_clips(
    const std::filesystem::path& nif_path);

/// Load a placement-animation NIF's per-bone REST node transforms, keyed by
/// node name. A BC placement NIF (e.g. db_stand_t_l.nif) stores the officer's
/// placed standing pose AS its static node skeleton — each NiNode's local
/// transform is the bone's parent-relative rest pose, with the root bone
/// carrying the station offset. Applying these to a body's matching bone nodes
/// poses + places the officer (the keyframe controllers only animate around
/// this rest pose; the rest pose alone is the static placement). Returns empty
/// on parse failure. The rest pose is a base; the clip's keyframe rotations are
/// overlaid (per channel) to settle it into the standing pose. `sample_at_start`
/// evaluates the START of the clip (officer at the station for "move-to-L1"
/// clips) instead of the settled END.
std::unordered_map<std::string, glm::mat4> load_pose_locals(
    const std::filesystem::path& nif_path, bool sample_at_start = false);

}  // namespace assets
