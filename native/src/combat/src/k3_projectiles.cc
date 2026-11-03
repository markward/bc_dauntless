// The K3 torpedo kernel -- see k3_projectiles.h. A resumable port of
// engine/appc/projectiles.update_all's decision steps 0-3 (projectiles.py
// update_all and _broadphase; K3M = docs/reference/engine/native-combat/
// k3-k4-map.md section A1.1, ordering contract A6). Each cursor state (enum
// St) is named after the Python line it stands for; Walker::run's switch
// reads top to bottom like the Python. Every float decision is made by
// projectile_geometry / beam_geometry / beam_trace / sensor_detect (the
// Python-exact ports) or the store's sweep_candidates; the inline literals
// here are the Python's, with their line.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/k3_projectiles.h"

#include <algorithm>
#include <cstdint>
#include <iterator>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>

#include "dauntless/combat/beam_geometry.h"
#include "dauntless/combat/damage.h"
#include "dauntless/combat/fire_gates.h"
#include "dauntless/combat/sensor_detect.h"
#include "geometry_internal.h"

namespace dauntless::combat {

namespace {

using detail::is_zero_offset;
using detail::shifted;

[[noreturn]] void lost(const std::string& why) {
    throw std::logic_error("combat K3: " + why);
}

// A torpedo row's TransformStore slot, if it is live (GetTranslate /
// SetTranslateXYZ through `_xform`).
bool torp_slot(const TransformStore& store, const TorpedoRow& r, uint32_t& xi,
               uint32_t& xg) {
    if (r.xform_index < 0 || r.xform_gen < 0 ||
        r.xform_index > std::numeric_limits<uint32_t>::max() ||
        r.xform_gen > std::numeric_limits<uint32_t>::max())
        return false;
    xi = static_cast<uint32_t>(r.xform_index);
    xg = static_cast<uint32_t>(r.xform_gen);
    return store.valid(xi, xg);
}

constexpr uint32_t bit(TorpField f) { return 1u << static_cast<int>(f); }

// What the advance reads of a torpedo Python guided (ASK guide).
constexpr uint32_t kAdvanceReads =
    bit(TorpField::_age) | bit(TorpField::_ttl) | bit(TorpField::_velocity) |
    bit(TorpField::_source_ship) | bit(TorpField::_containing_set);

}  // namespace

const char* k3_kind_name(K3Kind k) {
    static constexpr const char* kNames[] = {"DONE", "ASK"};
    static_assert(std::size(kNames) == static_cast<size_t>(K3Kind::kCount));
    const auto i = static_cast<size_t>(k);
    return i < std::size(kNames) ? kNames[i] : "?";
}

const char* k3_query_name(K3Query q) {
    static constexpr const char* kNames[] = {
        "frame", "steer_point", "guide", "shields_block", "bubble",
        "resolve_hit"};
    static_assert(std::size(kNames) == static_cast<size_t>(K3Query::kCount));
    const auto i = static_cast<size_t>(q);
    return i < std::size(kNames) ? kNames[i] : "?";
}

const char* k3_why_name(K3Why w) {
    static constexpr const char* kNames[] = {
        "scan", "table", "unrepresentable", "stale_ref", "torpedo_xform",
        "ship_cache"};
    static_assert(std::size(kNames) == static_cast<size_t>(K3Why::kCount));
    const auto i = static_cast<size_t>(w);
    return i < std::size(kNames) ? kNames[i] : "?";
}

// ── The cursor ───────────────────────────────────────────────────────────────

enum class St : int32_t {
    TORP_FOR,          // for t in list(_active):
                       //   if t._target_ship is not None and
                       //       t._age < t._guidance_lifetime:  (PRE-increment)
    GUIDE,             //     _guide(t, dt)
    FRAME_ANSWER,      //       (ASK frame answered: the compare again)
    STEER_ANSWER,      //       (ASK steer_point answered: the rest of _guide)
    GUIDE_ANSWER,      //       (ASK guide answered: Python ran _guide)
    ADVANCE,           //   prev_pos = t.GetTranslate()
                       //   cur_pos = prev_pos + t._velocity * dt; t._age += dt
                       //   if t._age >= t._ttl: t.SetTranslateXYZ(cur_pos);
                       //     expired.append(t); continue
                       //   seg, seg_len, aim_unit; moving.append(...)
    BROADPHASE,        // candidates = _broadphase(moving, ship_cache, offsets)
    BROAD_FRAME_ANSWER,//   (ASK frame answered: the broadphase again)
    NARROW_FOR,        // for (t, prev_pos, cur_pos, ...), near in zip(...):
                       //   source = t._source_ship
    CANDIDATE,         //   for j in near: if ship is source: continue
                       //     off; seg_prev; seg_cur; shields_block(ship)
    SHIELDS_ANSWER,    //     (ASK shields_block answered)
    BUBBLE,            //     bubble_entry = shield_bubble_entry(ship,
                       //         seg_prev, aim_unit, seg_len) if ... else None
    BUBBLE_ANSWER,     //     (ASK bubble answered)
    SPHERE,            //     if bubble_entry is None and not sphere_hit(...):
                       //       continue; the bubble write-back; the ray
    TRACE,             //     hit_point, hit_normal = _resolve_hit_point(...)
                       //     hits.append(...); expired.append(t); break
    TRACE_ANSWER,      //     (ASK resolve_hit answered)
    NARROW_WRITE,      //   t.SetTranslateXYZ(cur_pos.x, cur_pos.y, cur_pos.z)
    FINISH,            // for t in expired: expire(t)  -- Python's, after DONE
    DONE,              // returned DONE; only end() / abandon() may follow
};

// update_all's ship_cache entry: (ship, x, y, z, bound, ship_set).
struct ShipEntry {
    int64_t ship = -1;
    Vec3 pos{0, 0, 0};
    double bound = 0.0;
    int64_t set = -1;
};

// update_all's `moving` entry: (t, prev_pos, cur_pos, seg_len, aim_unit,
// torp_set), plus t._source_ship (read by the broadphase and the narrow).
struct Moving {
    int64_t torp = -1;
    Vec3 prev{0, 0, 0}, cur{0, 0, 0};
    double seg_len = 0.0;
    std::optional<Vec3> aim;
    int64_t set = -1;
    int64_t source = -1;
};

struct PosWrite {
    int64_t torp = -1;
    Vec3 pos{0, 0, 0};
};

struct K3Kernel::Session {
    double dt = 0.0;
    GuideClocks clocks{};
    bool use_memo = false;
    St st = St::TORP_FOR;

