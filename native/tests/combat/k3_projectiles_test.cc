// The K3 torpedo kernel (k3_projectiles.h) on hand-built mirror rows, a
// hand-built step scan and a FAKE trace: the record sequence of the
// update_all walk, the write log, the expired / hit lists, the store writes
// and the whole-step fallbacks. The native-vs-Python differentials run from
// the K3 driver's tests (Task 5) and the host-level differential (Task 6).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <functional>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "dauntless/combat/beam_geometry.h"
#include "dauntless/combat/beam_trace.h"
#include "dauntless/combat/k3_projectiles.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/combat/projectile_geometry.h"
#include "dauntless/combat/sensor_detect.h"
#include "dauntless/combat/step_scan.h"
#include "dauntless/combat/torpedo_table.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr double kDt = 1.0 / 60.0;
constexpr double kDrift = 0.0, kNow = 10.0;

// The trace: the instance {1, 1} is live at the origin and returns `hit`
// (or nothing); any other id is stale.
struct FakeHost {
    std::optional<TraceHit> hit;
    int calls = 0;
    TraceHooks hooks() {
        TraceHooks h;
        h.translation = [](InstanceId id) -> std::optional<Vec3> {
            if (id.index != 1 || id.generation != 1) return std::nullopt;
            return Vec3{0.0, 0.0, 0.0};
        };
        h.trace = [this](InstanceId id, const float*, const float*,
                         float) -> std::optional<TraceHit> {
            ++calls;
            if (id.index != 1 || id.generation != 1)
                throw StaleInstance("ray_trace_mesh: invalid InstanceId");
            return hit;
        };
        return h;
    }
};

struct World {
    TransformStore store;
    Mirror m{store};
    StepScan scan;
    K3Kernel k{m, store, scan};
    FakeHost host;
    int64_t set = -1;
    int64_t next_id = 1;
    // The step's ships_list, in order.
    std::vector<int64_t> ships;
    // frames.frame_of per set: (key, anchor); default (0, origin).
    std::map<int64_t, std::pair<int64_t, Vec3>> frame_of;
    // Sets whose frame-table entry is left out (an ASK frame).
    std::set<int64_t> no_frame;
    std::map<int64_t, std::string> names;

    World() {
        m.set_global_f(Global::SHIELD_ELLIPSOID_AXIS_SCALE, std::sqrt(3.0));
        m.set_global_f(Global::LEAD_ACCEL_K, 0.5);
        m.set_global_f(Global::sensorless_range_gu, 2000.0);
        m.set_global_f(Global::cloak_bubble_cap_gu, 30.0);
        m.set_global_f(Global::overboost_threshold, 1.2);
        m.set_global_f(Global::min_blocker_radius_gu, 2.0);
        m.set_global_f(Global::conceal_cap, 0.19);
        m.set_global_i(Global::occ_enabled, 0);
        m.set_global_i(Global::enhanced_sensor_contest, 0);
        m.set_global_f(Global::CONCEAL_K, 0.9);
        m.set_global_f(Global::LOCK_BREAK_T, 0.28);
        m.set_global_f(Global::HYSTERESIS, 0.08);
        m.set_global_f(Global::PROFILE_CONCEALMENT_CAP, 0.19);
        m.set_global_f(Global::CLOAK_RANGE_FACTOR, 0.005);
        m.set_global_f(Global::CLOAK_DETECTION_BASE_GU, 5.0);
        set = m.register_row(Kind::Set);
    }

    int64_t new_set(int64_t key, const Vec3& anchor) {
        const int64_t s = m.register_row(Kind::Set);
        frame_of[s] = {key, anchor};
        return s;
    }
    // A placed ShipClass, alive, radius 2 (no sensor subsystem: the
    // sensorless dial, 2000 GU). NOT in the step's ships_list.
    int64_t ship(const std::string& name, double x, double y, double z,
                 int64_t in_set = -3) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, x, y, z);
        const int64_t h = m.register_row(Kind::Object, i, g, next_id++);
        m.set_i(h, Field::has_real_is_dead, 1);
        m.set_f(h, Field::_life_time, 1.0e9);
        m.set_ref(h, Field::_containing_set, in_set == -3 ? set : in_set);
        m.set_f(h, Field::o_radius, 2.0);
        m.set_f(h, Field::_scale, 1.0);
        m.set_i(h, Field::is_ship_class, 1);
        m.set_i(h, Field::has_real_get_shields, 1);
        m.set_i(h, Field::has_sensor_getter, 1);
        m.set_i(h, Field::has_cloak_getter, 1);
        names[h] = name;
        return h;
    }
    // A ship in ships_list.
    int64_t listed(const std::string& name, double x, double y, double z,
                   int64_t in_set = -3) {
        const int64_t h = ship(name, x, y, z, in_set);
        ships.push_back(h);
        return h;
    }
    // Shields up, and a 1x1x1 half-extent hull box at the ship's centre.
    void shields(int64_t ship_h) {
        const int64_t s = m.register_row(Kind::Subsystem);
        m.set_i(s, Field::has_shields, 1);
        m.set_i(s, Field::_is_on, 1);
        m.set_f(s, Field::_max_condition, 100.0);
        m.set_f(s, Field::_condition, 100.0);
        m.set_f(s, Field::_disabled_percentage, 0.25);
        m.set_ref(ship_h, Field::_shield_subsystem, s);
        m.set_fv(ship_h, Field::_shield_hull_box_center, {0.0, 0.0, 0.0});
        m.set_fv(ship_h, Field::_shield_hull_box_half, {1.0, 1.0, 1.0});
        m.set_i(ship_h, Field::hull_box_set, 1);
    }
    // A torpedo row (BC's ctor defaults), appended to `_active`.
    int64_t torp(const std::string& name, const Vec3& pos, const Vec3& v,
                 int64_t target = -1, int64_t source = -1,
                 int64_t in_set = -3) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, pos[0], pos[1], pos[2]);
        auto& t = m.torpedoes();
        const int64_t h = t.add(i, g);
        t.set_f(h, TorpField::_age, 0.0);
        t.set_f(h, TorpField::_ttl, 60.0);
        t.set_f(h, TorpField::_guidance_lifetime, 4.0);
        t.set_f(h, TorpField::_guidance_initial, 4.0);
        t.set_f(h, TorpField::_max_angular_accel, 0.125);
        t.set_v(h, TorpField::_velocity, true, v);
        m.set_torpedo_ref(h, TorpField::_containing_set,
                          in_set == -3 ? set : in_set);
        m.set_torpedo_ref(h, TorpField::_target_ship, target);
        m.set_torpedo_ref(h, TorpField::_source_ship, source);
        tnames[h] = name;
        return h;
    }
    std::map<int64_t, std::string> tnames;

    const TorpedoRow& row(int64_t h) { return *m.torpedoes().find(h); }
    Vec3 pos(int64_t torp_h) {
        const TorpedoRow& r = row(torp_h);
        return store.position(static_cast<uint32_t>(r.xform_index),
                              static_cast<uint32_t>(r.xform_gen));
    }

    // The step scan for `ships` and its frame table, as the driver sends it.
    void scan_step() {
        scan.begin();
        scan.ships = ships;
        check_rows(m, scan);
        for (int64_t s : scan.sets) {
            if (no_frame.count(s)) continue;
            auto it = frame_of.find(s);
            const auto f = it == frame_of.end()
                               ? std::pair<int64_t, Vec3>{0, {0, 0, 0}}
                               : it->second;
            scan.frames.push_back({s, f.first, f.second});
        }
    }
    K2Context context() {
        K2Context ctx;
        ctx.hooks = host.hooks();
        for (const auto& [s, f] : frame_of) ctx.view_offsets[s] = std::nullopt;
        ctx.view_offsets[set] = std::nullopt;
        return ctx;
    }
    std::optional<K3Why> begin(bool use_memo = false,
                               std::function<void(K2Context&)> edit = {}) {
        scan_step();
        K2Context ctx = context();
        if (edit) edit(ctx);
        return k.begin(kDt, GuideClocks{kDrift, kNow}, use_memo,
                       std::move(ctx),
                       static_cast<int64_t>(m.torpedoes().size()));
    }

    std::string name(int64_t h) const {
        auto it = names.find(h);
        return it == names.end() ? std::to_string(h) : it->second;
    }
    std::string tname(int64_t h) const {
        auto it = tnames.find(h);
        return it == tnames.end() ? std::to_string(h) : it->second;
    }
    // "ASK query first-arg" or "DONE".
    std::string brief(const K3Record& r) const {
        std::string s = k3_kind_name(r.kind);
        if (r.kind == K3Kind::ASK) {
            s += std::string(" ") + k3_query_name(r.query);
            if (!r.args.empty()) {
                const auto* h = std::get_if<int64_t>(&r.args[0]);
                if (h) {
                    s += " ";
                    if (r.query == K3Query::steer_point ||
                        r.query == K3Query::guide)
                        s += tname(*h);
                    else if (r.query == K3Query::frame)
                        s += std::to_string(*h);
                    else
                        s += name(*h);
                }
            }
        }
        return s;
    }
    std::vector<std::string> expired(const K3Record& r) const {
        std::vector<std::string> out;
        for (int64_t h : r.expired) out.push_back(tname(h));
        return out;
    }
    std::vector<std::string> hits(const K3Record& r) const {
        std::vector<std::string> out;
        for (const K3Hit& h : r.hits)
            out.push_back(tname(h.torp) + "@" + name(h.ship));
        return out;
    }
    const K3TorpWrite& write_of(const K3Record& r, int64_t torp_h) {
        for (const K3TorpWrite& w : r.writes)
            if (w.torp == torp_h) return w;
        throw std::logic_error("no write for " + tname(torp_h));
    }
    // next() to DONE, failing on any ASK.
    K3Record done() {
        const K3Record r = k.next();
        EXPECT_EQ(r.kind, K3Kind::DONE) << brief(r);
        return r;
    }
    using V = std::vector<std::string>;
};

