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
};

}  // namespace assets
