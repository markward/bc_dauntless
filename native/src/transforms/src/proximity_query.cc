// TransformStore::within_radius, ::proximity_report and sweep_candidates --
// see transform_store.h.
//
// Their own translation unit so they can be compiled with -ffp-contract=off
// (see CMakeLists.txt): ProximityManager.GetNearObjects,
// ProximityCheck._evaluate_one and projectiles.update_all make these
// compares in Python, and a fused
// multiply-add would move objects sitting exactly on the radius in or out of
// the answer.
#include "dauntless/transform_store.h"

#if defined(__clang__)
#pragma clang fp contract(off)
#endif

namespace dauntless {

void TransformStore::within_radius(const std::uint32_t* handles, std::size_t n,
                                   const double point[3], double r2,
                                   std::uint8_t* out) const {
    for (std::size_t k = 0; k < n; ++k) {
        const std::uint32_t index = handles[2 * k];
        check(index, handles[2 * k + 1]);
        const Transform& t = slots_[index];
        const double dx = t.pos[0] - point[0];
        const double dy = t.pos[1] - point[1];
        const double dz = t.pos[2] - point[2];
        out[k] = (dx * dx + dy * dy + dz * dz <= r2) ? 1 : 0;
    }
}

void TransformStore::proximity_report(const std::uint32_t* anchors,
                                      const std::uint32_t* objects,
                                      const double* r2,
                                      const std::uint8_t* want, std::size_t n,
                                      std::size_t start,
                                      std::vector<std::uint32_t>& out) const {
    for (std::size_t k = start; k < n; ++k) {
        const std::uint8_t w = want[k];
        if (w == 2) {
            out.push_back(static_cast<std::uint32_t>(k));
            continue;
        }
        if (!valid(anchors[2 * k], anchors[2 * k + 1]) ||
            !valid(objects[2 * k], objects[2 * k + 1])) {
            out.push_back(static_cast<std::uint32_t>(k));
            continue;
        }
        if (w == 3) continue;
        const Transform& a = slots_[anchors[2 * k]];
        const Transform& o = slots_[objects[2 * k]];
        const double dx = o.pos[0] - a.pos[0];
        const double dy = o.pos[1] - a.pos[1];
        const double dz = o.pos[2] - a.pos[2];
        const bool inside = dx * dx + dy * dy + dz * dz <= r2[k];
        if (inside == (w == 0)) out.push_back(static_cast<std::uint32_t>(k));
    }
}

void sweep_candidates(const double* starts, const double* seg_lens,
                      const std::int32_t* skips, std::size_t n_torps,
                      const double* centres, const double* bounds,
                      std::size_t n_ships, std::vector<std::uint32_t>& out) {
    for (std::size_t t = 0; t < n_torps; ++t) {
        const double* p = starts + 3 * t;
        const double len = seg_lens[t];
        const std::int32_t skip = skips[t];
        for (std::size_t s = 0; s < n_ships; ++s) {
            if (static_cast<std::int32_t>(s) == skip) continue;
            const double* c = centres + 3 * s;
            const double dx = c[0] - p[0];
            const double dy = c[1] - p[1];
            const double dz = c[2] - p[2];
            const double reach = bounds[s] + len;
            // Written as update_all's rejection, negated: a NaN distance is
            // not "greater", so it stays a candidate there and here.
            if (dx * dx + dy * dy + dz * dz > reach * reach) continue;
            out.push_back(static_cast<std::uint32_t>(t));
            out.push_back(static_cast<std::uint32_t>(s));
        }
    }
}

}  // namespace dauntless