Vec3 add_scaled(const Vec3& p, const Vec3& v, double dt) {
    return {p[0] + v[0] * dt, p[1] + v[1] * dt, p[2] + v[2] * dt};
}

}  // namespace

TEST(K3Projectiles, KindsAndNames) {
    EXPECT_STREQ(k3_kind_name(K3Kind::DONE), "DONE");
    EXPECT_STREQ(k3_kind_name(K3Kind::ASK), "ASK");
    EXPECT_STREQ(k3_query_name(K3Query::frame), "frame");
    EXPECT_STREQ(k3_query_name(K3Query::steer_point), "steer_point");
    EXPECT_STREQ(k3_query_name(K3Query::guide), "guide");
    EXPECT_STREQ(k3_query_name(K3Query::shields_block), "shields_block");
    EXPECT_STREQ(k3_query_name(K3Query::bubble), "bubble");
    EXPECT_STREQ(k3_query_name(K3Query::resolve_hit), "resolve_hit");
    EXPECT_STREQ(k3_why_name(K3Why::scan), "scan");
    EXPECT_STREQ(k3_why_name(K3Why::table), "table");
    EXPECT_STREQ(k3_why_name(K3Why::unrepresentable), "unrepresentable");
    EXPECT_STREQ(k3_why_name(K3Why::stale_ref), "stale_ref");
    EXPECT_STREQ(k3_why_name(K3Why::torpedo_xform), "torpedo_xform");
    EXPECT_STREQ(k3_why_name(K3Why::ship_cache), "ship_cache");
}

// update_all steps 1 then 3: EVERY torpedo is steered and advanced before
// any narrow test. A (listed first) hits X and its trace must ask; B (listed
// second) must ask its guide. The guide ASK comes first.
TEST(K3Projectiles, GuideThenAdvanceEveryTorpedoBeforeNarrow) {
    World w;
    const int64_t x = w.listed("X", 0, 50, 0);
    const int64_t y = w.ship("Y", 0, -900, 0);  // not in ships_list
    const int64_t a = w.torp("A", {0, 40, 0}, {0, 600, 0});
    const int64_t b = w.torp("B", {0, -500, 0}, {0, 600, 0}, y);
    ASSERT_EQ(w.begin(false, [&](K2Context& c) {
                  c.iids[x] = K2Context::Iid{false, InstanceId{1, 1}};
                  c.view_offsets.clear();  // the trace must ask
              }),
              std::nullopt);
    K3Record r = w.k.next();
    ASSERT_EQ(w.brief(r), "ASK guide B");
    // Python's _guide pushes its velocity into B's row.
    w.m.torpedoes().set_v(b, TorpField::_velocity, true, {0, 0, 600});
    w.k.answer(K3Answer{});
    r = w.k.next();
    ASSERT_EQ(w.brief(r), "ASK resolve_hit X");
    ASSERT_EQ(r.args.size(), 5u);
    EXPECT_EQ(std::get<Vec3>(r.args[4]), (Vec3{0, 50, 0}));  // seg_cur
    K3Answer hit;
    hit.point = {0, 48.5, 0};
    hit.normal = Vec3{0, -1, 0};
    hit.tier = ResolvedHit::Tier::Mesh;
    w.k.answer(hit);
    r = w.done();
    EXPECT_EQ(w.hits(r), (World::V{"A@X"}));
    EXPECT_EQ(r.hits[0].hit.point, (Vec3{0, 48.5, 0}));
    EXPECT_EQ(r.hits[0].hit.tier, ResolvedHit::Tier::Mesh);
    EXPECT_FALSE(r.hits[0].hit_is_bubble);
    EXPECT_EQ(w.expired(r), (World::V{"A"}));
    // B advanced with the velocity Python's _guide left in its row; its
    // guide fields are not in the log (Python made them).
    EXPECT_EQ(w.pos(b), add_scaled({0, -500, 0}, {0, 0, 600}, kDt));
    const K3TorpWrite& wb = w.write_of(r, b);
    EXPECT_FALSE(wb.vel || wb.last_seen || wb.last_tvel);
    EXPECT_EQ(wb.age, 0.0 + kDt);
    EXPECT_EQ(w.pos(a), add_scaled({0, 40, 0}, {0, 600, 0}, kDt));
    w.k.end();
    EXPECT_EQ(w.k.counts().queries[static_cast<size_t>(K3Query::guide)], 1);
    EXPECT_EQ(w.k.counts().guide_why.at("target_not_in_scan"), 1);
}

// `expired`: TTL expiries (appended in step 1) before hits (step 3).
TEST(K3Projectiles, TtlExpiriesFirstInExpired) {
    World w;
    w.listed("X", 0, 50, 0);
    const int64_t a = w.torp("A", {0, 40, 0}, {0, 600, 0});
    const int64_t b = w.torp("B", {0, -500, 0}, {0, 600, 0});
    w.m.torpedoes().set_f(b, TorpField::_age, 59.99);
    ASSERT_EQ(w.begin(), std::nullopt);
    const K3Record r = w.done();
    EXPECT_EQ(w.expired(r), (World::V{"B", "A"}));
    EXPECT_EQ(w.hits(r), (World::V{"A@X"}));
    EXPECT_EQ(w.write_of(r, b).age, 59.99 + kDt);
    EXPECT_EQ(w.row(b).age, 59.99 + kDt);  // the row holds it at DONE
    EXPECT_EQ(w.pos(b), add_scaled({0, -500, 0}, {0, 600, 0}, kDt));
    EXPECT_EQ(w.write_of(r, a).age, kDt);
    w.k.end();
}

