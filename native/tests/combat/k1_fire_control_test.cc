// The K1 fire-control kernel (k1_fire_control.h) on hand-built mirror rows:
// the pump and the walk, the write log and the queue entries of a session's
// one record, the no-fires (NO FIRE) and the session stack. Fire control's
// Python copy is deleted (fire control native only, M3): the end-to-end
// checks are tests/unit/test_native_k1_dispatch.py (recorded expectations)
// and tests/integration/test_golden_fights.py.
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
#include "dauntless/combat/weapon_geometry.h"
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
        if (kind == 4) {  // its ammo type's launch cached: tubes launch
            const int64_t ammo = m.register_row(Kind::Ammo);
            m.set_i(ammo, Field::_unlimited, 1);
            m.set_i(ammo, Field::ammo_launch_state, 1);
            m.set_f(ammo, Field::ammo_launch_speed, 19.0);
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
        if (kind == 8) {  // its one slot loaded
            m.set_floats(b, Field::_reload_timers, {-1.0});
            m.set_floats(b, Field::_reload_advanced_at, {0.0});
        }
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
    // The record's kind (DONE: a session has no other).
    std::string brief(const K1Record& r) const { return k1_kind_name(r.kind); }
    // The session's one record.
    K1Record step() { return k.next(); }
    // One no-fire why's count.
    int64_t no_fire(K1NoFire why) const {
        return k.counts().no_fire[static_cast<size_t>(why)];
    }
    int64_t no_fires() const {
        int64_t n = 0;
        for (int64_t c : k.counts().no_fire) n += c;
        return n;
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
// is: a tube's Fire decision at it cannot be made (a Decision no-fire;
// an offset no mount claims is a plain point, fire control native only M5).
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
    // _can_engage. Each stops the system (its logged stop) with no walk.
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
        EXPECT_EQ(w.brief(r), "DONE") << "gate " << gate;
        EXPECT_EQ(w.writes(r).front(), "sys._fire_held=False") << "gate " << gate;
        EXPECT_EQ(w.k.counts().logged_system_stop, 1) << "gate " << gate;
        EXPECT_EQ(w.k.counts().logged_walk_start, 0) << "gate " << gate;
        // can_detect (memo, latch) runs only once the earlier gates passed;
        // the cloak gate answers before the latch is touched.
        const bool detect_ran = gate >= 2;
        EXPECT_EQ(w.m.sensor_state().memo.empty(), !detect_ran) << "gate " << gate;
        EXPECT_EQ(latched(w.m, ship, held), gate != 3) << "gate " << gate;
        w.k.end();
    }
    // A torpedo system has no range gate: the same far target walks.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t far = w.object("far", 0.0, 1500.0, 0.0);
    const int64_t sys = w.system("tsys", ship, 4, {far});
    w.bank("tube", sys);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.k.counts().logged_walk_start, 1);
    EXPECT_EQ(w.k.counts().logged_system_stop, 0);
}

TEST(K1, StopGatesRunBeforeTheWalkOnlyPrescan) {
    // A held system the pump's gates stop is stopped even when its WALK
    // could not be read (host_loop._pump_held_system ran the gates first,
    // then update_weapons): only what the gates themselves read is checked
    // ahead of them. A pulse system whose held target died has no live
    // target-list entry (PulseShipTarget, the walk's), and the held-dead
    // gate stops it; each walk-only reason under an offline system
    // likewise.
    using I = int64_t;
    struct Case {
        const char* name;
        int64_t kind;
        void (*setup)(World&, I ship, I t, I sys, I b0);
    };
    const Case cases[] = {
        {"pulse held dead", 2,
         [](World& w, I, I t, I, I) { w.m.set_i(t, Field::_dead, 1); }},
        {"pulse module, off", 2,
         [](World& w, I, I, I sys, I b0) {
             w.m.set_i(b0, Field::module_ok, 0);
             w.m.set_i(sys, Field::_is_on, 0);
         }},
        {"part stale, off", 1,
         [](World& w, I ship, I, I sys, I) {
             w.m.set_i(ship, Field::has_posed_parts, 1);
             w.m.set_i(sys, Field::_is_on, 0);
         }},
        {"target list entry, off", 1,
         [](World& w, I, I t, I sys, I) {
             w.m.set_ids(sys, Field::_target_list, {t, kRefUnrepresentable});
             w.m.set_i(sys, Field::_is_on, 0);
         }},
        {"ammo row, off", 4,
         [](World& w, I, I, I sys, I) {
             const int64_t gone = w.m.register_row(Kind::Ammo);
             w.m.set_ids(sys, Field::_ammo_by_slot, {0, gone});
             w.m.unregister_row(gone);
             w.m.set_i(sys, Field::_is_on, 0);
         }},
    };
    for (const Case& c : cases) {
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, c.kind, {t});
        const int64_t b0 = w.bank("b0", sys);
        c.setup(w, ship, t, sys, b0);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        const K1Record r = w.step();
        EXPECT_EQ(w.brief(r), "DONE") << c.name;
        EXPECT_EQ(w.m.get_i(sys, Field::_fire_held), 0) << c.name;
        EXPECT_EQ(w.k.counts().logged_system_stop, 1) << c.name;
        EXPECT_EQ(w.k.counts().logged_walk_start, 0) << c.name;
        EXPECT_EQ(w.no_fires(), 0) << c.name;
        w.k.end();
    }
}

TEST(K1, TargetWithNoRealIsDeadReadsAsDead) {
    // `hasattr(x, "IsDead") and x.IsDead()` on an object whose class has no
    // IsDead (a planet: AI or a script can SetTarget one) is a truthy _Stub:
    // dead. Held, the pump's IsDead gate stops the system; listed, the
    // walk's prune drops it. Neither is a no-fire.
    for (const int64_t kind : {int64_t{1}, int64_t{4}}) {
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t planet = w.object("planet", 0.0, 50.0, 0.0);
        w.m.set_i(planet, Field::has_real_is_dead, 0);
        const int64_t sys = w.system("sys", ship, kind, {planet});
        w.bank("b0", sys);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        const K1Record r = w.step();
        EXPECT_EQ(w.brief(r), "DONE") << kind;
        EXPECT_EQ(w.m.get_i(sys, Field::_fire_held), 0) << kind;
        EXPECT_EQ(w.k.counts().logged_system_stop, 1) << kind;
        EXPECT_EQ(w.no_fires(), 0) << kind;
        w.k.end();
    }
    // Listed behind a live held target: pruned, the walk goes on.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t planet = w.object("planet", 0.0, 60.0, 0.0);
    w.m.set_i(planet, Field::has_real_is_dead, 0);
    const int64_t sys = w.system("sys", ship, 1, {planet, t});
    w.m.set_ref(sys, Field::_held_target, t);
    w.bank("b0", sys);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record r = w.step();
    EXPECT_EQ(w.k.counts().logged_walk_start, 1);
    EXPECT_EQ(w.m.get_ids(sys, Field::_target_list), std::vector<int64_t>{t});
    EXPECT_EQ(w.no_fires(), 0);
    (void)r;
    w.k.end();
}

