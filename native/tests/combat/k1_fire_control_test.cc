// The K1 fire-control kernel (k1_fire_control.h) on hand-built mirror rows:
// the record sequence of the pump and the walk, the write log, the fallbacks
// and the session stack. The native-vs-Python differentials run from
// tests/unit/test_native_k1_dispatch.py and
// tests/integration/test_native_k1_differential.py (Tasks 5 and 6).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <variant>
#include <vector>

#include "dauntless/combat/k1_fire_control.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/combat/sensor_detect.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr double kDt = 1.0 / 60.0;

struct World {
    TransformStore store;
    Mirror m{store};
    K1Kernel k{m};
    int64_t set = -1;
    int64_t next_id = 1;
    std::map<int64_t, std::string> names;

    // `legacy`: every walk starts the old way, with a WALK_START record (a
    // walk check that always answers true) -- the record sequences the
    // walk tests below were written against. World(false) has no check:
    // walks start natively (round trips Task 1).
    explicit World(bool legacy = true) {
        if (legacy) k.set_walk_check([](int64_t, int64_t) { return true; });
        m.set_global_f(Global::FIRE_TIMER_THRESHOLD, 0.33);
        m.set_global_f(Global::PHASER_MAX_RANGE_GU, 700.0);
        m.set_global_f(Global::BEAM_ON_DELAY_S, 2 * 0.33);
        m.set_global_f(Global::TORPEDO_CONE_HALF_ANGLE, 0.5235984);
        m.set_global_f(Global::PULSE_RANGE_GATE_SECONDS, 30.0);
        m.set_global_f(Global::PULSE_COST_SCALE_0, 0.5);
        m.set_global_f(Global::PULSE_COST_SCALE_1, 1.0);
        m.set_global_f(Global::PULSE_COST_SCALE_2, 2.0);
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

    // A DamageableObject in the one set, alive.
    int64_t object(const std::string& name, double x, double y, double z) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, x, y, z);
        const int64_t h = m.register_row(Kind::Object, i, g, next_id++);
        m.set_i(h, Field::has_real_is_dead, 1);
        m.set_f(h, Field::_life_time, 1.0e9);
        m.set_ref(h, Field::_containing_set, set);
        names[h] = name;
        return h;
    }
    // A ShipClass row (no sensor subsystem: the sensorless dial, 2000 GU).
    int64_t ship(const std::string& name, double x = 0.0, double y = 0.0,
                 double z = 0.0) {
        const int64_t h = object(name, x, y, z);
        m.set_i(h, Field::has_sensor_getter, 1);
        m.set_i(h, Field::has_cloak_getter, 1);
        return h;
    }
    void cloak(int64_t obj) {
        const int64_t c = m.register_row(Kind::Subsystem);
        m.set_i(c, Field::_cloak_state, 2);  // cloaked
        m.set_i(obj, Field::has_cloak_getter, 1);
        m.set_ref(obj, Field::_cloaking_subsystem, c);
    }
    // A weapon system of `kind` (1 phaser, 2 pulse, 3 tractor, 4 torpedo) on
    // `ship`, powered, healthy, held at `targets` (held = the last one).
    int64_t system(const std::string& name, int64_t ship_h, int64_t kind,
                   std::vector<int64_t> targets) {
        const int64_t s = m.register_row(Kind::Subsystem);
        names[s] = name;
        m.set_i(s, Field::weapon_kind, kind);
        m.set_i(s, Field::_is_on, 1);
        m.set_i(s, Field::has_parent_ship_getter, 1);
        m.set_ref(s, Field::_parent_ship, ship_h);
        m.set_f(s, Field::_max_condition, 100.0);
        m.set_f(s, Field::_condition, 100.0);
        m.set_f(s, Field::_disabled_percentage, 0.25);
        m.set_i(s, Field::_last_weapon_idx, -1);
        m.set_i(s, Field::_last_group_fired, -1);
        m.set_f(s, Field::_last_system_fire_time, -1000.0);
        m.set_i(s, Field::_fire_held, 1);
        m.set_ids(s, Field::_target_list, targets);
        m.set_ref(s, Field::_held_target, targets.empty() ? -1 : targets.back());
        const Field getter = kind == 1   ? Field::_phaser_system
                             : kind == 2 ? Field::_pulse_weapon_system
                             : kind == 3 ? Field::_tractor_beam_system
                                         : Field::_torpedo_system;
        m.set_ref(ship_h, getter, s);
        if (kind == 4) {
            const int64_t ammo = m.register_row(Kind::Ammo);
            m.set_i(ammo, Field::_unlimited, 1);
            m.set_ids(s, Field::_ammo_by_slot, {0, ammo});
        }
        return s;
    }
    // A leaf weapon of the system's canonical kind, facing ship-forward (+y)
    // at the ship's origin, charged and ready.
    int64_t bank(const std::string& name, int64_t sys) {
        const int64_t b = m.register_row(Kind::Subsystem);
        names[b] = name;
        const int64_t sk = m.get_i(sys, Field::weapon_kind);
        const int64_t kind = sk == 1 ? 5 : sk == 2 ? 6 : sk == 3 ? 7 : 8;
        m.set_i(b, Field::weapon_kind, kind);
        m.set_i(b, Field::has_parent_ship_getter, 1);
        m.set_ref(b, Field::_parent_subsystem, sys);
        m.set_f(b, Field::_max_condition, 100.0);
        m.set_f(b, Field::_condition, 100.0);
        m.set_f(b, Field::_disabled_percentage, 0.25);
        m.set_fv(b, Field::_position, {0.0, 0.0, 0.0});
        m.set_fv(b, Field::_direction, {0.0, 1.0, 0.0});
        m.set_fv(b, Field::_up, {0.0, 0.0, 1.0});
        m.set_fv(b, Field::_right, {1.0, 0.0, 0.0});
        m.set_f(b, Field::_charge_level, 5.0);
        m.set_f(b, Field::_max_charge, 5.0);
        m.set_f(b, Field::_min_firing_charge, 1.0);
        m.set_f(b, Field::_normal_discharge_rate, 1.0);
        m.set_i(b, Field::_power_setting, 1);
        m.set_i(b, Field::module_ok, kind == 6 ? 1 : 0);
        m.set_f(b, Field::launch_speed, 50.0);
        m.set_f(b, Field::lifetime, 8.0);
        m.set_i(b, Field::_num_ready, 1);
        m.set_i(b, Field::_max_ready, 1);
        m.set_f(b, Field::_last_fire_time, -1000.0);
        auto kids = m.get_ids(sys, Field::_children);
        kids.push_back(b);
        m.set_ids(sys, Field::_children, kids);
        return b;
    }
    // A Property with Groups mask `groups`.
    int64_t prop(int64_t groups) {
        const int64_t p = m.register_row(Kind::Property);
        m.set_i(p, Field::_groups, groups);
        return p;
    }

    std::string name(int64_t h) const {
        auto it = names.find(h);
        return it == names.end() ? std::to_string(h) : it->second;
    }
    std::string value(const K1Value& v) const {
        char buf[64];
        if (std::holds_alternative<std::monostate>(v)) return "None";
        if (auto* b = std::get_if<bool>(&v)) return *b ? "True" : "False";
        if (auto* i = std::get_if<int64_t>(&v)) return std::to_string(*i);
        if (auto* d = std::get_if<double>(&v)) {
            std::snprintf(buf, sizeof buf, "%.17g", *d);
            return buf;
        }
        if (std::holds_alternative<K1WalkOffset>(v)) return "walk_offset";
        if (auto* sw = std::get_if<SlotWrite>(&v)) {
            const double d = std::get<double>(sw->value);
            std::snprintf(buf, sizeof buf, "[%lld]=%.17g",
                          static_cast<long long>(sw->index), d);
            return buf;
        }
        std::string out = "[";
        for (int64_t h : std::get<std::vector<int64_t>>(v))
            out += (out.size() > 1 ? "," : "") + name(h);
        return out + "]";
    }
    // The ref fields read back as names.
    std::vector<std::string> writes(const K1Record& r) const {
        std::vector<std::string> out;
        for (const K1Write& w : r.writes) {
            std::string v = value(w.value);
            if (w.field == "_target" && std::holds_alternative<int64_t>(w.value))
                v = std::get<int64_t>(w.value) == -1
                        ? "None"
                        : name(std::get<int64_t>(w.value));
            out.push_back(name(w.handle) + "." + std::string(w.field) + "=" + v);
        }
        return out;
    }
    // The record's queue entries as "KIND a[@b]^at" (at: the writes
    // logged before it).
    std::vector<std::string> entries(const K1Record& r) const {
        std::vector<std::string> out;
        for (const K1Entry& e : r.entries) {
            std::string s = std::string(k1_effect_name(e.kind)) + " " + name(e.a);
            if (e.kind == K1Effect::WEAPON_FIRED)
                s += "@" + (e.b == -1 ? std::string("None") : name(e.b));
            if (e.kind == K1Effect::SPAWN && e.spawn)
                s += "@" + (e.spawn->target == -1 ? std::string("None")
                                                  : name(e.spawn->target));
            out.push_back(s + "^" + std::to_string(e.at));
        }
        return out;
    }
    // "KIND a" for a quick sequence check.
    std::string brief(const K1Record& r) const {
        std::string s = k1_kind_name(r.kind);
        switch (r.kind) {
            case K1Kind::DONE: break;
            case K1Kind::FIRE: s += " " + name(r.a) + "@" + (r.b == -1 ? "None" : name(r.b)); break;
            case K1Kind::ASK: s += " " + r.query; break;
            case K1Kind::RUN_PYTHON:
                s += " " + (r.a < 0 ? std::to_string(r.a) : name(r.a)) + " " +
                     std::to_string(r.b) + " " + std::to_string(r.c);
                break;
            default: s += " " + name(r.a); break;
        }
        return s;
    }
    // next(), answering WALK_START with no offset.
    K1Record step() {
        K1Record r = k.next();
        if (r.kind == K1Kind::WALK_START) k.set_offset(std::nullopt);
        return r;
    }
    // Every record up to and including DONE, as brief strings.
    std::vector<std::string> run_to_done() {
        std::vector<std::string> out;
        for (int guard = 0; guard < 200; ++guard) {
            K1Record r = step();
            out.push_back(brief(r));
            if (r.kind == K1Kind::DONE) break;
        }
        return out;
    }
};

// The record's queue entries as "KIND a[@b]" (World::entries without the
// position).
std::vector<std::string> fx(const World& w, const K1Record& r) {
    std::vector<std::string> out;
    for (const std::string& e : w.entries(r)) out.push_back(e.substr(0, e.find('^')));
    return out;
}

// A posed ShipClass target whose mount order opens with an entry the
// mirror cannot name, so it cannot tell which mount `bank`'s stored offset
// is: a tube's Fire at it is Python's (ASK fire, mount_unknown) -- the
// Python point the walk tests below pause at, now that a beam's edge and a
// FIRE_FAILED are no longer records (and an offset no mount claims is a
// plain point, fire control native only M5).
PartPose shift_pose();
int64_t posed_target(World& w, const std::string& name, double x, double y,
                     double z, int64_t bank) {
    const int64_t t = w.ship(name, x, y, z);
    w.m.set_i(t, Field::is_ship_class, 1);
    const int64_t mnt = w.m.register_row(Kind::Subsystem);
    w.m.set_ref(mnt, Field::_parent_ship, t);
    w.m.set_fv(mnt, Field::_position, {0.5, 0.0, 0.0});
    w.m.set_mount_order(t, {kRefUnrepresentable, mnt});
    w.m.set_i(t, Field::has_posed_parts, 1);
    w.m.set_part_poses(t, {shift_pose()});
    w.m.set_part_slot(mnt, 0, w.m.part_gen());
    w.m.set_fv(bank, Field::_target_offset, {0.0, 0.0, 0.75});
    return t;
}

bool has_write(const World& w, const K1Record& r, const std::string& s) {
    const std::vector<std::string> ws = w.writes(r);
    return std::find(ws.begin(), ws.end(), s) != ws.end();
}

// The writes of `r` on `who`, in order, as w.writes() spells them.
std::vector<std::string> writes_on(const World& w, const K1Record& r,
                                   const std::string& who) {
    std::vector<std::string> out;
    for (const std::string& s : w.writes(r))
        if (s.rfind(who + ".", 0) == 0) out.push_back(s);
    return out;
}

}  // namespace

TEST(K1, GateOrderStopsBeforeWalk) {
    // The pump's gates in order: offline / IsOn, held dead, undetectable,
    // _can_engage. Each stops with no write and no walk.
    for (int gate = 0; gate < 4; ++gate) {
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
        w.bank("b0", sys);
        if (gate == 0) w.m.set_i(sys, Field::_is_on, 0);
        if (gate == 1) w.m.set_i(t, Field::_dead, 1);
        if (gate == 2) w.cloak(t);
        int64_t held = t;
        if (gate == 3) {  // beyond 700 GU, inside the 2000 GU sensor range
            held = w.object("far", 0.0, 700.5, 0.0);
            w.m.set_ids(sys, Field::_target_list, {held});
            w.m.set_ref(sys, Field::_held_target, held);
        }
        // A broken lock can_detect would clear (no concealment here).
        set_latched(w.m, ship, held, true);
        w.k.begin_pump({ship}, kDt, 10.0, true, 0.0);
        const K1Record r = w.step();
        EXPECT_EQ(w.brief(r), "STOP_SYSTEM sys") << "gate " << gate;
        EXPECT_TRUE(r.writes.empty());
        // can_detect (memo, latch) runs only once the earlier gates passed;
        // the cloak gate answers before the latch is touched.
        const bool detect_ran = gate >= 2;
        EXPECT_EQ(w.m.sensor_state().memo.empty(), !detect_ran) << "gate " << gate;
        EXPECT_EQ(latched(w.m, ship, held), gate != 3) << "gate " << gate;
        EXPECT_EQ(w.brief(w.step()), "DONE");
        w.k.end();
    }
    // A torpedo system has no range gate: the same far target walks.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t far = w.object("far", 0.0, 1500.0, 0.0);
    const int64_t sys = w.system("tsys", ship, 4, {far});
    w.bank("tube", sys);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.brief(w.step()), "WALK_START tsys");
}

TEST(K1, TimerGateAndForceUpdate) {
    {   // Below the 0.33 s threshold: no attempt, the timer only accumulates.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
        const int64_t b0 = w.bank("b0", sys);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        const K1Record ws = w.step();
        EXPECT_EQ(w.brief(ws), "WALK_START sys");
        EXPECT_EQ(w.writes(ws), (std::vector<std::string>{"sys._target_list=[t]"}));
        const K1Record done = w.step();
        EXPECT_EQ(w.brief(done), "DONE");
        char dt[64];
        std::snprintf(dt, sizeof dt, "%.17g", 0.0 + kDt);
        EXPECT_EQ(w.writes(done),
                  (std::vector<std::string>{
                      "sys._group_fire_mode=0", std::string("b0._fire_timer=") + dt,
                      "b0._target=None", "sys._force_update=False"}));
        EXPECT_EQ(w.m.get_f(b0, Field::_fire_timer), 0.0 + kDt);
    }
    {   // Crossing the threshold: attempt, and the timer resets to 0.0 (a
        // tube: its FIRE is a record; a beam's edge is logged writes).
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 4, {t});
        const int64_t b0 = w.bank("b0", sys);
        w.m.set_f(b0, Field::_fire_timer, 0.30);
        w.k.begin_pump({ship}, 0.05, 10.0, false, 0.0);
        w.step();
        const K1Record f = w.step();
        EXPECT_EQ(w.brief(f), "FIRE b0@t");
        EXPECT_EQ(w.writes(f), (std::vector<std::string>{
                                   "sys._group_fire_mode=0",
                                   "b0._fire_timer=0.34999999999999998",
                                   "b0._fire_timer=0"}));
        EXPECT_EQ(f.decision.shape, K1Decision::Shape::Tube);
        EXPECT_EQ(f.decision.target_used, t);
        EXPECT_EQ(w.m.get_f(b0, Field::_fire_timer), 0.0);
    }
    {   // _force_update bypasses the threshold (timer := 0.33), even at dt 0.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 4, {t});
        w.bank("b0", sys);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_system(sys, 0.0, 10.0, false, 0.0);
        w.step();
        const K1Record f = w.step();
        EXPECT_EQ(w.brief(f), "FIRE b0@t");
        EXPECT_EQ(w.writes(f)[1], "b0._fire_timer=0.33000000000000002");
    }
    {   // A lit beam ignores the threshold (its sustain is logged writes,
        // round trips Task 2: no FIRE record).
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
        const int64_t b0 = w.bank("b0", sys);
        w.m.set_i(b0, Field::_firing, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        w.step();
        const K1Record f = w.step();
        EXPECT_EQ(w.brief(f), "DONE");
        const auto b0w = writes_on(w, f, "b0");
        ASSERT_EQ(b0w.size(), 5u);
        EXPECT_EQ(b0w[1], "b0._fire_timer=0");
        // The sustain's three stamps, in _fire_effect's order (WS:895-898):
        // the target, then the walk's offset OBJECT (the marker).
        EXPECT_EQ(b0w[2], "b0._firing=True");
        EXPECT_EQ(b0w[3], "b0._target=t");
        EXPECT_EQ(b0w[4], "b0._target_offset=walk_offset");
        EXPECT_EQ(w.m.get_ref(b0, Field::_target), t);
        EXPECT_EQ(w.k.counts().logged_beam_sustain, 1);
    }
    {   // A passed gate resets the timer even when CanFire then refuses.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
        const int64_t b0 = w.bank("b0", sys);
        w.m.set_f(b0, Field::_charge_level, 0.0);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        w.step();
        // The idle bank's StopFiring is logged (round trips Task 2).
        const K1Record done = w.step();
        EXPECT_EQ(w.brief(done), "DONE");
        EXPECT_EQ(w.writes(done), (std::vector<std::string>{
                                      "sys._group_fire_mode=0",
                                      "b0._fire_timer=0.33000000000000002",
                                      "b0._fire_timer=0", "b0._firing=False",
                                      "b0._beam_on_countdown=0",
                                      "b0._target=None",
                                      "sys._force_update=False"}));
    }
}