    // Shared: next() copies the whole Session per call (its backup for a
    // throw), and sharing these keeps that copy from duplicating them.
    std::shared_ptr<const std::vector<int64_t>> torps;  // list(_active)
    std::shared_ptr<const std::vector<ShipEntry>> cache;
    std::shared_ptr<const std::unordered_set<int64_t>> in_scan;

    // Step 1: the torpedo being walked and what its guide wrote.
    size_t ti = 0;
    K3TorpWrite cur;
    GuideResume resume{};
    int64_t frame_set = -1;  // the set an ASK frame names

    // The decisions, applied at DONE.
    std::vector<K3TorpWrite> writes;
    std::vector<PosWrite> positions;
    std::vector<int64_t> ttl_expired;
    std::vector<Moving> moving;

    // Step 2: candidates per moving entry, and update_all's `offsets`,
    // (ship_set, torp_set) -> offset_between (nullopt: None).
    std::vector<std::vector<size_t>> near;
    std::map<std::pair<int64_t, int64_t>, std::optional<Vec3>> offsets;

    // Step 3: the narrow loop's locals.
    size_t mi = 0, ci = 0;
    Vec3 cur_pos{0, 0, 0};
    Vec3 off{0, 0, 0}, seg_prev{0, 0, 0}, seg_cur{0, 0, 0};
    std::optional<bool> shields;
    std::optional<Vec3> bubble;
    Vec3 ray_origin{0, 0, 0};
    double ray_max = 0.0;
    std::vector<K3Hit> hits;
    std::vector<int64_t> hit_expired;

    bool awaiting_answer = false, has_answer = false;
    K3Query pending = K3Query::kCount;
    K3Answer answer;
};

namespace {

using Session = K3Kernel::Session;

// One next() call: runs the cursor to the next record.
class Walker {
public:
    Walker(Mirror& m, TransformStore& store, StepScan& scan, Session& s,
           const K2Context& ctx, K3Kernel::Counts& c)
        : m_(m), store_(store), scan_(scan), s_(s), ctx_(ctx), c_(c) {}

    K3Record run();

private:
    // The torpedo's row, looked up afresh every time (ruling: never hold a
    // TorpedoTable pointer across Python, which may push into the table).
    const TorpedoRow& row(int64_t h) const {
        const TorpedoRow* r = m_.torpedoes().find(h);
        if (!r) lost("a torpedo row the walk needs is gone");
        return *r;
    }
    int64_t ref(const TorpedoRow& r, TorpField f) const {
        return m_.torpedo_ref(r, f);
    }

    K3Record ask(K3Query q, std::vector<K3Arg> args, St next) {
        K3Record r;
        r.kind = K3Kind::ASK;
        r.query = q;
        r.args = std::move(args);
        s_.st = next;
        s_.awaiting_answer = true;
        s_.has_answer = false;
        s_.pending = q;
        ++c_.records;
        ++c_.queries[static_cast<size_t>(q)];
        return r;
    }
    K3Record ask_guide(int64_t torp, const char* why) {
        ++c_.guide_why[why ? why : "?"];
        return ask(K3Query::guide, {torp}, St::GUIDE_ANSWER);
    }
    K3Record ask_frame(int64_t set, St next) {
        s_.frame_set = set;
        return ask(K3Query::frame, {set}, next);
    }
    K3Answer take_answer() {
        K3Answer a = s_.answer;
        s_.answer = K3Answer{};
        s_.pending = K3Query::kCount;
        return a;
    }
    // The answered frame, into this step's frame table.
    void install_frame(const K3Answer& a) {
        if (scan_.frame(s_.frame_set) == nullptr)
            scan_.frames.push_back(FrameEntry{s_.frame_set, a.key, a.point});
    }
    // A guide's writes, in _guide's order, into the torpedo's log entry.
    void take(const GuideResult& g) {
        for (int i = 0; i < g.n_writes; ++i) {
            const GuideWrite& w = g.writes[static_cast<size_t>(i)];
            switch (w.field) {
                case GuideField::last_seen: s_.cur.last_seen = w.value; break;
                case GuideField::last_tvel: s_.cur.last_tvel = w.value; break;
                case GuideField::velocity: s_.cur.vel = w.value; break;
            }
        }
    }