// A torpedo that expires this tick is still guided (guide precedes the age
// test), moved with the POST-guide velocity, and never hit-tested.
TEST(K3Projectiles, TtlTorpedoStillGuidedNotHitTested) {
    World w;
    const int64_t x = w.listed("X", 0, 50, 0);
    const Vec3 v0{6, 60, 0};
    const int64_t t = w.torp("T", {0, 48, 0}, v0, x);
    w.m.torpedoes().set_f(t, TorpField::_age, 59.99);
    w.m.torpedoes().set_f(t, TorpField::_guidance_lifetime, 100.0);
    ASSERT_EQ(w.begin(), std::nullopt);
    const K3Record r = w.done();
    EXPECT_TRUE(r.hits.empty());
    EXPECT_EQ(w.expired(r), (World::V{"T"}));
    const K3TorpWrite& wt = w.write_of(r, t);
    ASSERT_TRUE(wt.vel.has_value());
    ASSERT_TRUE(wt.last_seen.has_value());
    ASSERT_TRUE(wt.last_tvel.has_value());
    EXPECT_NE(*wt.vel, v0);
    EXPECT_EQ(w.pos(t), add_scaled({0, 48, 0}, *wt.vel, kDt));
    EXPECT_EQ(w.row(t).vel, *wt.vel);
    w.k.end();
}

// Candidates ascend by ship-cache index (ships_list order): the first ship
// whose test passes wins.
TEST(K3Projectiles, FirstHitByShipIndexWins) {
    for (int order = 0; order < 2; ++order) {
        World w;
        const int64_t x = w.ship("X", 0, 50, 0);
        const int64_t y = w.ship("Y", 0, 50.5, 0);
        w.ships = order == 0 ? std::vector<int64_t>{y, x}
                             : std::vector<int64_t>{x, y};
        w.torp("A", {0, 40, 0}, {0, 600, 0});
        ASSERT_EQ(w.begin(), std::nullopt);
        const K3Record r = w.done();
        EXPECT_EQ(w.hits(r), (World::V{order == 0 ? "A@Y" : "A@X"}));
        w.k.end();
    }
}

// `if ship is source: continue` -- the shooter is skipped, the next ship is
// still tested.
TEST(K3Projectiles, SourceShipNeverHit) {
    World w;
    const int64_t x = w.listed("X", 0, 50, 0);
    w.listed("Z", 0, 50.5, 0);
    w.torp("A", {0, 40, 0}, {0, 600, 0}, -1, x);
    ASSERT_EQ(w.begin(), std::nullopt);
    K3Record r = w.done();
    EXPECT_EQ(w.hits(r), (World::V{"A@Z"}));
    w.k.end();

    World u;
    const int64_t ux = u.listed("X", 0, 50, 0);
    const int64_t ua = u.torp("A", {0, 40, 0}, {0, 600, 0}, -1, ux);
    ASSERT_EQ(u.begin(), std::nullopt);
    r = u.done();
    EXPECT_TRUE(r.hits.empty());
    EXPECT_TRUE(r.expired.empty());
    EXPECT_EQ(u.pos(ua), (Vec3{0, 50, 0}));
    u.k.end();
}

// The ship cache drops a ship dead at step start before reading anything
// else of it (a dead ship's bound is never computed).
TEST(K3Projectiles, DeadAtStartShipNotCached) {
    World w;
    const int64_t x = w.listed("X", 0, 50, 0);
    w.m.set_i(x, Field::_dead, 1);
    const int64_t d = w.listed("D", 0, 0, 0);
    w.m.set_i(d, Field::_dead, 1);
    w.store.free(static_cast<uint32_t>(w.m.get_i(d, Field::xform_index)),
                 static_cast<uint32_t>(w.m.get_i(d, Field::xform_gen)));
    const int64_t a = w.torp("A", {0, 40, 0}, {0, 600, 0});
    ASSERT_EQ(w.begin(), std::nullopt);
    const K3Record r = w.done();
    EXPECT_TRUE(r.hits.empty());
    EXPECT_EQ(w.pos(a), (Vec3{0, 50, 0}));
    w.k.end();
}

// A bubble hit detonates ON the bubble: the store gets the bubble point, and
// on the fallback tier the hit point IS the bubble object.
TEST(K3Projectiles, BubbleHitWritesStoreOnBubble) {
    World w;
    const int64_t x = w.listed("X", 0, 50, 0);
    w.shields(x);
    const int64_t a = w.torp("A", {0, 40, 0}, {0, 600, 0});
    const Vec3 prev{0, 40, 0};
    const Advance adv = advance_torpedo(prev, {0, 600, 0}, kDt, 0.0, 60.0);
    const std::optional<Vec3> bubble =
        shield_bubble_entry(w.m, x, prev, *adv.aim_unit, adv.seg_len);
    ASSERT_TRUE(bubble.has_value());
    ASSERT_LT((*bubble)[1], 50.0 - 1.0);
    ASSERT_EQ(w.begin(), std::nullopt);
    const K3Record r = w.done();
    ASSERT_EQ(w.hits(r), (World::V{"A@X"}));
    const K3Hit& h = r.hits[0];
    ASSERT_TRUE(h.bubble.has_value());
    EXPECT_EQ(*h.bubble, *bubble);
    EXPECT_EQ(h.hit.tier, ResolvedHit::Tier::Fallback);
    EXPECT_TRUE(h.hit_is_bubble);
    EXPECT_EQ(h.hit.point, *bubble);
    EXPECT_EQ(w.pos(a), *bubble);
    w.k.end();
}

// A ship in another region of the torpedo's frame is a candidate by the
// shifted test (B2) and is hit in ITS coordinates; the torpedo's position is
// written back in its OWN set's (A13: bubble - off). Another frame never
// interacts.
TEST(K3Projectiles, CrossRegionCandidateUsesShiftedTest) {
    for (int shields = 0; shields < 2; ++shields) {
        World w;
        const int64_t ts = w.new_set(0, {1000, 0, 0});
        const int64_t ss = w.new_set(0, {0, 0, 0});
        const int64_t x = w.listed("X", 0, 50, 0, ss);
        if (shields) w.shields(x);
        const int64_t a =
            w.torp("A", {-1000, 40, 0}, {0, 600, 0}, -1, -1, ts);
        ASSERT_EQ(w.begin(), std::nullopt);
        const K3Record r = w.done();
        ASSERT_EQ(w.hits(r), (World::V{"A@X"})) << shields;
        const K3Hit& h = r.hits[0];
        if (!shields) {
            EXPECT_EQ(h.hit.point, (Vec3{0, 50, 0}));  // seg_cur = cur + off
            EXPECT_FALSE(h.hit_is_bubble);
            EXPECT_EQ(w.pos(a), (Vec3{-1000, 50, 0}));
        } else {
            ASSERT_TRUE(h.bubble.has_value());
            const Vec3& bb = *h.bubble;
            EXPECT_LT(bb[1], 49.0);
            EXPECT_EQ(w.pos(a), (Vec3{bb[0] + -1.0 * 1000.0, bb[1] + -1.0 * 0.0,
                                      bb[2] + -1.0 * 0.0}));
        }
        w.k.end();
    }
    // Another frame (different key): no candidate.
    World w;
    const int64_t ts = w.new_set(1, {1000, 0, 0});
    const int64_t ss = w.new_set(0, {0, 0, 0});
    w.listed("X", 0, 50, 0, ss);
    w.torp("A", {0, 40, 0}, {0, 600, 0}, -1, -1, ts);
    ASSERT_EQ(w.begin(), std::nullopt);
    const K3Record r = w.done();
    EXPECT_TRUE(r.hits.empty());
    w.k.end();
}

