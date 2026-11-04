#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/published_poses.h"

#include <limits>

#include "geometry_internal.h"

namespace dauntless::combat {

namespace {
uint64_t slot_key(uint32_t index, uint32_t gen) {
    return (static_cast<uint64_t>(index) << 32) | gen;
}
}  // namespace

void PublishedPoses::publish(const Mirror& m,
                             const dauntless::TransformStore& store,
                             const std::vector<int64_t>& objects,
                             int64_t tick) {
    poses_.clear();
    xforms_.clear();
    by_slot_.clear();
    tick_ = tick;
    open_ = true;
    for (const int64_t h : objects) {
        if (h < 0) continue;
        const ObjectRow* o = m.object(h);
        if (!o) continue;
        // A _velocity that is not a TGPoint3 (state 2: a tuple) has no
        // velocity to hold: the row is left out.
        if (o->_velocity_state == 2) continue;
        constexpr int64_t kMax = std::numeric_limits<uint32_t>::max();
        if (o->xform_index < 0 || o->xform_gen < 0 || o->xform_index > kMax ||
            o->xform_gen > kMax)
            continue;
        const auto idx = static_cast<uint32_t>(o->xform_index);
        if (!store.valid(idx, static_cast<uint32_t>(o->xform_gen))) continue;
        const TransformStore::Transform& t = store.at(idx);
        PublishedPose p;
        p.object = h;
        for (int i = 0; i < 3; ++i) {
            p.pos[i] = t.pos[i];
            p.vel[i] = o->_velocity[i];
        }
        for (int i = 0; i < 9; ++i) p.rot[i] = t.rot[i];
        poses_.push_back(p);
        by_slot_[slot_key(idx, static_cast<uint32_t>(o->xform_gen))] =
            xforms_.size();
        xforms_.push_back(t);
    }
}

const TransformStore::Transform* PublishedPoses::pose_for(
    uint32_t xform_index, uint32_t xform_gen) const {
    if (!open_) return nullptr;
    const auto it = by_slot_.find(slot_key(xform_index, xform_gen));
    return it == by_slot_.end() ? nullptr : &xforms_[it->second];
}

const PublishedPose* PublishedPoses::find(int64_t object) const {
    for (const PublishedPose& p : poses_)
        if (p.object == object) return &p;
    return nullptr;
}

void PublishedPoses::clear() {
    poses_.clear();
    xforms_.clear();
    by_slot_.clear();
    tick_ = 0;
    open_ = false;
}

PublishedPoses& published_poses() {
    static PublishedPoses p;
    return p;
}

const TransformStore::Transform& combat_pose(const Mirror& m, int64_t h) {
    return detail::xform(m, detail::obj(m, h));
}

}  // namespace dauntless::combat