TEST(K1, DepletedClearIsLoggedEvenWhenRefused) {
    // Task 3 ruling: CanFire writes _depleted = False before the condition
    // product refuses; the log carries it.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    const int64_t b0 = w.bank("b0", sys);
    w.m.set_i(b0, Field::_depleted, 1);
    w.m.set_f(b0, Field::_condition, 10.0);  // 0.1 <= 0.25: refused
    w.bank("b1", sys);  // healthy, so the system is not offline
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    // b0's stop is logged (idle, round trips Task 2), the clear before the
    // stop; b1's edge is logged too, so everything rides DONE.
    const K1Record s = w.step();
    EXPECT_EQ(w.brief(s), "DONE");
    const auto b0w = writes_on(w, s, "b0");
    const auto at = std::find(b0w.begin(), b0w.end(), "b0._depleted=False");
    ASSERT_NE(at, b0w.end());
    ASSERT_NE(at + 1, b0w.end());
    EXPECT_EQ(*(at + 1), "b0._firing=False");
    EXPECT_EQ(w.m.get_i(b0, Field::_depleted), 0);
}

TEST(K1, RoundRobinFromLastIdx) {
    // Tubes: each FIRE is a record, so the rotation shows record by record.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});
    w.bank("b0", sys);
    w.bank("b1", sys);
    w.bank("b2", sys);
    w.m.set_i(sys, Field::_last_weapon_idx, 1);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.brief(w.step()), "WALK_START sys");
    EXPECT_EQ(w.brief(w.step()), "FIRE b2@t");
    const K1Record second = w.step();
    EXPECT_EQ(w.brief(second), "FIRE b0@t");
    // base_idx is captured once: the cursor writes do not move the rotation.
    EXPECT_EQ(w.writes(second)[0], "sys._last_weapon_idx=2");
    EXPECT_EQ(w.writes(second)[1], "sys._last_group_fired=0");
    EXPECT_EQ(w.brief(w.step()), "FIRE b1@t");
    const K1Record done = w.step();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_EQ(w.writes(done), (std::vector<std::string>{
                                  "sys._last_weapon_idx=1",
                                  "sys._last_group_fired=0",
                                  "sys._force_update=False"}));
}

TEST(K1, SingleFireReseedsTimers) {
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});  // tubes: FIRE records
    const int64_t b0 = w.bank("b0", sys);
    const int64_t b1 = w.bank("b1", sys);
    const int64_t b2 = w.bank("b2", sys);
    w.m.set_i(sys, Field::_single_fire, 1);
    w.m.set_f(b1, Field::_fire_timer, 0.1);
    w.m.set_f(b2, Field::_fire_timer, 0.2);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.brief(w.step()), "FIRE b0@t");
    const K1Record done = w.step();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_EQ(w.writes(done), (std::vector<std::string>{
                                  "sys._last_weapon_idx=0",
                                  "sys._last_group_fired=0",
                                  "b0._fire_timer=0", "b1._fire_timer=0",
                                  "b2._fire_timer=0",
                                  "sys._force_update=False"}));
    EXPECT_EQ(w.m.get_f(b0, Field::_fire_timer), 0.0);
    EXPECT_EQ(w.m.get_f(b1, Field::_fire_timer), 0.0);
    EXPECT_EQ(w.m.get_f(b2, Field::_fire_timer), 0.0);
    w.k.end();

    // _single_fire's lit path: only the lit beam is tried.
    World v;
    const int64_t vship = v.ship("ship");
    const int64_t vt = v.object("t", 0.0, 50.0, 0.0);
    const int64_t vsys = v.system("sys", vship, 1, {vt});
    v.bank("b0", vsys);
    const int64_t vb1 = v.bank("b1", vsys);
    v.m.set_i(vsys, Field::_single_fire, 1);
    v.m.set_i(vb1, Field::_firing, 1);
    v.k.begin_pump({vship}, kDt, 10.0, false, 0.0);
    v.step();
    // The lit beam sustains: logged writes, no FIRE record (Task 2).
    const K1Record vdone = v.step();
    EXPECT_EQ(v.brief(vdone), "DONE");
    EXPECT_EQ(v.writes(vdone), (std::vector<std::string>{
                                   "b1._fire_timer=0.016666666666666666",
                                   "b1._fire_timer=0", "b1._firing=True",
                                   "b1._target=t",
                                   "b1._target_offset=walk_offset",
                                   "sys._force_update=False"}));
}

TEST(K1, GroupWalkAdvancesOnDryGroup) {
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});  // tubes: FIRE records
    const int64_t b0 = w.bank("b0", sys);
    const int64_t b1 = w.bank("b1", sys);
    const int64_t sp = w.m.register_row(Kind::Property);
    w.m.set_id_lists(sp, Field::_firing_chains, {{1, 2}});
    w.m.set_ref(sys, Field::_property, sp);
    w.m.set_ref(b0, Field::_property, w.prop(1));  // group 1
    w.m.set_ref(b1, Field::_property, w.prop(2));  // group 2
    w.m.set_f(b1, Field::_fire_timer, 0.4);        // only b1 is due
    w.k.begin_pump({ship}, 0.0, 10.0, false, 0.0);
    w.step();
    const K1Record f = w.step();
    EXPECT_EQ(w.brief(f), "FIRE b1@t");
    EXPECT_EQ(w.writes(f), (std::vector<std::string>{
                               "sys._group_fire_mode=1", "b0._fire_timer=0",
                               "b0._target=None", "sys._group_fire_mode=2",
                               "b1._fire_timer=0.40000000000000002",
                               "b1._fire_timer=0"}));
    const K1Record done = w.step();
    EXPECT_EQ(w.writes(done), (std::vector<std::string>{
                                  "sys._last_weapon_idx=1",
                                  "sys._last_group_fired=2",
                                  "sys._force_update=False"}));
    w.k.end();

    // Every group dry: the walk wraps to its start and clears the resume.
    w.m.set_f(b1, Field::_fire_timer, 0.0);
    w.k.begin_pump({ship}, 0.0, 10.0, false, 0.0);
    w.step();
    const K1Record dry = w.step();
    EXPECT_EQ(w.brief(dry), "DONE");
    const auto ws = w.writes(dry);
    ASSERT_GE(ws.size(), 2u);
    EXPECT_EQ(ws[ws.size() - 2], "sys._last_group_fired=-1");
    EXPECT_EQ(ws.back(), "sys._force_update=False");
    // _last_group_fired (2, from the first walk) was the working group.
    EXPECT_EQ(ws[0], "sys._group_fire_mode=2");
}

TEST(K1, TubeRetryPostsFailedPerAttempt) {
    // Both targets are behind the tube: Fire(list[0]) fails, then the retry
    // re-tries list[0] and the other entry: 1 + 2 WEAPON_FIRE_FAILED
    // entries, no record between them.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t1 = w.object("t1", 0.0, -50.0, 0.0);
    const int64_t t2 = w.object("t2", 10.0, -50.0, 0.0);
    const int64_t sys = w.system("tsys", ship, 4, {t1, t2});
    const int64_t tube = w.bank("tube", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.brief(w.step()), "WALK_START tsys");
    const K1Record done = w.step();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_EQ(fx(w, done), (std::vector<std::string>(
                               3, "WEAPON_FIRE_FAILED tube")));
    w.k.end();

    // The retry reads the list LIVE after the first failure (an ASK fire's
    // Python, the one point a change can come from now): a t2 killed there
    // leaves one retry (posed t1 again, ASKed again).
    World v;
    const int64_t vship = v.ship("ship");
    const int64_t vtube_sys = v.system("tsys", vship, 4, {});
    const int64_t vtube = v.bank("tube", vtube_sys);
    const int64_t p1 = posed_target(v, "t1", 0.0, 50.0, 0.0, vtube);
    const int64_t v2 = v.object("t2", 10.0, -50.0, 0.0);
    v.m.set_ids(vtube_sys, Field::_target_list, {p1, v2});
    v.m.set_ref(vtube_sys, Field::_held_target, v2);
    v.m.set_i(vtube_sys, Field::_force_update, 1);
    v.k.begin_pump({vship}, kDt, 10.0, false, 0.0);
    v.step();
    EXPECT_EQ(v.brief(v.step()), "ASK fire");
    v.m.set_i(v2, Field::_dead, 1);
    v.k.answer(0);
    EXPECT_EQ(v.brief(v.step()), "ASK fire");  // the retry: t1 only
    v.k.answer(0);
    const K1Record vdone = v.step();
    EXPECT_EQ(v.brief(vdone), "DONE");
    EXPECT_TRUE(vdone.entries.empty());
    (void)tube;
}

TEST(K1, HeldTargetVsListHead) {
    // K1M 1.6: an AI that re-targets without StopFiring leaves [t1, t2] with
    // _held_target t2. The pump gates on t2, the walk fires at t1.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t1 = w.object("t1", 0.0, 900.0, 0.0);  // beyond 700
    const int64_t t2 = w.object("t2", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t1, t2});
    EXPECT_EQ(w.m.get_ref(sys, Field::_held_target), t2);
    w.bank("b0", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    // The beam's edge: logged, its ET_WEAPON_FIRED aimed at t1.
    const K1Record done = w.step();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_EQ(fx(w, done), (std::vector<std::string>{"FIRE_SOUND b0",
                                                     "WEAPON_FIRED b0@t1"}));
}

TEST(K1, DumbFireOnlyWithNoTargets) {
    {   // An empty list and a tube that cannot fire: stop (idle: logged,
        // round trips Task 2), then dumb fire -- whose Fire refuses too,
        // decided natively (launch deferral): no record.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t sys = w.system("tsys", ship, 4, {});
        const int64_t tube = w.bank("tube", sys);
        w.m.set_i(tube, Field::_num_ready, 0);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        EXPECT_EQ(w.run_to_done(),
                  (std::vector<std::string>{"WALK_START tsys", "DONE"}));
        EXPECT_EQ(w.k.counts().logged_idle_bank_stop, 1);
        EXPECT_EQ(w.k.counts().logged_dumb_refused, 1);
    }
    {   // An empty list and a ready tube: Fire(None) fires dumb itself.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t sys = w.system("tsys", ship, 4, {});
        w.bank("tube", sys);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        w.step();
        const K1Record f = w.step();
        EXPECT_EQ(w.brief(f), "FIRE tube@None");
        EXPECT_EQ(f.decision.shape, K1Decision::Shape::Tube);
        EXPECT_EQ(f.decision.target_used, -1);
    }
    {   // A failure with a target in the list never dumb-fires.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, -50.0, 0.0);
        const int64_t sys = w.system("tsys", ship, 4, {t});
        w.bank("tube", sys);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        EXPECT_EQ(w.brief(w.step()), "WALK_START tsys");
        const K1Record done = w.step();
        EXPECT_EQ(w.brief(done), "DONE");
        EXPECT_EQ(fx(w, done), (std::vector<std::string>(
                                   2, "WEAPON_FIRE_FAILED tube")));
    }
    {   // A phaser bank is not dumb-fire capable.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t sys = w.system("sys", ship, 1, {});
        const int64_t b0 = w.bank("b0", sys);
        w.m.set_f(b0, Field::_charge_level, 0.0);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_system(sys, 0.0, 10.0, false, 0.0);
        EXPECT_EQ(w.run_to_done(),
                  (std::vector<std::string>{"WALK_START sys", "DONE"}));
        EXPECT_EQ(w.k.counts().logged_idle_bank_stop, 1);
    }
}

TEST(K1, DeadShipEarlyReturnKeepsForceUpdate) {
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    w.bank("b0", sys);
    w.m.set_i(ship, Field::_dead, 1);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_system(sys, 0.0, 10.0, false, 0.0);
    const K1Record r = w.step();
    EXPECT_EQ(w.brief(r), "DONE");
    EXPECT_TRUE(r.writes.empty());
    EXPECT_EQ(w.m.get_i(sys, Field::_force_update), 1);
}

