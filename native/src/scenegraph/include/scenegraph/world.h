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
    void set_bone_palette(InstanceId id, std::vector<glm::mat4> palette);
    void set_visible(InstanceId id, bool visible);
    void set_pass(InstanceId id, Pass pass);
    void set_comm_set_id(InstanceId id, std::uint32_t set_id);
    void set_rim_eligible(InstanceId id, bool eligible);
    void set_rim_strength(InstanceId id, float strength);
    void set_emissive_scale(InstanceId id, float scale);
    void set_officer_face(InstanceId id, std::uint32_t tex_a,
                          std::uint32_t tex_b, float mix);
    void set_officer_jaw(InstanceId id, float openness);

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

    /// Iterate every visible instance whose `pass` matches `pass`.
    template <typename Fn>
    void for_each_visible_in_pass(Pass pass, Fn&& fn) const {
        for (std::size_t i = 0; i < slots_.size(); ++i) {
            if (slots_[i].alive
                && slots_[i].instance.visible
                && slots_[i].instance.pass == pass) {
                fn(slots_[i].instance);
            }
        }
    }

    /// Iterate every alive instance (mutable). Used to age per-instance
    /// state (e.g. decal rings) regardless of visibility.
    template <typename Fn>
    void for_each_alive(Fn&& fn) {
        for (std::size_t i = 0; i < slots_.size(); ++i) {
            if (slots_[i].alive) fn(slots_[i].instance);
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
