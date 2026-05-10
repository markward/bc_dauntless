// native/src/scenegraph/include/scenegraph/world.h
#pragma once

#include "scenegraph/instance.h"

#include <vector>

namespace scenegraph {

class World {
public:
    InstanceId create_instance(ModelHandle model);
    void destroy_instance(InstanceId id);
    void set_world_transform(InstanceId id, const glm::mat4& world);
    void set_visible(InstanceId id, bool visible);

    bool is_valid(InstanceId id) const noexcept;
    Instance* get(InstanceId id) noexcept;
    const Instance* get(InstanceId id) const noexcept;

    /// Per-frame propagation hook. v1 is a pass-through (intra-model node
    /// hierarchy is already baked into Model::nodes by the asset pipeline;
    /// inter-instance hierarchy doesn't exist yet). Reserved so item 6
    /// hardpoint-attachment work can hook in later without an API break.
    void propagate() noexcept {}

    /// Iterate every visible instance. Used by the renderer's frame submitter.
    template <typename Fn>
    void for_each_visible(Fn&& fn) const {
        for (std::size_t i = 0; i < slots_.size(); ++i) {
            if (slots_[i].alive && slots_[i].instance.visible) {
                fn(slots_[i].instance);
            }
        }
    }

private:
    struct Slot {
        Instance instance;
        std::uint32_t generation = 0;
        bool alive = false;
    };
    std::vector<Slot> slots_;
    std::vector<std::uint32_t> free_;
};

}  // namespace scenegraph