TEST(K1, PulseStampsBeforeArc) {
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("psys", ship, 2, {t});
    const int64_t c = w.bank("cannon", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    // The launch handed back (a cannon's launch is logged writes and a
    // SPAWN otherwise: K1PulseLaunch), so the FIRE record shows the stamps.
    w.m.set_global_i(Global::K1_LAUNCH_PATCHED, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.brief(w.k.next()), "WALK_START psys");
    w.k.set_offset(Vec3{1.0, 2.0, 3.0});
    const K1Record f = w.step();
    EXPECT_EQ(w.brief(f), "FIRE cannon@t");
    const auto ws = w.writes(f);
    ASSERT_GE(ws.size(), 2u);
    EXPECT_EQ(ws[ws.size() - 2], "cannon._target=t");
    EXPECT_EQ(ws.back(), "cannon._target_offset=walk_offset");
    EXPECT_EQ(f.decision.shape, K1Decision::Shape::Pulse);
    EXPECT_EQ(f.decision.target_used, t);
    EXPECT_EQ(w.m.get_fv(c, Field::_target_offset),
              (std::vector<double>{1.0, 2.0, 3.0}));
    w.k.abandon();

    // Out of the arc: the stamps persist, _target is cleared again after,
    // _target_offset is not.
    World v;
    const int64_t vship = v.ship("ship");
    const int64_t vt = v.object("t", 0.0, -50.0, 0.0);
    const int64_t vsys = v.system("psys", vship, 2, {vt});
    const int64_t vc = v.bank("cannon", vsys);
    v.m.set_i(vsys, Field::_force_update, 1);
    v.k.begin_pump({vship}, kDt, 10.0, false, 0.0);
    v.step();
    const K1Record done = v.step();
    EXPECT_EQ(v.brief(done), "DONE");
    EXPECT_EQ(v.writes(done), (std::vector<std::string>{
                                  "psys._group_fire_mode=0",
                                  "cannon._fire_timer=0.33000000000000002",
                                  "cannon._fire_timer=0",
                                  "cannon._target=t", "cannon._target_offset=None",
                                  "cannon._target=None",
                                  "cannon._target=t", "cannon._target_offset=None",
                                  "cannon._target=None",
                                  "psys._force_update=False"}));
    EXPECT_EQ(v.m.get_ref(vc, Field::_target), -1);
}

TEST(K1, PythonFallbackBeforeAnyWrite) {
    auto fallback = [](auto&& setup, const std::string& want) {
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
        const int64_t b0 = w.bank("b0", sys);
        w.m.set_i(sys, Field::_force_update, 1);
        setup(w, ship, t, sys, b0);
        const uint64_t before = w.m.epoch();
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        const K1Record r = w.step();
        EXPECT_EQ(w.brief(r), want);
        EXPECT_TRUE(r.writes.empty());
        EXPECT_EQ(w.m.epoch(), before) << want;  // nothing written
        EXPECT_EQ(w.k.counts().python_systems, 1);
    };
    fallback([](World& w, int64_t ship, int64_t, int64_t, int64_t) {
        w.m.set_i(ship, Field::has_posed_parts, 1);
    }, "RUN_PYTHON sys 0 0");
    fallback([](World& w, int64_t, int64_t t, int64_t sys, int64_t) {
        w.m.set_ids(sys, Field::_target_list, {t, kRefUnrepresentable});
    }, "RUN_PYTHON sys 0 0");
    fallback([](World& w, int64_t, int64_t t, int64_t, int64_t) {
        w.m.set_i(t, Field::has_real_is_dead, 0);
    }, "RUN_PYTHON sys 0 0");
    {   // An unresolved pulse module.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("psys", ship, 2, {t});
        const int64_t c = w.bank("cannon", sys);
        w.m.set_i(c, Field::module_ok, 0);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        const K1Record r = w.step();
        EXPECT_EQ(w.brief(r), "RUN_PYTHON psys 0 1");
        EXPECT_TRUE(r.writes.empty());
    }
    {   // A ship with no row: every getter but the tractor's (THE TRACTOR
        // WALK: K1's whole); a tractor walks natively, no record.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("tr", ship, 3, {t});
        w.bank("beam", sys);
        w.k.begin_pump({-1, ship}, kDt, 10.0, false, 0.0);
        EXPECT_EQ(w.run_to_done(),
                  (std::vector<std::string>{
                      "RUN_PYTHON -1 0 0", "RUN_PYTHON -1 0 1",
                      "RUN_PYTHON -1 0 3", "DONE"}));
    }
    {   // A system session falls back to update_weapons (no ship position).
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
        w.bank("b0", sys);
        w.m.set_i(ship, Field::has_posed_parts, 1);
        w.k.begin_system(sys, 0.0, 10.0, false, 0.0);
        EXPECT_EQ(w.run_to_done(),
                  (std::vector<std::string>{"RUN_PYTHON sys -1 -1", "DONE"}));
    }
}

TEST(K1, ReentrantSessionStack) {
    // Tubes: their FIREs are records, Python points a handler can act at.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});
    w.bank("b0", sys);
    w.bank("b1", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    const int64_t other = w.ship("other", 0.0, -100.0, 0.0);
    const int64_t osys = w.system("osys", other, 4, {t});
    w.bank("ob", osys);
    w.m.set_i(osys, Field::_fire_held, 0);

    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.brief(w.step()), "FIRE b0@t");
    // The FIRE effect's handler calls osys.StartFiring(t): a nested session.
    w.m.set_i(osys, Field::_fire_held, 1);
    w.m.set_i(osys, Field::_force_update, 1);
    w.k.begin_system(osys, 0.0, 10.0, false, 0.0);
    EXPECT_EQ(w.k.depth(), 2u);
    EXPECT_EQ(w.run_to_done(), (std::vector<std::string>{
                                   "WALK_START osys", "FIRE ob@t", "DONE"}));
    w.k.end();
    EXPECT_EQ(w.k.depth(), 1u);
    // The outer walk resumes where it stopped.
    const K1Record r = w.step();
    EXPECT_EQ(w.brief(r), "FIRE b1@t");
    EXPECT_EQ(w.writes(r)[0], "sys._last_weapon_idx=0");
    EXPECT_EQ(w.brief(w.step()), "DONE");
    w.k.end();
    EXPECT_EQ(w.k.depth(), 0u);
    EXPECT_THROW(w.k.next(), std::logic_error);
}

TEST(K1, ResumeReadsLiveMirror) {
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});
    w.bank("b0", sys);
    const int64_t b1 = w.bank("b1", sys);
    w.m.set_i(b1, Field::_firing, 1);
    const int64_t ship2 = w.ship("ship2", 5.0, 0.0, 0.0);  // pumped after
    const int64_t psys = w.system("psys", ship2, 2, {t});
    w.bank("cannon", psys);
    w.m.set_i(sys, Field::_force_update, 1);
    w.m.set_i(psys, Field::_force_update, 1);
    w.k.begin_pump({ship, ship2}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.brief(w.step()), "FIRE b0@t");
    // A handler empties b1 and releases both triggers. The running walk
    // keeps its locals (Python does not re-check _fire_held mid-walk) but
    // reads b1 live: its stop (logged writes, no record); the pump then
    // skips the released pulse system.
    w.m.set_i(b1, Field::_num_ready, 0);
    w.m.set_i(sys, Field::_fire_held, 0);
    w.m.set_i(psys, Field::_fire_held, 0);
    const K1Record done = w.step();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_TRUE(has_write(w, done, "b1._firing=False"))
        << ::testing::PrintToString(w.writes(done));
}

TEST(K1, MidWalkThrowBecomesAsk) {
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});  // tubes: FIRE records
    w.bank("b0", sys);
    const int64_t b1 = w.bank("b1", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.brief(w.step()), "FIRE b0@t");
    // A handler re-parents b1 under something the mirror cannot name: its
    // CanFire can no longer be answered natively, and no whole-system
    // fallback is possible after an effect.
    w.m.set_ref(b1, Field::_parent_subsystem, kRefUnrepresentable);
    const K1Record a = w.step();
    EXPECT_EQ(w.brief(a), "ASK can_fire");
    EXPECT_EQ(a.args, (std::vector<int64_t>{b1}));
    EXPECT_THROW(w.k.next(), std::logic_error);  // no answer yet
    w.k.answer(1);
    const K1Record f = w.step();
    EXPECT_EQ(w.brief(f), "ASK fire");
    EXPECT_EQ(f.args, (std::vector<int64_t>{sys, b1, t}));
    w.k.answer(1);
    const K1Record done = w.step();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_EQ(w.writes(done)[0], "sys._last_weapon_idx=1");
    EXPECT_EQ(w.k.counts().asks, 2);
    w.k.end();

    // An entry the mirror cannot name in the retry list: the whole retry
    // loop is asked. The list changes at the Python point before the
    // failure (an ASK fire on a posed target), the failed aim itself being
    // an entry now.
    World v;
    const int64_t vship = v.ship("ship");
    const int64_t vsys = v.system("tsys", vship, 4, {});
    const int64_t tube = v.bank("tube", vsys);
    const int64_t vt = posed_target(v, "t", 0.0, 50.0, 0.0, tube);
    v.m.set_ids(vsys, Field::_target_list, {vt});
    v.m.set_ref(vsys, Field::_held_target, vt);
    v.m.set_i(vsys, Field::_force_update, 1);
    v.k.begin_pump({vship}, kDt, 10.0, false, 0.0);
    v.step();
    EXPECT_EQ(v.brief(v.step()), "ASK fire");
    v.m.set_ids(vsys, Field::_target_list, {vt, kRefUnrepresentable});
    v.k.answer(0);
    const K1Record r = v.step();
    EXPECT_EQ(v.brief(r), "ASK retry");
    EXPECT_EQ(r.args, (std::vector<int64_t>{vsys, tube}));
    EXPECT_EQ(v.writes(r), (std::vector<std::string>{"tube._target=None"}));
    v.k.answer(0);
    const K1Record done2 = v.step();
    EXPECT_EQ(v.brief(done2), "DONE");
    EXPECT_EQ(v.writes(done2), (std::vector<std::string>{
                                   "tube._target=None",
                                   "tsys._force_update=False"}));
}

TEST(K1, CountsAndKinds) {
    EXPECT_STREQ(k1_kind_name(K1Kind::WALK_START), "WALK_START");
    EXPECT_STREQ(k1_kind_name(K1Kind::ASK), "ASK");
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});
    w.bank("b0", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.run_to_done().size(), 3u);  // WALK_START, FIRE, DONE
    EXPECT_EQ(w.k.counts().records, 3);
    w.k.end();
    // A system with no row: Python runs its update_weapons.
    w.k.begin_system(-1, 0.0, 0.0, false, 0.0);
    EXPECT_EQ(w.run_to_done(),
              (std::vector<std::string>{"RUN_PYTHON -1 -1 -1", "DONE"}));
    EXPECT_EQ(w.k.counts().python_systems, 1);
}

TEST(K1, EveryAskQuery) {
    {   // is_member: a bank's property became unnamed mid-walk.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 4, {t});  // tubes
        const int64_t b0 = w.bank("b0", sys);
        const int64_t b1 = w.bank("b1", sys);
        const int64_t sp = w.m.register_row(Kind::Property);
        w.m.set_id_lists(sp, Field::_firing_chains, {{1}});
        w.m.set_ref(sys, Field::_property, sp);
        w.m.set_ref(b0, Field::_property, w.prop(1));
        w.m.set_ref(b1, Field::_property, w.prop(1));
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        w.step();
        EXPECT_EQ(w.brief(w.step()), "FIRE b0@t");
        w.m.set_ref(b1, Field::_property, kRefUnrepresentable);
        const K1Record a = w.step();
        EXPECT_EQ(w.brief(a), "ASK is_member");
        EXPECT_EQ(a.args, (std::vector<int64_t>{b1, 1}));
        w.k.answer(1);
        // A tube's CanFire has no condition product (the unnamed property's
        // MaxCondition): answered natively.
        EXPECT_EQ(w.brief(w.step()), "FIRE b1@t");
    }
    for (int64_t answer : {1, 2}) {  // group_step: an unnamed child
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 4, {t});  // tubes
        const int64_t b0 = w.bank("b0", sys);
        w.bank("b1", sys);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        w.step();
        EXPECT_EQ(w.brief(w.step()), "FIRE b0@t");
        w.m.set_ids(sys, Field::_children, {b0, kRefUnrepresentable});
        const K1Record a = w.step();
        EXPECT_EQ(w.brief(a), "ASK group_step");
        EXPECT_EQ(a.args, (std::vector<int64_t>{sys, 1, 0, t}));
        w.k.answer(answer);
        const K1Record done = w.step();
        EXPECT_EQ(w.brief(done), "DONE");
        if (answer == 1)
            EXPECT_EQ(w.writes(done)[0], "sys._last_weapon_idx=1");
        else
            EXPECT_EQ(w.writes(done)[0], "sys._force_update=False");
    }
    {   // reseed: single fire with an unnamed child to re-seed.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 4, {t});  // tubes
        const int64_t b0 = w.bank("b0", sys);
        w.m.set_i(sys, Field::_single_fire, 1);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        w.step();
        EXPECT_EQ(w.brief(w.step()), "FIRE b0@t");
        w.m.set_ids(sys, Field::_children, {b0, kRefUnrepresentable});
        const K1Record a = w.step();
        EXPECT_EQ(w.brief(a), "ASK reseed");
        EXPECT_EQ(a.args, (std::vector<int64_t>{sys}));
        EXPECT_EQ(w.writes(a), (std::vector<std::string>{
                                   "sys._last_weapon_idx=0",
                                   "sys._last_group_fired=0"}));
        w.k.answer(std::nullopt);
        const K1Record done = w.step();
        EXPECT_EQ(w.writes(done),
                  (std::vector<std::string>{"sys._force_update=False"}));
    }
    {   // is_dead, then fire: a retry entry lost its real IsDead mid-loop
        // (at the retry's ASK fire of the posed t1, the one Python point
        // inside the loop).
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t sys = w.system("tsys", ship, 4, {});
        const int64_t tube = w.bank("tube", sys);
        const int64_t t1 = posed_target(w, "t1", 0.0, 50.0, 0.0, tube);
        const int64_t t2 = w.object("t2", 10.0, -50.0, 0.0);
        w.m.set_ids(sys, Field::_target_list, {t1, t2});
        w.m.set_ref(sys, Field::_held_target, t2);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        w.step();
        EXPECT_EQ(w.brief(w.step()), "ASK fire");  // Fire(t1)
        w.k.answer(0);
        EXPECT_EQ(w.brief(w.step()), "ASK fire");  // retry t1
        w.m.set_i(t2, Field::has_real_is_dead, 0);
        w.k.answer(0);
        const K1Record d = w.step();
        EXPECT_EQ(w.brief(d), "ASK is_dead");
        EXPECT_EQ(d.args, (std::vector<int64_t>{t2}));
        w.k.answer(0);
        const K1Record f = w.step();
        EXPECT_EQ(w.brief(f), "ASK fire");
        EXPECT_EQ(f.args, (std::vector<int64_t>{sys, tube, t2}));
        w.k.answer(0);
        EXPECT_EQ(w.brief(w.step()), "DONE");
        EXPECT_EQ(w.k.counts().asks, 4);
    }
}

TEST(K1, MemoOnlyWhenAsked) {
    // use_memo is step_memo.active(): the mount and can_detect memos are read
    // and filled only then (StartFiring runs outside the step: no memo).
    for (bool use_memo : {false, true}) {
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
        w.bank("b0", sys);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, use_memo, 0.0);
        w.run_to_done();
        EXPECT_EQ(w.m.sensor_state().mounts.empty(), !use_memo);
        EXPECT_EQ(w.m.sensor_state().memo.empty(), !use_memo);
    }
}

TEST(K1, RangeGateNeverThrowsAfterCanDetect) {
    // The phaser range gate reads both containing sets. An unnamed one must
    // send the system to Python BEFORE can_detect writes its memo / latch,
    // or Python would run can_detect a second time.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    w.bank("b0", sys);
    w.m.set_ref(ship, Field::_containing_set, kRefUnrepresentable);
    w.k.begin_pump({ship}, kDt, 10.0, true, 0.0);
    const K1Record r = w.step();
    EXPECT_EQ(w.brief(r), "RUN_PYTHON sys 0 0");
    EXPECT_TRUE(w.m.sensor_state().memo.empty());
}

TEST(K1, UnwindLeavesMirrorEqualToPython) {
    // A throw mid-walk after a write: the pending writes never reached
    // Python, so they are undone, and the session is as it was.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t sys = w.system("sys", ship, 4, {});
    const int64_t b0 = w.bank("b0", sys);
    const int64_t t = posed_target(w, "t", 0.0, 50.0, 0.0, b0);
    w.m.set_ids(sys, Field::_target_list, {t});
    w.m.set_ref(sys, Field::_held_target, t);
    w.m.set_ref(b0, Field::_target, t);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.brief(w.step()), "ASK fire");
    // The Fire's Python leaves the walked system's row gone.
    w.m.unregister_row(sys);
    w.k.answer(0);
    // Resuming writes b0._target = None, then cannot read the system.
    EXPECT_THROW(w.k.next(), std::logic_error);
    EXPECT_EQ(w.m.get_ref(b0, Field::_target), t);  // undone
    EXPECT_THROW(w.k.next(), std::logic_error);       // same state, same throw
    EXPECT_EQ(w.m.get_ref(b0, Field::_target), t);
    w.k.abandon();
    EXPECT_EQ(w.k.depth(), 0u);
}

TEST(K1, ThrowKeepsThePendingAnswer) {
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});  // tubes: FIRE records
    const int64_t b0 = w.bank("b0", sys);
    const int64_t b1 = w.bank("b1", sys);
    const int64_t sp = w.m.register_row(Kind::Property);
    w.m.set_id_lists(sp, Field::_firing_chains, {{1}});
    w.m.set_ref(sys, Field::_property, sp);
    w.m.set_ref(b0, Field::_property, w.prop(1));
    w.m.set_ref(b1, Field::_property, w.prop(1));
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.brief(w.step()), "FIRE b0@t");
    w.m.set_ref(b1, Field::_property, kRefUnrepresentable);
    EXPECT_EQ(w.brief(w.step()), "ASK is_member");
    w.k.answer(0);
    EXPECT_TRUE(w.k.answer_pending());
    w.m.unregister_row(sys);
    EXPECT_THROW(w.k.next(), std::logic_error);
    EXPECT_TRUE(w.k.answer_pending());  // not consumed by the failed call
    w.k.abandon();
}

