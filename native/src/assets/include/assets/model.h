// native/src/assets/include/assets/model.h
#pragma once

#include <filesystem>
#include <string>
#include <vector>

#include <glm/glm.hpp>

#include <assets/animation.h>
#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/skeleton.h>
#include <assets/texture.h>

namespace assets {

struct Node {
    std::string       name;
    int               parent_index = -1;
    glm::mat4         local_transform{1.0f};
    std::vector<int>  children;
    std::vector<int>  meshes;
};

struct Model {
    std::vector<Node>          nodes;
    int                        root_node = 0;
    std::vector<Mesh>          meshes;
    std::vector<Texture>       textures;
    std::vector<Material>      materials;
    Skeleton                   skeleton;
    std::vector<AnimationClip> animations;
    std::filesystem::path      source;
};

}  // namespace assets
