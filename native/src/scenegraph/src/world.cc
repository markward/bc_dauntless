// native/src/scenegraph/src/world.cc
#include "scenegraph/world.h"

namespace scenegraph {

InstanceId World::create_instance(ModelHandle model) {
    std::uint32_t idx;
    if (!free_.empty()) {
        idx = free_.back();
        free_.pop_back();
        slots_[idx].generation += 1;
    } else {
        idx = static_cast<std::uint32_t>(slots_.size());
        slots_.push_back(Slot{});
        slots_.back().generation = 1;
    }
    slots_[idx].alive = true;
    slots_[idx].instance = Instance{};
    slots_[idx].instance.model_handle = model;
    return InstanceId{idx, slots_[idx].generation};
}

void World::destroy_instance(InstanceId id) {
    if (!is_valid(id)) return;
    slots_[id.index].alive = false;
    free_.push_back(id.index);
}

void World::set_world_transform(InstanceId id, const glm::mat4& world) {
    if (auto* inst = get(id)) inst->world = world;
}

void World::set_visible(InstanceId id, bool visible) {
    if (auto* inst = get(id)) inst->visible = visible;
}

void World::set_pass(InstanceId id, Pass pass) {
    if (auto* inst = get(id)) inst->pass = pass;
}

void World::set_rim_eligible(InstanceId id, bool eligible) {
    if (auto* inst = get(id)) inst->rim_eligible = eligible;
}

bool World::is_valid(InstanceId id) const noexcept {
    return id.index < slots_.size()
        && slots_[id.index].alive
        && slots_[id.index].generation == id.generation;
}

Instance* World::get(InstanceId id) noexcept {
    return is_valid(id) ? &slots_[id.index].instance : nullptr;
}

const Instance* World::get(InstanceId id) const noexcept {
    return is_valid(id) ? &slots_[id.index].instance : nullptr;
}

}  // namespace scenegraph
