// native/src/scenegraph/src/hull_damage.cc
#include "scenegraph/hull_damage.h"

#include <algorithm>
#include <cmath>
#include <limits>

namespace scenegraph {

namespace {

// One process-wide counter: a revision is never reused, not even by a fresh
// store that inherits an old instance's cache key.
std::uint32_t next_revision() {
    static std::uint32_t counter = 0;
    return ++counter;
}

bool finite(const glm::vec3& v) {
    return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z);
}

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

HullDamageAddResult HullDamageStore::add(const glm::vec3& centre_body,
                                         const glm::vec3& normal_body, float reach,
                                         float wear, HullDamageKind kind, int node) {
    if (!(wear > 0.0f) || !(reach > 0.0f)) return {};
    if (!std::isfinite(wear) || !std::isfinite(reach) || !finite(centre_body) ||
        !finite(normal_body))
        return {};

    HullDamageRecord in;
    in.centre_body = centre_body;
    in.normal_body = kind == HullDamageKind::Surface ? normal_body : glm::vec3(0.0f);
    in.reach = reach;
    in.wear = wear;
    in.kind = kind;
    in.active = true;
    in.node = node;

    revision_ = next_revision();

    // Voluntary merge into the nearest eligible record of the same kind and
    // node (records on different nodes live in different rest frames).
    HullDamageRecord* best = nullptr;
    HullDamageRecord best_merge;
    float best_d = std::numeric_limits<float>::max();
    for (auto& s : slots_) {
        if (!s.active || s.kind != kind || s.node != node) continue;
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
        const float before = best->wear;
        *best = best_merge;
        return {static_cast<int>(best - slots_.data()), before, best->wear};
    }

    HullDamageRecord* free_slot = nullptr;
    for (auto& s : slots_) if (!s.active) { free_slot = &s; break; }

    if (!free_slot) {
        // Forced merge: the same-kind, same-node pair whose merge grows reach least
        // (merged reach - the larger input reach), no growth cap. Nearest
        // centres is the wrong measure: a small record beside a big one
        // folds in almost free even when two equal records sit closer.
        HullDamageRecord *pa = nullptr, *pb = nullptr;
        HullDamageRecord pm;
        float pg = std::numeric_limits<float>::max();
        for (std::size_t i = 0; i < kCapacity; ++i) {
            for (std::size_t j = i + 1; j < kCapacity; ++j) {
                if (slots_[i].kind != slots_[j].kind || slots_[i].node != slots_[j].node)
                    continue;
                const HullDamageRecord m = merged(slots_[i], slots_[j]);
                const float g = m.reach - std::max(slots_[i].reach, slots_[j].reach);
                if (g < pg) { pg = g; pa = &slots_[i]; pb = &slots_[j]; pm = m; }
            }
        }
        if (pa) {
            *pa = pm;
            *pb = HullDamageRecord{};
            free_slot = pb;
        } else {
            // Every slot holds a different (kind, node): fold the input into
            // the record of its own kind and node that grows least. With no
            // such record (64 distinct kind/node pairs -- no stock rig comes
            // near it) the input is dropped: a record never crosses frames.
            HullDamageRecord* host = nullptr;
            HullDamageRecord hm;
            float hg = std::numeric_limits<float>::max();
            for (auto& s : slots_) {
                if (s.kind != kind || s.node != node) continue;
                const HullDamageRecord m = merged(s, in);
                const float g = m.reach - std::max(s.reach, in.reach);
                if (g < hg) { hg = g; host = &s; hm = m; }
            }
            if (host == nullptr) return {};
            const float before = host->wear;
            *host = hm;
            return {static_cast<int>(host - slots_.data()), before, host->wear};
        }
    }
    *free_slot = in;
    return {static_cast<int>(free_slot - slots_.data()), 0.0f, in.wear};
}

std::size_t HullDamageStore::count() const {
    return static_cast<std::size_t>(std::count_if(
        slots_.begin(), slots_.end(), [](const HullDamageRecord& r) { return r.active; }));
}

void HullDamageStore::clear() {
    slots_ = {};
    revision_ = next_revision();   // never reset: a revision-keyed cache must see the clear
}

}  // namespace scenegraph