    K3Record guide();
    K3Record broadphase();
    K3Record trace();
    void hit();
    K3Record finish();

    Mirror& m_;
    TransformStore& store_;
    StepScan& scan_;
    Session& s_;
    const K2Context& ctx_;
    K3Kernel::Counts& c_;
};

// _guide(t, dt) (projectiles.py:1103) for the torpedo at s_.ti.
K3Record Walker::guide() {
    const int64_t h = (*s_.torps)[s_.ti];
    const TorpedoRow& r = row(h);
    const int64_t target = ref(r, TorpField::_target_ship);
    const int64_t source = ref(r, TorpField::_source_ship);
    // A target or source outside the step scan: its class and overrides were
    // never checked (a ship's are, by the scan), so _guide is Python's.
    if (!s_.in_scan->count(target))
        return ask_guide(h, "target_not_in_scan");
    if (source != -1 && !s_.in_scan->count(source))
        return ask_guide(h, "source_not_in_scan");
    const GuideResult g =
        guide_torpedo(m_, r, s_.dt, scan_, s_.use_memo, s_.clocks);
    switch (g.status) {
        case GuideResult::Status::done:
            if (g.posed_steer) ++c_.posed_steers;
            if (g.attributed) {
                // _steer_point's `_mount_key = (target, x, y, z, mount)`,
                // logged for DONE (round trips, Task 4).
                s_.cur.mount =
                    K3MountWrite{target, r.target_offset, g.mount};
                ++c_.native_attributions;
            }
            take(g);
            s_.st = St::ADVANCE;
            return K3Record{};  // no record: the caller carries on
        case GuideResult::Status::need_frame:
            return ask_frame(g.frame_set, St::FRAME_ANSWER);
        case GuideResult::Status::need_steer_point: {
            // off = frames.offset_between(containing_set(torpedo),
            // containing_set(target)): resolved, as guide_torpedo got here.
            Vec3 off{0, 0, 0};
            const ObjectRow* tr = m_.object(target);
            if (!tr ||
                offset_between(m_, scan_, ref(r, TorpField::_containing_set),
                               tr->_containing_set, off) != OffsetStatus::ok)
                lost("the steer point's offset is no longer resolvable");
            s_.resume = g.resume;
            if (g.steer_why != SteerWhy::kCount)
                ++c_.steer_why[static_cast<size_t>(g.steer_why)];
            return ask(K3Query::steer_point, {h, target, off},
                       St::STEER_ANSWER);
        }
        case GuideResult::Status::need_guide:
            return ask_guide(h, g.why);
    }
    lost("unknown guide status");
}

// _broadphase(moving, ship_cache, offsets) (projectiles.py:746). Pure: an
// ASK frame restarts it from the top.
K3Record Walker::broadphase() {
    const std::vector<ShipEntry>& cache = *s_.cache;
    s_.near.assign(s_.moving.size(), {});
    s_.offsets.clear();
    // by_set: torpedo set -> member indices, in first-seen (dict) order.
    std::vector<std::pair<int64_t, std::vector<size_t>>> by_set;
    for (size_t i = 0; i < s_.moving.size(); ++i) {
        const int64_t ts = s_.moving[i].set;
        auto it = std::find_if(by_set.begin(), by_set.end(),
                               [ts](const auto& e) { return e.first == ts; });
        if (it == by_set.end()) {
            by_set.push_back({ts, {}});
            it = std::prev(by_set.end());
        }
        it->second.push_back(i);
    }
    std::vector<double> starts, lens, centres, bounds;
    std::vector<int32_t> skips;
    std::vector<uint32_t> pairs;
    for (const auto& [torp_set, members] : by_set) {
        std::vector<size_t> same;
        std::vector<std::pair<size_t, Vec3>> other;
        for (size_t j = 0; j < cache.size(); ++j) {
            const std::pair<int64_t, int64_t> key{cache[j].set, torp_set};
            auto found = s_.offsets.find(key);
            if (found == s_.offsets.end()) {
                // offsets[key] = frames.offset_between(entry[5], torp_set)
                Vec3 off{0, 0, 0};
                std::optional<Vec3> v;
                switch (offset_between(m_, scan_, key.first, key.second, off)) {
                    case OffsetStatus::ok: v = off; break;
                    case OffsetStatus::none: break;
                    case OffsetStatus::missing:
                        return ask_frame(scan_.frame(key.first) == nullptr
                                             ? key.first
                                             : key.second,
                                         St::BROAD_FRAME_ANSWER);
                    case OffsetStatus::unrepresentable:
                        lost("a ship or torpedo set became unnameable");
                }
                found = s_.offsets.emplace(key, v).first;
            }
            if (!found->second) continue;  // another frame: never interacts
            if (is_zero_offset(*found->second))
                same.push_back(j);
            else
                other.push_back({j, *found->second});
        }
        if (!same.empty()) {
            // at = {id(ship): k for k, j in enumerate(same)} (the scan has
            // no duplicate, so "last wins" never arises)
            starts.clear();
            lens.clear();
            skips.clear();
            centres.clear();
            bounds.clear();
            pairs.clear();
            for (const size_t i : members) {
                const Moving& mv = s_.moving[i];
                starts.insert(starts.end(), mv.prev.begin(), mv.prev.end());
                lens.push_back(mv.seg_len);
                int32_t skip = -1;
                for (size_t k = 0; k < same.size(); ++k)
                    if (cache[same[k]].ship == mv.source)
                        skip = static_cast<int32_t>(k);
                skips.push_back(skip);
            }
            for (const size_t j : same) {
                centres.insert(centres.end(), cache[j].pos.begin(),
                               cache[j].pos.end());
                bounds.push_back(cache[j].bound);
            }
            dauntless::sweep_candidates(starts.data(), lens.data(),
                                        skips.data(), members.size(),
                                        centres.data(), bounds.data(),
                                        same.size(), pairs);
            for (size_t k = 0; k < pairs.size(); k += 2)
                s_.near[members[pairs[k]]].push_back(same[pairs[k + 1]]);
        }
        // A ship in ANOTHER REGION of the system: the shifted test (B2).
        for (const auto& [j, off] : other) {
            const ShipEntry& e = cache[j];
            for (const size_t i : members) {
                const Moving& mv = s_.moving[i];
                if (e.ship == mv.source) continue;
                const Vec3 seg_prev = shifted(mv.prev, off);
                const double ddx = e.pos[0] - seg_prev[0];
                const double ddy = e.pos[1] - seg_prev[1];
                const double ddz = e.pos[2] - seg_prev[2];
                const double reach = e.bound + mv.seg_len;
                // projectiles.py:_broadphase: a NaN stays a candidate
                if ((ddx * ddx + ddy * ddy + ddz * ddz) > reach * reach)
                    continue;
                s_.near[i].push_back(j);
            }
        }
        if (!other.empty())
            for (const size_t i : members)
                std::sort(s_.near[i].begin(), s_.near[i].end());
    }
    s_.mi = 0;
    s_.st = St::NARROW_FOR;
    return K3Record{};
}

// _resolve_hit_point(ship_instances=..., ship=ship, ray_origin=ray_origin,
//     ray_direction=aim_unit, max_dist=ray_max, fallback_point=seg_cur)
// with K2's context and conditions (k2_beams.cc, St::TRACE).
K3Record Walker::trace() {
    static const TraceHooks kNoHost;
    const Moving& mv = s_.moving[s_.mi];
    const ShipEntry& e = (*s_.cache)[s_.near[s_.mi][s_.ci]];
    const std::optional<Vec3>& dir = mv.aim;
    std::optional<InstanceId> iid;
    std::optional<Vec3> view_off;
    const TraceHooks* hooks = &ctx_.hooks;
    if (dir) {
        const auto it = ctx_.iids.find(e.ship);
        if (it != ctx_.iids.end()) {
            // to_view = frames.view_offset(frames.containing_set(ship))
            const auto vo = ctx_.view_offsets.find(e.set);
            if (vo == ctx_.view_offsets.end())
                return ask(K3Query::resolve_hit,
                           {e.ship, s_.ray_origin, *dir, s_.ray_max,
                            s_.seg_cur},
                           St::TRACE_ANSWER);
            view_off = vo->second;
            iid = it->second.id;
            if (it->second.bad) hooks = &kNoHost;
        }
    }
    ResolvedHit h;
    try {
        h = resolve_hit_point(m_, *hooks, e.ship, iid, s_.ray_origin, dir,
                              s_.ray_max, s_.seg_cur, view_off);
    } catch (const std::invalid_argument&) {
        return ask(K3Query::resolve_hit,
                   {e.ship, s_.ray_origin,
                    dir ? K3Arg(*dir) : K3Arg(std::monostate{}), s_.ray_max,
                    s_.seg_cur},
                   St::TRACE_ANSWER);
    }
    s_.answer.point = h.point;
    s_.answer.normal = h.normal;
    s_.answer.tier = h.tier;
    hit();
    return K3Record{};
}

// hits.append((t, ship, hit_point, hit_normal)); expired.append(t); break
// -- the resolved point is in s_.answer (native or Python's).
void Walker::hit() {
    const Moving& mv = s_.moving[s_.mi];
    const ShipEntry& e = (*s_.cache)[s_.near[s_.mi][s_.ci]];
    K3Hit h;
    h.torp = mv.torp;
    h.ship = e.ship;
    h.hit.point = s_.answer.point;
    h.hit.normal = s_.answer.normal;
    h.hit.tier = s_.answer.tier;
    h.bubble = s_.bubble;
    // The fallback point IS seg_cur, which IS the bubble object on a bubble
    // hit (projectiles.py: `seg_cur = bubble_entry`).
    h.hit_is_bubble =
        s_.bubble.has_value() && h.hit.tier == ResolvedHit::Tier::Fallback;
    // What host_loop's hit loop reads of the torpedo (THE HITS): no ASK
    // writes them, so they are the values the loop will read.
    const TorpedoRow& tr = row(mv.torp);
    h.damage = tr.damage;
    h.drf = tr.damage_radius_factor;
    h.source = m_.torpedo_ref(tr, TorpField::_source_ship);
    s_.answer = K3Answer{};
    s_.hits.push_back(std::move(h));
    s_.hit_expired.push_back(mv.torp);
    s_.st = St::NARROW_WRITE;
}

// The decisions into the table and the store, then DONE. Everything is
// checked before anything is written, so the writes are all-or-nothing.
K3Record Walker::finish() {
    TorpedoTable& tt = m_.torpedoes();
    for (const K3TorpWrite& w : s_.writes) {
        if (!tt.find(w.torp)) lost("a torpedo row was dropped mid-walk");
        // No ASK frees a row (PINNING): the attributed mount is still live.
        if (w.mount && w.mount->sub != -1 && !m_.subsystem(w.mount->sub))
            lost("an attributed mount's row was dropped mid-walk");
    }
    std::vector<std::pair<uint32_t, uint32_t>> slots;
    slots.reserve(s_.positions.size());
    for (const PosWrite& p : s_.positions) {
        uint32_t xi = 0, xg = 0;
        if (!torp_slot(store_, row(p.torp), xi, xg))
            lost("a torpedo transform was freed mid-walk");
        slots.push_back({xi, xg});
    }
    // t._age += dt; _guide's _last_seen_target_pos, _last_target_vel,
    // _velocity (kernel-owned: the row takes them here, Python copies them
    // without pushing).
    for (const K3TorpWrite& w : s_.writes) {
        tt.set_f(w.torp, TorpField::_age, w.age);
        if (w.last_seen)
            tt.set_v(w.torp, TorpField::_last_seen_target_pos, true,
                     *w.last_seen);
        if (w.last_tvel)
            tt.set_v(w.torp, TorpField::_last_target_vel, true, *w.last_tvel);
        if (w.vel) tt.set_v(w.torp, TorpField::_velocity, true, *w.vel);
        // `_mount_key`: its target IS the torpedo's `_target_ship` (the
        // attributed flag), key[1:4] the offset, key[4] the mount.
        if (w.mount)
            tt.set_mount(w.torp, true, w.mount->sub, w.mount->offset);
    }
    // t.SetTranslateXYZ(cur_pos.x, cur_pos.y, cur_pos.z): ObjectClass's,
    // store.set_position(*self._xform, float(x), float(y), float(z)).
    for (size_t i = 0; i < s_.positions.size(); ++i) {
        const Vec3& p = s_.positions[i].pos;
        store_.set_position(slots[i].first, slots[i].second, p[0], p[1], p[2]);
    }
    K3Record r;
    r.kind = K3Kind::DONE;
    r.writes = std::move(s_.writes);
    // expired: the TTL expiries (step 1), then the hits (step 3).
    r.expired = std::move(s_.ttl_expired);
    r.expired.insert(r.expired.end(), s_.hit_expired.begin(),
                     s_.hit_expired.end());
    r.hits = std::move(s_.hits);
    s_.writes.clear();
    s_.ttl_expired.clear();
    s_.hit_expired.clear();
    s_.hits.clear();
    s_.positions.clear();
    s_.st = St::DONE;
    ++c_.records;
    return r;
}

// ── The cursor loop ──────────────────────────────────────────────────────────

K3Record Walker::run() {
    for (;;) {
        try {
            switch (s_.st) {
            // for t in list(_active):
            case St::TORP_FOR: {
                if (s_.ti >= s_.torps->size()) {
                    s_.st = St::BROADPHASE;
                    break;
                }
                const int64_t h = (*s_.torps)[s_.ti];
                const TorpedoRow& r = row(h);
                s_.cur = K3TorpWrite{};
                s_.cur.torp = h;
                // if t._target_ship is not None and
                //     t._age < t._guidance_lifetime: _guide(t, dt)
                // -- the age BEFORE this tick's `+= dt` (NaN: not guided)
                const bool guided = ref(r, TorpField::_target_ship) != -1 &&
                                    r.age < r.guidance_lifetime;
                s_.st = guided ? St::GUIDE : St::ADVANCE;
                break;
            }
            case St::GUIDE: {
                K3Record rec = guide();
                if (s_.st == St::ADVANCE) break;  // decided natively
                return rec;
            }
            case St::FRAME_ANSWER:
                install_frame(take_answer());
                s_.st = St::GUIDE;  // nothing was decided: start over
                break;
            case St::STEER_ANSWER: {
                const K3Answer a = take_answer();
                // can_detect has run: carry on, never start over. A throw
                // here (the target's row gone) is a protocol error.
                GuideResult g;
                try {
                    g = guide_torpedo_resume(m_, row((*s_.torps)[s_.ti]),
                                             s_.dt, s_.resume, a.point);
                } catch (const std::invalid_argument& e) {
                    lost(std::string("steer-point resume: ") + e.what());
                }
                take(g);
                s_.st = St::ADVANCE;
                break;
            }
            case St::GUIDE_ANSWER: {
                take_answer();
                // Python's _guide pushed its writes into the row.
                if (row((*s_.torps)[s_.ti]).unrepresentable & kAdvanceReads)
                    lost("Python's _guide left a field the advance reads "
                         "unrepresentable");
                s_.st = St::ADVANCE;
                break;
            }

            // prev_pos = t.GetTranslate(); cur_pos = prev_pos +
            // t._velocity * dt (the POST-guide velocity); t._age += dt;
            // if t._age >= t._ttl: t.SetTranslateXYZ(cur_pos);
            //     expired.append(t); continue
            // seg = cur_pos - prev_pos; seg_len; aim_unit;
            // moving.append((t, prev_pos, cur_pos, seg_len, aim_unit,
            //                frames.containing_set(t)))
            case St::ADVANCE: {
                const int64_t h = (*s_.torps)[s_.ti];
                const TorpedoRow& r = row(h);
                uint32_t xi = 0, xg = 0;
                if (!torp_slot(store_, r, xi, xg))
                    lost("a torpedo transform was freed mid-walk");
                const auto& t = store_.at(xi);
                const Vec3 prev{t.pos[0], t.pos[1], t.pos[2]};
                const Vec3 vel = s_.cur.vel ? *s_.cur.vel : r.vel;
                const Advance a =
                    advance_torpedo(prev, vel, s_.dt, r.age, r.ttl);
                s_.cur.age = a.age;
                s_.writes.push_back(s_.cur);
                if (a.expired) {
                    s_.positions.push_back({h, a.cur});
                    s_.ttl_expired.push_back(h);
                } else {
                    Moving mv;
                    mv.torp = h;
                    mv.prev = prev;
                    mv.cur = a.cur;
                    mv.seg_len = a.seg_len;
                    mv.aim = a.aim_unit;
                    mv.set = ref(r, TorpField::_containing_set);
                    mv.source = ref(r, TorpField::_source_ship);
                    s_.moving.push_back(std::move(mv));
                }
                ++s_.ti;
                s_.st = St::TORP_FOR;
                break;
            }

            case St::BROADPHASE: {
                K3Record rec = broadphase();
                if (s_.st == St::NARROW_FOR) break;
                return rec;
            }
            case St::BROAD_FRAME_ANSWER:
                install_frame(take_answer());
                s_.st = St::BROADPHASE;
                break;

            // for (t, ...), near in zip(moving, candidates):
            //     source = t._source_ship
            case St::NARROW_FOR:
                if (s_.mi >= s_.moving.size()) {
                    s_.st = St::FINISH;
                    break;
                }
                s_.cur_pos = s_.moving[s_.mi].cur;
                s_.ci = 0;
                s_.st = St::CANDIDATE;
                break;

            // for j in near: if ship is source: continue
            //     off = offsets[(ship_set, torp_set)]
            //     seg_prev = _shifted(prev_pos, off)
            //     seg_cur = _shifted(cur_pos, off)
            //     ... (aim_unit is not None and shields_block(ship)) ...
            case St::CANDIDATE: {
                const Moving& mv = s_.moving[s_.mi];
                if (s_.ci >= s_.near[s_.mi].size()) {
                    s_.st = St::NARROW_WRITE;
                    break;
                }
                const ShipEntry& e = (*s_.cache)[s_.near[s_.mi][s_.ci]];
                if (e.ship == mv.source) {
                    ++s_.ci;
                    break;
                }
                const auto o = s_.offsets.find({e.set, mv.set});
                if (o == s_.offsets.end() || !o->second)
                    lost("a candidate with no offset");
                s_.off = *o->second;
                s_.seg_prev = shifted(mv.prev, s_.off);
                s_.seg_cur = shifted(mv.cur, s_.off);
                s_.shields.reset();
                s_.bubble.reset();
                if (mv.aim) {
                    try {
                        s_.shields = shields_block(m_, e.ship,
                                                   ctx_.npc_shields_off,
                                                   ctx_.player);
                    } catch (const std::invalid_argument&) {
                        return ask(K3Query::shields_block, {e.ship},
                                   St::SHIELDS_ANSWER);
                    }
                }
                s_.st = St::BUBBLE;
                break;
            }
            case St::SHIELDS_ANSWER:
                s_.shields = take_answer().flag;
                s_.st = St::BUBBLE;
                break;

            // bubble_entry = shield_bubble_entry(ship, seg_prev, aim_unit,
            //     seg_len)                     (max_dist = seg_len)
            case St::BUBBLE: {
                const Moving& mv = s_.moving[s_.mi];
                if (mv.aim && s_.shields && *s_.shields) {
                    const int64_t ship = (*s_.cache)[s_.near[s_.mi][s_.ci]].ship;
                    try {
                        s_.bubble = shield_bubble_entry(m_, ship, s_.seg_prev,
                                                        *mv.aim, mv.seg_len);
                    } catch (const std::invalid_argument&) {
                        return ask(K3Query::bubble,
                                   {ship, s_.seg_prev, *mv.aim, mv.seg_len},
                                   St::BUBBLE_ANSWER);
                    }
                }
                s_.st = St::SPHERE;
                break;
            }
            case St::BUBBLE_ANSWER: {
                const K3Answer a = take_answer();
                if (a.none)
                    s_.bubble.reset();
                else
                    s_.bubble = a.point;
                s_.st = St::SPHERE;
                break;
            }

            case St::SPHERE: {
                const Moving& mv = s_.moving[s_.mi];
                const ShipEntry& e = (*s_.cache)[s_.near[s_.mi][s_.ci]];
                // if bubble_entry is None and not sphere_hit(seg_cur,
                //     ship.GetWorldLocation(), world_radius(ship)): continue
                // (GetWorldLocation is the cached read: no ship moves inside
                // update_all)
                if (!s_.bubble &&
                    !sphere_hit(s_.seg_cur, e.pos, world_radius(m_, e.ship))) {
                    ++s_.ci;
                    s_.st = St::CANDIDATE;
                    break;
                }
                if (s_.bubble) {
                    // seg_cur = bubble_entry
                    // cur_pos = _shifted(bubble_entry, off, -1.0)
                    // (projectiles.py:985: back into the torpedo's frame)
                    s_.seg_cur = *s_.bubble;
                    s_.cur_pos = shifted(*s_.bubble, s_.off, -1.0);
                }
                if (mv.aim) {
                    const Vec3& u = *mv.aim;
                    // radius = world_radius(ship) if hasattr(ship,
                    // "GetRadius") else 0.0 (a ship always has it)
                    const double radius = world_radius(m_, e.ship);
                    const double backoff = radius + mv.seg_len;
                    s_.ray_origin = {s_.seg_cur[0] - u[0] * backoff,
                                     s_.seg_cur[1] - u[1] * backoff,
                                     s_.seg_cur[2] - u[2] * backoff};
                    // ray_max = 2.0 * radius + seg_len (projectiles.py:1003)
                    s_.ray_max = 2.0 * radius + mv.seg_len;
                } else {
                    s_.ray_origin = s_.seg_prev;
                    s_.ray_max = mv.seg_len;
                }
                s_.st = St::TRACE;
                break;
            }
            case St::TRACE: {
                K3Record rec = trace();
                if (s_.st == St::NARROW_WRITE) break;
                return rec;
            }
            case St::TRACE_ANSWER: {
                // The answer stays in s_.answer for hit().
                s_.pending = K3Query::kCount;
                hit();
                break;
            }

            // t.SetTranslateXYZ(cur_pos.x, cur_pos.y, cur_pos.z)
            case St::NARROW_WRITE:
                s_.positions.push_back({s_.moving[s_.mi].torp, s_.cur_pos});
                ++s_.mi;
                s_.st = St::NARROW_FOR;
                break;

            case St::FINISH:
                return finish();
            case St::DONE:
                lost("the session already returned DONE");
            }
        } catch (const std::invalid_argument& e) {
            // No RUN_PYTHON after begin: a read begin validated failed.
            lost(std::string("a validated read failed (protocol invariant, "
                             "k3_projectiles.h): ") +
                 e.what());
        }
    }
}

}  // namespace

// ── K3Kernel ─────────────────────────────────────────────────────────────────

K3Kernel::K3Kernel(Mirror& m, TransformStore& store, StepScan& scan)
    : m_(m), store_(store), scan_(scan) {
    if (&store != &m.store())
        throw std::logic_error(
            "combat K3: the kernel must write the store the mirror reads");
}
K3Kernel::~K3Kernel() = default;

void K3Kernel::clear() {
    session_.reset();
    hits_.clear();
}

std::optional<K3Why> K3Kernel::begin(double dt, const GuideClocks& clocks,
                                     bool use_memo, K2Context ctx,
                                     int64_t n_active, bool keep_iids,
                                     std::optional<uint64_t> scan_serial) {
    if (session_) lost("a session is already open");
    hits_.clear();
    if (keep_iids) ctx.iids = std::move(ctx_.iids);
    ctx_ = std::move(ctx);
    auto python = [this](K3Why w) -> std::optional<K3Why> {
        ++counts_.python_steps;
        ++counts_.why[static_cast<size_t>(w)];
        return w;
    };

    // Not representable, or not the scan the driver took this step (a scan
    // of another ships_list, or a reset, since): never walk a stale scan.
    if (!scan_.representable ||
        (scan_serial && *scan_serial != scan_.serial))
        return python(K3Why::scan);
    const TorpedoTable& tt = m_.torpedoes();
    // A dirty table (emptied), a torpedo listed twice (the rebuild leaves it
    // empty), anything in `_active` that has no row.
    if (n_active < 0 || tt.size() != static_cast<size_t>(n_active))
        return python(K3Why::table);
    auto torps = std::make_shared<std::vector<int64_t>>(tt.handles());
    for (const int64_t h : *torps) {
        const TorpedoRow& r = *tt.find(h);
        if (r.unrepresentable) return python(K3Why::unrepresentable);
        for (TorpField f : {TorpField::_target_ship, TorpField::_source_ship,
                            TorpField::_containing_set, TorpField::_mount_key})
            if (m_.torpedo_ref(r, f) == kRefUnrepresentable)
                return python(K3Why::stale_ref);
        uint32_t xi = 0, xg = 0;
        if (!torp_slot(store_, r, xi, xg)) return python(K3Why::torpedo_xform);
    }

    // Step 0, the ship cache (projectiles.py update_all), in all_ships order:
    //   if ship.IsDead(): continue      (BEFORE any other read of the ship)
    //   pos = ship.GetWorldLocation()
    //   (ship, pos.x, pos.y, pos.z, bubble_bound_radius(ship),
    //    frames.containing_set(ship))
    auto cache = std::make_shared<std::vector<ShipEntry>>();
    auto in_scan = std::make_shared<std::unordered_set<int64_t>>(
        scan_.ships.begin(), scan_.ships.end());
    cache->reserve(scan_.ships.size());
    try {
        for (const int64_t h : scan_.ships) {
            if (ship_dead(m_, h)) continue;
            const ObjectRow& o = detail::obj(m_, h);
            ShipEntry e;
            e.ship = h;
            e.pos = detail::world_location(m_, o);
            e.bound = bubble_bound_radius(m_, h);
            e.set = o._containing_set;
            cache->push_back(e);
        }
    } catch (const std::invalid_argument&) {
        return python(K3Why::ship_cache);
    }

    auto s = std::make_unique<Session>();
    s->dt = dt;
    s->clocks = clocks;
    s->use_memo = use_memo;
    s->st = St::TORP_FOR;
    s->torps = std::move(torps);
    s->cache = std::move(cache);
    s->in_scan = std::move(in_scan);
    session_ = std::move(s);
    ++counts_.runs;
    return std::nullopt;
}

K3Record K3Kernel::next() {
    if (!session_) lost("no session is open");
    Session& s = *session_;
    if (s.awaiting_answer && !s.has_answer)
        lost("ASK has no answer (combat_k3_answer)");
    if (s.st == St::DONE) lost("the session already returned DONE");
    // A throw leaves the session as it was (nothing has been written: the
    // writes are made at DONE, after every check).
    Session before = s;
    s.awaiting_answer = false;
    s.has_answer = false;
    try {
        Walker w(m_, store_, scan_, s, ctx_, counts_);
        K3Record r = w.run();
        if (r.kind == K3Kind::DONE) hits_ = r.hits;  // THE HITS
        return r;
    } catch (...) {
        s = std::move(before);
        throw;
    }
}

K3Query K3Kernel::awaiting() const {
    if (!session_ || !session_->awaiting_answer || session_->has_answer)
        return K3Query::kCount;
    return session_->pending;
}

void K3Kernel::answer(const K3Answer& a) {
    if (!session_ || !session_->awaiting_answer || session_->has_answer)
        lost("no ASK is waiting for an answer");
    session_->answer = a;
    session_->has_answer = true;
}

void K3Kernel::end() {
    if (!session_) lost("no session is open");
    if (session_->st != St::DONE) lost("the session has not returned DONE");
    session_.reset();
}

void K3Kernel::abandon() {
    if (!session_) lost("no session is open");
    session_.reset();
}

// THE HITS (k3_projectiles.h): host_loop's
//   for torpedo, ship, hit_point, hit_normal in hits:
//       combat.apply_hit(ship, torpedo._damage, hit_point,
//           source=torpedo._source_ship, normal=hit_normal,
//           ship_instances=ship_instances, weapon_type="torpedo",
//           hardpoint_weapon=torpedo, shield_point=torpedo._bubble_entry)
// from hit `from`, until one the kernel cannot apply.
size_t K3Kernel::apply_hits(size_t from, const K2PulseCtx& p,
                            const std::unordered_set<size_t>& python,
                            std::vector<K3Applied>& out) {
    auto handed = [this](K2PulseWhy why, size_t i) {
        ++counts_.hit_why[static_cast<size_t>(why)];
        return i;
    };
    for (size_t i = from; i < hits_.size(); ++i) {
        const K3Hit& h = hits_[i];
        if (!p.ok) return handed(K2PulseWhy::not_ok, i);
        if (p.clean.count(h.ship) == 0) return handed(K2PulseWhy::unscanned, i);
        if (python.count(i)) return i;  // the driver's own reason
        HitInput in;
        in.ship = h.ship;
        in.source = h.source;
        in.damage = h.damage;
        in.point = h.hit.point;
        in.has_normal = h.hit.normal.has_value();
        if (in.has_normal) in.normal = *h.hit.normal;
        // weapon_splash_radius(torpedo, None): its DRF if > 0, else the
        // default.
        in.r_hit = h.drf > 0.0 ? h.drf : p.default_radius;
        in.damage_hull = true;
        in.has_shield_point = h.bubble.has_value();
        if (in.has_shield_point) in.shield_point = *h.bubble;
        // On a fallback-tier bubble hit the hit point, seg_cur and
        // `_bubble_entry` are one object (projectiles.py).
        in.shield_point_is_point = h.hit_is_bubble;
        in.hit_weapon = p.hit_weapon;
        in.weapon_hit_type = p.weapon_hit_type;
        in.has_instances = p.has_instances;
        K3Applied a;
        a.index = i;
        a.source = h.source;
        // combat.apply_hit: step_memo.forget() on the way in and out.
        memo_clear(m_);
        try {
            apply_hit(m_, in, p.dc, a.out);
        } catch (const std::invalid_argument&) {
            return handed(K2PulseWhy::fallback, i);  // the mirror as it was
        }
        memo_clear(m_);
        out.push_back(std::move(a));
        ++counts_.native_hits;
    }
    return hits_.size();
}

K3Kernel& k3_kernel() {
    static K3Kernel k(mirror(), transform_store(), step_scan());
    return k;
}

}  // namespace dauntless::combat