TEST(K1, TractorOnATargetWithNoRealIsDeadStops) {
    // A tractor engaged on a planet-like object: the update's IsDead gate
    // reads it as dead and stops the system (its projectors stop, the drain
    // ends) -- not a throw rolled back every tick with the beam held.
    World w;
    w.m.set_global_f(Global::TRACTOR_MAX_RANGE_GU, 120.0);
    const int64_t ship = w.ship("ship");
    const int64_t planet = w.object("planet", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("tr", ship, 3, {planet});
    const int64_t beam = w.bank("beam", sys);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();                                   // gripped
    w.k.end();
    ASSERT_EQ(w.m.get_i(beam, Field::_firing), 1);
    w.m.set_i(planet, Field::has_real_is_dead, 0);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.m.get_i(sys, Field::_fire_held), 0);
    EXPECT_EQ(w.m.get_i(beam, Field::_firing), 0);
    EXPECT_EQ(w.no_fires(), 0);
    w.k.end();
}

TEST(K1, TimerGateAndForceUpdate) {
    {   // Below the 0.33 s threshold: no attempt, the timer only accumulates.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
        const int64_t b0 = w.bank("b0", sys);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        const K1Record done = w.step();
        EXPECT_EQ(w.brief(done), "DONE");
        char dt[64];
        std::snprintf(dt, sizeof dt, "%.17g", 0.0 + kDt);
        EXPECT_EQ(w.writes(done),
                  (std::vector<std::string>{
                      "sys._target_list=[t]", "sys._group_fire_mode=0",
                      std::string("b0._fire_timer=") + dt, "b0._target=None",
                      "sys._force_update=False"}));
        EXPECT_EQ(w.m.get_f(b0, Field::_fire_timer), 0.0 + kDt);
    }
    {   // Crossing the threshold: attempt, and the timer resets to 0.0 (a
        // tube: its launch).
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 4, {t});
        const int64_t b0 = w.bank("b0", sys);
        w.m.set_f(b0, Field::_fire_timer, 0.30);
        w.k.begin_pump({ship}, 0.05, 10.0, false, 0.0);
        const K1Record f = w.step();
        EXPECT_EQ(writes_on(w, f, "b0")[0], "b0._fire_timer=0.34999999999999998");
        EXPECT_EQ(writes_on(w, f, "b0")[1], "b0._fire_timer=0");
        EXPECT_EQ(fx(w, f), (std::vector<std::string>{
                                "SPAWN b0@t", "WEAPON_FIRED b0@t",
                                "AMMO_CONSUMED b0"}));
        EXPECT_EQ(w.m.get_f(b0, Field::_fire_timer), 0.0);
        EXPECT_EQ(w.k.counts().logged_tube_launch, 1);
    }
    {   // _force_update bypasses the threshold (timer := 0.33), even at dt 0.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 4, {t});
        w.bank("b0", sys);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_system(sys, 0.0, 10.0, false, 0.0);
        const K1Record f = w.step();
        EXPECT_EQ(writes_on(w, f, "b0")[0], "b0._fire_timer=0.33000000000000002");
        EXPECT_EQ(w.k.counts().logged_tube_launch, 1);
    }
    {   // A lit beam ignores the threshold (its sustain is logged writes).
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
        const int64_t b0 = w.bank("b0", sys);
        w.m.set_i(b0, Field::_firing, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        const K1Record f = w.step();
        EXPECT_EQ(w.brief(f), "DONE");
        const auto b0w = writes_on(w, f, "b0");
        ASSERT_EQ(b0w.size(), 4u);
        EXPECT_EQ(b0w[1], "b0._fire_timer=0");
        // The sustain's stamps, in _fire_effect's order (WS:895-898): the
        // target, then the walk's offset OBJECT (the marker). `_firing` is
        // already True: not logged (phase 6 A3).
        EXPECT_EQ(b0w[2], "b0._target=t");
        EXPECT_EQ(b0w[3], "b0._target_offset=walk_offset");
        EXPECT_EQ(w.k.counts().logged_beam_sustain_skips, 1);
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
        // The idle bank's StopFiring is logged (round trips Task 2).
        const K1Record done = w.step();
        EXPECT_EQ(w.brief(done), "DONE");
        EXPECT_EQ(w.writes(done), (std::vector<std::string>{
                                      "sys._target_list=[t]",
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
    // b0's stop is logged (idle), the clear before the stop.
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
    // Tubes, multi fire: the rotation shows in the launches' order (skew
    // fire: exempt from the ship-wide stagger, so every tube launches).
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});
    for (const char* n : {"b0", "b1", "b2"})
        w.m.set_i(w.bank(n, sys), Field::_skew_fire, 1);
    w.m.set_i(sys, Field::_last_weapon_idx, 1);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record done = w.step();
    std::vector<std::string> spawns;
    for (const std::string& e : fx(w, done))
        if (e.rfind("SPAWN", 0) == 0) spawns.push_back(e);
    EXPECT_EQ(spawns, (std::vector<std::string>{"SPAWN b2@t", "SPAWN b0@t",
                                                "SPAWN b1@t"}));
    // base_idx is captured once: the cursor writes do not move the rotation.
    std::vector<std::string> idx;
    for (const std::string& s : w.writes(done))
        if (s.rfind("sys._last_weapon_idx", 0) == 0) idx.push_back(s);
    EXPECT_EQ(idx, (std::vector<std::string>{"sys._last_weapon_idx=2",
                                             "sys._last_weapon_idx=0",
                                             "sys._last_weapon_idx=1"}));
    EXPECT_EQ(w.writes(done).back(), "sys._force_update=False");
}

TEST(K1, SingleFireReseedsTimers) {
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});
    const int64_t b0 = w.bank("b0", sys);
    const int64_t b1 = w.bank("b1", sys);
    const int64_t b2 = w.bank("b2", sys);
    w.m.set_i(sys, Field::_single_fire, 1);
    w.m.set_f(b1, Field::_fire_timer, 0.1);
    w.m.set_f(b2, Field::_fire_timer, 0.2);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record done = w.step();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_EQ(writes_from(w, done, "sys._last_weapon_idx=0", 6),
              (std::vector<std::string>{
                  "sys._last_weapon_idx=0", "sys._last_group_fired=0",
                  "b0._fire_timer=0", "b1._fire_timer=0", "b2._fire_timer=0",
                  "sys._force_update=False"}));
    EXPECT_EQ(w.k.counts().logged_tube_launch, 1);  // one shot: single fire
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
    const K1Record vdone = v.step();
    EXPECT_EQ(v.brief(vdone), "DONE");
    EXPECT_EQ(v.writes(vdone), (std::vector<std::string>{
                                   "sys._target_list=[t]",
                                   "b1._fire_timer=0.016666666666666666",
                                   "b1._fire_timer=0", "b1._target=t",
                                   "b1._target_offset=walk_offset",
                                   "sys._force_update=False"}));
}