// A picked spot (mount None): the steer point is the offset as a plain
// body point, X + R·(scale·offset), with NO part pose, natively, whatever
// the target's parts do (fire control native only, M5; there is no bake).
// Counted a posed steer at a posed target; at an unposed one it is the
// same arithmetic and not counted. (Was BakedPickSteersNatively and
// UnbakedPickAsksSteerPoint.)
TEST(K3Projectiles, PickSteersAtPlainPointNatively) {
    for (const bool posed : {true, false}) {
        World w;
        const int64_t x = w.listed("X", 0, 100, 0);
        PartPose shift;
        shift.t[2] = 0.25;
        shift.identity = false;
        w.m.set_i(x, Field::has_posed_parts, posed ? 1 : 0);
        if (posed) w.m.set_part_poses(x, {shift});
        const int64_t t = w.torp("T", {0, 0, 0}, {0, 60, 0}, x);
        w.m.torpedoes().set_v(t, TorpField::_target_offset, true, {1, 0, 0});
        w.m.set_torpedo_mount(t, true, -1, {1, 0, 0});
        const GuideResult want = guide_torpedo_resume(
            w.m, w.row(t), kDt, GuideResume{x, 60.0, {0, 0, 0}},
            Vec3{1.0, 100.0, 0.0});
        ASSERT_EQ(w.begin(), std::nullopt) << posed;
        const K3Record r = w.done();
        const K3TorpWrite& wt = w.write_of(r, t);
        ASSERT_TRUE(wt.last_seen && wt.last_tvel && wt.vel) << posed;
        EXPECT_EQ(*wt.last_seen, want.writes[0].value) << posed;
        EXPECT_EQ(*wt.vel, want.writes[2].value) << posed;
        w.k.end();
        const auto& n = w.k.counts();
        for (const int64_t k : n.steer_why) EXPECT_EQ(k, 0) << posed;
        EXPECT_EQ(n.posed_steers, posed ? 1 : 0);
    }
}

// A posed target under an offset that IS its attributed mount's point, the
// mount's part slot current: the steer point is the posed mount, decided
// natively (posed parts, Task 4: PG:310). The offset off the mount's own
// point (within 1e-5): a plain body point, natively too (fire control
// native only, M8.5). A stale slot: _steer_point is Python's, counted by
// why.
TEST(K3Projectiles, PosedTargetMountSteersNatively) {
    enum Case { kNative, kOffMount, kStale };
    for (int c = kNative; c <= kStale; ++c) {
        World w;
        const int64_t x = w.listed("X", 0, 100, 0);
        const int64_t mnt = w.m.register_row(Kind::Subsystem);
        w.m.set_ref(mnt, Field::_parent_ship, x);
        w.m.set_fv(mnt, Field::_position,
                   {1.0, 0.0, c == kOffMount ? 1e-9 : 0.0});
        PartPose shift;
        shift.t[2] = 0.25;
        shift.identity = false;
        w.m.set_i(x, Field::has_posed_parts, 1);
        w.m.set_part_poses(x, {shift});
        w.m.set_part_slot(mnt, 0, w.m.part_gen());
        if (c == kStale) w.m.set_part_gen(w.m.part_gen() + 1);
        const int64_t t = w.torp("T", {0, 0, 0}, {0, 60, 0}, x);
        w.m.torpedoes().set_v(t, TorpField::_target_offset, true, {1, 0, 0});
        w.m.set_torpedo_mount(t, true, mnt, {1, 0, 0});
        ASSERT_EQ(w.begin(), std::nullopt) << c;
        const auto& n = w.k.counts();
        if (c == kNative || c == kOffMount) {
            // The steer point: X + (offset + t) = (1, 100, 0.25) on the
            // mount; X + offset = (1, 100, 0) off it.
            const GuideResult want = guide_torpedo_resume(
                w.m, w.row(t), kDt, GuideResume{x, 60.0, {0, 0, 0}},
                Vec3{1.0, 100.0, c == kNative ? 0.25 : 0.0});
            const K3Record r = w.done();
            const K3TorpWrite& wt = w.write_of(r, t);
            ASSERT_TRUE(wt.last_seen.has_value());
            EXPECT_EQ(*wt.last_seen, want.writes[0].value);
            EXPECT_EQ(n.posed_steers, 1);
            for (const int64_t k : n.steer_why) EXPECT_EQ(k, 0);
        } else {
            EXPECT_EQ(w.brief(w.k.next()), "ASK steer_point T") << c;
            const SteerWhy want = SteerWhy::part_stale;
            EXPECT_EQ(n.steer_why[static_cast<size_t>(want)], 1) << c;
            EXPECT_STREQ(steer_why_name(want), "part_stale");
            EXPECT_EQ(n.posed_steers, 0) << c;
            w.k.abandon();
            continue;
        }
        w.k.end();
    }
}

// A shot whose mount is not yet attributed: the kernel attributes it itself
// (round trips, Task 4) -- the FIRST subsystem of the mount order within
// 1e-5 per axis -- steers at it with no ASK, logs Python's `_mount_key`
// write and, at DONE, puts the mount in the row: the next tick needs no
// attribution.
TEST(K3Projectiles, UnattributedMountAttributedNatively) {
    World w;
    const int64_t x = w.listed("X", 0, 100, 0);
    const Vec3 off{1.0 + 0.25e-5, 0.0, 0.0};
    // Both within 1e-5 of the offset; `b` is the exact point, `a` first.
    const int64_t a = w.m.register_row(Kind::Subsystem);
    w.m.set_ref(a, Field::_parent_ship, x);
    w.m.set_fv(a, Field::_position, {1.0, 0.0, 0.0});
    const int64_t b = w.m.register_row(Kind::Subsystem);
    w.m.set_ref(b, Field::_parent_ship, x);
    w.m.set_fv(b, Field::_position, {off[0], off[1], off[2]});
    w.m.set_mount_order(x, {a, b});
    const int64_t t = w.torp("T", {0, 0, 0}, {0, 60, 0}, x);
    w.m.torpedoes().set_v(t, TorpField::_target_offset, true, off);
    // A stale key: another offset.
    w.m.set_torpedo_mount(t, true, b, {2.0, 0.0, 0.0});
    const GuideResult want = guide_torpedo_resume(
        w.m, w.row(t), kDt, GuideResume{x, 60.0, {0, 0, 0}},
        steer_point_native(w.m, x, off, a, {0, 0, 0}));
    ASSERT_EQ(w.begin(), std::nullopt);
    K3Record r = w.done();
    const K3TorpWrite& wt = w.write_of(r, t);
    ASSERT_TRUE(wt.last_seen && wt.last_tvel && wt.vel);
    EXPECT_EQ(*wt.last_seen, want.writes[0].value);
    EXPECT_EQ(*wt.vel, want.writes[2].value);
    ASSERT_TRUE(wt.mount.has_value());
    EXPECT_EQ(wt.mount->target, x);
    EXPECT_EQ(wt.mount->offset, off);
    EXPECT_EQ(wt.mount->sub, a);
    // The row holds the key now (Python copies it without pushing).
    EXPECT_TRUE(w.row(t).mount_attributed);
    EXPECT_EQ(w.row(t).mount_sub, a);
    EXPECT_EQ(w.row(t).mount_offset, off);
    w.k.end();
    EXPECT_EQ(w.k.counts().native_attributions, 1);
    for (const int64_t k : w.k.counts().steer_why) EXPECT_EQ(k, 0);
    // Next tick: attributed, nothing to write.
    ASSERT_EQ(w.begin(), std::nullopt);
    r = w.done();
    EXPECT_FALSE(w.write_of(r, t).mount.has_value());
    w.k.end();
    EXPECT_EQ(w.k.counts().native_attributions, 1);
    EXPECT_EQ(
        w.k.counts().queries[static_cast<size_t>(K3Query::steer_point)], 0);
}

