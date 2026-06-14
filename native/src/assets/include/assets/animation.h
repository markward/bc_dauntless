// native/src/assets/include/assets/animation.h
#pragma once

#include <filesystem>
#include <string>
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

}  // namespace assets
