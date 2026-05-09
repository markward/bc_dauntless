// native/src/assets/include/assets/animation.h
#pragma once

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

}  // namespace assets
