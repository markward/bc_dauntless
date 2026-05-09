// native/src/scenegraph/include/scenegraph/instance.h
#pragma once

#include <cstdint>
#include <glm/glm.hpp>

namespace scenegraph {

using ModelHandle = std::uint64_t;  // Opaque key into the asset cache.

struct InstanceId {
    std::uint32_t index = 0;
    std::uint32_t generation = 0;
    bool operator==(const InstanceId&) const = default;
};

struct Instance {
    ModelHandle model_handle = 0;
    glm::mat4 world{1.0f};
    bool visible = true;
};

}  // namespace scenegraph