// A mount order entry the mirror cannot name (or a freed row) before any
// match: it might have matched, so the attribution is Python's (ASK,
// unattributed), and the kernel logs no `_mount_key` (Python wrote it).
TEST(K3Projectiles, MountUnknownAsksUnattributed) {
    for (const bool freed : {false, true}) {
        World w;
        const int64_t x = w.listed("X", 0, 100, 0);
        const int64_t a = w.m.register_row(Kind::Subsystem);
        w.m.set_fv(a, Field::_position, {1.0, 0.0, 0.0});
        int64_t first = kRefUnrepresentable;
        if (freed) {
            first = w.m.register_row(Kind::Subsystem);
            w.m.set_fv(first, Field::_position, {7.0, 0.0, 0.0});
        }
        w.m.set_mount_order(x, {first, a});
        if (freed) w.m.unregister_row(first);
        const int64_t t = w.torp("T", {0, 0, 0}, {0, 60, 0}, x);
        w.m.torpedoes().set_v(t, TorpField::_target_offset, true, {1, 0, 0});
        ASSERT_EQ(w.begin(), std::nullopt) << freed;
        EXPECT_EQ(w.brief(w.k.next()), "ASK steer_point T") << freed;
        w.m.set_torpedo_mount(t, true, a, {1, 0, 0});  // Python's _mount_key
        K3Answer ans;
        ans.point = {1, 100, 0};
        w.k.answer(ans);
        const K3Record r = w.done();
        EXPECT_FALSE(w.write_of(r, t).mount.has_value()) << freed;
        w.k.end();
        const auto& n = w.k.counts();
        EXPECT_EQ(n.steer_why[static_cast<size_t>(SteerWhy::unattributed)], 1)
            << freed;
        EXPECT_EQ(n.native_attributions, 0) << freed;
    }
}

// No mount claims the offset (a picked spot): the kernel attributes None
// itself, logs Python's `_mount_key` write and steers at the plain point
// with no ASK (fire control native only, M5; was the unbaked ASK).
TEST(K3Projectiles, NoMountPickAttributedNatively) {
    World w;
    const int64_t x = w.listed("X", 0, 100, 0);
    const int64_t t = w.torp("T", {0, 0, 0}, {0, 60, 0}, x);
    w.m.torpedoes().set_v(t, TorpField::_target_offset, true, {1, 0, 0});
    ASSERT_EQ(w.begin(), std::nullopt);
    K3Record r = w.done();
    const K3TorpWrite& wt = w.write_of(r, t);
    EXPECT_TRUE(wt.vel.has_value());
    ASSERT_TRUE(wt.mount.has_value());
    EXPECT_EQ(wt.mount->sub, -1);
    w.k.end();
    const auto& n = w.k.counts();
    EXPECT_EQ(n.queries[static_cast<size_t>(K3Query::steer_point)], 0);
    for (const int64_t k : n.steer_why) EXPECT_EQ(k, 0);
    EXPECT_EQ(n.native_attributions, 1);
}

// A target with a stub IsDead cannot be in the step scan, so its torpedo's
// whole _guide is Python's; the advance uses the velocity it left.
TEST(K3Projectiles, StubIsDeadTargetAsksGuide) {
    World w;
    w.listed("X", 0, 500, 0);
    const int64_t s = w.ship("S", 0, 100, 0);
    w.m.set_i(s, Field::has_real_is_dead, 0);
    const int64_t t = w.torp("T", {0, 0, 0}, {0, 60, 0}, s);
    ASSERT_EQ(w.begin(), std::nullopt);
    K3Record r = w.k.next();
    ASSERT_EQ(w.brief(r), "ASK guide T");
    ASSERT_EQ(r.args.size(), 1u);
    EXPECT_EQ(w.k.awaiting(), K3Query::guide);
    // Python: the stub IsDead is truthy -> ballistic; nothing written.
    w.k.answer(K3Answer{});
    r = w.done();
    const K3TorpWrite& wt = w.write_of(r, t);
    EXPECT_FALSE(wt.vel || wt.last_seen || wt.last_tvel);
    EXPECT_EQ(w.pos(t), add_scaled({0, 0, 0}, {0, 60, 0}, kDt));
    w.k.end();
}

// A set with no frame-table entry asks `frame` and the compare is repeated
// (torpedo->target). The source->target compare inside _target_visible does
// NOT ask a frame: Python swallows a raise there into True, so a missing
// source frame hands the whole _guide to Python ("source or target frame").
TEST(K3Projectiles, MissingFrameAsksFrame) {
    World w;
    const int64_t tb = w.new_set(0, {0, 0, 0});
    const int64_t sc = w.new_set(0, {0, 0, 0});
    const int64_t x = w.listed("X", 0, 100, 0, tb);
    const int64_t src = w.listed("S", 0, -100, 0, sc);
    const int64_t t = w.torp("T", {0, 0, 0}, {0, 60, 0}, x, src);
    w.no_frame = {tb, sc};
    ASSERT_EQ(w.begin(), std::nullopt);
    K3Record r = w.k.next();
    ASSERT_EQ(w.brief(r), "ASK frame " + std::to_string(tb));
    K3Answer f;
    f.key = 0;
    f.point = {0, 0, 0};
    w.k.answer(f);
    r = w.k.next();
    ASSERT_EQ(w.brief(r), "ASK guide T");
    w.k.answer(K3Answer{});     // Python's _guide: nothing written here
    // The broad phase still needs the source's set framed (S is listed,
    // so its set is offset against the torpedo's): a frame ASK there.
    r = w.k.next();
    ASSERT_EQ(w.brief(r), "ASK frame " + std::to_string(sc));
    w.k.answer(f);
    r = w.done();
    EXPECT_FALSE(w.write_of(r, t).vel.has_value());
    EXPECT_NE(w.scan.frame(tb), nullptr);
    EXPECT_NE(w.scan.frame(sc), nullptr);
    w.k.end();
    EXPECT_EQ(w.k.counts().queries[static_cast<size_t>(K3Query::frame)], 2);
    EXPECT_EQ(w.k.counts().guide_why.at("source or target frame"), 1);
}

// can_detect runs natively from each torpedo's SOURCE in list order, with
// Python's arguments: memo-eligible for the same set and for another frame
// (off None still asks), dist_sq (never memoised) across regions. The memo
// and latch after the walk equal those after Python's calls in that order.
TEST(K3Projectiles, CanDetectCalledInListOrder) {
    auto build = [](World& w) {
        const int64_t b = w.new_set(0, {500, 0, 0});
        const int64_t d = w.new_set(1, {0, 0, 0});
        const int64_t x = w.listed("X", 0, 100, 0);
        const int64_t s0 = w.listed("S0", 0, -100, 0);
        const int64_t s1 = w.listed("S1", -500, 0, 0, b);
        const int64_t s2 = w.listed("S2", 0, 0, 0, d);
        w.torp("T0", {0, 0, 0}, {0, 60, 0}, x, s0);
        w.torp("T1", {0, 0, 0}, {0, 60, 0}, x, s1);
        w.torp("T2", {0, 0, 0}, {0, 60, 0}, x, s2);
        const int64_t t3 = w.torp("T3", {0, 0, 0}, {0, 60, 0}, x, s0);
        w.m.torpedoes().set_f(t3, TorpField::_age, 4.0);  // window over
        w.torp("T4", {0, 0, 0}, {0, 60, 0}, x, -1);
        // Two more cross-region shots from S1 at X: never memoised, so each
        // makes its own can_detect call, after T2's.
        w.torp("T5", {0, 0, 0}, {0, 60, 0}, x, s1);
        w.torp("T6", {0, 0, 0}, {0, 60, 0}, x, s1);
        return std::vector<int64_t>{x, s0, s1, s2};
    };
    World w;
    build(w);
    ASSERT_EQ(w.begin(true), std::nullopt);
    w.done();
    w.k.end();

    World p;
    const auto h = build(p);
    const int64_t x = h[0], s0 = h[1], s1 = h[2], s2 = h[3];
    can_detect(p.m, s0, x, kDrift, true, std::nullopt, true, std::nullopt,
               kNow);
    // S1 in the region anchored at (500, 0, 0): its frame -> X's is -500.
    const double dx = (0.0 + 1.0 * -500.0) - -500.0, dy = 100.0 - 0.0,
                 dz = 0.0 - 0.0;
    can_detect(p.m, s1, x, kDrift, true, dx * dx + dy * dy + dz * dz, true,
               std::nullopt, kNow);
    can_detect(p.m, s2, x, kDrift, true, std::nullopt, true, std::nullopt,
               kNow);
    for (int i = 0; i < 2; ++i)  // T5, T6
        can_detect(p.m, s1, x, kDrift, true, dx * dx + dy * dy + dz * dz,
                   true, std::nullopt, kNow);

    const auto& a = w.m.sensor_state();
    const auto& b = p.m.sensor_state();
    EXPECT_EQ(a.memo.size(), 2u);
    EXPECT_EQ(a.memo, b.memo);
    EXPECT_EQ(a.latch, b.latch);
    EXPECT_EQ(a.memo.count({s0, x}), 1u);
    EXPECT_EQ(a.memo.count({s2, x}), 1u);
    EXPECT_EQ(a.memo.count({s1, x}), 0u);
}

