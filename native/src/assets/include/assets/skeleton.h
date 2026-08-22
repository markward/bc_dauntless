// native/src/assets/include/assets/skeleton.h
#pragma once

#include <string>
#include <vector>

#include <glm/glm.hpp>

namespace assets {

struct Bone {
    std::string name;
    int         parent_index = -1;
    glm::mat4   local_transform{1.0f};
    glm::mat4   inverse_bind_pose{1.0f};
};

struct Skeleton {
    std::vector<Bone> bones;
    int               root_bone_index = -1;
    /// The bone that carries placement and root motion — NOT root_bone_index.
    /// BC character bodies nest the biped three levels down
    /// (NiNode '' -> NiNode '' -> 'Scene Root' -> 'Bip01'), so the skeleton
    /// root is an UNNAMED node no clip track can ever name, while every
    /// placement offset and every baked root translation lives on "Bip01".
    /// -1 when the skeleton has no biped (ships, props): callers fall back to
    /// root_bone_index.
    int               anim_root_bone_index = -1;
};

}  // namespace assets