TEST(K1, GroupWalkAdvancesOnDryGroup) {
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});
    const int64_t b0 = w.bank("b0", sys);
    const int64_t b1 = w.bank("b1", sys);
    const int64_t sp = w.m.register_row(Kind::Property);
    w.m.set_id_lists(sp, Field::_firing_chains, {{1, 2}});
    w.m.set_ref(sys, Field::_property, sp);
    w.m.set_ref(b0, Field::_property, w.prop(1));  // group 1
    w.m.set_ref(b1, Field::_property, w.prop(2));  // group 2
    w.m.set_f(b1, Field::_fire_timer, 0.4);        // only b1 is due
    w.k.begin_pump({ship}, 0.0, 10.0, false, 0.0);
    const K1Record f = w.step();
    EXPECT_EQ(writes_from(w, f, "sys._group_fire_mode=1", 6),
              (std::vector<std::string>{
                  "sys._group_fire_mode=1", "b0._fire_timer=0",
                  "b0._target=None", "sys._group_fire_mode=2",
                  "b1._fire_timer=0.40000000000000002", "b1._fire_timer=0"}));
    EXPECT_EQ(fx(w, f).front(), "SPAWN b1@t");
    const auto ws = w.writes(f);
    ASSERT_GE(ws.size(), 3u);
    EXPECT_EQ((std::vector<std::string>(ws.end() - 3, ws.end())),
              (std::vector<std::string>{"sys._last_weapon_idx=1",
                                        "sys._last_group_fired=2",
                                        "sys._force_update=False"}));
    w.k.end();

    // Every group dry: the walk wraps to its start and clears the resume.
    w.m.set_f(b1, Field::_fire_timer, 0.0);
    w.k.begin_pump({ship}, 0.0, 10.0, false, 0.0);
    const K1Record dry = w.step();
    EXPECT_EQ(w.brief(dry), "DONE");
    const auto dws = w.writes(dry);
    ASSERT_GE(dws.size(), 3u);
    EXPECT_EQ(dws[dws.size() - 2], "sys._last_group_fired=-1");
    EXPECT_EQ(dws.back(), "sys._force_update=False");
    // _last_group_fired (2, from the first walk) was the working group.
    EXPECT_EQ(dws[1], "sys._group_fire_mode=2");
}