// abandon() before DONE leaves every torpedo row and position as at begin
// (the kernel writes only at DONE), and the next step begins cleanly.
TEST(K3Projectiles, AbandonLeavesMirrorEqual) {
    World w;
    const int64_t x = w.listed("X", 0, 100, 0);
    const int64_t y = w.ship("Y", 0, -900, 0);
    const int64_t t0 = w.torp("T0", {0, 0, 0}, {6, 60, 0}, x);
    const int64_t t1 = w.torp("T1", {0, -500, 0}, {0, 600, 0}, y);
    w.m.torpedoes().set_f(t0, TorpField::_age, 59.99);  // TTL this tick
    w.m.torpedoes().set_f(t0, TorpField::_guidance_lifetime, 100.0);
    const TorpedoRow r0 = w.row(t0), r1 = w.row(t1);
    const Vec3 p0 = w.pos(t0), p1 = w.pos(t1);
    ASSERT_EQ(w.begin(), std::nullopt);
    ASSERT_EQ(w.brief(w.k.next()), "ASK guide T1");  // T0 already decided
    w.k.abandon();
    EXPECT_FALSE(w.k.open());
    for (const auto& [h, before] :
         {std::pair{t0, r0}, std::pair{t1, r1}}) {
        const TorpedoRow& now = w.row(h);
        EXPECT_EQ(now.age, before.age);
        EXPECT_EQ(now.vel, before.vel);
        EXPECT_EQ(now.last_seen_set, before.last_seen_set);
        EXPECT_EQ(now.last_seen, before.last_seen);
        EXPECT_EQ(now.last_tvel_set, before.last_tvel_set);
        EXPECT_EQ(now.last_tvel, before.last_tvel);
    }
    EXPECT_EQ(w.pos(t0), p0);
    EXPECT_EQ(w.pos(t1), p1);
    ASSERT_EQ(w.begin(), std::nullopt);
    EXPECT_TRUE(w.k.open());
    w.k.abandon();
}

// Everything begin() hands to Python whole, before any session opens.
TEST(K3Projectiles, BeginHandsWholeStepToPython) {
    auto expect_why = [](World& w, K3Why why, int64_t n_active = -1) {
        w.scan_step();
        const int64_t n = n_active >= 0
                              ? n_active
                              : static_cast<int64_t>(w.m.torpedoes().size());
        EXPECT_EQ(w.k.begin(kDt, GuideClocks{kDrift, kNow}, false,
                            w.context(), n),
                  std::optional<K3Why>(why));
        EXPECT_FALSE(w.k.open());
        EXPECT_EQ(w.k.counts().why[static_cast<size_t>(why)], 1);
        EXPECT_EQ(w.k.counts().python_steps, 1);
        EXPECT_EQ(w.k.counts().runs, 0);
    };
    {
        World w;  // a stale ship in ships_list: the scan is not representable
        const int64_t x = w.listed("X", 0, 0, 0);
        w.m.unregister_row(x);
        expect_why(w, K3Why::scan);
    }
    {
        World w;  // the table does not hold every `_active` entry
        w.torp("T", {0, 0, 0}, {0, 60, 0});
        expect_why(w, K3Why::table, 2);
    }
    {
        World w;
        const int64_t t = w.torp("T", {0, 0, 0}, {0, 60, 0});
        w.m.torpedoes().set_unrepresentable(t, TorpField::_ttl);
        expect_why(w, K3Why::unrepresentable);
    }
    {
        World w;  // the target's row was dropped: the ref reads -2
        const int64_t y = w.ship("Y", 0, 100, 0);
        w.torp("T", {0, 0, 0}, {0, 60, 0}, y);
        w.m.unregister_row(y);
        expect_why(w, K3Why::stale_ref);
    }
    {
        World w;
        const int64_t t = w.torp("T", {0, 0, 0}, {0, 60, 0});
        const TorpedoRow& r = w.row(t);
        w.store.free(static_cast<uint32_t>(r.xform_index),
                     static_cast<uint32_t>(r.xform_gen));
        expect_why(w, K3Why::torpedo_xform);
    }
    {
        World w;  // an ALIVE listed ship with no transform
        const int64_t x = w.listed("X", 0, 0, 0);
        w.store.free(static_cast<uint32_t>(w.m.get_i(x, Field::xform_index)),
                     static_cast<uint32_t>(w.m.get_i(x, Field::xform_gen)));
        w.torp("T", {0, 0, 0}, {0, 60, 0});
        expect_why(w, K3Why::ship_cache);
    }
    {
        World w;  // no torpedo: a session over nothing returns DONE
        ASSERT_EQ(w.begin(), std::nullopt);
        const K3Record r = w.done();
        EXPECT_TRUE(r.writes.empty() && r.expired.empty() && r.hits.empty());
        w.k.end();
        EXPECT_EQ(w.k.counts().runs, 1);
        EXPECT_THROW(w.k.next(), std::logic_error);
    }
}

// The driver passes the serial of the scan it took this step (ctx
// "scan_serial"): a scan taken since -- another ships_list, a reset -- is not
// this step's, so the whole step is Python's ("scan"). No serial: unchecked.
TEST(K3Projectiles, BeginRefusesAStaleScanSerial) {
    World w;
    w.listed("X", 0, 50, 0);
    w.torp("T", {0, 0, 0}, {0, 60, 0});
    w.scan_step();
    const uint64_t taken = w.scan.serial;
    w.scan_step();  // a newer scan of the same ships
    ASSERT_NE(w.scan.serial, taken);
    EXPECT_EQ(w.k.begin(kDt, GuideClocks{kDrift, kNow}, false, w.context(), 1,
                        false, taken),
              std::optional<K3Why>(K3Why::scan));
    EXPECT_FALSE(w.k.open());
    EXPECT_EQ(w.k.counts().why[static_cast<size_t>(K3Why::scan)], 1);
    EXPECT_EQ(w.k.counts().runs, 0);
    EXPECT_EQ(w.k.begin(kDt, GuideClocks{kDrift, kNow}, false, w.context(), 1,
                        false, w.scan.serial),
              std::nullopt);
    w.k.abandon();
    EXPECT_EQ(w.k.begin(kDt, GuideClocks{kDrift, kNow}, false, w.context(), 1),
              std::nullopt);
    w.k.abandon();
    EXPECT_EQ(w.k.counts().runs, 2);
}

