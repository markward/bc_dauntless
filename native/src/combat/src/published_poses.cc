#include "dauntless/combat/published_poses.h"

#include <limits>

namespace dauntless::combat {

void PublishedPoses::publish(const Mirror& m,
                             const dauntless::TransformStore& store,
                             const std::vector<int64_t>& objects,
                             int64_t tick) {
    poses_.clear();
    tick_ = tick;
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
    }
}

const PublishedPose* PublishedPoses::find(int64_t object) const {
    for (const PublishedPose& p : poses_)
        if (p.object == object) return &p;
    return nullptr;
}

void PublishedPoses::clear() {
    poses_.clear();
    tick_ = 0;
}

PublishedPoses& published_poses() {
    static PublishedPoses p;
    return p;
}

}  // namespace dauntless::combat