TEST(K1, GroupReReadsWeaponCount) {
    // n = self.GetNumWeapons() is re-read for each group: Python that drops
    // a child during group 1 (b2's Fire, asked: its stored offset names no
    // mount on the posed target) changes group 2's rotation.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t sys = w.system("sys", ship, 4, {});
    const int64_t b0 = w.bank("b0", sys);
    const int64_t b1 = w.bank("b1", sys);
    const int64_t b2 = w.bank("b2", sys);
    const int64_t t = posed_target(w, "t", 0.0, 50.0, 0.0, b2);
    w.m.set_ids(sys, Field::_target_list, {t});
    w.m.set_ref(sys, Field::_held_target, t);
    const int64_t sp = w.m.register_row(Kind::Property);
    w.m.set_id_lists(sp, Field::_firing_chains, {{1, 2}});
    w.m.set_ref(sys, Field::_property, sp);
    w.m.set_ref(b0, Field::_property, w.prop(2));
    w.m.set_ref(b1, Field::_property, w.prop(2));
    w.m.set_ref(b2, Field::_property, w.prop(1));
    w.m.set_i(sys, Field::_last_weapon_idx, 2);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.brief(w.step()), "ASK fire");
    w.m.set_ids(sys, Field::_children, {b0, b1});  // the Python drops b2
    w.k.answer(0);
    EXPECT_EQ(w.brief(w.step()), "ASK fire");  // b2's retry: group 1 dry
    w.k.answer(0);
    // n = 2, base_idx 2: idx 1 then 0. (n kept at 3 would give 0, 1, None.)
    EXPECT_EQ(w.brief(w.step()), "FIRE b1@t");
    EXPECT_EQ(w.brief(w.step()), "FIRE b0@t");
    EXPECT_EQ(w.brief(w.step()), "DONE");
}

TEST(K1, RetryWalksItsSnapshot) {
    // for entry in list(self._target_list): the list is copied when the
    // retry starts; a later change (at the retry's ASK fire, its one Python
    // point) does not alter the loop.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t sys = w.system("tsys", ship, 4, {});
    const int64_t tube = w.bank("tube", sys);
    const int64_t t1 = posed_target(w, "t1", 0.0, 50.0, 0.0, tube);
    const int64_t t2 = w.object("t2", 10.0, -50.0, 0.0);
    w.m.set_ids(sys, Field::_target_list, {t1, t2});
    w.m.set_ref(sys, Field::_held_target, t2);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.brief(w.step()), "ASK fire");  // Fire(t1)
    w.k.answer(0);
    EXPECT_EQ(w.brief(w.step()), "ASK fire");  // retry t1
    w.m.set_ids(sys, Field::_target_list, {t1});  // the Python drops t2
    w.k.answer(0);
    const K1Record done = w.step();             // retry t2 (snapshot)
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_EQ(fx(w, done),
              (std::vector<std::string>{"WEAPON_FIRE_FAILED tube"}));
}

// ── Fallback reasons (Task 5 fix round: every RUN_PYTHON is counted by why,
// pump and StartFiring system sessions apart) ──────────────────────────────

namespace {
int64_t why_of(const K1Kernel::Counts& c, K1Why w, bool system = false) {
    return (system ? c.system_why : c.pump_why)[static_cast<size_t>(w)];
}
int64_t why_total(const K1Kernel::Counts& c) {
    int64_t n = 0;
    for (size_t i = 0; i < static_cast<size_t>(K1Why::kCount); ++i)
        n += c.pump_why[i] + c.system_why[i];
    return n;
}
}  // namespace


TEST(K1, BankRowGoneAfterAFireAskAsksPython) {
    // The Python of an asked Fire drops the tube's row (a value it cannot
    // encode) and the Fire fails. Python carries on with the object:
    // `weapon._target = None` is logged for Python with no mirror write
    // (the row is gone), and the retry's Fire is ASKed.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t sys = w.system("sys", ship, 4, {});
    const int64_t b0 = w.bank("b0", sys);
    const int64_t t = posed_target(w, "t", 0.0, 50.0, 0.0, b0);
    w.m.set_ids(sys, Field::_target_list, {t});
    w.m.set_ref(sys, Field::_held_target, t);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.brief(w.step()), "WALK_START sys");
    EXPECT_EQ(w.brief(w.step()), "ASK fire");
    w.m.unregister_row(b0);
    w.k.answer(0);
    K1Record r = w.step();
    EXPECT_EQ(w.brief(r), "ASK fire");
    EXPECT_TRUE(has_write(w, r, "b0._target=None"))
        << ::testing::PrintToString(w.writes(r));
    w.k.answer(0);
    r = w.step();
    EXPECT_EQ(w.brief(r), "DONE");
    EXPECT_TRUE(has_write(w, r, "b0._target=None"))
        << ::testing::PrintToString(w.writes(r));
    w.k.end();
}

TEST(K1, BankRowGoneBeforeTheDumbCheckAsksPython) {
    // An asked Fire's Python drops the tube's row and empties the list; the
    // Fire fails, so update_weapons asks weapon.IsDumbFire() -- of Python,
    // the row being gone -- and dumb-fires on its answer.
    for (const int64_t answer : {1, 0}) {
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t sys = w.system("sys", ship, 4, {});
        const int64_t b0 = w.bank("b0", sys);
        const int64_t t = posed_target(w, "t", 0.0, 50.0, 0.0, b0);
        w.m.set_ids(sys, Field::_target_list, {t});
        w.m.set_ref(sys, Field::_held_target, t);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        EXPECT_EQ(w.brief(w.step()), "WALK_START sys");
        EXPECT_EQ(w.brief(w.step()), "ASK fire");
        w.m.unregister_row(b0);
        w.m.set_ids(sys, Field::_target_list, {});
        w.k.answer(0);
        K1Record r = w.step();
        EXPECT_EQ(w.brief(r), "ASK is_dumb");
        EXPECT_EQ(r.args, (std::vector<int64_t>{b0}));
        EXPECT_TRUE(has_write(w, r, "b0._target=None"))
            << ::testing::PrintToString(w.writes(r));
        w.k.answer(answer);
        // Not dumb-capable (0): no FireDumb.
        if (answer) EXPECT_EQ(w.brief(w.step()), "FIRE_DUMB b0");
        EXPECT_EQ(w.brief(w.step()), "DONE");
        w.k.end();
    }
}

TEST(K1, WalkedSystemRowGoneMidWalkThrows) {
    // The protocol invariant (k1_fire_control.h): the walked SYSTEM's row
    // must outlive its walk. Gone after Python ran (an asked Fire), next()
    // throws and leaves the session as it was, for run_k1 to abandon.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t sys = w.system("sys", ship, 4, {});
    const int64_t b0 = w.bank("b0", sys);
    const int64_t t = posed_target(w, "t", 0.0, 50.0, 0.0, b0);
    w.m.set_ids(sys, Field::_target_list, {t});
    w.m.set_ref(sys, Field::_held_target, t);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.brief(w.step()), "WALK_START sys");
    EXPECT_EQ(w.brief(w.step()), "ASK fire");
    w.m.unregister_row(sys);
    w.k.answer(0);
    EXPECT_ANY_THROW(w.k.next());
    EXPECT_EQ(w.k.depth(), 1u);
    w.k.abandon();
    EXPECT_EQ(w.k.depth(), 0u);
}

TEST(K1, NoneAmmoSlotWalksNatively) {
    // A torpedo system whose slot holds None (-1) is no fallback: the tube
    // gate reads it as "no ammo configured", as Python does.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});
    w.bank("b0", sys);
    w.m.set_ids(sys, Field::_ammo_by_slot, {0, -1});
    w.m.set_i(sys, Field::_force_update, 1);  // past the fire timer
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const std::vector<std::string> recs = w.run_to_done();
    EXPECT_EQ(recs.front(), "WALK_START sys");
    EXPECT_NE(std::find(recs.begin(), recs.end(), "FIRE b0@t"), recs.end())
        << ::testing::PrintToString(recs);
    EXPECT_EQ(w.k.counts().python_systems, 0);
}

TEST(K1, FallbackReasonsAreCounted) {
    EXPECT_STREQ(k1_why_name(K1Why::PosedShip), "posed_ship");
    EXPECT_STREQ(k1_why_name(K1Why::PosedTarget), "posed_target");
    EXPECT_STREQ(k1_why_name(K1Why::PartStale), "part_stale");
    EXPECT_STREQ(k1_why_name(K1Why::MountUnknown), "mount_unknown");
    EXPECT_STREQ(k1_why_name(K1Why::StubOrUnplaced), "stub_or_unplaced");
    EXPECT_STREQ(k1_why_name(K1Why::InstancePatch), "instance_patch");
    // One pump over one phaser (or `kind`) system, set up to fall back.
    auto pump = [](int64_t kind, auto&& setup, K1Why want) {
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, kind, {t});
        const int64_t b0 = w.bank("b0", sys);
        setup(w, ship, t, sys, b0);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        const K1Record r = w.step();
        EXPECT_EQ(r.kind, K1Kind::RUN_PYTHON) << k1_why_name(want);
        EXPECT_EQ(why_of(w.k.counts(), want), 1) << k1_why_name(want);
        EXPECT_EQ(why_total(w.k.counts()), 1) << k1_why_name(want);
        EXPECT_EQ(w.k.counts().python_systems, 1);
    };
    using I = int64_t;
    // A posed ship whose bank's part slot was never resolved (stamp 0): the
    // mount is Python's. (Was K1Why::PosedShip before posed parts went
    // native; a posed TARGET is no pre-scan fallback any more -- see
    // PosedTargetOffsetAimByReason.)
    pump(1, [](World& w, I ship, I, I, I) {
        w.m.set_i(ship, Field::has_posed_parts, 1);
    }, K1Why::PartStale);
    pump(1, [](World& w, I, I t, I, I) {
        w.m.set_i(t, Field::has_real_is_dead, 0);
    }, K1Why::StubOrUnplaced);
    pump(1, [](World& w, I, I t, I sys, I) {
        w.m.set_ids(sys, Field::_target_list, {t, kRefUnrepresentable});
    }, K1Why::StaleRow);
    pump(2, [](World& w, I, I, I, I c) {
        w.m.set_i(c, Field::module_ok, 0);
    }, K1Why::PulseModule);
    pump(2, [](World& w, I, I, I sys, I) {
        w.m.set_ids(sys, Field::_target_list, {});
    }, K1Why::PulseShipTarget);
    pump(4, [](World& w, I, I, I sys, I) {
        const int64_t gone = w.m.register_row(Kind::Ammo);
        w.m.set_ids(sys, Field::_ammo_by_slot, {0, gone});
        w.m.unregister_row(gone);
    }, K1Why::AmmoRow);
    pump(1, [](World& w, I, I, I sys, I) {
        w.m.set_i(sys, Field::k1_overridden, 1);
    }, K1Why::Overridden);
    pump(1, [](World& w, I, I, I, I b0) {
        w.m.set_i(b0, Field::k1_overridden, 1);    // one overridden bank
    }, K1Why::Overridden);

    {   // A ship with no row: one per getter but the tractor's.
        World w;
        w.k.begin_pump({-1}, kDt, 10.0, false, 0.0);
        w.run_to_done();
        EXPECT_EQ(why_of(w.k.counts(), K1Why::UnslottedShip), 3);
        EXPECT_EQ(w.k.counts().python_systems, 3);
    }
    {   // A StartFiring system session counts apart from the pump.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
        w.bank("b0", sys);
        w.m.set_i(ship, Field::has_posed_parts, 1);
        w.k.begin_system(sys, 0.0, 10.0, false, 0.0);
        w.run_to_done();
        EXPECT_EQ(why_of(w.k.counts(), K1Why::PartStale, true), 1);
        EXPECT_EQ(why_of(w.k.counts(), K1Why::PartStale), 0);
        EXPECT_EQ(why_of(w.k.counts(), K1Why::PosedShip, true), 0);
        w.k.reset_counts();
        EXPECT_EQ(why_total(w.k.counts()), 0);
    }
}

TEST(K1, SkipWalkHandsTheWalkToPython) {
    // Python found an instance-patched Fire at WALK_START and ran the
    // system's update_weapons itself: the kernel moves on with no write.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    w.bank("b0", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    EXPECT_THROW(w.k.skip_walk(), std::logic_error);   // no session
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record ws = w.k.next();
    ASSERT_EQ(w.brief(ws), "WALK_START sys");
    w.k.skip_walk();
    EXPECT_THROW(w.k.skip_walk(), std::logic_error);   // not awaiting
    const K1Record r = w.k.next();
    EXPECT_EQ(w.brief(r), "DONE");
    EXPECT_TRUE(r.writes.empty());
    EXPECT_EQ(why_of(w.k.counts(), K1Why::InstancePatch), 1);
    EXPECT_EQ(w.k.counts().python_systems, 1);
    w.k.end();
}

// ── Posed parts (native-combat posed parts, Task 4) ─────────────────────────

namespace {
// A pose that moves a point by +x (0.25): not identity.
PartPose shift_pose() {
    PartPose p;
    p.t[0] = 0.25;
    p.identity = false;
    return p;
}
}  // namespace

TEST(K1, PosedShipWalksNatively) {
    // The firing ship is posed and its bank's slot is current: the walk is
    // the kernel's (its mount through the pose). A generation bump makes the
    // slot stale: the system is Python's, part_stale -- never posed_ship.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    const int64_t b0 = w.bank("b0", sys);
    w.m.set_i(ship, Field::has_posed_parts, 1);
    w.m.set_part_poses(ship, {shift_pose()});
    w.m.set_part_slot(b0, 0, w.m.part_gen());
    w.m.set_i(sys, Field::_force_update, 1);  // past the fire timer
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    std::vector<std::string> recs = w.run_to_done();
    // The beam lit (its edge: logged writes and entries, no record).
    EXPECT_EQ(w.k.counts().logged_beam_edge, 1)
        << ::testing::PrintToString(recs);
    w.k.end();
    EXPECT_EQ(w.k.counts().python_systems, 0);
    EXPECT_EQ(w.k.counts().posed_walks, 1);

    w.m.set_part_gen(w.m.part_gen() + 1);
    w.k.reset_counts();
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.brief(w.step()), "RUN_PYTHON sys 0 0");
    w.run_to_done();
    w.k.end();
    EXPECT_EQ(why_of(w.k.counts(), K1Why::PartStale), 1);
    EXPECT_EQ(why_of(w.k.counts(), K1Why::PosedShip), 0);
    EXPECT_EQ(w.k.counts().posed_walks, 0);
}

TEST(K1, PosedTargetOffsetAimByReason) {
    // A tube aims at a posed target's offset (`_RESOLVE`): the first mount
    // at the offset, its slot current -> FIRE, decided natively; so is an
    // offset no mount claims, or one within 1e-5 of a mount but not on it
    // (a plain body point: fire control native only, M5, M8.5). The mirror
    // cannot tell the mount (not a ShipClass) or the slot is stale -> the
    // Fire is Python's (ASK fire), counted by why. The system is never
    // handed back whole (no posed_target).
    enum Case { kNative, kUnknown, kNoMountHere, kStale, kOffMount };
    for (int c = kNative; c <= kOffMount; ++c) {
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.ship("t", 0.0, 50.0, 0.0);
        w.m.set_i(t, Field::is_ship_class, c == kUnknown ? 0 : 1);
        const int64_t mnt = w.m.register_row(Kind::Subsystem);
        w.m.set_ref(mnt, Field::_parent_ship, t);
        w.m.set_fv(mnt, Field::_position, {0.5, 0.0, 0.0});
        w.m.set_mount_order(t, {mnt});
        w.m.set_i(t, Field::has_posed_parts, 1);
        w.m.set_part_poses(t, {shift_pose()});
        w.m.set_part_slot(mnt, 0, w.m.part_gen());
        const int64_t sys = w.system("sys", ship, 4, {t});
        const int64_t b0 = w.bank("b0", sys);
        if (c == kNoMountHere)
            w.m.set_fv(b0, Field::_target_offset, {0.0, 0.0, 0.75});
        else if (c == kOffMount)  // the mount's within 1e-5, not its point
            w.m.set_fv(b0, Field::_target_offset, {0.5 + 0.5e-5, 0.0, 0.0});
        else
            w.m.set_fv(b0, Field::_target_offset, {0.5, 0.0, 0.0});
        if (c == kStale) w.m.set_part_gen(w.m.part_gen() + 1);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        EXPECT_EQ(w.brief(w.step()), "WALK_START sys") << c;
        const K1Record r = w.step();
        const auto& n = w.k.counts();
        auto ask_why = [&](K1Why why) {
            return n.fire_ask_why[static_cast<size_t>(why)];
        };
        if (c == kNative || c == kNoMountHere || c == kOffMount) {
            EXPECT_EQ(w.brief(r), "FIRE b0@t") << c;
            EXPECT_EQ(n.posed_target_aims, 1) << c;
        } else {
            EXPECT_EQ(w.brief(r), "ASK fire") << c;
            const K1Why want = c == kUnknown ? K1Why::MountUnknown
                                             : K1Why::PartStale;
            EXPECT_EQ(ask_why(want), 1) << c;
            EXPECT_EQ(n.posed_target_aims, 0) << c;
        }
        EXPECT_EQ(n.python_systems, 0) << c;
        EXPECT_EQ(why_of(n, K1Why::PosedTarget), 0) << c;
        w.k.abandon();
    }
}


