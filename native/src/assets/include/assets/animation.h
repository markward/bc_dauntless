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

    /// Per-node REST local transform of the clip's SOURCE NIF, keyed by node
    /// name. A BC placement clip (e.g. db_stand_t_l.nif) animates a skeleton
    /// whose REST pose is the placed standing pose — NOT the body NIF's bind
    /// (T-pose). The clip's tracks are sparse (often only some bones, some
    /// channels), so the rest pose IS the base the keyframes overlay. Posing a
    /// body against its own T-pose bind instead contorts it (the clip lacks the
    /// arm rotations that the rest pose carries). sample_pose uses this as the
    /// per-bone base/fallback. Empty if the source had no node hierarchy.
    std::unordered_map<std::string, glm::mat4> rest_locals;
};

/// Parse a NIF and extract its animation clips WITHOUT building a model.
/// Placement/animation NIFs (e.g. data/animations/db_stand_t_l.nif) carry only
/// keyframe controllers and no NiTriShape geometry, so the full model build
/// rejects them ("no NiTriShape in NIF file"). This loads just the clips.
/// Returns empty on parse failure or if the NIF has no animation.
std::vector<AnimationClip> load_animation_clips(
    const std::filesystem::path& nif_path);

}  // namespace assets