// A bubble the mirror cannot answer (a zero semi-axis raises in Python) and
// a shields_block it cannot answer are K2's ASKs on the narrow path.
TEST(K3Projectiles, NarrowAsksAsK2) {
    World w;
    const int64_t x = w.listed("X", 0, 50, 0);
    w.shields(x);
    w.m.set_i(x, Field::has_real_get_shields, 0);  // shields_block -> ASK
    const int64_t a = w.torp("A", {0, 40, 0}, {0, 600, 0});
    ASSERT_EQ(w.begin(), std::nullopt);
    K3Record r = w.k.next();
    ASSERT_EQ(w.brief(r), "ASK shields_block X");
    K3Answer yes;
    yes.flag = true;
    w.k.answer(yes);
    // has_real_get_shields does not stop the native bubble: it answers.
    r = w.done();
    ASSERT_EQ(w.hits(r), (World::V{"A@X"}));
    ASSERT_TRUE(r.hits[0].bubble.has_value());
    EXPECT_EQ(w.pos(a), *r.hits[0].bubble);
    w.k.end();

    // The bubble ASK: a semi-axis that underflows to zero (Python raises
    // ZeroDivisionError). Python's answer is the bubble point.
    World u;
    const int64_t ux = u.listed("X", 0, 50, 0);
    u.shields(ux);
    u.m.set_fv(ux, Field::_shield_hull_box_half, {1e-30, 1e-30, 1e-30});
    u.m.set_f(ux, Field::_scale, 1e-300);
    const int64_t ua = u.torp("A", {0, 41, 0}, {0, 540, 0});
    ASSERT_EQ(u.begin(), std::nullopt);
    r = u.k.next();
    ASSERT_EQ(u.brief(r), "ASK bubble X");
    ASSERT_EQ(r.args.size(), 4u);
    EXPECT_EQ(std::get<Vec3>(r.args[1]), (Vec3{0, 41, 0}));  // seg_prev
    EXPECT_EQ(std::get<Vec3>(r.args[2]), (Vec3{0, 1, 0}));   // aim_unit
    EXPECT_EQ(std::get<double>(r.args[3]), 9.0);             // seg_len
    K3Answer pt;
    pt.point = {0, 48, 0};
    u.k.answer(pt);
    r = u.done();
    ASSERT_EQ(u.hits(r), (World::V{"A@X"}));
    ASSERT_TRUE(r.hits[0].bubble.has_value());
    EXPECT_EQ(*r.hits[0].bubble, (Vec3{0, 48, 0}));
    EXPECT_TRUE(r.hits[0].hit_is_bubble);
    EXPECT_EQ(u.pos(ua), (Vec3{0, 48, 0}));
    u.k.end();
}

// update_all's gate `t._age < t._guidance_lifetime` reads the age BEFORE
// this tick's `+= dt`; a NaN age is never guided and never expires.
TEST(K3Projectiles, GuidanceWindowUsesPreIncrementAge) {
    World w;
    const int64_t x = w.listed("X", 0, 100, 0);
    const int64_t in = w.torp("IN", {0, 0, 0}, {6, 60, 0}, x);
    const int64_t at = w.torp("AT", {0, 0, 0}, {6, 60, 0}, x);
    const int64_t nan = w.torp("NAN", {0, 0, 0}, {6, 60, 0}, x);
    w.m.torpedoes().set_f(in, TorpField::_age, 4.0 - kDt / 2.0);
    w.m.torpedoes().set_f(at, TorpField::_age, 4.0);
    w.m.torpedoes().set_f(nan, TorpField::_age, std::nan(""));
    ASSERT_EQ(w.begin(), std::nullopt);
    const K3Record r = w.done();
    EXPECT_TRUE(w.write_of(r, in).vel.has_value());
    EXPECT_FALSE(w.write_of(r, at).vel.has_value());
    EXPECT_FALSE(w.write_of(r, nan).vel.has_value());
    EXPECT_TRUE(std::isnan(w.write_of(r, nan).age));
    EXPECT_TRUE(r.expired.empty());
    w.k.end();
}

// A SOURCE outside the step scan: _target_visible's can_detect would read a
// ship whose class was never checked, so _guide is Python's.
TEST(K3Projectiles, SourceOutsideScanAsksGuide) {
    World w;
    const int64_t x = w.listed("X", 0, 100, 0);
    const int64_t s = w.ship("S", 0, -100, 0);  // not in ships_list
    w.torp("T", {0, 0, 0}, {0, 60, 0}, x, s);
    ASSERT_EQ(w.begin(), std::nullopt);
    ASSERT_EQ(w.brief(w.k.next()), "ASK guide T");
    w.k.answer(K3Answer{});
    w.done();
    w.k.end();
    EXPECT_EQ(w.k.counts().guide_why.at("source_not_in_scan"), 1);
}

// The shooter in ANOTHER region is skipped by the shifted broadphase too.
TEST(K3Projectiles, CrossRegionSourceNeverHit) {
    for (int with_z = 0; with_z < 2; ++with_z) {
        World w;
        const int64_t ts = w.new_set(0, {1000, 0, 0});
        const int64_t ss = w.new_set(0, {0, 0, 0});
        const int64_t x = w.listed("X", 0, 50, 0, ss);
        if (with_z) w.listed("Z", 0, 50.5, 0, ss);
        w.torp("A", {-1000, 40, 0}, {0, 600, 0}, -1, x, ts);
        ASSERT_EQ(w.begin(), std::nullopt);
        const K3Record r = w.done();
        EXPECT_EQ(w.hits(r), with_z ? World::V{"A@Z"} : World::V{});
        w.k.end();
    }
}

// Same-set (swept) and other-region (shifted) candidates merge into one
// ascending list: the lower ship-cache index wins whichever test found it.
TEST(K3Projectiles, CandidatesMergeAcrossRegionsByIndex) {
    for (int order = 0; order < 2; ++order) {
        World w;
        const int64_t ts = w.new_set(0, {1000, 0, 0});
        const int64_t ss = w.new_set(0, {0, 0, 0});
        const int64_t o = w.ship("O", 0, 50, 0, ss);         // other region
        const int64_t x = w.ship("X", -1000, 50.5, 0, ts);   // same set
        w.ships = order == 0 ? std::vector<int64_t>{o, x}
                             : std::vector<int64_t>{x, o};
        w.torp("A", {-1000, 40, 0}, {0, 600, 0}, -1, -1, ts);
        ASSERT_EQ(w.begin(), std::nullopt);
        const K3Record r = w.done();
        EXPECT_EQ(w.hits(r), (World::V{order == 0 ? "A@O" : "A@X"}));
        w.k.end();
    }
}

// ── THE HITS (native damage, Task 4) ────────────────────────────────────────

namespace {

// A ship the hit can damage: hurtable, stood in for, a critical hull and no
// other subsystem.
int64_t hull_of(World& w, int64_t ship, double hull_max) {
    w.m.set_i(ship, Field::dmg_ship, 1);
    w.m.set_i(ship, Field::_hurtable, 1);
    const int64_t hull = w.m.register_row(Kind::Subsystem);
    w.m.set_f(hull, Field::_max_condition, hull_max);
    w.m.set_f(hull, Field::_condition, hull_max);
    w.m.set_f(hull, Field::_disabled_percentage, 0.5);
    w.m.set_ref(hull, Field::_parent_ship, ship);
    w.m.set_i(hull, Field::dmg_class, kDmgLeaf);
    w.m.set_i(hull, Field::_critical, 1);
    w.m.set_ref(ship, Field::_hull, hull);
    w.m.set_mount_order(ship, {});
    return hull;
}

void payload(World& w, int64_t torp_h, double damage, double drf) {
    w.m.torpedoes().set_f(torp_h, TorpField::_damage, damage);
    w.m.torpedoes().set_f(torp_h, TorpField::_damage_radius_factor, drf);
}

K2PulseCtx hit_ctx(std::initializer_list<int64_t> clean) {
    K2PulseCtx p;
    p.ok = true;
    p.default_radius = 0.15;
    p.hit_weapon = 2;       // HIT_WEAPON_TORPEDO
    p.weapon_hit_type = 1;  // WeaponHitEvent.TORPEDO
    p.clean = clean;
    return p;
}

const DamageEntry& first(const K3Applied& a, DamageKind kind) {
    for (const DamageEntry& e : a.out.entries)
        if (e.kind == kind) return e;
    throw std::logic_error("no such entry");
}

}  // namespace