// ── Round trips, Task 1: the walk starts natively ───────────────────────────

TEST(K1Native, LiveHeldOffsetPredicate) {
    // _live_held_offset: a ShipClass ship with is_using_target_offset()
    // (the flag AND a manual offset) -> the manual offset; anything else ->
    // the held offset when it is a TGPoint3, else none.
    World w(false);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("tsys", ship, 4, {t});
    using O = std::optional<Vec3>;
    EXPECT_EQ(k1_live_held_offset(w.m, sys, ship), O{});
    w.m.set_fv(sys, Field::_held_offset, {1.0, 2.0, 3.0});
    const O held = Vec3{1.0, 2.0, 3.0}, manual = Vec3{4.0, 5.0, 6.0};
    EXPECT_EQ(k1_live_held_offset(w.m, sys, ship), held);
    w.m.set_i(ship, Field::is_ship_class, 1);
    w.m.set_i(ship, Field::_use_target_offset, 1);   // no manual offset
    EXPECT_EQ(k1_live_held_offset(w.m, sys, ship), held);
    w.m.set_fv(ship, Field::_manual_target_offset, {4.0, 5.0, 6.0});
    EXPECT_EQ(k1_live_held_offset(w.m, sys, ship), manual);
    w.m.set_fv(sys, Field::_held_offset, {});        // held unset: manual
    EXPECT_EQ(k1_live_held_offset(w.m, sys, ship), manual);
    w.m.set_fv(sys, Field::_held_offset, {1.0, 2.0, 3.0});
    w.m.set_i(ship, Field::_use_target_offset, 0);   // flag off: held
    EXPECT_EQ(k1_live_held_offset(w.m, sys, ship), held);
    w.m.set_i(ship, Field::_use_target_offset, 1);
    w.m.set_i(ship, Field::is_ship_class, 0);        // not a ShipClass: held
    EXPECT_EQ(k1_live_held_offset(w.m, sys, ship), held);
    EXPECT_EQ(k1_live_held_offset(w.m, sys, -1), held);  // no ship
    w.m.set_fv(sys, Field::_held_offset, {});
    EXPECT_EQ(k1_live_held_offset(w.m, sys, -1), O{});
}

TEST(K1Native, RecordlessWalkReturnsOnlyDone) {
    // Below the timer threshold the walk returns nothing: its writes (the
    // pruned list first, a NEW list every walk) ride DONE, untagged.
    World w(false);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    w.bank("b0", sys);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record done = w.k.next();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_FALSE(done.walk_first);
    char dt[64];
    std::snprintf(dt, sizeof dt, "%.17g", 0.0 + kDt);
    EXPECT_EQ(w.writes(done),
              (std::vector<std::string>{
                  "sys._target_list=[t]", "sys._group_fire_mode=0",
                  std::string("b0._fire_timer=") + dt, "b0._target=None",
                  "sys._force_update=False"}));
    EXPECT_EQ(w.k.counts().logged_walk_start, 1);
    EXPECT_EQ(w.k.counts().records, 1);
    w.k.end();
    // The list write is made on every walk, even of an unchanged list.
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.writes(w.k.next())[0], "sys._target_list=[t]");
    EXPECT_EQ(w.k.counts().logged_walk_start, 2);
}

