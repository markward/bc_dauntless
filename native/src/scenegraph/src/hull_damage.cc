// native/src/scenegraph/src/hull_damage.cc
#include "scenegraph/hull_damage.h"

#include <algorithm>
#include <limits>

namespace scenegraph {

namespace {

// Fold `b` into `a`: summed wear, wear-weighted centroid and normal, and the
// smallest sphere about that centroid enclosing both inputs.
HullDamageRecord merged(const HullDamageRecord& a, const HullDamageRecord& b) {
    HullDamageRecord m = a;
    m.wear = a.wear + b.wear;
    m.centre_body = (a.centre_body * a.wear + b.centre_body * b.wear) / m.wear;
    m.reach = std::max(glm::length(a.centre_body - m.centre_body) + a.reach,
                       glm::length(b.centre_body - m.centre_body) + b.reach);
    if (a.kind == HullDamageKind::Surface) {
        const glm::vec3 n = a.normal_body * a.wear + b.normal_body * b.wear;
        const float len = glm::length(n);
        m.normal_body = len > 0.0f ? n / len : a.normal_body;
    } else {
        m.normal_body = glm::vec3(0.0f);
    }
    m.active = true;
    return m;
}

}  // namespace

void HullDamageStore::add(const glm::vec3& centre_body, const glm::vec3& normal_body,
                          float reach, float wear, HullDamageKind kind) {
    if (!(wear > 0.0f) || !(reach > 0.0f)) return;

    HullDamageRecord in;
    in.centre_body = centre_body;
    in.normal_body = kind == HullDamageKind::Surface ? normal_body : glm::vec3(0.0f);
    in.reach = reach;
    in.wear = wear;
    in.kind = kind;
    in.active = true;

    ++revision_;

    // Voluntary merge into the nearest eligible record of the same kind.
    HullDamageRecord* best = nullptr;
    HullDamageRecord best_merge;
    float best_d = std::numeric_limits<float>::max();
    for (auto& s : slots_) {
        if (!s.active || s.kind != kind) continue;
        const float d = glm::length(s.centre_body - centre_body);
        const float larger = std::max(reach, s.reach);
        if (d > kMergeFactor * larger || d >= best_d) continue;
        const HullDamageRecord m = merged(s, in);
        if (m.reach > kMaxMergeGrowth * larger) continue;
        best = &s;
        best_merge = m;
        best_d = d;
    }
    if (best) {
        *best = best_merge;
        return;
    }

    HullDamageRecord* free_slot = nullptr;
    for (auto& s : slots_) if (!s.active) { free_slot = &s; break; }

    if (!free_slot) {
        // Forced merge: the two nearest records of one kind, no growth cap.
        HullDamageRecord *pa = nullptr, *pb = nullptr;
        float pd = std::numeric_limits<float>::max();
        for (std::size_t i = 0; i < kCapacity; ++i) {
            for (std::size_t j = i + 1; j < kCapacity; ++j) {
                if (slots_[i].kind != slots_[j].kind) continue;
                const float d = glm::length(slots_[i].centre_body - slots_[j].centre_body);
                if (d < pd) { pd = d; pa = &slots_[i]; pb = &slots_[j]; }
            }
        }
        if (pa) {
            *pa = merged(*pa, *pb);
            *pb = HullDamageRecord{};
            free_slot = pb;
        } else {
            // Unreachable with two kinds and 64 slots; never drop wear anyway.
            free_slot = &slots_[0];
            *free_slot = merged(*free_slot, in);
            return;
        }
    }
    *free_slot = in;
}

std::size_t HullDamageStore::count() const {
    return static_cast<std::size_t>(std::count_if(
        slots_.begin(), slots_.end(), [](const HullDamageRecord& r) { return r.active; }));
}

void HullDamageStore::clear() {
    slots_ = {};
    ++revision_;   // never reset: a revision-keyed cache must see the clear
}

}  // namespace scenegraph