TEST(K1, TubeRetryPostsFailedPerAttempt) {
    // Both targets are behind the tube: Fire(list[0]) fails, then the retry
    // re-tries list[0] and the other entry: 1 + 2 WEAPON_FIRE_FAILED
    // entries.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t1 = w.object("t1", 0.0, -50.0, 0.0);
    const int64_t t2 = w.object("t2", 10.0, -50.0, 0.0);
    const int64_t sys = w.system("tsys", ship, 4, {t1, t2});
    w.bank("tube", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record done = w.step();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_EQ(fx(w, done), (std::vector<std::string>(
                               3, "WEAPON_FIRE_FAILED tube")));
    EXPECT_EQ(w.no_fires(), 0);
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
    // The beam's edge: logged, its ET_WEAPON_FIRED aimed at t1.
    const K1Record done = w.step();
    EXPECT_EQ(w.brief(done), "DONE");
    EXPECT_EQ(fx(w, done), (std::vector<std::string>{"FIRE_SOUND b0",
                                                     "WEAPON_FIRED b0@t1"}));
}

TEST(K1, DumbFireOnlyWithNoTargets) {
    {   // An empty list and a tube that cannot fire: stop (idle: logged),
        // then dumb fire -- whose Fire refuses too, decided natively.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t sys = w.system("tsys", ship, 4, {});
        const int64_t tube = w.bank("tube", sys);
        w.m.set_i(tube, Field::_num_ready, 0);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        EXPECT_EQ(w.brief(w.step()), "DONE");
        EXPECT_EQ(w.k.counts().logged_idle_bank_stop, 1);
        EXPECT_EQ(w.k.counts().logged_dumb_refused, 1);
    }
    {   // An empty list and a ready tube: Fire(None) fires dumb itself (the
        // walk's own Fire: a tube launch at no target).
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t sys = w.system("tsys", ship, 4, {});
        w.bank("tube", sys);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        const K1Record f = w.step();
        EXPECT_EQ(fx(w, f), (std::vector<std::string>{
                                "SPAWN tube@None", "WEAPON_FIRED tube@None",
                                "AMMO_CONSUMED tube"}));
        EXPECT_EQ(w.k.counts().logged_tube_launch, 1);
    }
    {   // A failure with a target in the list never dumb-fires.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, -50.0, 0.0);
        const int64_t sys = w.system("tsys", ship, 4, {t});
        w.bank("tube", sys);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        const K1Record done = w.step();
        EXPECT_EQ(w.brief(done), "DONE");
        EXPECT_EQ(fx(w, done), (std::vector<std::string>(
                                   2, "WEAPON_FIRE_FAILED tube")));
        EXPECT_EQ(w.k.counts().logged_dumb_launch, 0);
    }
    {   // A phaser bank is not dumb-fire capable.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t sys = w.system("sys", ship, 1, {});
        const int64_t b0 = w.bank("b0", sys);
        w.m.set_f(b0, Field::_charge_level, 0.0);
        w.m.set_i(sys, Field::_force_update, 1);
        w.k.begin_system(sys, 0.0, 10.0, false, 0.0);
        EXPECT_EQ(w.brief(w.step()), "DONE");
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
    w.m.set_fv(sys, Field::_held_offset, {1.0, 2.0, 3.0});
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record f = w.step();
    // The stamps, then the launch's SPAWN after them.
    const auto cw = writes_on(w, f, "cannon");
    ASSERT_GE(cw.size(), 4u);
    EXPECT_EQ(cw[2], "cannon._target=t");
    EXPECT_EQ(cw[3], "cannon._target_offset=walk_offset");
    EXPECT_EQ(fx(w, f), (std::vector<std::string>{"SPAWN cannon@t"}));
    EXPECT_EQ(w.m.get_fv(c, Field::_target_offset),
              (std::vector<double>{1.0, 2.0, 3.0}));
    EXPECT_EQ(w.k.counts().logged_pulse_launch, 1);
    w.k.end();

    // Out of the arc: the stamps persist, _target is cleared again after,
    // _target_offset is not.
    World v;
    const int64_t vship = v.ship("ship");
    const int64_t vt = v.object("t", 0.0, -50.0, 0.0);
    const int64_t vsys = v.system("psys", vship, 2, {vt});
    const int64_t vc = v.bank("cannon", vsys);
    v.m.set_i(vsys, Field::_force_update, 1);
    v.k.begin_pump({vship}, kDt, 10.0, false, 0.0);
    const K1Record done = v.step();
    EXPECT_EQ(v.brief(done), "DONE");
    EXPECT_EQ(v.writes(done), (std::vector<std::string>{
                                  "psys._target_list=[t]",
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

TEST(K1, NoFireBeforeAnyWrite) {
    // Whatever the pre-scan finds the mirror cannot represent: the system
    // does not fire that tick, nothing written, counted by why (NO FIRE).
    auto no_fire = [](auto&& setup, K1NoFire want) {
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
        EXPECT_EQ(w.brief(r), "DONE");
        EXPECT_TRUE(r.writes.empty()) << k1_no_fire_name(want);
        EXPECT_EQ(w.m.epoch(), before) << k1_no_fire_name(want);
        EXPECT_EQ(w.no_fire(want), 1) << k1_no_fire_name(want);
        EXPECT_EQ(w.no_fires(), 1) << k1_no_fire_name(want);
        EXPECT_EQ(r.no_fire_new, uint64_t{1} << static_cast<int>(want));
    };
    using I = int64_t;
    no_fire([](World& w, I ship, I, I, I) {
        w.m.set_i(ship, Field::has_posed_parts, 1);
    }, K1NoFire::PartStale);
    no_fire([](World& w, I, I t, I sys, I) {
        w.m.set_ids(sys, Field::_target_list, {t, kRefUnrepresentable});
    }, K1NoFire::StaleRow);
    // The FIRING ship with no real IsDead (a target with none reads as
    // dead: TargetWithNoRealIsDeadReadsAsDead).
    no_fire([](World& w, I ship, I, I, I) {
        w.m.set_i(ship, Field::has_real_is_dead, 0);
    }, K1NoFire::StubOrUnplaced);
    {   // A ship with no row: none of its systems fires (counted once).
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("tr", ship, 3, {t});
        w.bank("beam", sys);
        w.k.begin_pump({-1, ship}, kDt, 10.0, false, 0.0);
        EXPECT_EQ(w.brief(w.step()), "DONE");
        EXPECT_EQ(w.no_fire(K1NoFire::UnslottedShip), 1);
        EXPECT_EQ(w.no_fires(), 1);
    }
    {   // A system session: the same, nothing written.
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, 1, {t});
        w.bank("b0", sys);
        w.m.set_i(ship, Field::has_posed_parts, 1);
        w.k.begin_system(sys, 0.0, 10.0, false, 0.0);
        const K1Record r = w.step();
        EXPECT_TRUE(r.writes.empty());
        EXPECT_EQ(w.no_fire(K1NoFire::PartStale), 1);
    }
}

TEST(K1, ReentrantSessionStack) {
    // An effect's handler, delivered at a session's end, may StartFiring: a
    // nested one-system session runs whole before the outer one resumes.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});
    w.bank("b0", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    const int64_t other = w.ship("other", 0.0, -100.0, 0.0);
    const int64_t osys = w.system("osys", other, 4, {t});
    w.bank("ob", osys);
    w.m.set_i(osys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.k.begin_system(osys, 0.0, 10.0, false, 0.0);
    EXPECT_EQ(w.k.depth(), 2u);
    const K1Record inner = w.step();
    EXPECT_EQ(fx(w, inner).front(), "SPAWN ob@t");
    w.k.end();
    EXPECT_EQ(w.k.depth(), 1u);
    const K1Record outer = w.step();
    EXPECT_EQ(fx(w, outer).front(), "SPAWN b0@t");
    w.k.end();
    EXPECT_EQ(w.k.depth(), 0u);
    EXPECT_THROW(w.k.next(), std::logic_error);
    EXPECT_EQ(w.k.counts().records, 2);
}

TEST(K1, CountsAndKinds) {
    EXPECT_STREQ(k1_kind_name(K1Kind::DONE), "DONE");
    EXPECT_EQ(static_cast<int>(K1Kind::kCount), 1);
    EXPECT_STREQ(k1_no_fire_name(K1NoFire::Launch), "launch");
    EXPECT_STREQ(k1_no_fire_name(K1NoFire::IsDead), "is_dead");
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});
    w.bank("b0", sys);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.brief(w.step()), "DONE");  // one record a session
    EXPECT_EQ(w.k.counts().records, 1);
    EXPECT_THROW(w.k.next(), std::logic_error);  // already DONE
    w.k.end();
    // A system with no row does not fire (a stale row).
    w.k.begin_system(-1, 0.0, 0.0, false, 0.0);
    EXPECT_EQ(w.brief(w.step()), "DONE");
    EXPECT_EQ(w.no_fire(K1NoFire::StaleRow), 1);
    w.k.end();
    w.k.reset_counts();
    EXPECT_EQ(w.no_fires(), 0);
    EXPECT_EQ(w.k.counts().no_fire_reported, uint64_t{0});
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
        w.step();
        EXPECT_EQ(w.m.sensor_state().mounts.empty(), !use_memo);
        EXPECT_EQ(w.m.sensor_state().memo.empty(), !use_memo);
    }
}

TEST(K1, RangeGateNeverThrowsAfterCanDetect) {
    // The phaser range gate reads both containing sets. An unnamed one is a
    // no-fire found BEFORE can_detect writes its memo / latch.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    w.bank("b0", sys);
    w.m.set_ref(ship, Field::_containing_set, kRefUnrepresentable);
    w.k.begin_pump({ship}, kDt, 10.0, true, 0.0);
    const K1Record r = w.step();
    EXPECT_TRUE(r.writes.empty());
    EXPECT_EQ(w.no_fire(K1NoFire::StaleRow), 1);
    EXPECT_TRUE(w.m.sensor_state().memo.empty());
}

TEST(K1, NoFireBeforeTheFirstShotRollsTheWalkBack) {
    // NO FIRE (R2): a Fire decision the mirror cannot make (a posed target
    // whose mount it cannot tell) before the walk's first shot rolls the
    // walk back -- its pruned list, its timers -- and the walk ends: the
    // mirror is as if it had not walked, and nothing is logged.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t sys = w.system("sys", ship, 4, {});
    const int64_t b0 = w.bank("b0", sys);
    const int64_t t = posed_target(w, "t", 0.0, 50.0, 0.0, b0);
    w.m.set_ids(sys, Field::_target_list, {t});
    w.m.set_ref(sys, Field::_held_target, t);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record r = w.step();
    EXPECT_EQ(w.brief(r), "DONE");
    EXPECT_TRUE(r.writes.empty()) << ::testing::PrintToString(w.writes(r));
    EXPECT_TRUE(r.entries.empty());
    EXPECT_EQ(w.no_fire(K1NoFire::Decision), 1);
    EXPECT_EQ(w.m.get_i(sys, Field::_force_update), 1);   // not consumed
    EXPECT_EQ(w.m.get_f(b0, Field::_fire_timer), 0.0);
    EXPECT_EQ(w.k.counts().logged_tube_launch, 0);
}

TEST(K1, NoFireAfterTheFirstShotKeepsTheShot) {
    // NO FIRE (R2): b0 launches at t, then b1's decision cannot be made (its
    // stored offset names a mount the mirror cannot tell): the shot is
    // kept, the walk ends there (no `_force_update = False`). Skew fire:
    // exempt from the ship-wide stagger, so b1 is tried.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t sys = w.system("sys", ship, 4, {});
    const int64_t b0 = w.bank("b0", sys);
    const int64_t b1 = w.bank("b1", sys);
    w.m.set_i(b0, Field::_skew_fire, 1);
    w.m.set_i(b1, Field::_skew_fire, 1);
    const int64_t t = posed_target(w, "t", 0.0, 50.0, 0.0, b1);
    w.m.set_fv(b0, Field::_target_offset, {});   // b0 aims at the centre
    w.m.set_ids(sys, Field::_target_list, {t});
    w.m.set_ref(sys, Field::_held_target, t);
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record r = w.step();
    EXPECT_EQ(fx(w, r), (std::vector<std::string>{
                            "SPAWN b0@t", "WEAPON_FIRED b0@t",
                            "AMMO_CONSUMED b0"}));
    EXPECT_EQ(w.k.counts().logged_tube_launch, 1);
    EXPECT_EQ(w.no_fire(K1NoFire::Decision), 1);
    // Kept: b0's shot and bookkeeping, b1's passed timer gate; b1's
    // decision writes nothing (its own rollback), nor anything after it.
    EXPECT_TRUE(has_write(w, r, "sys._last_group_fired=0"));
    EXPECT_EQ(w.writes(r).back(), "b1._fire_timer=0");
    EXPECT_EQ(w.m.get_i(sys, Field::_force_update), 1);
    EXPECT_EQ(w.m.get_i(b0, Field::_num_ready), 0);
}



TEST(K1, NoneAmmoSlotWalksNatively) {
    // A torpedo system whose slot holds None (-1) is no no-fire at the
    // pre-scan: the tube gate reads it as "no ammo configured", as Python
    // did, and the launch is the hardpoint's slot-0 script's (none here:
    // the launch cannot be made, a counted no-fire of its own).
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 4, {t});
    w.bank("b0", sys);
    w.m.set_ids(sys, Field::_ammo_by_slot, {0, -1});
    w.m.set_i(sys, Field::_force_update, 1);  // past the fire timer
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.step();
    EXPECT_EQ(w.k.counts().logged_walk_start, 1);
    EXPECT_EQ(w.no_fire(K1NoFire::Launch), 1);
    EXPECT_EQ(w.no_fires(), 1);
}

TEST(K1, NoFireReasonsAreCounted) {
    // One pump over one phaser (or `kind`) system, set up not to fire.
    auto pump = [](int64_t kind, auto&& setup, K1NoFire want) {
        World w;
        const int64_t ship = w.ship("ship");
        const int64_t t = w.object("t", 0.0, 50.0, 0.0);
        const int64_t sys = w.system("sys", ship, kind, {t});
        const int64_t b0 = w.bank("b0", sys);
        setup(w, ship, t, sys, b0);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        const K1Record r = w.step();
        EXPECT_EQ(r.kind, K1Kind::DONE) << k1_no_fire_name(want);
        EXPECT_EQ(w.no_fire(want), 1) << k1_no_fire_name(want);
        EXPECT_EQ(w.no_fires(), 1) << k1_no_fire_name(want);
    };
    using I = int64_t;
    // A posed ship whose bank's part slot was never resolved (stamp 0).
    pump(1, [](World& w, I ship, I, I, I) {
        w.m.set_i(ship, Field::has_posed_parts, 1);
    }, K1NoFire::PartStale);
    pump(1, [](World& w, I ship, I, I, I) {
        w.m.set_i(ship, Field::has_real_is_dead, 0);   // the firing ship's
    }, K1NoFire::StubOrUnplaced);
    pump(1, [](World& w, I, I t, I sys, I) {
        w.m.set_ids(sys, Field::_target_list, {t, kRefUnrepresentable});
    }, K1NoFire::StaleRow);
    pump(2, [](World& w, I, I, I, I c) {
        w.m.set_i(c, Field::module_ok, 0);
    }, K1NoFire::PulseModule);
    pump(2, [](World& w, I, I, I sys, I) {
        w.m.set_ids(sys, Field::_target_list, {});
    }, K1NoFire::PulseShipTarget);
    pump(4, [](World& w, I, I, I sys, I) {
        const int64_t gone = w.m.register_row(Kind::Ammo);
        w.m.set_ids(sys, Field::_ammo_by_slot, {0, gone});
        w.m.unregister_row(gone);
    }, K1NoFire::AmmoRow);
    pump(1, [](World& w, I, I, I sys, I) {
        w.m.set_i(sys, Field::weapon_kind, 0);   // a plain WeaponSystem
    }, K1NoFire::NotK1System);
    pump(1, [](World& w, I, I, I, I b0) {
        w.m.set_i(b0, Field::weapon_kind, 8);    // a tube under phasers
    }, K1NoFire::Structure);
    // The first count of a why is reported once in a record, then not again
    // until the counts are reset.
    World w;
    w.k.begin_pump({-1}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.step().no_fire_new,
              uint64_t{1} << static_cast<int>(K1NoFire::UnslottedShip));
    w.k.end();
    w.k.begin_pump({-1}, kDt, 10.0, false, 0.0);
    EXPECT_EQ(w.step().no_fire_new, uint64_t{0});
    w.k.end();
    EXPECT_EQ(w.no_fire(K1NoFire::UnslottedShip), 2);
    w.k.reset_counts();
    w.k.begin_pump({-1}, kDt, 10.0, false, 0.0);
    EXPECT_NE(w.step().no_fire_new, uint64_t{0});
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
    // slot stale: the system does not fire, part_stale.
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
    w.step();
    // The beam lit (its edge: logged writes and entries).
    EXPECT_EQ(w.k.counts().logged_beam_edge, 1);
    w.k.end();
    EXPECT_EQ(w.no_fires(), 0);
    EXPECT_EQ(w.k.counts().posed_walks, 1);

    w.m.set_part_gen(w.m.part_gen() + 1);
    w.k.reset_counts();
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    EXPECT_TRUE(w.step().writes.empty());
    w.k.end();
    EXPECT_EQ(w.no_fire(K1NoFire::PartStale), 1);
    EXPECT_EQ(w.k.counts().posed_walks, 0);
}

TEST(K1, PosedTargetOffsetAimByReason) {
    // A tube aims at a posed target's offset (`_RESOLVE`): the first mount
    // at the offset, its slot current -> launched, decided natively; so is
    // an offset no mount claims, or one within 1e-5 of a mount but not on it
    // (a plain body point: fire control native only, M5, M8.5). The mirror
    // cannot tell the mount (not a ShipClass) or the slot is stale -> the
    // Fire's decision is a no-fire (decision), never the system's.
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
        const K1Record r = w.step();
        const auto& n = w.k.counts();
        if (c == kNative || c == kNoMountHere || c == kOffMount) {
            EXPECT_EQ(fx(w, r).front(), "SPAWN b0@t") << c;
            EXPECT_EQ(n.posed_target_aims, 1) << c;
            EXPECT_EQ(w.no_fires(), 0) << c;
        } else {
            EXPECT_TRUE(r.entries.empty()) << c;
            EXPECT_EQ(w.no_fire(K1NoFire::Decision), 1) << c;
            EXPECT_EQ(n.posed_target_aims, 0) << c;
        }
    }
}


// ── Round trips, Task 1: the walk starts natively ───────────────────────────

TEST(K1Native, LiveHeldOffsetPredicate) {
    // _live_held_offset: a ShipClass ship with is_using_target_offset()
    // (the flag AND a manual offset) -> the manual offset; anything else ->
    // the held offset when it is a TGPoint3, else none.
    World w;
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
    // Below the timer threshold the walk fires nothing: its writes (the
    // pruned list first, a NEW list every walk) ride DONE.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    w.bank("b0", sys);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record done = w.k.next();
    EXPECT_EQ(w.brief(done), "DONE");
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

TEST(K1Native, WalkManualOffsetRecordsEachWalksSource) {
    // THE WALK OFFSET (M8.8): per walk of the session, the Manual Aim pick
    // its offset came from (the driver makes a TGPoint3 of it), or nullopt
    // (its object is the system's own _held_offset).
    World w;
    const int64_t ship = w.ship("ship");
    w.m.set_i(ship, Field::is_ship_class, 1);
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t psys = w.system("sys", ship, 1, {t});
    w.bank("b0", psys);
    const int64_t tsys = w.system("tsys", ship, 4, {t});
    w.bank("tube0", tsys);
    w.m.set_fv(psys, Field::_held_offset, {1.0, 2.0, 3.0});
    EXPECT_THROW(w.k.walk_manual_offset(1), std::logic_error);  // no session
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.k.next();
    using O = std::optional<Vec3>;
    EXPECT_EQ(w.k.walk_manual_offset(1), O{});   // the held offset's object
    EXPECT_EQ(w.k.walk_manual_offset(2), O{});
    EXPECT_THROW(w.k.walk_manual_offset(3), std::logic_error);
    w.k.end();
    w.m.set_i(ship, Field::_use_target_offset, 1);
    w.m.set_fv(ship, Field::_manual_target_offset, {7.0, 8.0, 9.0});
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    w.k.next();
    EXPECT_EQ(w.k.walk_manual_offset(1), (O{Vec3{7.0, 8.0, 9.0}}));
    EXPECT_EQ(w.k.walk_manual_offset(2), (O{Vec3{7.0, 8.0, 9.0}}));
}

TEST(K1Native, WalkOffsetMarkerNamesItsWalk) {
    // A cannon's stamp of the walk's offset names the walk and its system,
    // and the mirror holds the value the kernel computed (the held offset).
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("psys", ship, 2, {t});
    const int64_t c = w.bank("cannon", sys);
    w.m.set_fv(sys, Field::_held_offset, {1.0, 2.0, 3.0});
    w.m.set_i(sys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record f = w.k.next();
    const K1Write* stamp = nullptr;
    for (const K1Write& wr : f.writes)
        if (wr.handle == c && wr.field == "_target_offset") stamp = &wr;
    ASSERT_NE(stamp, nullptr);
    ASSERT_TRUE(std::holds_alternative<K1WalkOffset>(stamp->value));
    EXPECT_EQ(std::get<K1WalkOffset>(stamp->value), (K1WalkOffset{1, sys}));
    EXPECT_EQ(w.m.get_fv(c, Field::_target_offset),
              (std::vector<double>{1.0, 2.0, 3.0}));
    w.k.end();

    // Manual Aim on the firing ShipClass: the manual offset is stamped.
    World v;
    const int64_t vship = v.ship("ship");
    v.m.set_i(vship, Field::is_ship_class, 1);
    v.m.set_i(vship, Field::_use_target_offset, 1);
    v.m.set_fv(vship, Field::_manual_target_offset, {7.0, 8.0, 9.0});
    const int64_t vt = v.object("t", 0.0, 50.0, 0.0);
    const int64_t vsys = v.system("psys", vship, 2, {vt});
    const int64_t vc = v.bank("cannon", vsys);
    v.m.set_fv(vsys, Field::_held_offset, {1.0, 2.0, 3.0});
    v.m.set_i(vsys, Field::_force_update, 1);
    v.k.begin_pump({vship}, kDt, 10.0, false, 0.0);
    v.k.next();
    EXPECT_EQ(v.m.get_fv(vc, Field::_target_offset),
              (std::vector<double>{7.0, 8.0, 9.0}));
}

// ── Round trips Task 2: beam sustain and idle stops as logged writes ─────────

TEST(K1Native, BeamSustainIsLoggedWrites) {
    // A Fire on a beam already firing: _EnergyWeaponFireMixin._fire_effect
    // with was_firing -- `_firing = True; _target = target; _target_offset =
    // offset`, nothing else -- logged in that order, no FIRE record, each
    // only when it changes something (phase 6 A3: `_firing` is already
    // True here). The stamp is the walk's offset OBJECT (the marker),
    // whatever it is: with no TGPoint3 offset the mirror reads unset.
    for (const bool with_offset : {true, false}) {
        World w;
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
                      "b0._target=t", "b0._target_offset=walk_offset"}))
            << with_offset;  // `_firing` already True (phase 6 A3)
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
    World w;
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

TEST(K1Native, EntriesRideTheRecordInWalkOrder) {
    // The phasers' entries (their edge), then the tubes' (the launch), in
    // walk order, each after the writes logged before it.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t psys = w.system("psys", ship, 1, {t});
    w.bank("b0", psys);
    const int64_t tsys = w.system("tsys", ship, 4, {t});
    w.bank("tube", tsys);
    w.m.set_i(psys, Field::_force_update, 1);
    w.m.set_i(tsys, Field::_force_update, 1);
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record done = w.k.next();
    EXPECT_EQ(fx(w, done), (std::vector<std::string>{
                               "FIRE_SOUND b0", "WEAPON_FIRED b0@t",
                               "SPAWN tube@t", "WEAPON_FIRED tube@t",
                               "AMMO_CONSUMED tube"}));
    size_t last = 0;
    for (const K1Entry& e : done.entries) {
        EXPECT_GE(e.at, last);
        last = e.at;
    }
}

TEST(K1Native, FireFailedIsAnEntry) {
    // A tube's failed aim (the cone): `self._broadcast_weapon_fire_failed();
    // return False` is the entry WEAPON_FIRE_FAILED(tube), no record; the
    // retry over the list fails again, a second entry. Both ride DONE, each
    // after the writes made before it.
    World w;
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
        World w;
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
        World w;
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
    World w;
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


// ── Launches at the boundary (spec 2026-11-02-combat-launch-deferral §4.1) ──
// A tube's or a dumb launch is the launcher writes, logged in Python's order
// (TorpedoTube._fire_effect, _start_slot_cooldown, _spawn_torpedo's ammo
// debit), and SPAWN(tube, fire-time record), WEAPON_FIRED, AMMO_CONSUMED
// queued after them. A launch the kernel cannot make does not fire (NO
// FIRE), counted by why.

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
    World w;
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
    World w;
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
        World w;
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
    World w;
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
    World w;
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

TEST(K1Launch, LaunchesTheKernelCannotMakeAreNoFires) {
    // Never guessed: a launch the kernel cannot make does not fire (NO
    // FIRE: Launch, its why in launch_why) -- before the walk's first shot,
    // the walk rolled back: no launch write, nothing queued.
    enum Case { kUncached, kUnresolved, kNoAmmo, kSlots };
    for (int c = kUncached; c <= kSlots; ++c) {
        World w;
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
            case kNoAmmo:  // no ammo type and no slot-0 script
                w.m.set_ids(l.sys, Field::_ammo_by_slot, {});
                want = K1LaunchWhy::Unresolved;
                break;
            case kSlots:  // _ensure_slots would rebuild the lists
                w.m.set_floats(l.tube, Field::_reload_timers, {});
                want = K1LaunchWhy::Other;
                break;
        }
        w.k.begin_pump({l.ship}, kDt, 10.0, false, 0.0);
        const K1Record r = w.k.next();
        EXPECT_EQ(w.brief(r), "DONE") << c;
        EXPECT_EQ(launch_why(w, want), 1u) << c << " " << k1_launch_why_name(want);
        EXPECT_EQ(w.no_fire(K1NoFire::Launch), 1) << c;
        EXPECT_TRUE(r.entries.empty()) << c;
        EXPECT_TRUE(r.writes.empty()) << c << ::testing::PrintToString(w.writes(r));
        EXPECT_EQ(w.m.get_i(l.tube, Field::_num_ready), 1) << c;
        EXPECT_EQ(w.m.get_i(l.sys, Field::_force_update), 1) << c;
        EXPECT_EQ(w.k.counts().logged_tube_launch, 0) << c;
    }
}

TEST(K1Launch, DumbFireIsDecidedNatively) {
    // An empty target list and the timer below its threshold: try_fire
    // returns False, `_target = None`, then Weapon.FireDumb(0, 1):
    // _dewarp_blocks_fire, then Fire(None, None) -- CanFire, the launch with
    // no target and no offset.
    World w;
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
        World w;
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

TEST(K1Launch, DumbLaunchTheKernelCannotMakeIsANoFire) {
    // Counted once (the FIRE_DUMB hand-back counted its why twice: once in
    // the walk, once in Python's Fire): launch_why 1, no_fire launch 1.
    World w;
    const Launcher l = launcher(w, {});
    w.m.set_i(l.sys, Field::_force_update, 0);
    w.m.set_i(l.ammo, Field::ammo_launch_state, 0);
    w.k.begin_pump({l.ship}, kDt, 10.0, false, 0.0);
    const K1Record r = w.k.next();
    EXPECT_TRUE(r.entries.empty());
    EXPECT_FALSE(has_write(w, r, "tube._firing=True"));
    EXPECT_EQ(launch_why(w, K1LaunchWhy::Uncached), 1u);
    EXPECT_EQ(w.no_fire(K1NoFire::Launch), 1);
    w.k.end();
    // The SDK's own dumb fire: the same, once.
    w.k.reset_counts();
    w.k.begin_dumb(l.tube, 10.0, false, 0.0);
    const K1Record d = w.k.next();
    EXPECT_TRUE(d.writes.empty() && d.entries.empty());
    EXPECT_EQ(launch_why(w, K1LaunchWhy::Uncached), 1u);
    EXPECT_EQ(w.no_fire(K1NoFire::Launch), 1);
    EXPECT_EQ(w.k.counts().logged_sdk_dumb_fire, 1);
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

// The led launch direction the kernel decides for cannon_world's shot: the
// lead solve itself (weapon_geometry), on the same rows and offset.
Vec3 decided_dir(int64_t power) {
    World p;
    const Cannon c = cannon_world(p, power);
    p.m.set_fv(c.cannon, Field::_target_offset, {0.25, -0.5, 0.125});
    const std::optional<Vec3> dir =
        _solve_pulse_launch_direction(p.m, c.cannon, c.ship, c.target, false);
    EXPECT_TRUE(dir.has_value());
    return dir.value_or(Vec3{0.0, 0.0, 0.0});
}

}  // namespace

TEST(K1PulseLaunch, CannonLaunchIsLoggedWritesAndASpawnEntry) {
    const Vec3 dir = decided_dir(2);
    World w;
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
        World w;
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

// ── THE TRACTOR WALK (fire control native only, M4, R8) ─────────────────────

// The pump's tractor walk: no record. A held target in range and arc is
// gripped -- the beam's edge writes, its FIRE_SOUND, the cursor -- and the
// system's firing edge is a TRACTOR_STARTED(system, ship) entry after its
// `_was_firing` write. Out of range the beam drops, the engage intent kept,
// with a TRACTOR_STOPPED.
TEST(K1, TractorWalkGripsAndDrops) {
    World w;
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
    EXPECT_EQ(w.no_fires(), 0);
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
    World w;
    w.m.set_global_f(Global::TRACTOR_MAX_RANGE_GU, 120.0);
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("tr", ship, 3, {t});
    const int64_t beam = w.bank("beam", sys);
    w.m.set_i(beam, Field::weapon_kind, 1);     // a projector it cannot name
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    const K1Record r = w.step();
    EXPECT_EQ(w.brief(r), "DONE");
    EXPECT_TRUE(r.writes.empty());
    EXPECT_TRUE(r.entries.empty());
    EXPECT_EQ(w.k.counts().no_fire[static_cast<size_t>(K1NoFire::TractorRow)],
              1);
    EXPECT_EQ(w.no_fires(), 1);
    EXPECT_EQ(w.k.counts().entries[static_cast<size_t>(
                  K1Effect::TRACTOR_STARTED)], 0);
    w.k.end();
}

// StartFiring's session: the engage with the session's own offset (walk 1)
// and the sync; nothing for a target out of range but the intent Python
// wrote.
TEST(K1, TractorStartSession) {
    World w;
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

    World far;
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
        World w;
        w.m.set_global_f(Global::TRACTOR_MAX_RANGE_GU, 120.0);
        const int64_t ship = w.ship("ship");
        w.m.set_ref(ship, Field::_tractor_beam_system, kRefUnrepresentable);
        w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
        const K1Record r = w.step();
        EXPECT_EQ(w.brief(r), "DONE");
        EXPECT_EQ(w.no_fire(K1NoFire::TractorRow), 1);
        EXPECT_EQ(w.no_fires(), 1);
        w.k.end();
    }
    {   // A ship with no row: one unslotted-ship no-fire, its tractor
        // included.
        World w;
        w.k.begin_pump({-1}, kDt, 10.0, false, 0.0);
        EXPECT_EQ(w.brief(w.step()), "DONE");
        EXPECT_EQ(w.no_fire(K1NoFire::UnslottedShip), 1);
        EXPECT_EQ(w.no_fires(), 1);
    }
}

TEST(K1Sdk, FireThatCannotBeDecidedReturnsFalseOnce) {
    // THE SDK ROUTES: weapon.Fire whose decision the mirror cannot make
    // (here: a posed target's mount it cannot tell) or whose launch it
    // cannot make returns 0 with nothing written -- never a hand-back, so
    // nothing can make the shot a second time.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t sys = w.system("tsys", ship, 4, {});
    const int64_t tube = w.bank("tube", sys);
    const int64_t t = posed_target(w, "t", 0.0, 50.0, 0.0, tube);
    w.k.begin_fire(tube, t, std::nullopt, std::nullopt, 10.0, false, 0.0);
    const K1Record r = w.k.next();
    EXPECT_EQ(w.k.result(), 0);
    EXPECT_TRUE(r.writes.empty() && r.entries.empty());
    EXPECT_EQ(w.no_fire(K1NoFire::Decision), 1);
    w.k.end();
    // The launch it cannot make.
    const int64_t ok = w.object("ok", 0.0, 50.0, 0.0);
    w.m.set_fv(tube, Field::_target_offset, {});
    w.m.set_i(w.m.get_ids(sys, Field::_ammo_by_slot)[1],
              Field::ammo_launch_state, 0);
    w.k.begin_fire(tube, ok, std::nullopt, std::nullopt, 10.0, false, 0.0);
    const K1Record l = w.k.next();
    EXPECT_EQ(w.k.result(), 0);
    EXPECT_TRUE(l.writes.empty() && l.entries.empty());
    EXPECT_EQ(w.no_fire(K1NoFire::Launch), 1);
    EXPECT_EQ(w.m.get_i(tube, Field::_num_ready), 1);
    w.k.end();
    // And one it can: 1.
    w.m.set_i(w.m.get_ids(sys, Field::_ammo_by_slot)[1],
              Field::ammo_launch_state, 1);
    w.k.begin_fire(tube, ok, std::nullopt, std::nullopt, 10.0, false, 0.0);
    w.k.next();
    EXPECT_EQ(w.k.result(), 1);
}

// Python's drop loop: `(not engageable) or (not in arc)` -- out of range
// the aim is never resolved, so a mount the mirror cannot place (a posed
// ship's stale part slot) does not stop the out-of-range drop.
TEST(K1, TractorDropOutOfRangeResolvesNoAim) {
    World w;
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

// ── Phase 6 A3: a beam already firing logs only what changes ─────────────────
//
// The sustain's three stamps (`_firing = True; _target = target;
// _target_offset = <the walk's offset object>`) are skipped when they
// change nothing in Python: `_firing` already True (a firing bank is never
// asleep, so the WakeField's wake is a no-op), `_target` the same live
// handle, and `_target_offset` the very OBJECT the bank already holds -- the
// same system's `_held_offset`, unchanged since K1 stamped it (the mirror's
// offset source: never a value comparison).

namespace {

// The bank's sustain stamps in the record, as "field=value".
std::vector<std::string> stamps(const World& w, const K1Record& r,
                                const std::string& bank) {
    std::vector<std::string> out;
    for (const std::string& s : writes_on(w, r, bank)) {
        const std::string f = s.substr(s.find('.') + 1);
        if (f.rfind("_firing=", 0) == 0 || f.rfind("_target=", 0) == 0 ||
            f.rfind("_target_offset=", 0) == 0)
            out.push_back(s);
    }
    return out;
}

// One pump tick of `ship`, its session ended.
K1Record pump_tick(World& w, int64_t ship) {
    w.k.begin_pump({ship}, kDt, 10.0, false, 0.0);
    K1Record r = w.step();
    w.k.end();
    return r;
}

// A phaser system held on `t` (its _held_offset a TGPoint3) with one bank,
// lit on the first tick (its edge).
struct Lit {
    int64_t ship, t, sys, b0;
};
Lit lit_beam(World& w) {
    Lit l;
    l.ship = w.ship("ship");
    l.t = w.object("t", 0.0, 50.0, 0.0);
    l.sys = w.system("sys", l.ship, 1, {l.t});
    l.b0 = w.bank("b0", l.sys);
    w.m.set_fv(l.sys, Field::_held_offset, {0.25, 0.5, -0.125});
    w.m.set_f(l.b0, Field::_fire_timer, 0.33);
    const K1Record edge = pump_tick(w, l.ship);
    EXPECT_EQ(stamps(w, edge, "b0"),
              (std::vector<std::string>{"b0._firing=True", "b0._target=t",
                                        "b0._target_offset=walk_offset"}));
    EXPECT_EQ(w.k.counts().logged_beam_edge, 1);
    return l;
}

}  // namespace

TEST(K1, ASustainedHeldOffsetBeamLogsNoSustainWritesOnItsSecondTick) {
    World w;
    const Lit l = lit_beam(w);
    for (int tick = 2; tick <= 4; ++tick) {
        const K1Record r = pump_tick(w, l.ship);
        EXPECT_TRUE(stamps(w, r, "b0").empty()) << "tick " << tick;
        EXPECT_EQ(w.k.counts().logged_beam_sustain, tick - 1);
        EXPECT_EQ(w.k.counts().logged_beam_sustain_skips, 3 * (tick - 1));
    }
    // The mirror still holds what Python holds.
    EXPECT_EQ(w.m.get_i(l.b0, Field::_firing), 1);
    EXPECT_EQ(w.m.get_ref(l.b0, Field::_target), l.t);
}

TEST(K1, ASustainedBeamWithNoHeldOffsetObjectStillSkips) {
    // `_held_offset` None: the walk's object is None, which the bank holds.
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t t = w.object("t", 0.0, 50.0, 0.0);
    const int64_t sys = w.system("sys", ship, 1, {t});
    const int64_t b0 = w.bank("b0", sys);
    w.m.set_f(b0, Field::_fire_timer, 0.33);
    EXPECT_EQ(stamps(w, pump_tick(w, ship), "b0").size(), 3u);
    EXPECT_TRUE(stamps(w, pump_tick(w, ship), "b0").empty());
}

TEST(K1, AManualAimBeamStillWritesItsOffsetEveryTick) {
    // Manual Aim: every walk's object is a NEW TGPoint3 of the pick.
    World w;
    const Lit l = lit_beam(w);
    w.m.set_i(l.ship, Field::is_ship_class, 1);
    w.m.set_i(l.ship, Field::_use_target_offset, 1);
    w.m.set_fv(l.ship, Field::_manual_target_offset, {0.0, 0.5, 0.0});
    for (int tick = 2; tick <= 3; ++tick) {
        const K1Record r = pump_tick(w, l.ship);
        EXPECT_EQ(stamps(w, r, "b0"), (std::vector<std::string>{
                                          "b0._target_offset=walk_offset"}))
            << "tick " << tick;
    }
    // Back from Manual Aim: the bank holds the last pick's object, so the
    // held offset is stamped again, once.
    w.m.set_i(l.ship, Field::_use_target_offset, 0);
    EXPECT_EQ(stamps(w, pump_tick(w, l.ship), "b0"),
              (std::vector<std::string>{"b0._target_offset=walk_offset"}));
    EXPECT_TRUE(stamps(w, pump_tick(w, l.ship), "b0").empty());
}

TEST(K1, ARetargetStillWritesTheTarget) {
    World w;
    const Lit l = lit_beam(w);
    const int64_t t2 = w.object("t2", 0.0, 60.0, 0.0);
    w.m.set_ids(l.sys, Field::_target_list, {t2});
    w.m.set_ref(l.sys, Field::_held_target, t2);
    EXPECT_EQ(stamps(w, pump_tick(w, l.ship), "b0"),
              (std::vector<std::string>{"b0._target=t2"}));
    EXPECT_EQ(w.m.get_ref(l.b0, Field::_target), t2);
    EXPECT_TRUE(stamps(w, pump_tick(w, l.ship), "b0").empty());
}

TEST(K1, ANewHeldOffsetObjectIsStampedAgain) {
    // Python's `_held_offset = TGPoint3(...)` (a push, even of the same
    // value) is a new object: the bank must be given it.
    World w;
    const Lit l = lit_beam(w);
    w.m.set_fv(l.sys, Field::_held_offset, {0.25, 0.5, -0.125});
    EXPECT_EQ(stamps(w, pump_tick(w, l.ship), "b0"),
              (std::vector<std::string>{"b0._target_offset=walk_offset"}));
    EXPECT_TRUE(stamps(w, pump_tick(w, l.ship), "b0").empty());
}

TEST(K1, AnotherTargetOffsetOnTheBankIsStampedAgain) {
    // Anything else writing the bank's `_target_offset` (a push, another
    // kernel's write) leaves its source unknown.
    World w;
    const Lit l = lit_beam(w);
    w.m.set_fv(l.b0, Field::_target_offset, {0.25, 0.5, -0.125});
    EXPECT_EQ(stamps(w, pump_tick(w, l.ship), "b0"),
              (std::vector<std::string>{"b0._target_offset=walk_offset"}));
    EXPECT_TRUE(stamps(w, pump_tick(w, l.ship), "b0").empty());
}

TEST(K1, ForgottenOffsetSourcesAreStampedAgain) {
    // An apply that raised (the binding): Python may not hold what K1
    // stamped, so every source is forgotten.
    World w;
    const Lit l = lit_beam(w);
    w.m.forget_offset_sources();
    EXPECT_EQ(stamps(w, pump_tick(w, l.ship), "b0"),
              (std::vector<std::string>{"b0._target_offset=walk_offset"}));
}

TEST(K1, AnotherSystemsHeldOffsetIsNotTheSameObject) {
    // A Fire session's walk object is Fire's own offset, not the held one:
    // it never records a source, and a later held walk stamps again.
    World w;
    const Lit l = lit_beam(w);
    w.k.begin_fire(l.b0, l.t, Vec3{0.25, 0.5, -0.125}, std::nullopt, 10.0,
                   false, 0.0);
    const K1Record f = w.step();
    w.k.end();
    EXPECT_EQ(stamps(w, f, "b0"),
              (std::vector<std::string>{"b0._target_offset=walk_offset"}));
    EXPECT_EQ(stamps(w, pump_tick(w, l.ship), "b0"),
              (std::vector<std::string>{"b0._target_offset=walk_offset"}));
}