TEST(K1Native, FirstRecordOfEachWalkIsTagged) {
    // Two walks in one pump: the phasers' returns nothing, the tubes' two
    // FIREs. The tubes' first FIRE is tagged (walk 2, tsys) and carries the
    // phaser walk's writes before its own; the second FIRE is not tagged.
    World w(false);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t psys = w.system("sys", ship, 1, {t});
    w.bank("b0", psys);
    const int64_t tsys = w.system("tsys", ship, 4, {t});
    w.bank("tube0", tsys);
    w.bank("tube1", tsys);
    w.m.set_i(tsys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record first = w.k.next();
    EXPECT_EQ(w.brief(first), "FIRE tube0@t");
    EXPECT_TRUE(first.walk_first);
    EXPECT_EQ(first.walk, 2);
    EXPECT_EQ(first.walk_system, tsys);
    const auto ws = w.writes(first);
    ASSERT_GE(ws.size(), 2u);
    EXPECT_EQ(ws.front(), "sys._target_list=[t]");
    EXPECT_NE(std::find(ws.begin(), ws.end(), "tsys._target_list=[t]"),
              ws.end());
    const K1Record second = w.k.next();
    EXPECT_EQ(w.brief(second), "FIRE tube1@t");
    EXPECT_FALSE(second.walk_first);
    EXPECT_EQ(second.walk, -1);
    EXPECT_EQ(second.walk_system, -1);
    const K1Record done = w.k.next();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_FALSE(done.walk_first);
    EXPECT_EQ(w.k.counts().logged_walk_start, 2);
}

TEST(K1Native, WalkOffsetMarkerNamesItsWalk) {
    // A cannon's stamp of the walk's offset names the walk and its system,
    // and the mirror holds the value the kernel computed (the held offset).
    World w(false);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("psys", ship, 2, {t});
    const int64_t c = w.bank("cannon", sys);
    w.m.set_fv(sys, Field::_held_offset, {1.0, 2.0, 3.0});
    w.m.set_i(sys, Field::_force_update, 1);
    // The launch handed back, so the stamp is the FIRE record's last write.
    w.m.set_global_i(Global::K1_LAUNCH_PATCHED, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record f = w.k.next();
    EXPECT_EQ(w.brief(f), "FIRE cannon@t");
    EXPECT_TRUE(f.walk_first);
    ASSERT_FALSE(f.writes.empty());
    const K1Write& stamp = f.writes.back();
    EXPECT_EQ(stamp.field, "_target_offset");
    ASSERT_TRUE(std::holds_alternative<K1WalkOffset>(stamp.value));
    EXPECT_EQ(std::get<K1WalkOffset>(stamp.value), (K1WalkOffset{1, sys}));
    EXPECT_EQ(w.m.get_fv(c, Field::_target_offset),
              (std::vector<double>{1.0, 2.0, 3.0}));
    w.k.abandon();

    // Manual Aim on the firing ShipClass: the manual offset is stamped.
    World v(false);
    const int64_t vship = v.ship("ship");
    v.m.set_i(vship, Field::is_ship_class, 1);
    v.m.set_i(vship, Field::_use_target_offset, 1);
    v.m.set_fv(vship, Field::_manual_target_offset, {7.0, 8.0, 9.0});
    const int64_t vt = v.object("t", 0.0, 50.0, 0.0);
    const int64_t vsys = v.system("psys", vship, 2, {vt});
    const int64_t vc = v.bank("cannon", vsys);
    v.m.set_fv(vsys, Field::_held_offset, {1.0, 2.0, 3.0});
    v.m.set_i(vsys, Field::_force_update, 1);
    v.m.set_global_i(Global::K1_LAUNCH_PATCHED, 1);
    v.k.begin_pump({vship}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(v.brief(v.k.next()), "FIRE cannon@t");
    EXPECT_EQ(v.m.get_fv(vc, Field::_target_offset),
              (std::vector<double>{7.0, 8.0, 9.0}));
}

TEST(K1Native, WalkCheckHandsTheWalkStartBack) {
    // The walk check sees (system, ship) at every walk start; true -> the
    // old WALK_START (tagged: it is the walk's first record), answered by
    // set_offset or skip_walk; false -> the walk starts natively.
    World w(false);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t psys = w.system("sys", ship, 1, {t});
    w.bank("b0", psys);
    const int64_t tsys = w.system("tsys", ship, 4, {t});
    w.bank("tube", tsys);
    std::vector<std::pair<int64_t, int64_t>> seen;
    w.k.set_walk_check([&](int64_t s, int64_t sh) {
        seen.emplace_back(s, sh);
        return s == tsys;
    });
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record ws = w.k.next();
    EXPECT_EQ(w.brief(ws), "WALK_START tsys");
    EXPECT_TRUE(ws.walk_first);
    EXPECT_EQ(ws.walk, 2);
    EXPECT_EQ(ws.walk_system, tsys);
    EXPECT_EQ(seen, (std::vector<std::pair<int64_t, int64_t>>{
                        {psys, ship}, {tsys, ship}}));
    EXPECT_THROW(w.k.next(), std::logic_error);   // awaiting the offset
    w.k.skip_walk();
    EXPECT_EQ(w.brief(w.k.next()), "DONE");
    EXPECT_EQ(w.k.counts().logged_walk_start, 1);
    EXPECT_EQ(why_of(w.k.counts(), K1Why::InstancePatch), 1);
}

TEST(K1Native, SessionWalkCheckIsAskedAndNests) {
    // A session begun with its own walk check (the bindings' per-session
    // verdict sets) asks it instead of the kernel's; a session begun inside
    // it asks ITS own, and the outer one's is asked again once it ends.
    World w(false);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t psys = w.system("sys", ship, 1, {t});
    w.bank("b0", psys);
    const int64_t tsys = w.system("tsys", ship, 4, {t});
    w.bank("tube", tsys);
    std::vector<std::string> asked;
    w.k.set_walk_check([&](int64_t, int64_t) {
        asked.push_back("kernel");
        return true;
    });
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0,
                   [&](int64_t s, int64_t sh) {
                       asked.push_back("outer " + w.names[s] + "/" +
                                       w.names[sh]);
                       return s == psys;
                   });
    ASSERT_NE(w.k.top_walk_check(), nullptr);
    EXPECT_EQ(w.brief(w.k.next()), "WALK_START sys");
    w.k.skip_walk();
    w.k.begin_system(tsys, kDt, 10.0, false, 0.0, [&](int64_t s, int64_t) {
        asked.push_back("inner " + w.names[s]);
        return true;
    });
    EXPECT_EQ(w.brief(w.k.next()), "WALK_START tsys");
    w.k.skip_walk();
    EXPECT_EQ(w.brief(w.k.next()), "DONE");
    w.k.end();
    std::string last;
    for (int i = 0; i < 8 && last != "DONE"; ++i) last = w.brief(w.k.next());
    EXPECT_EQ(last, "DONE");
    w.k.end();
    EXPECT_EQ(asked, (std::vector<std::string>{"outer sys/ship", "inner tsys",
                                               "outer tsys/ship"}));
    // A session begun with none asks the kernel's.
    w.k.begin_system(psys, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.k.top_walk_check(), nullptr);
    EXPECT_EQ(w.brief(w.k.next()), "WALK_START sys");
    EXPECT_EQ(asked.back(), "kernel");
}

// ── Round trips Task 2: beam sustain and idle stops as logged writes ─────────

TEST(K1Native, BeamSustainIsLoggedWrites) {
    // A Fire on a beam already firing: _EnergyWeaponFireMixin._fire_effect
    // with was_firing -- `_firing = True; _target = target; _target_offset =
    // offset`, nothing else -- logged in that order, no FIRE record. The
    // stamp is the walk's offset OBJECT (the marker), whatever it is: with
    // no TGPoint3 offset the mirror reads unset.
    for (const bool with_offset : {true, false}) {
        World w(false);
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
        const int64_t b0 = w.bank("b0", sys);
        w.m.set_i(b0, Field::_firing, 1);
        if (with_offset) w.m.set_fv(sys, Field::_held_offset, {1.0, 2.0, 3.0});
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        const K1Record done = w.k.next();
        EXPECT_EQ(w.brief(done), "DONE") << with_offset;
        char dt[64];
        std::snprintf(dt, sizeof dt, "%.17g", 0.0 + kDt);
        EXPECT_EQ(writes_on(w, done, "b0"),
                  (std::vector<std::string>{
                      std::string("b0._fire_timer=") + dt, "b0._fire_timer=0",
                      "b0._firing=True", "b0._target=t",
                      "b0._target_offset=walk_offset"}))
            << with_offset;
        const K1Write& stamp = done.writes[std::distance(
            done.writes.begin(),
            std::find_if(done.writes.begin(), done.writes.end(),
                         [&](const K1Write& x) {
                             return x.handle == b0 &&
                                    x.field == "_target_offset";
                         }))];
        ASSERT_TRUE(std::holds_alternative<K1WalkOffset>(stamp.value));
        EXPECT_EQ(std::get<K1WalkOffset>(stamp.value), (K1WalkOffset{1, sys}));
        EXPECT_EQ(w.m.get_fv(b0, Field::_target_offset),
                  with_offset ? (std::vector<double>{1.0, 2.0, 3.0})
                              : std::vector<double>{});
        EXPECT_EQ(w.m.get_ref(b0, Field::_target), t);
        EXPECT_EQ(w.m.get_i(b0, Field::_firing), 1);
        EXPECT_EQ(w.k.counts().logged_beam_sustain, 1);
        EXPECT_EQ(w.k.counts().records, 1);
    }
}

TEST(K1Native, BeamEdgeIsLoggedWritesAndEntries) {
    // was_firing False (spec 2026-11-02-combat-fire-events §4.3): the
    // mixin's _fire_effect writes -- `_firing = True; _target = target;
    // _target_offset = offset; _beam_on_countdown = BEAM_ON_DELAY_S; _dwell
    // = 0.0` -- logged in that order, then FIRE_SOUND(bank) and
    // PhaserBank's WEAPON_FIRED(bank, target), both after those writes. No
    // FIRE record: the walk's writes and entries ride DONE.
    World w(false);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    const int64_t b0 = w.bank("b0", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    w.m.set_f(b0, Field::_dwell, 0.25);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record done = w.k.next();
    EXPECT_EQ(w.brief(done), "DONE");
    char delay[64];
    std::snprintf(delay, sizeof delay, "%.17g", 2 * 0.33);
    EXPECT_EQ(writes_on(w, done, "b0"),
              (std::vector<std::string>{
                  "b0._fire_timer=0.33000000000000002", "b0._fire_timer=0",
                  "b0._firing=True", "b0._target=t",
                  "b0._target_offset=walk_offset",
                  std::string("b0._beam_on_countdown=") + delay,
                  "b0._dwell=0"}));
    // Both entries follow the edge's last write (`_dwell`).
    const size_t after = static_cast<size_t>(
        std::find_if(done.writes.begin(), done.writes.end(),
                     [&](const K1Write& x) {
                         return x.handle == b0 && x.field == "_dwell";
                     }) -
        done.writes.begin()) + 1;
    EXPECT_EQ(w.entries(done),
              (std::vector<std::string>{
                  "FIRE_SOUND b0^" + std::to_string(after),
                  "WEAPON_FIRED b0@t^" + std::to_string(after)}));
    EXPECT_EQ(w.m.get_i(b0, Field::_firing), 1);
    EXPECT_EQ(w.m.get_ref(b0, Field::_target), t);
    EXPECT_EQ(w.m.get_f(b0, Field::_beam_on_countdown), 2 * 0.33);
    EXPECT_EQ(w.m.get_f(b0, Field::_dwell), 0.0);
    EXPECT_EQ(w.k.counts().logged_beam_edge, 1);
    EXPECT_EQ(w.k.counts().logged_beam_sustain, 0);
    EXPECT_EQ(w.k.counts().records, 1);
    EXPECT_EQ(w.k.counts().entries[static_cast<size_t>(K1Effect::FIRE_SOUND)], 1);
    EXPECT_EQ(w.k.counts().entries[static_cast<size_t>(K1Effect::WEAPON_FIRED)], 1);
}

TEST(K1Native, EntriesRideTheNextRecordInWalkOrder) {
    // The remaining records are unchanged: a tube's FIRE is still a record,
    // and it carries the entries the phaser walk before it produced; the
    // tube's own Python (its launch events) follows them.
    World w(false);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t psys = w.system("psys", ship, 1, {t});
    w.bank("b0", psys);
    const int64_t tsys = w.system("tsys", ship, 4, {t});
    w.bank("tube", tsys);
    w.m.set_i(psys, Field::_force_update, 1);
    w.m.set_i(tsys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record f = w.k.next();
    EXPECT_EQ(w.brief(f), "FIRE tube@t");
    EXPECT_EQ(f.decision.shape, K1Decision::Shape::Tube);
    std::vector<std::string> e = w.entries(f);
    ASSERT_EQ(e.size(), 2u);
    EXPECT_EQ(e[0].substr(0, e[0].find('^')), "FIRE_SOUND b0");
    EXPECT_EQ(e[1].substr(0, e[1].find('^')), "WEAPON_FIRED b0@t");
    const K1Record done = w.k.next();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_TRUE(done.entries.empty());
}

TEST(K1Native, FireFailedIsAnEntry) {
    // A tube's failed aim (the cone): `self._broadcast_weapon_fire_failed();
    // return False` is the entry WEAPON_FIRE_FAILED(tube), no record; the
    // retry over the list fails again, a second entry. Both ride DONE, each
    // after the writes made before it.
    World w(false);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, -50.0, 0.0);  // behind: no cone
    const int64_t sys = w.system("tsys", ship, 4, {t});
    w.bank("tube", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record done = w.k.next();
    EXPECT_EQ(w.brief(done), "DONE");
    std::vector<std::string> ws = w.writes(done);
    // Fire(t) fails after `_fire_timer = 0.0`; the retry after
    // `tube._target = None`.
    const size_t first = static_cast<size_t>(
        std::find(ws.begin(), ws.end(), "tube._fire_timer=0") - ws.begin()) + 1;
    const size_t second = static_cast<size_t>(
        std::find(ws.begin(), ws.end(), "tube._target=None") - ws.begin()) + 1;
    EXPECT_EQ(w.entries(done),
              (std::vector<std::string>{
                  "WEAPON_FIRE_FAILED tube^" + std::to_string(first),
                  "WEAPON_FIRE_FAILED tube^" + std::to_string(second)}));
    EXPECT_EQ(w.k.counts().logged_fire_failed, 2);
    EXPECT_EQ(w.k.counts().records, 1);
    EXPECT_EQ(
        w.k.counts().entries[static_cast<size_t>(K1Effect::WEAPON_FIRE_FAILED)],
        2);
}

TEST(K1Native, AThrowDropsTheEntriesItsCallProduced) {
    // Entries are session state like the write log: a call that throws
    // after producing some leaves none behind, and the retried call
    // produces them once.
    World w(false);
    const int64_t a = w.ship("a");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", a, 1, {t});
    const int64_t b0 = w.bank("b0", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    const int64_t b = w.ship("b", 0.0, 10.0, 0.0);
    const int64_t sys2 = w.system("sys2", b, 1, {t});
    w.bank("c0", sys2);
    bool boom = true;
    w.k.set_walk_check([&](int64_t s, int64_t) {
        if (s == sys2 && boom) throw std::runtime_error("walk check");
        return false;
    });
    w.k.begin_pump({a, b}, kDt, 10.0, false, 0.0);
    EXPECT_THROW(w.k.next(), std::runtime_error);
    EXPECT_EQ(w.m.get_i(b0, Field::_firing), 0);  // undone
    boom = false;
    const K1Record done = w.k.next();
    EXPECT_EQ(w.brief(done), "DONE");
    std::vector<std::string> e = w.entries(done);
    ASSERT_EQ(e.size(), 2u);
    EXPECT_EQ(e[0].substr(0, e[0].find('^')), "FIRE_SOUND b0");
    EXPECT_EQ(e[1].substr(0, e[1].find('^')), "WEAPON_FIRED b0@t");
}

TEST(K1Native, IdleStopIsLoggedPerBankClass) {
    // A bank that is not firing and cannot fire: its class's StopFiring is
    // pure writes, logged in Python's order, no BANK_STOP record --
    //   energy bank (WS:905): _firing = False; _beam_on_countdown = 0.0
    //   tube (Weapon, WS:1192): _firing = False
    //   pulse (WS:2971): _firing = False; _target = None;
    //                    _target_offset = None
    struct Case {
        int64_t kind;
        std::vector<std::string> stop;
    };
    const Case cases[] = {
        {1, {"b0._firing=False", "b0._beam_on_countdown=0"}},
        {4, {"b0._firing=False"}},
        {2, {"b0._firing=False", "b0._target=None", "b0._target_offset=None"}},
    };
    for (const Case& c : cases) {
        World w(false);
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, c.kind, {t});
        const int64_t b0 = w.bank("b0", sys);
        w.bank("b1", sys);  // healthy: the system is not offline
        if (c.kind == 1) {
            w.m.set_f(b0, Field::_charge_level, 0.0);
            w.m.set_f(b0, Field::_beam_on_countdown, 0.25);
        } else if (c.kind == 2) {
            w.m.set_f(b0, Field::_cooldown_remaining, 1.0);
            w.m.set_ref(b0, Field::_target, t);
            w.m.set_fv(b0, Field::_target_offset, {1.0, 2.0, 3.0});
        } else {
            w.m.set_i(b0, Field::_num_ready, 0);
        }
        w.m.set_i(sys, Field::_single_fire, 0);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        std::vector<K1Record> recs;
        for (int guard = 0; guard < 10; ++guard) {
            recs.push_back(w.k.next());
            if (recs.back().kind == K1Kind::DONE) break;
        }
        std::vector<std::string> b0w;
        for (const K1Record& r : recs) {
            EXPECT_NE(w.brief(r), "BANK_STOP b0") << c.kind;
            for (const std::string& s : writes_on(w, r, "b0")) b0w.push_back(s);
        }
        // After the passed gate's `_fire_timer = 0.0`: the stop, then the
        // not-fired path's `weapon._target = None`.
        const auto at = std::find(b0w.begin(), b0w.end(), "b0._fire_timer=0");
        ASSERT_NE(at, b0w.end()) << c.kind;
        std::vector<std::string> stop(at + 1, at + 1 + std::min<ptrdiff_t>(
                                                  c.stop.size(),
                                                  b0w.end() - at - 1));
        EXPECT_EQ(stop, c.stop) << c.kind;
        EXPECT_EQ(w.m.get_i(b0, Field::_firing), 0) << c.kind;
        if (c.kind == 1) EXPECT_EQ(w.m.get_f(b0, Field::_beam_on_countdown), 0.0);
        if (c.kind == 2) {
            EXPECT_EQ(w.m.get_ref(b0, Field::_target), -1);
            EXPECT_EQ(w.m.get_fv(b0, Field::_target_offset),
                      std::vector<double>{});
        }
        EXPECT_EQ(w.k.counts().logged_idle_bank_stop, 1) << c.kind;
    }
}

TEST(K1Native, FiringBankStopIsLoggedPerBankClass) {
    // A FIRING bank that cannot fire: its class's StopFiring writes, logged
    // as for an idle one, plus LOOP_STOP(bank) for the energy bank's loop
    // sound (after its writes); a tube and a pulse cannon have no loop. No
    // BANK_STOP record.
    struct Case {
        int64_t kind;
        std::vector<std::string> stop;
        bool loop;
    };
    const Case cases[] = {
        {1, {"b0._firing=False", "b0._beam_on_countdown=0"}, true},
        {4, {"b0._firing=False"}, false},
        {2, {"b0._firing=False", "b0._target=None", "b0._target_offset=None"},
         false},
    };
    for (const Case& c : cases) {
        World w(false);
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, c.kind, {t});
        const int64_t b0 = w.bank("b0", sys);
        w.bank("b1", sys);
        w.m.set_i(b0, Field::_firing, 1);
        if (c.kind == 1) {
            w.m.set_f(b0, Field::_charge_level, 0.0);
            w.m.set_f(b0, Field::_beam_on_countdown, 0.25);
        } else if (c.kind == 2) {
            w.m.set_f(b0, Field::_cooldown_remaining, 1.0);
            w.m.set_ref(b0, Field::_target, t);
            w.m.set_fv(b0, Field::_target_offset, {1.0, 2.0, 3.0});
        } else {
            w.m.set_i(b0, Field::_num_ready, 0);
        }
        w.m.set_i(sys, Field::_single_fire, 0);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        std::vector<K1Record> recs;
        for (int guard = 0; guard < 10; ++guard) {
            recs.push_back(w.k.next());
            if (recs.back().kind == K1Kind::DONE) break;
        }
        std::vector<std::string> b0w, loops;
        for (const K1Record& r : recs) {
            EXPECT_NE(w.brief(r), "BANK_STOP b0") << c.kind;
            for (const std::string& s : writes_on(w, r, "b0")) b0w.push_back(s);
            for (const std::string& s : w.entries(r)) loops.push_back(s);
        }
        const auto at = std::find(b0w.begin(), b0w.end(), "b0._fire_timer=0");
        ASSERT_NE(at, b0w.end()) << c.kind;
        std::vector<std::string> stop(at + 1, at + 1 + std::min<ptrdiff_t>(
                                                  c.stop.size(),
                                                  b0w.end() - at - 1));
        EXPECT_EQ(stop, c.stop) << c.kind;
        if (c.loop) {
            ASSERT_EQ(recs.size(), 1u);
            const std::vector<std::string> ws = w.writes(recs[0]);
            const size_t after = static_cast<size_t>(
                std::find(ws.begin(), ws.end(), "b0._beam_on_countdown=0") -
                ws.begin()) + 1;
            EXPECT_EQ(loops, (std::vector<std::string>{
                                 "LOOP_STOP b0^" + std::to_string(after)}));
        } else {
            EXPECT_TRUE(loops.empty()) << c.kind;
        }
        EXPECT_EQ(w.m.get_i(b0, Field::_firing), 0) << c.kind;
        EXPECT_EQ(w.k.counts().logged_firing_bank_stop, 1) << c.kind;
        EXPECT_EQ(w.k.counts().logged_idle_bank_stop, 0) << c.kind;
    }
}

TEST(K1Native, SystemStopIsLoggedWrites) {
    // The pump's `sys_.StopFiring()` (a gate stopped the system):
    // WeaponSystem.StopFiring's writes -- `_fire_held = False; _held_target
    // = None; _held_offset = None; _target_list = []; _last_group_fired =
    // -1` -- then each child's StopFiring in order, a firing energy bank's
    // LOOP_STOP after its writes. No STOP_SYSTEM record.
    World w(false);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    w.bank("b0", sys);
    const int64_t b1 = w.bank("b1", sys);
    w.m.set_i(b1, Field::_firing, 1);
    w.m.set_fv(sys, Field::_held_offset, {1.0, 2.0, 3.0});
    w.m.set_i(sys, Field::_last_group_fired, 2);
    w.m.set_i(sys, Field::_is_on, 0);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record done = w.k.next();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_EQ(w.writes(done),
              (std::vector<std::string>{
                  "sys._fire_held=False", "sys._held_target=-1",
                  "sys._held_offset=None", "sys._target_list=[]",
                  "sys._last_group_fired=-1", "b0._firing=False",
                  "b0._beam_on_countdown=0", "b1._firing=False",
                  "b1._beam_on_countdown=0"}));
    EXPECT_EQ(w.entries(done), (std::vector<std::string>{"LOOP_STOP b1^9"}));
    EXPECT_EQ(w.m.get_i(sys, Field::_fire_held), 0);
    EXPECT_EQ(w.m.get_ref(sys, Field::_held_target), -1);
    EXPECT_EQ(w.m.get_fv(sys, Field::_held_offset), std::vector<double>{});
    EXPECT_TRUE(w.m.get_ids(sys, Field::_target_list).empty());
    EXPECT_EQ(w.m.get_i(sys, Field::_last_group_fired), -1);
    EXPECT_EQ(w.m.get_i(b1, Field::_firing), 0);
    EXPECT_EQ(w.k.counts().logged_system_stop, 1);
    EXPECT_EQ(w.k.counts().records, 1);
}

TEST(K1Native, SystemStopTheWalkCheckRefusesStaysARecord) {
    // The stop runs before any walk, so the walk check is asked first: when
    // it hands the system back, the STOP_SYSTEM record stays and nothing of
    // the stop is logged. (Which patches it answers for is the bindings':
    // tests/unit/test_native_k1_dispatch.py
    // test_system_instance_stop_patch_runs_python.)
    World w(false);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    const int64_t b0 = w.bank("b0", sys);
    w.m.set_i(b0, Field::_firing, 1);
    w.m.set_i(sys, Field::_is_on, 0);
    int64_t asked = -1;
    w.k.set_walk_check([&](int64_t s, int64_t) {
        asked = s;
        return true;
    });
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record r = w.k.next();
    EXPECT_EQ(w.brief(r), "STOP_SYSTEM sys");
    EXPECT_TRUE(r.writes.empty());
    EXPECT_TRUE(r.entries.empty());
    EXPECT_EQ(asked, sys);
    EXPECT_EQ(w.m.get_i(b0, Field::_firing), 1);
    EXPECT_EQ(w.k.counts().logged_system_stop, 0);
}


// ── Launches at the boundary (spec 2026-11-02-combat-launch-deferral §4.1) ──
// A tube's or a dumb launch is the launcher writes, logged in Python's order
// (TorpedoTube._fire_effect, _start_slot_cooldown, _spawn_torpedo's ammo
// debit), and SPAWN(tube, fire-time record), WEAPON_FIRED, AMMO_CONSUMED
// queued after them; no FIRE record. A launch the kernel cannot make is the
// FIRE (or FIRE_DUMB) record as before, counted by why.

namespace {

struct Launcher {
    int64_t ship = -1, sys = -1, tube = -1, ammo = -1;
};

// A torpedo system on a ship at (10, 20, 30) moving (1, 2, 3), held at
// `targets`, with one tube that launches natively: its ammo type's launch
// cached (19 GU/s), a finite magazine of `rounds` (max 4),
// its one slot loaded, its DamageRadiusFactor 0.2, the timer forced.
Launcher launcher(World& w, std::vector<int64_t> targets, int64_t rounds = 3) {
    Launcher l;
    l.ship = w.ship("ship", 10.0, 20.0, 30.0);
    l.sys = w.system("tsys", l.ship, 4, std::move(targets));
    l.tube = w.bank("tube", l.sys);
    l.ammo = w.m.get_ids(l.sys, Field::_ammo_by_slot)[1];
    w.names[l.ammo] = "ammo";
    w.m.set_i(l.ammo, Field::_unlimited, 0);
    w.m.set_i(l.ammo, Field::_available, rounds);
    w.m.set_i(l.ammo, Field::_max_torpedoes, 4);
    w.m.set_i(l.ammo, Field::ammo_launch_state, 1);
    w.m.set_f(l.ammo, Field::ammo_launch_speed, 19.0);
    w.m.set_floats(l.tube, Field::_reload_timers, {-1.0});
    w.m.set_floats(l.tube, Field::_reload_advanced_at, {0.0});
    w.m.set_f(l.tube, Field::_damage_radius_factor, 0.2);
    w.m.set_fv(l.ship, Field::_velocity, {1.0, 2.0, 3.0});
    w.m.set_i(l.sys, Field::_force_update, 1);
    return l;
}

// The writes of `r` from the first one equal to `from`, `n` of them.
std::vector<std::string> writes_from(const World& w, const K1Record& r,
                                     const std::string& from, size_t n) {
    const std::vector<std::string> ws = w.writes(r);
    auto it = std::find(ws.begin(), ws.end(), from);
    if (it == ws.end()) return {};
    const size_t at = static_cast<size_t>(it - ws.begin());
    return std::vector<std::string>(
        it, it + static_cast<std::ptrdiff_t>(std::min(n, ws.size() - at)));
}

size_t launch_why(const World& w, K1LaunchWhy why) {
    return static_cast<size_t>(
        w.k.counts().launch_why[static_cast<size_t>(why)]);
}

const K1Entry* spawn_of(const K1Record& r) {
    for (const K1Entry& e : r.entries)
        if (e.kind == K1Effect::SPAWN) return &e;
    return nullptr;
}

}  // namespace

TEST(K1Launch, TubeLaunchIsLoggedWritesAndASpawnEntry) {
    World w(false);
    const int64_t t = w.object("t", 10.0, 270.0, 30.0);
    const Launcher l = launcher(w, {t});
    w.m.set_i(l.tube, Field::_skew_fire, 1);
    w.m.set_fv(l.sys, Field::_held_offset, {0.25, -0.5, 0.125});
    w.k.begin_pump({l.ship}, kDt, 10.0, false, 0.0);
    const K1Record done = w.k.next();
    EXPECT_EQ(w.brief(done), "DONE");
    // _fire_effect's stamps, _start_slot_cooldown's first loaded slot, the
    // ammo debit (AddAvailable(-1)), and `_firing = False` at the end.
    EXPECT_EQ(writes_from(w, done, "tube._target=t", 10),
              (std::vector<std::string>{
                  "tube._target=t", "tube._target_offset=walk_offset",
                  "tube._firing=True", "tube._num_ready=0",
                  "tube._last_fire_time=10",
                  "tsys._last_system_fire_time=10",
                  "tube._reload_timers=[0]=0",
                  "tube._reload_advanced_at=[0]=10", "ammo._available=2",
                  "tube._firing=False"}));
    // The three entries follow the debit, before `_firing = False`.
    const auto ws = w.writes(done);
    const size_t after = static_cast<size_t>(
        std::find(ws.begin(), ws.end(), "ammo._available=2") - ws.begin()) + 1;
    EXPECT_EQ(w.entries(done),
              (std::vector<std::string>{
                  "SPAWN tube@t^" + std::to_string(after),
                  "WEAPON_FIRED tube@t^" + std::to_string(after),
                  "AMMO_CONSUMED tube^" + std::to_string(after)}));
    const K1Entry* e = spawn_of(done);
    ASSERT_NE(e, nullptr);
    ASSERT_TRUE(e->spawn.has_value());
    const K1Spawn& s = *e->spawn;
    EXPECT_EQ(s.kind, K1Spawn::Kind::Tube);
    EXPECT_EQ(s.ship, l.ship);
    EXPECT_EQ(s.set, w.set);
    EXPECT_EQ(s.ammo, l.ammo);
    EXPECT_EQ(s.target, t);
    EXPECT_EQ(s.position, (Vec3{10.0, 20.0, 30.0}));
    // _emitter_forward_world(skew=True): Direction + 0.033 x Right, then
    // unit(dir) * 19 + the ship's velocity (the Python's operand order).
    const double dx = 0.0 + 0.033 * 1.0, dy = 1.0 + 0.033 * 0.0,
                 dz = 0.0 + 0.033 * 0.0;
    const double len = std::sqrt(dx * dx + dy * dy + dz * dz);
    ASSERT_TRUE(s.has_velocity);
    EXPECT_EQ(s.velocity, (Vec3{dx / len * 19.0 + 1.0, dy / len * 19.0 + 2.0,
                                dz / len * 19.0 + 3.0}));
    ASSERT_TRUE(s.has_offset);
    EXPECT_EQ(s.offset, (Vec3{0.25, -0.5, 0.125}));
    EXPECT_EQ(s.drf_override, 0.2);
    // A pulse's (Task 3): a tube's carries none.
    EXPECT_EQ(s.damage_scale, 1.0);
    EXPECT_EQ(s.fired_at, -1);
    // The mirror holds what Python will.
    EXPECT_EQ(w.m.get_i(l.tube, Field::_num_ready), 0);
    EXPECT_EQ(w.m.get_i(l.tube, Field::_firing), 0);
    EXPECT_EQ(w.m.get_floats(l.tube, Field::_reload_timers),
              (std::vector<double>{0.0}));
    EXPECT_EQ(w.m.get_floats(l.tube, Field::_reload_advanced_at),
              (std::vector<double>{10.0}));
    EXPECT_EQ(w.m.get_i(l.ammo, Field::_available), 2);
    EXPECT_EQ(w.m.get_f(l.sys, Field::_last_system_fire_time), 10.0);
    const auto& c = w.k.counts();
    EXPECT_EQ(c.logged_tube_launch, 1);
    EXPECT_EQ(c.records, 1);
    EXPECT_EQ(c.entries[static_cast<size_t>(K1Effect::SPAWN)], 1);
    EXPECT_EQ(c.entries[static_cast<size_t>(K1Effect::AMMO_CONSUMED)], 1);
}

TEST(K1Launch, LaunchDirectionTurnsWithTheShip) {
    // A ship turned 90 degrees about Z: the tube's Direction (+y) becomes
    // world -x, the mount (0.5, 0, 0) world (0, 0.5, 0); no skew.
    World w(false);
    const int64_t t = w.object("t", -240.0, 20.0, 30.0);
    const Launcher l = launcher(w, {t});
    const ObjectRow* so = w.m.object(l.ship);
    w.store.set_rotation(static_cast<uint32_t>(so->xform_index),
                         static_cast<uint32_t>(so->xform_gen),
                         {0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0});
    w.m.set_fv(l.tube, Field::_position, {0.5, 0.0, 0.0});
    w.k.begin_pump({l.ship}, kDt, 10.0, false, 0.0);
    const K1Record done = w.k.next();
    EXPECT_EQ(w.brief(done), "DONE");
    const K1Entry* e = spawn_of(done);
    ASSERT_TRUE(e != nullptr && e->spawn);
    EXPECT_EQ(e->spawn->position, (Vec3{10.0, 20.5, 30.0}));
    EXPECT_EQ(e->spawn->velocity, (Vec3{-1.0 * 19.0 + 1.0, 0.0 * 19.0 + 2.0,
                                        0.0 * 19.0 + 3.0}));
    EXPECT_FALSE(e->spawn->has_offset);  // the walk's offset is None
}

TEST(K1Launch, AmmoDebitIsAddAvailableMinusOne) {
    // max(0, min(available - 1, max_torpedoes)): the last round, a magazine
    // over its maximum, and an unlimited type (no write at all).
    struct Case { int64_t available; bool unlimited; int64_t want; };
    for (const Case c : {Case{1, false, 0}, Case{7, false, 4},
                         Case{5, true, -1}}) {
        World w(false);
        const int64_t t = w.object("t", 10.0, 270.0, 30.0);
        const Launcher l = launcher(w, {t}, c.available);
        w.m.set_i(l.ammo, Field::_unlimited, c.unlimited ? 1 : 0);
        w.k.begin_pump({l.ship}, kDt, 10.0, false, 0.0);
        const K1Record done = w.k.next();
        EXPECT_EQ(w.brief(done), "DONE") << c.available;
        if (c.want < 0) {
            EXPECT_TRUE(writes_on(w, done, "ammo").empty()) << c.available;
            EXPECT_EQ(w.m.get_i(l.ammo, Field::_available), c.available);
        } else {
            EXPECT_EQ(writes_on(w, done, "ammo"),
                      (std::vector<std::string>{"ammo._available=" +
                                                std::to_string(c.want)}))
                << c.available;
        }
        // AMMO_CONSUMED is queued either way (the player gate is read at
        // delivery).
        EXPECT_EQ(w.k.counts().entries[static_cast<size_t>(
                      K1Effect::AMMO_CONSUMED)], 1);
    }
}

TEST(K1Launch, NoLoadedSlotWritesNoSlot) {
    // _start_slot_cooldown finds no loaded slot (all cooling): no write.
    World w(false);
    const int64_t t = w.object("t", 10.0, 270.0, 30.0);
    const Launcher l = launcher(w, {t});
    w.m.set_floats(l.tube, Field::_reload_timers, {0.5});
    w.k.begin_pump({l.ship}, kDt, 10.0, false, 0.0);
    const K1Record done = w.k.next();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_EQ(writes_from(w, done, "tsys._last_system_fire_time=10", 2),
              (std::vector<std::string>{"tsys._last_system_fire_time=10",
                                        "ammo._available=2"}));
}

TEST(K1Launch, PosedTargetLaunchCarriesTheOffsetAsIs) {
    // A posed target: the walk's offset (no mount claims it) is launched as
    // it is, with no bake (fire control native only, M5): the torpedo
    // steers at it as a plain body point for its whole flight.
    World w(false);
    const int64_t t = w.ship("t", 10.0, 270.0, 30.0);
    w.m.set_i(t, Field::is_ship_class, 1);
    w.m.set_i(t, Field::has_posed_parts, 1);
    w.m.set_part_poses(t, {shift_pose()});
    const Launcher l = launcher(w, {t});
    w.m.set_fv(l.sys, Field::_held_offset, {0.25, -0.5, 0.125});
    w.k.begin_pump({l.ship}, kDt, 10.0, false, 0.0);
    const K1Record r = w.k.next();
    EXPECT_EQ(w.brief(r), "DONE");
    const K1Entry* e = spawn_of(r);
    ASSERT_TRUE(e != nullptr && e->spawn);
    EXPECT_TRUE(e->spawn->has_offset);
    EXPECT_EQ(e->spawn->offset, (Vec3{0.25, -0.5, 0.125}));
    for (int i = 0; i < static_cast<int>(K1LaunchWhy::kCount); ++i)
        EXPECT_EQ(launch_why(w, static_cast<K1LaunchWhy>(i)), 0u) << i;
}

TEST(K1Launch, LaunchesTheKernelCannotMakeAreFireRecords) {
    // Never guessed: the FIRE record as before (no launch write, nothing
    // queued), counted by why.
    enum Case { kUncached, kUnresolved, kNoAmmo, kPatched, kSlots };
    for (int c = kUncached; c <= kSlots; ++c) {
        World w(false);
        const int64_t t = w.object("t", 10.0, 270.0, 30.0);
        const Launcher l = launcher(w, {t});
        K1LaunchWhy want = K1LaunchWhy::Other;
        switch (c) {
            case kUncached:
                w.m.set_i(l.ammo, Field::ammo_launch_state, 0);
                want = K1LaunchWhy::Uncached;
                break;
            case kUnresolved:
                w.m.set_i(l.ammo, Field::ammo_launch_state, 2);
                want = K1LaunchWhy::Unresolved;
                break;
            case kNoAmmo:  // the property's script: Python's
                w.m.set_ids(l.sys, Field::_ammo_by_slot, {});
                want = K1LaunchWhy::Unresolved;
                break;
            case kPatched:  // a spawn function patched (a test, a tool)
                w.m.set_global_i(Global::K1_LAUNCH_PATCHED, 1);
                want = K1LaunchWhy::Patched;
                break;
            case kSlots:  // _ensure_slots would rebuild the lists
                w.m.set_floats(l.tube, Field::_reload_timers, {});
                want = K1LaunchWhy::Other;
                break;
        }
        w.k.begin_pump({l.ship}, kDt, 10.0, false, 0.0);
        const K1Record r = w.k.next();
        EXPECT_EQ(w.brief(r), "FIRE tube@t") << c;
        EXPECT_EQ(r.decision.shape, K1Decision::Shape::Tube) << c;
        EXPECT_EQ(launch_why(w, want), 1u) << c << " " << k1_launch_why_name(want);
        EXPECT_TRUE(r.entries.empty()) << c;
        EXPECT_FALSE(has_write(w, r, "tube._firing=True")) << c;
        EXPECT_EQ(w.m.get_i(l.tube, Field::_num_ready), 1) << c;
        EXPECT_EQ(w.k.counts().logged_tube_launch, 0) << c;
    }
}

TEST(K1Launch, DumbFireIsDecidedNatively) {
    // An empty target list and the timer below its threshold: try_fire
    // returns False, `_target = None`, then Weapon.FireDumb(0, 1):
    // _dewarp_blocks_fire, then Fire(None, None) -- CanFire, the launch with
    // no target and no offset.
    World w(false);
    const Launcher l = launcher(w, {});
    w.m.set_i(l.sys, Field::_force_update, 0);
    w.k.begin_pump({l.ship}, kDt, 10.0, false, 0.0);
    const K1Record done = w.k.next();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_EQ(writes_from(w, done, "tube._target_offset=None", 3),
              (std::vector<std::string>{"tube._target_offset=None",
                                        "tube._firing=True",
                                        "tube._num_ready=0"}));
    EXPECT_EQ(fx(w, done),
              (std::vector<std::string>{"SPAWN tube@None",
                                        "WEAPON_FIRED tube@None",
                                        "AMMO_CONSUMED tube"}));
    const K1Entry* e = spawn_of(done);
    ASSERT_TRUE(e != nullptr && e->spawn);
    EXPECT_EQ(e->spawn->kind, K1Spawn::Kind::Dumb);
    EXPECT_FALSE(e->spawn->has_offset);
    EXPECT_EQ(w.k.counts().logged_dumb_launch, 1);
    EXPECT_EQ(w.k.counts().logged_tube_launch, 0);
}

TEST(K1Launch, DumbFireRefusedIsNoRecord) {
    // FireDumb that does nothing in Python: the ship is sliding onto its
    // warp-in placement, or the tube's Fire refuses (not loaded). No record,
    // no write of its own.
    for (bool arriving : {true, false}) {
        World w(false);
        const Launcher l = launcher(w, {});
        w.m.set_i(l.sys, Field::_force_update, 0);
        if (arriving)
            w.m.set_i(l.ship, Field::arriving, 1);
        else
            w.m.set_i(l.tube, Field::_num_ready, 0);
        w.k.begin_pump({l.ship}, kDt, 10.0, false, 0.0);
        const K1Record done = w.k.next();
        EXPECT_EQ(w.brief(done), "DONE") << arriving;
        EXPECT_TRUE(done.entries.empty()) << arriving;
        EXPECT_FALSE(has_write(w, done, "tube._firing=True")) << arriving;
        EXPECT_EQ(w.k.counts().logged_dumb_refused, 1) << arriving;
    }
}

TEST(K1Launch, DumbLaunchTheKernelCannotMakeIsAFireDumbRecord) {
    World w(false);
    const Launcher l = launcher(w, {});
    w.m.set_i(l.sys, Field::_force_update, 0);
    w.m.set_i(l.ammo, Field::ammo_launch_state, 0);
    w.k.begin_pump({l.ship}, kDt, 10.0, false, 0.0);
    const K1Record r = w.k.next();
    EXPECT_EQ(w.brief(r), "FIRE_DUMB tube");
    EXPECT_TRUE(r.entries.empty());
    EXPECT_FALSE(has_write(w, r, "tube._firing=True"));
    EXPECT_EQ(launch_why(w, K1LaunchWhy::Uncached), 1u);
}

TEST(K1Launch, AThrowUndoesTheLaunchWrites) {
    // A later walk of the same call throws: the launch's writes (the slot
    // and the ammo debit included) are undone in the mirror and its entries
    // dropped; the retried call makes them once.
    World w(false);
    const int64_t t = w.object("t", 10.0, 270.0, 30.0);
    const Launcher l = launcher(w, {t});
    const int64_t b = w.ship("b", 0.0, 10.0, 0.0);
    const int64_t sys2 = w.system("sys2", b, 1, {t});
    w.bank("c0", sys2);
    bool boom = true;
    w.k.set_walk_check([&](int64_t s, int64_t) {
        if (s == sys2 && boom) throw std::runtime_error("walk check");
        return false;
    });
    w.k.begin_pump({l.ship, b}, kDt, 10.0, false, 0.0);
    EXPECT_THROW(w.k.next(), std::runtime_error);
    EXPECT_EQ(w.m.get_i(l.tube, Field::_num_ready), 1);
    EXPECT_EQ(w.m.get_floats(l.tube, Field::_reload_timers),
              (std::vector<double>{-1.0}));
    EXPECT_EQ(w.m.get_floats(l.tube, Field::_reload_advanced_at),
              (std::vector<double>{0.0}));
    EXPECT_EQ(w.m.get_i(l.ammo, Field::_available), 3);
    boom = false;
    const K1Record done = w.k.next();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_EQ(fx(w, done).size(), 3u);
    EXPECT_EQ(w.m.get_i(l.ammo, Field::_available), 2);
}

// ── A cannon's launch at the boundary (launch deferral, Task 3) ────────────
// PulseWeapon._fire_effect inside the deferral: SPAWN(cannon, the fire-time
// record) -- Python's _defer_spawn, appended first -- then the drain
// (`_charge_level = max(0.0, _charge_level - _shot_cost())`) and the
// cooldown (`_cooldown_remaining = GetCooldownTime()`). Its ET_WEAPON_FIRED
// is the SPAWN delivery's (once the bolt exists: M4), never a K1 entry.

namespace {

struct Cannon {
    int64_t ship = -1, target = -1, sys = -1, cannon = -1;
};

// A pulse system on a ship at (10, 20, 30) moving (1, 2, 3), held at a
// target ahead with the offset (0.25, -0.5, 0.125); one cannon at the
// ship's origin (launch speed 50, charge 5 of 5, discharge rate 1) at power
// setting `power`, its cooldown 0.2 and DamageRadiusFactor 0.3, the timer
// forced. The power setting's damage scales are BC's 0.2 / 0.5 / 1.0.
Cannon cannon_world(World& w, int64_t power = 2) {
    Cannon c;
    c.ship = w.ship("ship", 10.0, 20.0, 30.0);
    c.target = w.object("t", 10.0, 270.0, 30.0);
    c.sys = w.system("psys", c.ship, 2, {c.target});
    c.cannon = w.bank("cannon", c.sys);
    w.m.set_i(c.cannon, Field::_power_setting, power);
    w.m.set_f(c.cannon, Field::_cooldown_time, 0.2);
    w.m.set_f(c.cannon, Field::_damage_radius_factor, 0.3);
    w.m.set_fv(c.ship, Field::_velocity, {1.0, 2.0, 3.0});
    w.m.set_fv(c.sys, Field::_held_offset, {0.25, -0.5, 0.125});
    w.m.set_i(c.sys, Field::_force_update, 1);
    w.m.set_global_f(Global::PULSE_DAMAGE_SCALE_0, 0.2);
    w.m.set_global_f(Global::PULSE_DAMAGE_SCALE_1, 0.5);
    w.m.set_global_f(Global::PULSE_DAMAGE_SCALE_2, 1.0);
    return c;
}

// The led launch direction the kernel decides for cannon_world's shot (the
// FIRE record's, with every launch handed back).
Vec3 decided_dir(int64_t power) {
    World p(false);
    const Cannon c = cannon_world(p, power);
    p.m.set_global_i(Global::K1_LAUNCH_PATCHED, 1);
    p.k.begin_pump({c.ship}, kDt, 10.0, false, 0.0);
    const K1Record r = p.k.next();
    EXPECT_EQ(p.brief(r), "FIRE cannon@t");
    return r.decision.world_dir;
}

}  // namespace

TEST(K1PulseLaunch, CannonLaunchIsLoggedWritesAndASpawnEntry) {
    const Vec3 dir = decided_dir(2);
    World w(false);
    const Cannon c = cannon_world(w);
    w.k.begin_pump({c.ship}, kDt, 10.0, false, 0.0);
    const K1Record done = w.k.next();
    ASSERT_EQ(w.brief(done), "DONE");
    // The decision's stamps, then the effect's drain (5 - 1 x 2.0) and the
    // cooldown; the SPAWN between them (Python appends it first).
    EXPECT_EQ(writes_from(w, done, "cannon._target=t", 4),
              (std::vector<std::string>{
                  "cannon._target=t", "cannon._target_offset=walk_offset",
                  "cannon._charge_level=3",
                  "cannon._cooldown_remaining=0.20000000000000001"}));
    const auto ws = w.writes(done);
    const size_t after = static_cast<size_t>(
        std::find(ws.begin(), ws.end(), "cannon._target_offset=walk_offset") -
        ws.begin()) + 1;
    // No WEAPON_FIRED entry: the delivery posts it once the bolt exists.
    EXPECT_EQ(w.entries(done),
              (std::vector<std::string>{"SPAWN cannon@t^" +
                                        std::to_string(after)}));
    const K1Entry* e = spawn_of(done);
    ASSERT_TRUE(e != nullptr && e->spawn);
    const K1Spawn& s = *e->spawn;
    EXPECT_EQ(s.kind, K1Spawn::Kind::Pulse);
    EXPECT_EQ(s.ship, c.ship);
    EXPECT_EQ(s.set, w.set);
    EXPECT_EQ(s.ammo, c.cannon);  // the row its module is kept by
    EXPECT_EQ(s.target, c.target);
    EXPECT_EQ(s.position, (Vec3{10.0, 20.0, 30.0}));
    // unit(the decided world_dir) x 50 + the ship's velocity.
    const double len =
        std::sqrt(dir[0] * dir[0] + dir[1] * dir[1] + dir[2] * dir[2]);
    ASSERT_TRUE(s.has_velocity);
    EXPECT_EQ(s.velocity, (Vec3{dir[0] / len * 50.0 + 1.0,
                                dir[1] / len * 50.0 + 2.0,
                                dir[2] / len * 50.0 + 3.0}));
    ASSERT_TRUE(s.has_offset);
    EXPECT_EQ(s.offset, (Vec3{0.25, -0.5, 0.125}));
    EXPECT_EQ(s.drf_override, 0.3);
    EXPECT_EQ(s.damage_scale, 1.0);
    EXPECT_EQ(s.fired_at, c.target);
    // The mirror holds what Python will.
    EXPECT_EQ(w.m.get_f(c.cannon, Field::_charge_level), 3.0);
    EXPECT_EQ(w.m.get_f(c.cannon, Field::_cooldown_remaining), 0.2);
    const auto& n = w.k.counts();
    EXPECT_EQ(n.logged_pulse_launch, 1);
    EXPECT_EQ(n.records, 1);
    EXPECT_EQ(n.entries[static_cast<size_t>(K1Effect::SPAWN)], 1);
    EXPECT_EQ(n.entries[static_cast<size_t>(K1Effect::WEAPON_FIRED)], 0);
}

TEST(K1PulseLaunch, DrainClampsAndTheScaleFollowsThePowerSetting) {
    // A charge just under the shot's cost (the gate's 1e-9 slack): the drain
    // is max(0.0, charge - cost) = 0; the bolt's scale is the setting's.
    for (const int64_t power : {0, 1}) {
        World w(false);
        const Cannon c = cannon_world(w, power);
        const double cost = power == 0 ? 0.5 : 1.0;
        w.m.set_f(c.cannon, Field::_charge_level, cost - 5e-10);
        w.k.begin_pump({c.ship}, kDt, 10.0, false, 0.0);
        const K1Record done = w.k.next();
        ASSERT_EQ(w.brief(done), "DONE") << power;
        EXPECT_TRUE(has_write(w, done, "cannon._charge_level=0")) << power;
        const K1Entry* e = spawn_of(done);
        ASSERT_TRUE(e != nullptr && e->spawn) << power;
        EXPECT_EQ(e->spawn->damage_scale, power == 0 ? 0.2 : 0.5) << power;
    }
}

TEST(K1PulseLaunch, LaunchesTheKernelCannotMakeAreFireRecords) {
    // A launch function patched, or a cannon module sys.modules no longer
    // holds (Python's decide would import another, or none): the FIRE record
    // as before -- the decision's stamps only, nothing queued -- counted.
    for (const bool stale : {false, true}) {
        World w(false);
        const Cannon c = cannon_world(w);
        w.m.set_global_i(stale ? Global::K1_PULSE_MODULE_STALE
                               : Global::K1_LAUNCH_PATCHED,
                         1);
        w.k.begin_pump({c.ship}, kDt, 10.0, false, 0.0);
        const K1Record r = w.k.next();
        EXPECT_EQ(w.brief(r), "FIRE cannon@t") << stale;
        EXPECT_EQ(r.decision.shape, K1Decision::Shape::Pulse) << stale;
        EXPECT_EQ(launch_why(w, stale ? K1LaunchWhy::Unresolved
                                      : K1LaunchWhy::Patched),
                  1u)
            << stale;
        EXPECT_TRUE(r.entries.empty()) << stale;
        EXPECT_EQ(w.writes(r).back(), "cannon._target_offset=walk_offset");
        EXPECT_EQ(w.m.get_f(c.cannon, Field::_charge_level), 5.0) << stale;
        EXPECT_EQ(w.k.counts().logged_pulse_launch, 0) << stale;
    }
}

TEST(K1PulseLaunch, AThrowUndoesTheLaunchWrites) {
    // As a tube's: a later walk of the same call throws, the drain and the
    // cooldown are undone in the mirror and the SPAWN dropped; the retried
    // call makes them once.
    World w(false);
    const Cannon c = cannon_world(w);
    const int64_t b = w.ship("b", 0.0, 10.0, 0.0);
    const int64_t sys2 = w.system("sys2", b, 1, {c.target});
    w.bank("c0", sys2);
    bool boom = true;
    w.k.set_walk_check([&](int64_t s, int64_t) {
        if (s == sys2 && boom) throw std::runtime_error("walk check");
        return false;
    });
    w.k.begin_pump({c.ship, b}, kDt, 10.0, false, 0.0);
    EXPECT_THROW(w.k.next(), std::runtime_error);
    EXPECT_EQ(w.m.get_f(c.cannon, Field::_charge_level), 5.0);
    EXPECT_EQ(w.m.get_f(c.cannon, Field::_cooldown_remaining), 0.0);
    boom = false;
    const K1Record done = w.k.next();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_EQ(w.m.get_f(c.cannon, Field::_charge_level), 3.0);
    EXPECT_EQ(w.entries(done).size(), 1u);
}

// ── THE TRACTOR WALK (fire control native only, M4, R8) ─────────────────────

// The pump's tractor walk: no record. A held target in range and arc is
// gripped -- the beam's edge writes, its FIRE_SOUND, the cursor -- and the
// system's firing edge is a TRACTOR_STARTED(system, ship) entry after its
// `_was_firing` write. Out of range the beam drops, the engage intent kept,
// with a TRACTOR_STOPPED.
TEST(K1, TractorWalkGripsAndDrops) {
    World w(false);
    w.m.set_global_f(Global::TRACTOR_MAX_RANGE_GU, 120.0);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("tr", ship, 3, {t});
    const int64_t beam = w.bank("beam", sys);
    w.m.set_i(sys, Field::_single_fire, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    K1Record r = w.step();
    EXPECT_EQ(w.brief(r), "DONE");
    EXPECT_EQ(w.writes(r),
              (std::vector<std::string>{
                  "beam._firing=True", "beam._target=t",
                  "beam._target_offset=walk_offset",
                  "beam._beam_on_countdown=0.66000000000000003",
                  "beam._dwell=0", "tr._next_emitter_index=0",
                  "tr._was_firing=True"}));
    EXPECT_EQ(w.entries(r), (std::vector<std::string>{
                                "FIRE_SOUND beam^5", "TRACTOR_STARTED tr^7"}));
    EXPECT_EQ(w.k.counts().logged_tractor_walk, 1);
    EXPECT_EQ(w.k.counts().python_systems, 0);
    w.k.end();

    // Out of range: dropped (the mixin's stop, LOOP_STOP), intent kept.
    w.store.set_position(static_cast<uint32_t>(w.m.object(t)->xform_index),
                         static_cast<uint32_t>(w.m.object(t)->xform_gen), 0.0,
                         125.0, 0.0);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    r = w.step();
    EXPECT_EQ(w.writes(r), (std::vector<std::string>{
                               "beam._firing=False",
                               "beam._beam_on_countdown=0",
                               "tr._was_firing=False"}));
    EXPECT_EQ(w.entries(r), (std::vector<std::string>{
                                "LOOP_STOP beam^2", "TRACTOR_STOPPED tr^3"}));
    EXPECT_EQ(w.m.get_i(sys, Field::_fire_held), 1);
    EXPECT_EQ(w.m.get_i(beam, Field::_firing), 0);
    w.k.end();
}

// A tractor walk the mirror cannot read does not fire that tick: nothing
// written, nothing queued, counted (no Python hand-back).
TEST(K1, TractorWalkTheMirrorCannotReadDoesNotFire) {
    World w(false);
    w.m.set_global_f(Global::TRACTOR_MAX_RANGE_GU, 120.0);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("tr", ship, 3, {t});
    w.bank("beam", sys);
    w.m.set_i(t, Field::has_real_is_dead, 0);   // a stub IsDead
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record r = w.step();
    EXPECT_EQ(w.brief(r), "DONE");
    EXPECT_TRUE(r.writes.empty());
    EXPECT_TRUE(r.entries.empty());
    EXPECT_EQ(w.k.counts().no_fire[static_cast<size_t>(K1NoFire::TractorRow)],
              1);
    EXPECT_EQ(w.k.counts().python_systems, 0);
    EXPECT_EQ(w.k.counts().entries[static_cast<size_t>(
                  K1Effect::TRACTOR_STARTED)], 0);
    w.k.end();
}

// StartFiring's session: the engage with the session's own offset (walk 1)
// and the sync; nothing for a target out of range but the intent Python
// wrote.
TEST(K1, TractorStartSession) {
    World w(false);
    w.m.set_global_f(Global::TRACTOR_MAX_RANGE_GU, 120.0);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("tr", ship, 3, {t});
    w.bank("beam", sys);
    w.m.set_i(sys, Field::_single_fire, 1);
    w.k.begin_tractor(sys, t, Vec3{0.5, 0.0, 0.0}, 10.0, false, 0.0);
    K1Record r = w.step();
    EXPECT_EQ(w.brief(r), "DONE");
    ASSERT_EQ(r.writes.size(), 7u);
    EXPECT_EQ(std::get<K1WalkOffset>(r.writes[2].value).walk, 1);
    EXPECT_EQ(w.entries(r).back(), "TRACTOR_STARTED tr^7");
    EXPECT_EQ(w.k.counts().logged_tractor_start, 1);
    w.k.end();

    World far(false);
    far.m.set_global_f(Global::TRACTOR_MAX_RANGE_GU, 120.0);
    const int64_t s2 = far.ship("ship");
    const int64_t t2 = far.object("t", 0.0, 130.0, 0.0);
    const int64_t sys2 = far.system("tr", s2, 3, {t2});
    far.bank("beam", sys2);
    far.k.begin_tractor(sys2, t2, std::nullopt, 10.0, false, 0.0);
    r = far.step();
    EXPECT_TRUE(r.writes.empty());
    EXPECT_TRUE(r.entries.empty());
    far.k.end();
}

// ── Task 3 fix round 1 ──────────────────────────────────────────────────────

// Getter 2 is never handed to Python: a ship whose tractor system the
// mirror cannot name (-2, e.g. its row dropped) and a ship with no row are
// each a counted no-fire, and the pump goes on.
TEST(K1, TractorGetterIsNeverHandedBack) {
    {
        World w(false);
        w.m.set_global_f(Global::TRACTOR_MAX_RANGE_GU, 120.0);
        const int64_t ship = w.ship("ship");
        w.m.set_ref(ship, Field::_tractor_beam_system, kRefUnrepresentable);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        const K1Record r = w.step();
        EXPECT_EQ(w.brief(r), "DONE");
        EXPECT_EQ(w.k.counts().python_systems, 0);
        EXPECT_EQ(w.k.counts().no_fire[static_cast<size_t>(
                      K1NoFire::TractorRow)], 1);
        w.k.end();
    }
    {
        World w(false);
        w.k.begin_pump({-1}, kDt, 10.0, false, 0.0);
        EXPECT_EQ(w.run_to_done(),
                  (std::vector<std::string>{
                      "RUN_PYTHON -1 0 0", "RUN_PYTHON -1 0 1",
                      "RUN_PYTHON -1 0 3", "DONE"}));
        EXPECT_EQ(w.k.counts().no_fire[static_cast<size_t>(
                      K1NoFire::TractorRow)], 1);
    }
}

// Python's drop loop: `(not engageable) or (not in arc)` -- out of range
// the aim is never resolved, so a mount the mirror cannot place (a posed
// ship's stale part slot) does not stop the out-of-range drop.
TEST(K1, TractorDropOutOfRangeResolvesNoAim) {
    World w(false);
    w.m.set_global_f(Global::TRACTOR_MAX_RANGE_GU, 120.0);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 125.0, 0.0);
    const int64_t sys = w.system("tr", ship, 3, {t});
    const int64_t beam = w.bank("beam", sys);
    w.m.set_i(beam, Field::_firing, 1);
    w.m.set_i(sys, Field::_was_firing, 1);
    w.m.set_i(ship, Field::has_posed_parts, 1);  // its mount: slot stale
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record r = w.step();
    EXPECT_EQ(w.writes(r), (std::vector<std::string>{
                               "beam._firing=False",
                               "beam._beam_on_countdown=0",
                               "tr._was_firing=False"}));
    EXPECT_EQ(w.k.counts().no_fire[static_cast<size_t>(K1NoFire::TractorRow)],
              0);
    w.k.end();
}
