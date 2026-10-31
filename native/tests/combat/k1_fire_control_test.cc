// The K1 fire-control kernel (k1_fire_control.h) on hand-built mirror rows:
// the record sequence of the pump and the walk, the write log, the fallbacks
// and the session stack. The native-vs-Python differentials run from
// tests/unit/test_native_k1_dispatch.py and
// tests/integration/test_native_k1_differential.py (Tasks 5 and 6).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cstdint>
#include <cstdio>
#include <map>
#include <stdexcept>
#include <string>
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

    World() {
        m.set_global_f(Global::FIRE_TIMER_THRESHOLD, 0.33);
        m.set_global_f(Global::PHASER_MAX_RANGE_GU, 700.0);
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
        m.set_i(s, Field::pump_self_managed, kind == 3 ? 1 : 0);
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
        if (auto* s = std::get_if<std::string>(&v)) return *s;
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
            out.push_back(name(w.handle) + "." + w.field + "=" + v);
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
    {   // Crossing the threshold: attempt, and the timer resets to 0.0.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
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
        EXPECT_EQ(f.decision.shape, K1Decision::Shape::Beam);
        EXPECT_FALSE(f.decision.was_firing);
        EXPECT_EQ(w.m.get_f(b0, Field::_fire_timer), 0.0);
    }
    {   // _force_update bypasses the threshold (timer := 0.33), even at dt 0.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
        w.bank("b0", sys);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_system(sys, 0.0, 10.0, false, 0.0);
        w.step();
        const K1Record f = w.step();
        EXPECT_EQ(w.brief(f), "FIRE b0@t");
        EXPECT_EQ(w.writes(f)[1], "b0._fire_timer=0.33000000000000002");
    }
    {   // A lit beam ignores the threshold.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
        const int64_t b0 = w.bank("b0", sys);
        w.m.set_i(b0, Field::_firing, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        w.step();
        const K1Record f = w.step();
        EXPECT_EQ(w.brief(f), "FIRE b0@t");
        EXPECT_TRUE(f.decision.was_firing);
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
        const K1Record s = w.step();
        EXPECT_EQ(w.brief(s), "BANK_STOP b0");
        EXPECT_EQ(w.writes(s).back(), "b0._fire_timer=0");
        const K1Record done = w.step();
        EXPECT_EQ(w.writes(done), (std::vector<std::string>{
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
    const K1Record s = w.step();
    EXPECT_EQ(w.brief(s), "BANK_STOP b0");
    EXPECT_EQ(w.writes(s).back(), "b0._depleted=False");
    EXPECT_EQ(w.m.get_i(b0, Field::_depleted), 0);
}

TEST(K1, RoundRobinFromLastIdx) {
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
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
    const int64_t sys = w.system("sys", ship, 1, {t});
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
    const K1Record f = v.step();
    EXPECT_EQ(v.brief(f), "FIRE b1@t");
    EXPECT_EQ(v.writes(f), (std::vector<std::string>{
                               "b1._fire_timer=0.016666666666666666",
                               "b1._fire_timer=0"}));
    const K1Record vdone = v.step();
    EXPECT_EQ(v.writes(vdone),
              (std::vector<std::string>{"sys._force_update=False"}));
}

TEST(K1, GroupWalkAdvancesOnDryGroup) {
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
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
    // re-tries list[0] and the other entry: 1 + 2 FIRE_FAILED.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t1 = w.object("t1", 0.0, -50.0, 0.0);
    const int64_t t2 = w.object("t2", 10.0, -50.0, 0.0);
    const int64_t sys = w.system("tsys", ship, 4, {t1, t2});
    w.bank("tube", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.run_to_done(),
              (std::vector<std::string>{"WALK_START tsys", "FIRE_FAILED tube",
                                        "FIRE_FAILED tube", "FIRE_FAILED tube",
                                        "DONE"}));
    w.k.end();

    // The retry reads the list LIVE after the first failure: a handler that
    // kills t2 there leaves one retry (t1 again).
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.brief(w.step()), "FIRE_FAILED tube");
    w.m.set_i(t2, Field::_dead, 1);
    EXPECT_EQ(w.brief(w.step()), "FIRE_FAILED tube");
    EXPECT_EQ(w.brief(w.step()), "DONE");
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
    EXPECT_EQ(w.brief(w.step()), "FIRE b0@t1");
}

TEST(K1, DumbFireOnlyWithNoTargets) {
    {   // An empty list and a tube that cannot fire: stop, then dumb fire.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t sys = w.system("tsys", ship, 4, {});
        const int64_t tube = w.bank("tube", sys);
        w.m.set_i(tube, Field::_num_ready, 0);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        EXPECT_EQ(w.run_to_done(),
                  (std::vector<std::string>{"WALK_START tsys", "BANK_STOP tube",
                                            "FIRE_DUMB tube", "DONE"}));
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
        EXPECT_EQ(w.run_to_done(),
                  (std::vector<std::string>{"WALK_START tsys", "FIRE_FAILED tube",
                                            "FIRE_FAILED tube", "DONE"}));
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
                  (std::vector<std::string>{"WALK_START sys", "BANK_STOP b0",
                                            "DONE"}));
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
    {   // A tractor (self-managed) and a ship with no row (every getter).
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("tr", ship, 3, {t});
        w.bank("beam", sys);
        w.k.begin_pump({-1, ship}, kDt, 10.0, false, 0.0);
        EXPECT_EQ(w.run_to_done(),
                  (std::vector<std::string>{
                      "RUN_PYTHON -1 0 0", "RUN_PYTHON -1 0 1",
                      "RUN_PYTHON -1 0 2", "RUN_PYTHON -1 0 3",
                      "RUN_PYTHON tr 1 2", "DONE"}));
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
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    w.bank("b0", sys);
    w.bank("b1", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    const int64_t other = w.ship("other", 0.0, -100.0, 0.0);
    const int64_t osys = w.system("osys", other, 1, {t});
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
    const int64_t sys = w.system("sys", ship, 1, {t});
    w.bank("b0", sys);
    const int64_t b1 = w.bank("b1", sys);
    const int64_t psys = w.system("psys", ship, 2, {t});
    w.bank("cannon", psys);
    w.m.set_i(sys, Field::_force_update, 1);
    w.m.set_i(psys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.brief(w.step()), "FIRE b0@t");
    // A handler drains b1 and releases both triggers. The running walk keeps
    // its locals (Python does not re-check _fire_held mid-walk) but reads
    // b1's charge live; the pump then skips the released pulse system.
    w.m.set_f(b1, Field::_charge_level, 0.0);
    w.m.set_i(sys, Field::_fire_held, 0);
    w.m.set_i(psys, Field::_fire_held, 0);
    EXPECT_EQ(w.brief(w.step()), "BANK_STOP b1");
    EXPECT_EQ(w.brief(w.step()), "DONE");
}

TEST(K1, MidWalkThrowBecomesAsk) {
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
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
    // loop is asked.
    World v;
    const int64_t vship = v.ship("ship");
    const int64_t vt = v.object("t", 0.0, -50.0, 0.0);
    const int64_t vsys = v.system("tsys", vship, 4, {vt});
    const int64_t tube = v.bank("tube", vsys);
    v.m.set_i(vsys, Field::_force_update, 1);
    v.k.begin_pump({vship}, kDt, 10.0, false, 0.0);
    v.step();
    EXPECT_EQ(v.brief(v.step()), "FIRE_FAILED tube");
    v.m.set_ids(vsys, Field::_target_list, {vt, kRefUnrepresentable});
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
    const int64_t sys = w.system("sys", ship, 1, {t});
    w.bank("b0", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.run_to_done().size(), 3u);
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
        const int64_t sys = w.system("sys", ship, 1, {t});
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
        // The unnamed property also holds b1's MaxCondition (CanFire's
        // condition product): that is asked too.
        EXPECT_EQ(w.brief(w.step()), "ASK can_fire");
    }
    for (int64_t answer : {1, 2}) {  // group_step: an unnamed child
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
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
        const int64_t sys = w.system("sys", ship, 1, {t});
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
    {   // is_dead, then fire: a retry entry lost its real IsDead mid-loop.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t1 = w.object("t1", 0.0, -50.0, 0.0);
        const int64_t t2 = w.object("t2", 10.0, -50.0, 0.0);
        const int64_t sys = w.system("tsys", ship, 4, {t1, t2});
        const int64_t tube = w.bank("tube", sys);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        w.step();
        EXPECT_EQ(w.brief(w.step()), "FIRE_FAILED tube");
        EXPECT_EQ(w.brief(w.step()), "FIRE_FAILED tube");  // retry t1
        w.m.set_i(t2, Field::has_real_is_dead, 0);
        const K1Record d = w.step();
        EXPECT_EQ(w.brief(d), "ASK is_dead");
        EXPECT_EQ(d.args, (std::vector<int64_t>{t2}));
        w.k.answer(0);
        const K1Record f = w.step();
        EXPECT_EQ(w.brief(f), "ASK fire");
        EXPECT_EQ(f.args, (std::vector<int64_t>{sys, tube, t2}));
        w.k.answer(0);
        EXPECT_EQ(w.brief(w.step()), "DONE");
        EXPECT_EQ(w.k.counts().asks, 2);
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
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    const int64_t b0 = w.bank("b0", sys);
    w.m.set_ref(b0, Field::_target, t);
    w.m.set_f(b0, Field::_charge_level, 0.0);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.brief(w.step()), "BANK_STOP b0");
    // The effect's handler leaves the walked system's row gone.
    w.m.unregister_row(sys);
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
    const int64_t sys = w.system("sys", ship, 1, {t});
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
    // n = self.GetNumWeapons() is re-read for each group: a handler that
    // drops a child during group 1 changes group 2's rotation.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    const int64_t b0 = w.bank("b0", sys);
    const int64_t b1 = w.bank("b1", sys);
    const int64_t b2 = w.bank("b2", sys);
    const int64_t sp = w.m.register_row(Kind::Property);
    w.m.set_id_lists(sp, Field::_firing_chains, {{1, 2}});
    w.m.set_ref(sys, Field::_property, sp);
    w.m.set_ref(b0, Field::_property, w.prop(2));
    w.m.set_ref(b1, Field::_property, w.prop(2));
    w.m.set_ref(b2, Field::_property, w.prop(1));
    w.m.set_f(b2, Field::_charge_level, 0.0);  // group 1 runs dry
    w.m.set_i(sys, Field::_last_weapon_idx, 2);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.brief(w.step()), "BANK_STOP b2");
    w.m.set_ids(sys, Field::_children, {b0, b1});  // the handler drops b2
    // n = 2, base_idx 2: idx 1 then 0. (n kept at 3 would give 0, 1, None.)
    EXPECT_EQ(w.brief(w.step()), "FIRE b1@t");
    EXPECT_EQ(w.brief(w.step()), "FIRE b0@t");
    EXPECT_EQ(w.brief(w.step()), "DONE");
}

TEST(K1, RetryWalksItsSnapshot) {
    // for entry in list(self._target_list): the list is copied when the
    // retry starts; a handler's later change does not alter the loop.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t1 = w.object("t1", 0.0, -50.0, 0.0);
    const int64_t t2 = w.object("t2", 10.0, -50.0, 0.0);
    const int64_t sys = w.system("tsys", ship, 4, {t1, t2});
    w.bank("tube", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.brief(w.step()), "FIRE_FAILED tube");  // Fire(t1)
    EXPECT_EQ(w.brief(w.step()), "FIRE_FAILED tube");  // retry t1
    w.m.set_ids(sys, Field::_target_list, {t1});       // the handler drops t2
    EXPECT_EQ(w.brief(w.step()), "FIRE_FAILED tube");  // retry t2 (snapshot)
    EXPECT_EQ(w.brief(w.step()), "DONE");
}