TEST(K3Hits, DoneKeepsItsHitsWithWhatTheirTorpedoesCarry) {
    World w;
    const int64_t src = w.listed("S", 0, 0, 0);
    const int64_t x = w.listed("X", 0, 50, 0);
    const int64_t a = w.torp("A", {0, 40, 0}, {0, 600, 0}, -1, src);
    payload(w, a, 125.0, 0.5);
    ASSERT_EQ(w.begin(), std::nullopt);
    const K3Record r = w.done();
    w.k.end();
    ASSERT_EQ(w.k.hits().size(), 1u);
    const K3Hit& h = w.k.hits()[0];
    EXPECT_EQ(h.ship, x);
    EXPECT_EQ(h.damage, 125.0);
    EXPECT_EQ(h.drf, 0.5);
    EXPECT_EQ(h.source, src);
    // The row may go (the driver's expire) before the hit is applied.
    w.m.torpedoes().drop(a);
    EXPECT_EQ(w.k.hits()[0].damage, 125.0);
    EXPECT_EQ(r.hits.size(), 1u);
}

TEST(K3Hits, EachHitIsAppliedFullyBeforeTheNextInMovingOrder) {
    World w;
    const int64_t src = w.listed("S", 0, 0, 0);
    const int64_t x = w.listed("X", 0, 50, 0);
    const int64_t hull = hull_of(w, x, 50.0);
    const int64_t a = w.torp("A", {0, 40, 0}, {0, 600, 0}, -1, src);
    const int64_t b = w.torp("B", {0, 41, 0}, {0, 600, 0}, -1, src);
    payload(w, a, 40.0, 0.0);
    payload(w, b, 40.0, 0.5);
    ASSERT_EQ(w.begin(), std::nullopt);
    w.done();
    w.k.end();
    std::vector<K3Applied> out;
    EXPECT_EQ(w.k.apply_hits(0, hit_ctx({x}), {}, out), 2u);
    ASSERT_EQ(out.size(), 2u);
    EXPECT_EQ(out[0].index, 0u);
    EXPECT_EQ(out[1].index, 1u);
    EXPECT_EQ(out[0].source, src);
    EXPECT_EQ(w.m.get_f(hull, Field::_condition), 0.0);
    // A took 50 -> 10; B, written after, crossed zero.
    const DamageEntry& z = first(out[1], DamageKind::ZERO_CROSS);
    EXPECT_TRUE(z.ops[2].boolean);
    const DamageEntry& pa = first(out[0], DamageKind::HIT_PRESENT);
    const DamageEntry& pb = first(out[1], DamageKind::HIT_PRESENT);
    EXPECT_EQ(pa.ops[17].number, 0.15);  // no DRF: the default radius
    EXPECT_EQ(pb.ops[17].number, 0.5);
    EXPECT_EQ(pa.ops[16].integer, 2);
    EXPECT_TRUE(pa.ops[19].boolean);     // damage_hull
    EXPECT_EQ(first(out[0], DamageKind::WEAPON_HIT).ops[12].integer, 1);
    EXPECT_EQ(w.k.counts().native_hits, 2);
    EXPECT_TRUE(w.m.sensor_state().memo.empty());
}

TEST(K3Hits, ABubbleHitsShieldPointIsItsHitPoint) {
    World w;
    const int64_t x = w.listed("X", 0, 50, 0);
    w.shields(x);
    w.m.set_floats(w.m.get_ref(x, Field::_shield_subsystem),
                   Field::_current_shields, {0, 0, 0, 0, 0, 0});
    w.m.set_floats(w.m.get_ref(x, Field::_shield_subsystem),
                   Field::_max_shields, {0, 0, 0, 0, 0, 0});
    w.m.set_floats(w.m.get_ref(x, Field::_shield_subsystem),
                   Field::_ramp_fraction, {0, 0, 0, 0, 0, 0});
    w.m.set_floats(w.m.get_ref(x, Field::_shield_subsystem),
                   Field::_ramp_set, {0, 0, 0, 0, 0, 0});
    w.m.set_i(w.m.get_ref(x, Field::_shield_subsystem), Field::dmg_class,
              kDmgLeaf);
    hull_of(w, x, 500.0);
    const int64_t a = w.torp("A", {0, 40, 0}, {0, 600, 0});
    payload(w, a, 10.0, 0.0);
    ASSERT_EQ(w.begin(), std::nullopt);
    w.done();
    w.k.end();
    ASSERT_TRUE(w.k.hits()[0].hit_is_bubble);
    std::vector<K3Applied> out;
    EXPECT_EQ(w.k.apply_hits(0, hit_ctx({x}), {}, out), 1u);
    const DamageEntry& p = first(out[0], DamageKind::HIT_PRESENT);
    EXPECT_TRUE(p.ops[20].boolean);   // has_shield_point
    EXPECT_TRUE(p.ops[21].boolean);   // shield_point IS hit_point
}

TEST(K3Hits, ApplyStopsAtTheFirstHitItCannotApply) {
    struct Case {
        const char* why;
        int reason;  // K2PulseWhy, or -1: the driver's own `python` index
    };
    for (const Case c : {Case{"not_ok", 0}, Case{"unscanned", 1},
                         Case{"fallback", 3}, Case{"python", -1}}) {
        SCOPED_TRACE(c.why);
        World w;
        const int64_t x = w.listed("X", 0, 50, 0);
        const int64_t y = w.listed("Y", 100, 50, 0);
        const int64_t hx = hull_of(w, x, 500.0);
        const int64_t hy = hull_of(w, y, 500.0);
        payload(w, w.torp("A", {0, 40, 0}, {0, 600, 0}), 10.0, 0.0);
        payload(w, w.torp("B", {100, 40, 0}, {0, 600, 0}), 20.0, 0.0);
        ASSERT_EQ(w.begin(), std::nullopt);
        w.done();
        w.k.end();
        K2PulseCtx p = hit_ctx({x, y});
        std::unordered_set<size_t> python;
        if (c.reason == 0) p.ok = false;
        if (c.reason == 1) p.clean.erase(y);
        if (c.reason == 3) w.m.set_i(y, Field::dmg_ship, 0);
        if (c.reason == -1) python.insert(1);
        std::vector<K3Applied> out;
        if (c.reason == 0) {
            EXPECT_EQ(w.k.apply_hits(0, p, python, out), 0u);
            EXPECT_TRUE(out.empty());
            EXPECT_EQ(w.m.get_f(hx, Field::_condition), 500.0);
            continue;
        }
        // A lands; B is handed back with Y untouched; nothing after it.
        EXPECT_EQ(w.k.apply_hits(0, p, python, out), 1u);
        ASSERT_EQ(out.size(), 1u);
        EXPECT_EQ(w.m.get_f(hx, Field::_condition), 490.0);
        EXPECT_EQ(w.m.get_f(hy, Field::_condition), 500.0);
        if (c.reason >= 0)
            EXPECT_EQ(w.k.counts().hit_why[static_cast<size_t>(c.reason)], 1);
        // From past it: nothing left.
        out.clear();
        EXPECT_EQ(w.k.apply_hits(2, p, python, out), 2u);
        EXPECT_TRUE(out.empty());
    }
}

TEST(K3Hits, BeginForgetsTheLastStepsHits) {
    World w;
    w.listed("X", 0, 50, 0);
    w.torp("A", {0, 40, 0}, {0, 600, 0});
    ASSERT_EQ(w.begin(), std::nullopt);
    w.done();
    w.k.end();
    ASSERT_EQ(w.k.hits().size(), 1u);
    w.m.torpedoes().clear();
    ASSERT_EQ(w.begin(), std::nullopt);
    EXPECT_TRUE(w.k.hits().empty());
    w.k.abandon();
}
