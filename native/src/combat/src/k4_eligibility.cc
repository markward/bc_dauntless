#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/k4_eligibility.h"

#include <algorithm>
#include <cmath>
#include <limits>

#include "dauntless/combat/beam_geometry.h"
#include "dauntless/combat/published_poses.h"
#include "dauntless/combat/py_math.h"

namespace dauntless::combat {

namespace {

constexpr const char* kWhyNames[] = {
    "scan", "player", "nonfinite", "frame", "set",
};
static_assert(sizeof(kWhyNames) / sizeof(kWhyNames[0]) ==
              static_cast<size_t>(K4Why::kCount));

K4Result fail(K4Why why) {
    K4Result r;
    r.ok = false;
    r.why = why;
    return r;
}

// frames._xyz(obj): obj.GetWorldLocation(), the transform slot's position
// (the published pose inside the read window: read_pose). False when the
// row has no valid slot.
bool position(const Mirror& m, const ObjectRow& o, Vec3& out) {
    if (o.xform_index < 0 || o.xform_gen < 0 ||
        o.xform_index > std::numeric_limits<uint32_t>::max() ||
        o.xform_gen > std::numeric_limits<uint32_t>::max())
        return false;
    const auto xi = static_cast<uint32_t>(o.xform_index);
    const auto xg = static_cast<uint32_t>(o.xform_gen);
    if (!m.store().valid(xi, xg)) return false;
    const auto& t = read_pose(m.store(), xi, xg);
    out = {t.pos[0], t.pos[1], t.pos[2]};
    return true;
}

bool finite(const Vec3& v) {
    return std::isfinite(v[0]) && std::isfinite(v[1]) && std::isfinite(v[2]);
}

struct Candidate {
    double neg_score;  // the sort key's -score
    uint64_t py_id;    // the sort key's id(s)
    int64_t index;     // into ships_list
};

}  // namespace

const char* k4_why_name(K4Why w) { return kWhyNames[static_cast<size_t>(w)]; }

K4Counts& k4_counts() {
    static K4Counts c;
    return c;
}

K4Result k4_eligible(const Mirror& m, const StepScan& s, int64_t player,
                     int64_t max_count, double prox_w, double size_w) {
    if (!s.representable) return fail(K4Why::scan);
    const size_t n = s.ships.size();

    // The player's position and set (frames.system_distance reads both).
    Vec3 ppos{0.0, 0.0, 0.0};
    int64_t pset = -1;
    const bool has_player = player != -1;
    if (has_player) {
        const ObjectRow* p = player >= 0 ? m.object(player) : nullptr;
        if (p == nullptr || !position(m, *p, ppos)) return fail(K4Why::player);
        if (!finite(ppos)) return fail(K4Why::nonfinite);
        pset = p->_containing_set;
    }

    // E1: max((world_radius(s) for s in ships), default=0.0) or 1.0.
    // world_radius is GetRadius(), base x guarded scale (the C++ twin reads
    // the mirror rows). The builtin max keeps the first maximum (py_max
    // folded left from the first item).
    std::vector<const ObjectRow*> rows(n);
    std::vector<double> radii(n);
    double max_r = 0.0;
    for (size_t i = 0; i < n; ++i) {
        const ObjectRow* r = m.object(s.ships[i]);
        if (r == nullptr) return fail(K4Why::scan);
        const double wr = world_radius(m, s.ships[i]);
        if (!std::isfinite(wr)) return fail(K4Why::nonfinite);
        rows[i] = r;
        radii[i] = wr;
        max_r = (i == 0) ? wr : py_max(max_r, wr);
    }
    if (max_r == 0.0) max_r = 1.0;  // `or 1.0`: 0.0 and -0.0 are falsy

    std::vector<Candidate> others;
    others.reserve(n);
    for (size_t i = 0; i < n; ++i) {
        const ObjectRow& r = *rows[i];
        Vec3 pos;
        if (!position(m, r, pos)) return fail(K4Why::scan);
        if (!finite(pos)) return fail(K4Why::nonfinite);
        // others = [s for s in ships if player is None or id(s) !=
        // id(player)]: one row per object, so the handle is the identity.
        if (has_player && s.ships[i] == player) continue;
        // E2 (damage_eligibility.py score()).
        const double size = radii[i] / max_r;
        double score;
        if (!has_player) {
            score = size_w * size;
        } else {
            // E3: frames.system_distance(s, player) = math.dist(_xyz(s),
            // local_in(containing_set(s), player)), inf when None.
            Vec3 off;
            double d;
            switch (offset_between(m, s, r._containing_set, pset, off)) {
                case OffsetStatus::ok: {
                    const double pb[3] = {ppos[0] + off[0], ppos[1] + off[1],
                                          ppos[2] + off[2]};
                    d = dist3(pos.data(), pb);
                    break;
                }
                case OffsetStatus::none:
                    d = std::numeric_limits<double>::infinity();
                    break;
                case OffsetStatus::missing:
                    return fail(K4Why::frame);
                case OffsetStatus::unrepresentable:
                default:
                    return fail(K4Why::set);
            }
            const double prox = 1.0 / (1.0 + d);
            score = prox_w * prox + size_w * size;
        }
        if (!std::isfinite(score)) return fail(K4Why::nonfinite);
        others.push_back({-score, rows[i]->py_id, static_cast<int64_t>(i)});
    }

    K4Result res;
    res.ok = true;
    // for s in others: if len(eligible) >= max_count: break -- the player
    // already holds one slot; no duplicates (the scan checked).
    const int64_t room = max_count - (has_player ? 1 : 0);
    if (room <= 0 || others.empty()) return res;
    const size_t take = std::min(static_cast<size_t>(room), others.size());
    // E4: key (-score, id(s)), a tuple compare: == then < per element. Keys
    // are unique (py_id), so any exact top-N gives Python's set.
    auto before = [](const Candidate& a, const Candidate& b) {
        if (a.neg_score != b.neg_score) return a.neg_score < b.neg_score;
        return a.py_id < b.py_id;
    };
    std::partial_sort(others.begin(), others.begin() + take, others.end(),
                      before);
    res.indices.reserve(take);
    for (size_t i = 0; i < take; ++i) res.indices.push_back(others[i].index);
    return res;
}

}  // namespace dauntless::combat
