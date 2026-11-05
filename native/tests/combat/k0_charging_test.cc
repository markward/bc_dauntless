// The K0 charging kernel (k0_charging.h) on hand-built mirror rows: each
// pure step against the Python reference, the session's walk order, records,
// queue entries, hand-backs, write log, undo and counters. Every expected float is the
// REAL Python's (engine/appc/weapon_subsystems.py run on real PhaserBank /
// PulseWeapon / TorpedoTube objects), written as Python's float.hex(). The
// native-vs-Python differentials run from Task 5/6's Python tests.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <variant>
#include <vector>

#include "dauntless/combat/k0_charging.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr double kDt = 1.0 / 60.0;
constexpr double kNow = 100.0;
const double kNaN = std::numeric_limits<double>::quiet_NaN();

// Python's float.hex().
std::string py_hex(double v) {
    if (std::isnan(v)) return "nan";
    if (std::isinf(v)) return v < 0 ? "-inf" : "inf";
    uint64_t bits;
    std::memcpy(&bits, &v, sizeof bits);
    const bool neg = bits >> 63;
    const int e = static_cast<int>((bits >> 52) & 0x7ff);
    const unsigned long long mant = bits & ((1ULL << 52) - 1);
    char buf[64];
    if (e == 0 && mant == 0)
        std::snprintf(buf, sizeof buf, "%s0x0.0p+0", neg ? "-" : "");
    else if (e == 0)
        std::snprintf(buf, sizeof buf, "%s0x0.%013llxp-1022", neg ? "-" : "",
                      mant);
    else
        std::snprintf(buf, sizeof buf, "%s0x1.%013llxp%+d", neg ? "-" : "",
                      mant, e - 1023);
    return buf;
}

struct World {
    TransformStore store;
    Mirror m{store};
    K0Session k{m};
    std::map<int64_t, std::string> names;

    World() {
        // weapon_subsystems.PHASER_DISCHARGE_BY_POWER_LEVEL = (0.35, 1.0, 1.0)
        m.set_global_f(Global::PHASER_DISCHARGE_0, 0.35);
        m.set_global_f(Global::PHASER_DISCHARGE_1, 1.0);
        m.set_global_f(Global::PHASER_DISCHARGE_2, 1.0);
        m.set_global_i(Global::PHASER_DISCHARGE_LEN, 3);
    }

    int64_t ship(const std::string& name) {
        const int64_t h = m.register_row(Kind::Object);
        m.set_i(h, Field::is_ship_class, 1);
        names[h] = name;
        return h;
    }
    // A weapon system of `kind` (1 phaser, 2 pulse, 3 tractor, 4 torpedo),
    // on, power factor 1.0, phaser power level PP_HIGH (the constructor's).
    int64_t system(const std::string& name, int64_t ship_h, int64_t kind) {
        const int64_t s = m.register_row(Kind::Subsystem);
        names[s] = name;
        m.set_i(s, Field::weapon_kind, kind);
        m.set_i(s, Field::_is_on, 1);
        m.set_f(s, Field::_power_factor, 1.0);
        m.set_i(s, Field::_power_level, 2);
        m.set_f(s, Field::_max_condition, 100.0);
        m.set_f(s, Field::_condition, 100.0);
        if (ship_h != -1) {
            const Field getter = kind == 1   ? Field::_phaser_system
                                 : kind == 2 ? Field::_pulse_weapon_system
                                 : kind == 3 ? Field::_tractor_beam_system
                                             : Field::_torpedo_system;
            m.set_ref(ship_h, getter, s);
        }
        return s;
    }
    // A leaf of the system's kind (5 bank, 6 pulse, 7 tractor, 8 tube),
    // healthy, idle and full (charge 5 of 5; a tube 1 of 1, loaded).
    int64_t weapon(const std::string& name, int64_t sys) {
        const int64_t b = m.register_row(Kind::Subsystem);
        names[b] = name;
        const int64_t sk = m.get_i(sys, Field::weapon_kind);
        m.set_i(b, Field::weapon_kind, sk + 4);
        m.set_ref(b, Field::_parent_subsystem, sys);
        m.set_f(b, Field::_max_condition, 100.0);
        m.set_f(b, Field::_condition, 100.0);
        m.set_f(b, Field::_charge_level, 5.0);
        m.set_f(b, Field::_max_charge, 5.0);
        m.set_f(b, Field::_recharge_rate, 0.3);
        m.set_f(b, Field::_normal_discharge_rate, 1.0);
        m.set_i(b, Field::_num_ready, 1);
        m.set_i(b, Field::_max_ready, 1);
        m.set_f(b, Field::_reload_delay, 4.0);
        m.set_floats(b, Field::_reload_timers, {-1.0});
        m.set_floats(b, Field::_reload_advanced_at, {0.0});
        auto kids = m.get_ids(sys, Field::_children);
        kids.push_back(b);
        m.set_ids(sys, Field::_children, kids);
        return b;
    }
    // A tube with these slots.
    void slots(int64_t t, std::vector<double> timers, std::vector<double> adv,
               int64_t max_ready, int64_t ready) {
        m.set_floats(t, Field::_reload_timers, timers);
        m.set_floats(t, Field::_reload_advanced_at, adv);
        m.set_i(t, Field::_max_ready, max_ready);
        m.set_i(t, Field::_num_ready, ready);
    }

    std::string name(int64_t h) const {
        auto it = names.find(h);
        return it == names.end() ? std::to_string(h) : it->second;
    }
    std::vector<std::string> writes(const K0Record& r) const {
        std::vector<std::string> out;
        for (const K0Write& w : r.writes) {
            K0Step s;
            s.writes.push_back(w.w);
            for (std::string& x : writes(w.handle, s)) out.push_back(x);
        }
        return out;
    }
    // A pure step's writes, rendered like the log.
    std::vector<std::string> writes(int64_t h, const K0Step& s) const {
        std::vector<std::string> out;
        for (const K0FieldWrite& w : s.writes) {
            const std::string head =
                name(h) + "." +
                (w.type == K0FieldWrite::Type::Watcher ? "_charge_watcher"
                                                       : field_name(w.field));
            switch (w.type) {
                case K0FieldWrite::Type::Float:
                    out.push_back(head + "=" + py_hex(w.d));
                    break;
                case K0FieldWrite::Type::Flag:
                    out.push_back(head + "=" + (w.i ? "True" : "False"));
                    break;
                case K0FieldWrite::Type::Int:
                    out.push_back(head + "=" + std::to_string(w.i));
                    break;
                case K0FieldWrite::Type::Slot:
                    out.push_back(head + "[" + std::to_string(w.index) +
                                  "]=" + py_hex(w.d));
                    break;
                case K0FieldWrite::Type::Watcher:
                    out.push_back(head + "._value=" + py_hex(w.d));
                    break;
                case K0FieldWrite::Type::Ref:
                    out.push_back(head + "=" +
                                  (w.i == -1 ? std::string("None") : name(w.i)));
                    break;
                case K0FieldWrite::Type::Null:
                    out.push_back(head + "=None");
                    break;
            }
        }
        return out;
    }
    // A record's queue entries (THE EFFECT QUEUE): "KIND weapon@at", a
    // WATCH with its values "WATCH p old->new@at".
    std::vector<std::string> entries(const K0Record& r) const {
        std::vector<std::string> out;
        for (const K0Entry& e : r.entries) {
            std::string x = std::string(k0_effect_name(e.kind)) + " " +
                            name(e.a);
            if (e.kind == K0Effect::WATCH)
                x += " " + py_hex(e.old_value) + "->" + py_hex(e.new_value);
            out.push_back(x + "@" + std::to_string(e.at));
        }
        return out;
    }
    std::string rec(const K0Record& r) const {
        std::string s = k0_kind_name(r.kind);
        if (r.kind != K0Kind::DONE) s += " " + name(r.a);
        if (r.reason) s += std::string(" ") + k0_reason_name(*r.reason);
        return s;
    }
    // Every record to DONE (inclusive), then end().
    std::vector<std::string> run() {
        std::vector<std::string> out;
        for (int guard = 0; guard < 100; ++guard) {
            K0Record r = k.next();
            out.push_back(rec(r));
            if (r.kind == K0Kind::DONE) {
                k.end();
                return out;
            }
        }
        ADD_FAILURE() << "no DONE";
        return out;
    }
};

using V = std::vector<std::string>;

// A firing phaser bank on its own ship: (world, bank).
struct Firing {
    World w;
    int64_t ship, sys, b;
    explicit Firing(int64_t level = 2) {
        ship = w.ship("ship");
        sys = w.system("phasers", ship, 1);
        w.m.set_i(sys, Field::_power_level, level);
        b = w.weapon("b", sys);
        w.m.set_i(b, Field::_firing, 1);
        w.m.set_f(b, Field::_beam_on_countdown, 0.0);
    }
};

// ── _EnergyWeaponFireMixin.UpdateCharge ────────────────────────────────────

TEST(K0Charging, EnergyCountdownBranch) {
    Firing f;
    f.w.m.set_f(f.b, Field::_beam_on_countdown, 0.25);
    const K0Step s = step_energy(f.w.m, f.b, kDt);
    EXPECT_FALSE(s.handback);
    EXPECT_EQ(s.record, K0Kind::DONE);
    EXPECT_EQ(f.w.writes(f.b, s), (V{"b._beam_on_countdown=0x1.ddddddddddddep-3"}));
}

TEST(K0Charging, DrainAtEachPowerLevel) {
    // (level, Python's _charge_level after one tick from 5.0)
    const std::vector<std::pair<int64_t, std::string>> cases = {
        {0, "0x1.3fa06d3a06d3ap+2"},  {1, "0x1.3eeeeeeeeeeefp+2"},
        {2, "0x1.3eeeeeeeeeeefp+2"},  {-1, "0x1.3eeeeeeeeeeefp+2"},
        {-3, "0x1.3fa06d3a06d3ap+2"},
    };
    for (const auto& [level, want] : cases) {
        Firing f(level);
        const K0Step s = step_energy(f.w.m, f.b, kDt);
        EXPECT_FALSE(s.handback) << level;
        EXPECT_EQ(f.w.writes(f.b, s), (V{"b._charge_level=" + want})) << level;
    }
    // No parent: hasattr(None, "GetPowerLevel") is false -> level 1.
    Firing f;
    f.w.m.set_ref(f.b, Field::_parent_subsystem, -1);
    const K0Step s = step_energy(f.w.m, f.b, kDt);
    EXPECT_FALSE(s.handback);
    EXPECT_EQ(f.w.writes(f.b, s), (V{"b._charge_level=0x1.3eeeeeeeeeeefp+2"}));
}

TEST(K0Charging, DrainOutOfRangeLevelHandsBack) {
    // Python answers levels 3 and -4 with 0.0 (IndexError; _charge_level
    // stays 0x1.4000000000000p+2), but only entries 0..2 are pushed: the
    // lookup is answered natively only where it lands on them (ruling W5).
    for (int64_t level : {3, -4}) {
        Firing f(level);
        const K0Step s = step_energy(f.w.m, f.b, kDt);
        ASSERT_TRUE(s.handback) << level;
        EXPECT_EQ(*s.handback, K0Reason::PowerLevel);
        EXPECT_TRUE(s.writes.empty());
    }
    {   // A table shorter than 3: -1 lands on entry LEN-1 = 1.
        Firing f(-1);
        f.w.m.set_global_i(Global::PHASER_DISCHARGE_LEN, 2);
        const K0Step s = step_energy(f.w.m, f.b, kDt);
        EXPECT_FALSE(s.handback);
        EXPECT_EQ(f.w.writes(f.b, s), (V{"b._charge_level=0x1.3eeeeeeeeeeefp+2"}));
        f.w.m.set_i(f.sys, Field::_power_level, 2);  // past a 2-entry table
        EXPECT_EQ(*step_energy(f.w.m, f.b, kDt).handback, K0Reason::PowerLevel);
    }
    {   // The table never pushed.
        Firing f(1);
        f.w.m.set_global_i(Global::PHASER_DISCHARGE_LEN, 0);
        EXPECT_EQ(*step_energy(f.w.m, f.b, kDt).handback, K0Reason::PowerLevel);
    }
    {   // A parent that is not a PhaserSystem: hasattr is true on any engine
        // object, so only Python can answer.
        Firing f;
        f.w.m.set_i(f.sys, Field::weapon_kind, 2);
        EXPECT_EQ(*step_energy(f.w.m, f.b, kDt).handback, K0Reason::Parent);
        f.w.m.set_ref(f.b, Field::_parent_subsystem, kRefUnrepresentable);
        EXPECT_EQ(*step_energy(f.w.m, f.b, kDt).handback, K0Reason::Parent);
    }
}

TEST(K0Charging, DepletionLogsTheStopAndQueuesLoopStop) {
    // `self._depleted = True; self.StopFiring()`: the mixin's StopFiring is
    // logged writes (stop_firing.h) and its loop sound's stop a LOOP_STOP
    // entry after them; no record (combat fire events §4.3).
    Firing f;
    f.w.m.set_f(f.b, Field::_charge_level, 0.001);
    const K0Step s = step_energy(f.w.m, f.b, kDt);
    EXPECT_EQ(s.record, K0Kind::DEPLETE_STOP);
    EXPECT_TRUE(s.loop_stop);
    const V stopped{"b._charge_level=0x0.0p+0", "b._depleted=True",
                    "b._firing=False", "b._beam_on_countdown=0x0.0p+0"};
    EXPECT_EQ(f.w.writes(f.b, s), stopped);

    f.w.k.begin({f.ship}, kDt, kNow);
    const K0Record r = f.w.k.next();
    EXPECT_EQ(f.w.rec(r), "DONE");
    EXPECT_EQ(f.w.writes(r), stopped);
    EXPECT_EQ(f.w.entries(r), (V{"LOOP_STOP b@4"}));
    EXPECT_EQ(f.w.m.get_i(f.b, Field::_firing), 0);
    EXPECT_EQ(f.w.m.get_i(f.b, Field::_depleted), 1);
    EXPECT_EQ(f.w.m.get_f(f.b, Field::_charge_level), 0.0);
    f.w.k.end();
}

TEST(K0Charging, NegativeZeroChargeStaysPositive) {
    // max(0.0, -0.0 - 1.0 * 0.0): -0.0, and max's FIRST argument wins the
    // tie, so +0.0 (Python: 0x0.0p+0, then the depletion).
    Firing f;
    f.w.m.set_f(f.b, Field::_charge_level, -0.0);
    const K0Step s = step_energy(f.w.m, f.b, 0.0);
    EXPECT_EQ(f.w.writes(f.b, s),
              (V{"b._charge_level=0x0.0p+0", "b._depleted=True",
                 "b._firing=False", "b._beam_on_countdown=0x0.0p+0"}));
    ASSERT_FALSE(s.writes.empty());
    EXPECT_FALSE(std::signbit(s.writes[0].d));
    EXPECT_EQ(s.record, K0Kind::DEPLETE_STOP);
}

TEST(K0Charging, IdleEarlyOut) {
    World w;
    const int64_t ship = w.ship("ship");
    const int64_t sys = w.system("phasers", ship, 1);
    const int64_t b = w.weapon("b", sys);
    // Not reached by Python, so never a hand-back.
    w.m.set_ref(b, Field::_parent_subsystem, kRefUnrepresentable);
    const K0Step s = step_energy(w.m, b, kDt);
    EXPECT_FALSE(s.handback);
    EXPECT_TRUE(s.writes.empty());
    EXPECT_EQ(s.record, K0Kind::DONE);
}

// A bank recharging from 2.0 of 5.0.
struct Recharging {
    World w;
    int64_t ship, sys, b;
    Recharging(double pf, double cond, double max_charge = 5.0,
               double charge = 2.0, double rate = 0.3) {
        ship = w.ship("ship");
        sys = w.system("phasers", ship, 1);
        w.m.set_f(sys, Field::_power_factor, pf);
        b = w.weapon("b", sys);
        w.m.set_f(b, Field::_condition, cond);
        w.m.set_f(b, Field::_max_charge, max_charge);
        w.m.set_f(b, Field::_charge_level, charge);
        w.m.set_f(b, Field::_recharge_rate, rate);
    }
    V step() { return w.writes(b, step_energy(w.m, b, kDt)); }
};

TEST(K0Charging, RechargeFormula) {
    EXPECT_EQ(Recharging(0.8, 75.0).step(), (V{"b._charge_level=0x1.00624dd2f1aa0p+1"}));
    // From empty, so the left-associative product shows: rate * pf * cf *
    // dt ends ...efa; rate * (pf * cf * dt) would end ...efb.
    EXPECT_EQ(Recharging(0.8, 75.0, 5.0, 0.0).step(),
              (V{"b._charge_level=0x1.89374bc6a7efap-9"}));
    // And the operand ORDER: Python's rate * pf * cf ends ...f1b at power
    // 0.7, condition 75%; rate * cf * pf would end ...f1a.
    EXPECT_EQ(Recharging(0.7, 75.0, 5.0, 0.0).step(),
              (V{"b._charge_level=0x1.5810624dd2f1bp-9"}));
    // min(want, headroom): 4.99 + min(3.0 * dt, 0.01) -> exactly full.
    EXPECT_EQ(Recharging(1.0, 100.0, 5.0, 4.99, 3.0).step(),
              (V{"b._charge_level=0x1.4000000000000p+2"}));
}

TEST(K0Charging, RechargeNaNPowerIsZero) {
    // max(0.0, NaN) -> 0.0: the += still runs, adding 0.0.
    EXPECT_EQ(Recharging(kNaN, 75.0).step(), (V{"b._charge_level=0x1.0000000000000p+1"}));
}

TEST(K0Charging, RechargeNaNConditionReadsFull) {
    // min(1.0, NaN) -> 1.0.
    EXPECT_EQ(Recharging(0.8, kNaN).step(), (V{"b._charge_level=0x1.0083126e978d5p+1"}));
}

TEST(K0Charging, RechargeNaNHeadroomWritesNothing) {
    Recharging r(1.0, 100.0, kNaN);
    const K0Step s = step_energy(r.w.m, r.b, kDt);
    EXPECT_FALSE(s.handback);
    EXPECT_TRUE(s.writes.empty());
}

TEST(K0Charging, RechargeParentOffWritesNothing) {
    Recharging r(1.0, 100.0);
    r.w.m.set_i(r.sys, Field::_is_on, 0);
    EXPECT_TRUE(r.step().empty());
}

TEST(K0Charging, RechargeUnnamedPropertyHandsBack) {
    // GetConditionPercentage reads the property's MaxCondition.
    Recharging r(1.0, 100.0);
    r.w.m.set_ref(r.b, Field::_property, kRefUnrepresentable);
    const K0Step s = step_energy(r.w.m, r.b, kDt);
    ASSERT_TRUE(s.handback);
    EXPECT_EQ(*s.handback, K0Reason::Unrepresentable);
    EXPECT_TRUE(s.writes.empty());
}

// ── PulseWeapon.UpdateCharge ───────────────────────────────────────────────

struct Pulse {
    World w;
    int64_t ship, sys, p;
    explicit Pulse(double cooldown) {
        ship = w.ship("ship");
        sys = w.system("pulse", ship, 2);
        p = w.weapon("p", sys);
        w.m.set_f(p, Field::_cooldown_remaining, cooldown);
        w.m.set_f(p, Field::_charge_level, 1.0);
        w.m.set_f(p, Field::_max_charge, 2.0);
        w.m.set_f(p, Field::_recharge_rate, 0.5);
    }
};

TEST(K0Charging, PulseCooldownRechargeThenWatcher) {
    {
        Pulse q(0.01);  // max(0.0, 0.01 - dt) -> 0.0
        const K0Step s = step_pulse(q.w.m, q.p, kDt);
        EXPECT_EQ(q.w.writes(q.p, s), (V{"p._cooldown_remaining=0x0.0p+0",
                                         "p._charge_level=0x1.0222222222222p+0"}));
        q.w.k.begin({q.ship}, kDt, kNow);
        const K0Record r = q.w.k.next();
        EXPECT_EQ(q.w.rec(r), "DONE");
        EXPECT_EQ(q.w.writes(r), (V{"p._cooldown_remaining=0x0.0p+0",
                                    "p._charge_level=0x1.0222222222222p+0",
                                    "p._charge_watcher._value=0x1.0222222222222p-1"}));
        // No checks: the value is committed (and mirrored), nothing queued.
        EXPECT_TRUE(r.entries.empty());
        EXPECT_EQ(py_hex(q.w.m.get_f(q.p, Field::_watch_value)),
                  "0x1.0222222222222p-1");
    }
    {
        Pulse q(0.5);
        q.w.k.begin({q.ship}, kDt, kNow);
        EXPECT_EQ(q.w.writes(q.w.k.next()),
                  (V{"p._cooldown_remaining=0x1.eeeeeeeeeeeefp-2",
                     "p._charge_level=0x1.0222222222222p+0",
                     "p._charge_watcher._value=0x1.0222222222222p-1"}));
    }
    {   // No cooldown and full: no write, but the watcher line still runs.
        Pulse q(0.0);
        q.w.m.set_f(q.p, Field::_charge_level, 2.0);
        q.w.k.begin({q.ship}, kDt, kNow);
        EXPECT_EQ(q.w.writes(q.w.k.next()),
                  (V{"p._charge_watcher._value=0x1.0000000000000p+0"}));
    }
    {   // GetChargePercentage: 0.0 when _max_charge <= 0.0 (-0.0 included).
        Pulse q(0.0);
        q.w.m.set_f(q.p, Field::_max_charge, -0.0);
        q.w.m.set_f(q.p, Field::_charge_level, 0.0);
        EXPECT_EQ(q.w.writes(q.p, pulse_watch(q.w.m, q.p)),
                  (V{"p._charge_watcher._value=0x0.0p+0"}));
    }
}

TEST(K0Charging, PulseHandBackWritesNothing) {
    // The mixin's parent read cannot be answered: the cooldown write that
    // Python makes FIRST is not made either -- Python steps the whole weapon.
    Pulse q(0.5);
    q.w.m.set_ref(q.p, Field::_parent_subsystem, kRefUnrepresentable);
    const K0Step s = step_pulse(q.w.m, q.p, kDt);
    ASSERT_TRUE(s.handback);
    EXPECT_EQ(*s.handback, K0Reason::Parent);
    EXPECT_TRUE(s.writes.empty());
    q.w.k.begin({q.ship}, kDt, kNow);
    const K0Record r = q.w.k.next();
    EXPECT_EQ(q.w.rec(r), "RUN_PYTHON p parent");
    EXPECT_TRUE(r.writes.empty());
    EXPECT_EQ(q.w.m.get_f(q.p, Field::_cooldown_remaining), 0.5);
    EXPECT_EQ(q.w.rec(q.w.k.next()), "DONE");
    q.w.k.end();
}

TEST(K0Charging, PulseWithChecksQueuesWatch) {
    // A watcher with checks (FloatRangeWatcher._update inside the effect
    // queue's deferral): its value committed as a logged write, then
    // WATCH(p, old, new) -- old the mirrored `_watch_value` -- and the walk
    // goes on; delivery fires the crossings (ruling E3).
    Pulse q(0.5);
    q.w.m.set_i(q.p, Field::_watch_checks, 2);
    q.w.m.set_f(q.p, Field::_watch_value, 0.25);
    const int64_t p2 = q.w.weapon("p2", q.sys);
    q.w.m.set_f(p2, Field::_cooldown_remaining, 0.5);
    const K0Step w = pulse_watch(q.w.m, q.p);
    EXPECT_EQ(w.record, K0Kind::WATCH);
    EXPECT_EQ(w.watch_old, 0.25);
    EXPECT_EQ(w.watch_new, 0.5);
    q.w.k.begin({q.ship}, kDt, kNow);
    const K0Record r = q.w.k.next();
    EXPECT_EQ(q.w.rec(r), "DONE");
    EXPECT_EQ(q.w.writes(r), (V{"p._cooldown_remaining=0x1.eeeeeeeeeeeefp-2",
                                "p._charge_level=0x1.0222222222222p+0",
                                "p._charge_watcher._value=0x1.0222222222222p-1",
                                "p2._cooldown_remaining=0x1.eeeeeeeeeeeefp-2",
                                "p2._charge_watcher._value=0x1.0000000000000p+0"}));
    EXPECT_EQ(q.w.entries(r),
              (V{"WATCH p 0x1.0000000000000p-2->0x1.0222222222222p-1@3"}));
    EXPECT_EQ(py_hex(q.w.m.get_f(q.p, Field::_watch_value)),
              "0x1.0222222222222p-1");
    q.w.k.end();
}

TEST(K0Charging, PulseDepleteStopsThenWatcherLine) {
    // PulseWeapon.StopFiring (no loop sound: no entry), then the watcher
    // line on the stopped weapon, in the same call.
    Pulse q(0.0);
    q.w.m.set_i(q.p, Field::_firing, 1);
    q.w.m.set_ref(q.p, Field::_target, q.ship);
    q.w.m.set_fv(q.p, Field::_target_offset, {1.0, 2.0, 3.0});
    q.w.m.set_f(q.p, Field::_charge_level, 0.001);  // - 1.0 * dt -> 0.0
    // The watcher holds the last commit, 0.001 / 2.0 (a mirror at 0.0 would
    // make the line identical, not logged: AnIdenticalWatcherValue...).
    q.w.m.set_f(q.p, Field::_watch_value, 0.0005);
    q.w.k.begin({q.ship}, kDt, kNow);
    const K0Record r = q.w.k.next();
    EXPECT_EQ(q.w.rec(r), "DONE");
    EXPECT_EQ(q.w.writes(r), (V{"p._charge_level=0x0.0p+0", "p._depleted=True",
                                "p._firing=False", "p._target=None",
                                "p._target_offset=None",
                                "p._charge_watcher._value=0x0.0p+0"}));
    EXPECT_TRUE(q.w.entries(r).empty());
    EXPECT_EQ(q.w.m.get_i(q.p, Field::_firing), 0);
    EXPECT_EQ(q.w.m.get_ref(q.p, Field::_target), -1);
    EXPECT_FALSE(q.w.m.subsystem(q.p)->target_offset_set);
    q.w.k.end();
}

TEST(K0Charging, PulseWatcherNotOwnedHandsBack) {
    // `_watch_checks` WATCH_ALWAYS (-1): a watcher the weapon does not own
    // (a subclass, another weapon's) runs its own `_update` -- Python steps
    // the whole weapon, decided before any write.
    Pulse q(0.5);
    q.w.m.set_i(q.p, Field::_watch_checks, -1);
    const K0Step s = step_pulse(q.w.m, q.p, kDt);
    ASSERT_TRUE(s.handback);
    EXPECT_EQ(*s.handback, K0Reason::Watcher);
    EXPECT_TRUE(s.writes.empty());
    q.w.k.begin({q.ship}, kDt, kNow);
    EXPECT_EQ(q.w.run(), (V{"RUN_PYTHON p watcher", "DONE"}));
    EXPECT_EQ(q.w.m.get_f(q.p, Field::_cooldown_remaining), 0.5);
    EXPECT_STREQ(k0_reason_name(K0Reason::Watcher), "watcher");
}

TEST(K0Charging, AnIdenticalWatcherValueIsNotLogged) {
    // Phase 6 A2: an idle full cannon's watcher line commits the value the
    // watcher already holds (`_watch_value` mirrors the owned watcher's
    // `_value`, always a float: FloatRangeWatcher stores float(new_value)),
    // so it is not logged; the walk still counts it as identical.
    Pulse q(0.0);
    q.w.m.set_f(q.p, Field::_charge_level, 2.0);
    q.w.m.set_f(q.p, Field::_watch_value, 1.0);
    q.w.k.reset_counts();
    q.w.k.begin({q.ship}, kDt, kNow);
    const K0Record r = q.w.k.next();
    EXPECT_EQ(q.w.rec(r), "DONE");
    EXPECT_TRUE(r.writes.empty());
    EXPECT_TRUE(r.entries.empty());
    EXPECT_EQ(q.w.k.counts().steps, 1);
    EXPECT_EQ(q.w.k.counts().identical_writes, 1);
    EXPECT_EQ(q.w.k.counts().logged_writes, 0);
    q.w.k.end();
}

TEST(K0Charging, AnIdenticalWatcherValueStillQueuesWatchWithChecks) {
    // With checks the WATCH entry is Python's `_update` posting
    // WATCH(old, new) inside the deferral, equal values or not: it is still
    // queued (old == new), only the store is skipped.
    Pulse q(0.0);
    q.w.m.set_f(q.p, Field::_charge_level, 2.0);
    q.w.m.set_f(q.p, Field::_watch_value, 1.0);
    q.w.m.set_i(q.p, Field::_watch_checks, 1);
    q.w.k.begin({q.ship}, kDt, kNow);
    const K0Record r = q.w.k.next();
    EXPECT_EQ(q.w.rec(r), "DONE");
    EXPECT_TRUE(r.writes.empty());
    EXPECT_EQ(q.w.entries(r),
              (V{"WATCH p 0x1.0000000000000p+0->0x1.0000000000000p+0@0"}));
    q.w.k.end();
}

TEST(K0Charging, ANegativeZeroWatcherValueIsNotIdenticalToZero) {
    // An empty cannon with no recharge: the new value +0.0 against the
    // mirror's -0.0 differs bit for bit, so it is logged (the scalar
    // charge write is never skipped by the kernel: Python may hold an int).
    Pulse z(0.0);
    z.w.m.set_f(z.p, Field::_charge_level, 0.0);
    z.w.m.set_f(z.p, Field::_recharge_rate, 0.0);
    z.w.m.set_f(z.p, Field::_watch_value, -0.0);
    z.w.k.begin({z.ship}, kDt, kNow);
    const K0Record s = z.w.k.next();
    EXPECT_EQ(z.w.writes(s), (V{"p._charge_level=0x0.0p+0",
                                "p._charge_watcher._value=0x0.0p+0"}));
    EXPECT_FALSE(std::signbit(z.w.m.get_f(z.p, Field::_watch_value)));
    z.w.k.end();
}

// ── TorpedoTube.UpdateReload / ReloadTorpedo ───────────────────────────────

struct Tube {
    World w;
    int64_t ship, sys, t;
    Tube() {
        ship = w.ship("ship");
        sys = w.system("torps", ship, 4);
        t = w.weapon("t", sys);
    }
    V step() { return w.writes(t, step_tube(w.m, t, kNow)); }
};

TEST(K0Charging, TubeOneAttemptLoadsLongestCooling) {
    {   // Slot 0 qualifies first (4.5 >= 4.0); slot 1 (6.0) is loaded.
        Tube u;
        u.w.slots(u.t, {3.0, 5.0}, {98.5, 99.0}, 2, 0);
        const K0Step s = step_tube(u.w.m, u.t, kNow);
        EXPECT_EQ(s.record, K0Kind::RELOADED);
        EXPECT_EQ(u.w.writes(u.t, s),
                  (V{"t._reload_timers[0]=0x1.2000000000000p+2",
                     "t._reload_advanced_at[0]=0x1.9000000000000p+6",
                     "t._reload_timers[1]=0x1.8000000000000p+2",
                     "t._reload_advanced_at[1]=0x1.9000000000000p+6",
                     "t._reload_timers[1]=-0x1.0000000000000p+0",
                     "t._num_ready=1"}));
    }
    {   // A loaded slot is skipped; two qualify, one round per call.
        Tube u;
        u.w.slots(u.t, {-1.0, 3.5, 3.9}, {0.0, 99.5, 99.0}, 3, 1);
        EXPECT_EQ(u.step(), (V{"t._reload_timers[1]=0x1.0000000000000p+2",
                               "t._reload_advanced_at[1]=0x1.9000000000000p+6",
                               "t._reload_timers[2]=0x1.399999999999ap+2",
                               "t._reload_advanced_at[2]=0x1.9000000000000p+6",
                               "t._reload_timers[2]=-0x1.0000000000000p+0",
                               "t._num_ready=2"}));
    }
}

TEST(K0Charging, TubeTieGoesToFirstIndex) {
    Tube u;
    u.w.slots(u.t, {4.0, 4.0}, {100.0, 100.0}, 2, 0);
    EXPECT_EQ(u.step(), (V{"t._reload_timers[0]=0x1.0000000000000p+2",
                           "t._reload_advanced_at[0]=0x1.9000000000000p+6",
                           "t._reload_timers[1]=0x1.0000000000000p+2",
                           "t._reload_advanced_at[1]=0x1.9000000000000p+6",
                           "t._reload_timers[0]=-0x1.0000000000000p+0",
                           "t._num_ready=1"}));
}

TEST(K0Charging, TubeNaNFactorStalls) {
    Tube u;
    u.w.m.set_f(u.sys, Field::_power_factor, kNaN);
    u.w.slots(u.t, {3.9}, {99.0}, 1, 0);
    const K0Step s = step_tube(u.w.m, u.t, kNow);
    EXPECT_EQ(s.record, K0Kind::DONE);
    EXPECT_EQ(u.w.writes(u.t, s), (V{"t._reload_timers[0]=nan",
                                     "t._reload_advanced_at[0]=0x1.9000000000000p+6"}));
}

TEST(K0Charging, TubeNaNFirstSlotIsPicked) {
    // Slot 1 qualifies, but ReloadTorpedo's `oldest_t is None or t >
    // oldest_t` seeds with slot 0's NaN and nothing beats NaN.
    Tube u;
    u.w.slots(u.t, {kNaN, 5.0}, {99.0, 99.0}, 2, 0);
    EXPECT_EQ(u.step(), (V{"t._reload_timers[0]=nan",
                           "t._reload_advanced_at[0]=0x1.9000000000000p+6",
                           "t._reload_timers[1]=0x1.8000000000000p+2",
                           "t._reload_advanced_at[1]=0x1.9000000000000p+6",
                           "t._reload_timers[0]=-0x1.0000000000000p+0",
                           "t._num_ready=1"}));
}

TEST(K0Charging, TubeNegativeGameDtClamped) {
    Tube u;
    u.w.slots(u.t, {3.0}, {101.0}, 1, 0);
    EXPECT_EQ(u.step(), (V{"t._reload_timers[0]=0x1.8000000000000p+1",
                           "t._reload_advanced_at[0]=0x1.9000000000000p+6"}));
}

TEST(K0Charging, TubeNegativeFactorIsZero) {
    Tube u;
    u.w.m.set_f(u.sys, Field::_power_factor, -0.5);
    u.w.slots(u.t, {3.0}, {99.0}, 1, 0);
    EXPECT_EQ(u.step(), (V{"t._reload_timers[0]=0x1.8000000000000p+1",
                           "t._reload_advanced_at[0]=0x1.9000000000000p+6"}));
}

TEST(K0Charging, TubeAmmoDenial) {
    // Finite ammo with 1 round, already chambered in another tube:
    // GetAvailable() <= rounds loaded system-wide -> no reload (the slot
    // still advances).
    Tube u;
    const int64_t ammo = u.w.m.register_row(Kind::Ammo);
    u.w.m.set_i(ammo, Field::_unlimited, 0);
    u.w.m.set_i(ammo, Field::_available, 1);
    u.w.m.set_ids(u.sys, Field::_ammo_by_slot, {0, ammo});
    const int64_t other = u.w.weapon("o", u.sys);  // loaded, 1 of 1
    (void)other;
    u.w.slots(u.t, {3.0}, {99.0}, 1, 0);
    const K0Step s = step_tube(u.w.m, u.t, kNow);
    EXPECT_EQ(s.record, K0Kind::DONE);
    EXPECT_EQ(u.w.writes(u.t, s), (V{"t._reload_timers[0]=0x1.0000000000000p+2",
                                     "t._reload_advanced_at[0]=0x1.9000000000000p+6"}));
    // Two rounds: one is free.
    u.w.m.set_i(ammo, Field::_available, 2);
    EXPECT_EQ(step_tube(u.w.m, u.t, kNow).record, K0Kind::RELOADED);
    // An ammo row the mirror cannot name: Python answers.
    u.w.m.set_ids(u.sys, Field::_ammo_by_slot, {0, kRefUnrepresentable});
    const K0Step h = step_tube(u.w.m, u.t, kNow);
    ASSERT_TRUE(h.handback);
    EXPECT_EQ(*h.handback, K0Reason::Unrepresentable);
    EXPECT_TRUE(h.writes.empty());
}

TEST(K0Charging, TubeSlotHealHandsBack) {
    Tube u;
    u.w.slots(u.t, {3.0}, {99.0, 99.0}, 1, 0);
    K0Step s = step_tube(u.w.m, u.t, kNow);
    ASSERT_TRUE(s.handback);
    EXPECT_EQ(*s.handback, K0Reason::SlotHeal);
    EXPECT_TRUE(s.writes.empty());
    u.w.slots(u.t, {3.0, 3.0}, {99.0, 99.0}, 1, 0);
    EXPECT_EQ(*step_tube(u.w.m, u.t, kNow).handback, K0Reason::SlotHeal);
}

TEST(K0Charging, TubeFullIsNoop) {
    Tube u;  // 1 of 1 ready
    const K0Step s = step_tube(u.w.m, u.t, kNow);
    EXPECT_FALSE(s.handback);
    EXPECT_TRUE(s.writes.empty());
}

// ── The session ────────────────────────────────────────────────────────────

// One ship with all four groups: a firing bank that depletes, a pulse
// cannon with watcher checks, a tractor and a tube that reloads.
struct Armed {
    World w;
    int64_t ship, ph, pu, tr, to, b, p, tb, t;
    Armed() {
        ship = w.ship("ship");
        // Created out of walk order: the walk order is the GROUP order.
        to = w.system("torps", ship, 4);
        tr = w.system("tractors", ship, 3);
        pu = w.system("pulse", ship, 2);
        ph = w.system("phasers", ship, 1);
        t = w.weapon("t", to);
        tb = w.weapon("tb", tr);
        p = w.weapon("p", pu);
        b = w.weapon("b", ph);
        w.m.set_i(b, Field::_firing, 1);
        w.m.set_f(b, Field::_charge_level, 0.001);
        w.m.set_i(tb, Field::_firing, 1);
        w.m.set_i(p, Field::_watch_checks, 1);
        w.slots(t, {3.0}, {99.0}, 1, 0);
        w.m.set_f(t, Field::_reload_delay, 3.5);
        // The tractor beam is handed back (the weapon check): a record mid
        // walk.
        w.k.set_weapon_check([this](int64_t h) { return h == tb; });
    }
};

TEST(K0Charging, WalkOrderPhaserPulseTractorTorpedo) {
    // K0 returns only RUN_PYTHON and DONE; the bank's stop, the watcher and
    // the reload ride them as entries, in walk order, each placed after the
    // writes logged before it.
    Armed a;
    a.w.k.begin({a.ship}, kDt, kNow);
    K0Record r = a.w.k.next();
    EXPECT_EQ(a.w.rec(r), "RUN_PYTHON tb override");
    EXPECT_EQ(a.w.entries(r),
              (V{"LOOP_STOP b@4", "WATCH p 0x0.0p+0->0x1.0000000000000p+0@5"}));
    r = a.w.k.next();
    EXPECT_EQ(a.w.rec(r), "DONE");
    EXPECT_EQ(a.w.entries(r), (V{"TORPEDO_RELOAD t@4"}));
    a.w.k.end();
}

TEST(K0Charging, RecordPositions) {
    Armed a;
    a.w.k.begin({-1, a.ship}, kDt, kNow);
    K0Record r = a.w.k.next();
    EXPECT_EQ(a.w.rec(r), "RUN_PYTHON -1 no_row");
    EXPECT_EQ(r.ship_pos, 0);
    EXPECT_EQ(r.group, -1);
    EXPECT_EQ(r.index, -1);
    r = a.w.k.next();  // tractor
    EXPECT_EQ(r.a, a.tb);
    EXPECT_EQ(r.ship_pos, 1);
    EXPECT_EQ(r.group, 2);
    EXPECT_EQ(r.index, 0);
    r = a.w.k.next();
    EXPECT_EQ(r.kind, K0Kind::DONE);
    EXPECT_EQ(r.ship_pos, -1);
    a.w.k.end();
}

TEST(K0Charging, ReloadQueuesTorpedoReloadAndWalksOn) {
    // ReloadTorpedo's writes, then `self._broadcast_reload()` as a
    // TORPEDO_RELOAD(tube) entry after them; the walk goes on to t2.
    Tube u;
    const int64_t t2 = u.w.weapon("t2", u.sys);
    u.w.slots(u.t, {3.0}, {99.0}, 1, 0);
    u.w.slots(t2, {3.0}, {99.0}, 1, 0);
    u.w.m.set_f(u.t, Field::_reload_delay, 3.5);
    u.w.m.set_f(t2, Field::_reload_delay, 3.5);
    u.w.k.begin({u.ship}, kDt, kNow);
    const K0Record r = u.w.k.next();
    EXPECT_EQ(u.w.rec(r), "DONE");
    EXPECT_EQ(u.w.writes(r), (V{"t._reload_timers[0]=0x1.0000000000000p+2",
                                "t._reload_advanced_at[0]=0x1.9000000000000p+6",
                                "t._reload_timers[0]=-0x1.0000000000000p+0",
                                "t._num_ready=1",
                                "t2._reload_timers[0]=0x1.0000000000000p+2",
                                "t2._reload_advanced_at[0]=0x1.9000000000000p+6",
                                "t2._reload_timers[0]=-0x1.0000000000000p+0",
                                "t2._num_ready=1"}));
    EXPECT_EQ(u.w.entries(r), (V{"TORPEDO_RELOAD t@4", "TORPEDO_RELOAD t2@8"}));
    EXPECT_EQ(u.w.m.get_i(u.t, Field::_num_ready), 1);
    EXPECT_EQ(u.w.m.get_floats(u.t, Field::_reload_timers), std::vector<double>{-1.0});
    EXPECT_EQ(u.w.m.get_floats(u.t, Field::_reload_advanced_at), std::vector<double>{100.0});
    EXPECT_EQ(u.w.m.get_i(t2, Field::_num_ready), 1);
    u.w.k.end();
}

TEST(K0Charging, ReadsTheLiveMirrorAfterARecord) {
    // A record's Python writing a later weapon is seen (P1): the tractor's
    // Python sets the tube's reload delay out of reach.
    Armed a;
    a.w.k.begin({a.ship}, kDt, kNow);
    EXPECT_EQ(a.w.rec(a.w.k.next()), "RUN_PYTHON tb override");
    a.w.m.set_f(a.t, Field::_reload_delay, 100.0);
    const K0Record r = a.w.k.next();
    EXPECT_EQ(a.w.rec(r), "DONE");
    EXPECT_EQ(a.w.writes(r), (V{"t._reload_timers[0]=0x1.0000000000000p+2",
                                "t._reload_advanced_at[0]=0x1.9000000000000p+6"}));
    EXPECT_TRUE(r.entries.empty());
    a.w.k.end();
}

TEST(K0Charging, HandBacks) {
    {   // Ship-level: the caller's reason, and a group the mirror can't name.
        Armed a;
        World& w = a.w;
        const int64_t s2 = w.ship("s2");
        w.m.set_ref(s2, Field::_phaser_system, kRefUnrepresentable);
        const int64_t s3 = w.ship("s3");
        const int64_t s4 = w.ship("s4");
        w.m.set_i(s4, Field::is_ship_class, 0);
        w.k.begin({a.ship, s2, s3, s4}, kDt, kNow,
                  {K0Reason::Audit, std::nullopt, std::nullopt, std::nullopt});
        EXPECT_EQ(w.run(), (V{"RUN_PYTHON ship audit", "RUN_PYTHON s2 not_weapon_system",
                              "RUN_PYTHON s4 not_weapon_system", "DONE"}));
        // The handed-back ship was not stepped.
        EXPECT_EQ(w.m.get_f(a.b, Field::_charge_level), 0.001);
    }
    {   // A group that is not a weapon system.
        World w;
        const int64_t s = w.ship("s");
        const int64_t sensors = w.m.register_row(Kind::Subsystem);
        w.m.set_ref(s, Field::_phaser_system, sensors);
        w.k.begin({s}, kDt, kNow);
        EXPECT_EQ(w.run(), (V{"RUN_PYTHON s not_weapon_system", "DONE"}));
    }
    {   // Weapons: an unnamed child, one dropped mid-walk, the check, kind 0.
        Armed a;
        World& w = a.w;
        const int64_t b2 = w.weapon("b2", a.ph);
        const int64_t b3 = w.weapon("b3", a.ph);
        const int64_t odd = w.weapon("odd", a.ph);
        w.m.set_i(odd, Field::weapon_kind, 0);
        auto kids = w.m.get_ids(a.ph, Field::_children);
        kids.insert(kids.begin() + 1, kRefUnrepresentable);
        w.m.set_ids(a.ph, Field::_children, kids);
        w.k.set_weapon_check([&](int64_t h) { return h == b3 || h == a.tb; });
        w.k.begin({a.ship}, kDt, kNow);
        w.m.unregister_row(b2);  // dropped after the begin snapshot
        K0Record r = w.k.next();
        EXPECT_EQ(w.rec(r), "RUN_PYTHON -2 unrepresentable");
        EXPECT_EQ(r.index, 1);
        r = w.k.next();
        EXPECT_EQ(w.rec(r), "RUN_PYTHON b2 stale_row");
        EXPECT_EQ(r.index, 2);
        EXPECT_EQ(w.rec(w.k.next()), "RUN_PYTHON b3 override");
        EXPECT_EQ(w.rec(w.k.next()), "RUN_PYTHON odd unknown_kind");
        EXPECT_EQ(w.rec(w.k.next()), "RUN_PYTHON tb override");
        w.k.abandon();
    }
}

TEST(K0Charging, SnapshotAtBegin) {
    // A weapon added after begin is not walked this tick.
    Tube u;  // t is full
    u.w.k.begin({u.ship}, kDt, kNow);
    const int64_t t2 = u.w.weapon("t2", u.sys);
    u.w.slots(t2, {3.0}, {99.0}, 1, 0);
    EXPECT_EQ(u.w.run(), (V{"DONE"}));
    EXPECT_EQ(u.w.m.get_floats(t2, Field::_reload_timers), std::vector<double>{3.0});
}

TEST(K0Charging, UndoOnThrow) {
    Pulse q(0.5);
    q.w.m.set_i(q.p, Field::_watch_checks, 1);  // p queues a WATCH
    q.w.m.set_f(q.p, Field::_watch_value, 0.25);
    const int64_t p2 = q.w.weapon("p2", q.sys);
    q.w.m.set_f(p2, Field::_charge_level, 1.0);
    q.w.m.set_f(p2, Field::_max_charge, 2.0);
    q.w.m.set_f(p2, Field::_recharge_rate, 0.5);
    bool fail = true;
    q.w.k.set_weapon_check([&](int64_t h) {
        if (h == p2 && fail) throw std::runtime_error("check raised");
        return false;
    });
    q.w.k.begin({q.ship}, kDt, kNow);
    EXPECT_THROW(q.w.k.next(), std::runtime_error);
    // p's writes never reached Python: undone in the mirror.
    EXPECT_EQ(q.w.m.get_f(q.p, Field::_cooldown_remaining), 0.5);
    EXPECT_EQ(q.w.m.get_f(q.p, Field::_charge_level), 1.0);
    EXPECT_EQ(q.w.m.get_f(q.p, Field::_watch_value), 0.25);
    EXPECT_EQ(q.w.k.counts().steps, 0);
    EXPECT_EQ(q.w.k.counts().logged_writes, 0);
    EXPECT_EQ(q.w.k.counts().logged_watch, 0);
    EXPECT_EQ(q.w.k.counts().entries[static_cast<size_t>(K0Effect::WATCH)], 0);
    // The session is as before the call: a retry steps p again.
    fail = false;
    const K0Record r = q.w.k.next();
    EXPECT_EQ(q.w.rec(r), "DONE");
    EXPECT_EQ(q.w.writes(r), (V{"p._cooldown_remaining=0x1.eeeeeeeeeeeefp-2",
                                "p._charge_level=0x1.0222222222222p+0",
                                "p._charge_watcher._value=0x1.0222222222222p-1",
                                "p2._charge_level=0x1.0222222222222p+0",
                                "p2._charge_watcher._value=0x1.0222222222222p-1"}));
    // The entry the thrown call made went with its writes: one WATCH, from
    // the restored value.
    EXPECT_EQ(q.w.entries(r),
              (V{"WATCH p 0x1.0000000000000p-2->0x1.0222222222222p-1@3"}));
    q.w.k.end();
}

TEST(K0Charging, UndoRestoresSlotLists) {
    Tube u;
    const int64_t t2 = u.w.weapon("t2", u.sys);
    u.w.slots(u.t, {3.0}, {99.0}, 1, 0);
    u.w.m.set_f(u.t, Field::_reload_delay, 10.0);  // advances, no reload
    u.w.k.set_weapon_check([&](int64_t h) -> bool {
        if (h == t2) throw std::runtime_error("check raised");
        return false;
    });
    u.w.k.begin({u.ship}, kDt, kNow);
    EXPECT_THROW(u.w.k.next(), std::runtime_error);
    EXPECT_EQ(u.w.m.get_floats(u.t, Field::_reload_timers), std::vector<double>{3.0});
    EXPECT_EQ(u.w.m.get_floats(u.t, Field::_reload_advanced_at), std::vector<double>{99.0});
    u.w.k.abandon();
}

TEST(K0Charging, UndoRestoresMultiSlotLists) {
    // Every slot of a tube advances (two slot writes each): the snapshot a
    // throw restores is the lists as they were before the tube's step.
    Tube u;
    const int64_t t2 = u.w.weapon("t2", u.sys);
    u.w.slots(u.t, {3.0, -1.0, 1.0}, {99.0, 98.0, 97.0}, 3, 1);
    u.w.m.set_f(u.t, Field::_reload_delay, 1000.0);  // advances, no reload
    u.w.k.set_weapon_check([&](int64_t h) -> bool {
        if (h == t2) throw std::runtime_error("check raised");
        return false;
    });
    u.w.k.begin({u.ship}, kDt, kNow);
    EXPECT_THROW(u.w.k.next(), std::runtime_error);
    EXPECT_EQ(u.w.m.get_floats(u.t, Field::_reload_timers),
              (std::vector<double>{3.0, -1.0, 1.0}));
    EXPECT_EQ(u.w.m.get_floats(u.t, Field::_reload_advanced_at),
              (std::vector<double>{99.0, 98.0, 97.0}));
    // A retry makes the same writes from the restored lists.
    u.w.k.set_weapon_check({});
    const K0Record r = u.w.k.next();
    EXPECT_EQ(u.w.rec(r), "DONE");
    EXPECT_EQ(u.w.writes(r),
              // 3.0 + 1.0 * (100 - 99), 1.0 + 1.0 * (100 - 97); t2 is full.
              (V{"t._reload_timers[0]=0x1.0000000000000p+2",
                 "t._reload_advanced_at[0]=0x1.9000000000000p+6",
                 "t._reload_timers[2]=0x1.0000000000000p+2",
                 "t._reload_advanced_at[2]=0x1.9000000000000p+6"}));
    u.w.k.end();
}

TEST(K0Charging, LogStorageIsReused) {
    // A record's writes view the session's log (valid until the next
    // next()): cleared, not reallocated, so a later call or session logs
    // into the same storage. Each entry is the step's K0FieldWrite on its
    // handle.
    Tube u;
    u.w.slots(u.t, {3.0}, {99.0}, 1, 0);
    u.w.m.set_f(u.t, Field::_reload_delay, 1000.0);
    u.w.k.begin({u.ship}, kDt, kNow);
    const K0Record r1 = u.w.k.next();
    ASSERT_EQ(r1.writes.size(), 2u);
    const K0Write* first = r1.writes.data();
    EXPECT_EQ(r1.writes[0].handle, u.t);
    EXPECT_EQ(r1.writes[0].w.type, K0FieldWrite::Type::Slot);
    EXPECT_EQ(r1.writes[0].w.field, Field::_reload_timers);
    EXPECT_EQ(r1.writes[1].w.field, Field::_reload_advanced_at);
    u.w.k.end();
    // A longer log next session (40 slots: 80 writes) still lands in the
    // same storage: it was kept, not freed and grown again.
    u.w.slots(u.t, std::vector<double>(40, 3.0), std::vector<double>(40, 99.0),
              40, 0);
    u.w.k.begin({u.ship}, kDt, kNow + 1.0);
    const K0Record r2 = u.w.k.next();
    ASSERT_EQ(r2.writes.size(), 80u);
    EXPECT_EQ(r2.writes.data(), first);
    u.w.k.end();
}

TEST(K0Charging, Counters) {
    Armed a;
    a.w.k.begin({a.ship, -1}, kDt, kNow);
    a.w.run();
    const K0Session::Counts& c = a.w.k.counts();
    EXPECT_EQ(c.steps, 3);  // b, p, t (the tractor is handed back)
    // Never returned now (THE EFFECT QUEUE): their numbers are kept.
    EXPECT_EQ(c.records[static_cast<size_t>(K0Kind::DEPLETE_STOP)], 0);
    EXPECT_EQ(c.records[static_cast<size_t>(K0Kind::WATCH)], 0);
    EXPECT_EQ(c.records[static_cast<size_t>(K0Kind::RELOADED)], 0);
    EXPECT_EQ(c.records[static_cast<size_t>(K0Kind::RUN_PYTHON)], 2);
    EXPECT_EQ(c.records[static_cast<size_t>(K0Kind::DONE)], 1);
    EXPECT_EQ(c.logged_deplete_stop, 1);
    EXPECT_EQ(c.logged_watch, 1);
    EXPECT_EQ(c.logged_reload, 1);
    EXPECT_EQ(c.entries[static_cast<size_t>(K0Effect::LOOP_STOP)], 1);
    EXPECT_EQ(c.entries[static_cast<size_t>(K0Effect::WATCH)], 1);
    EXPECT_EQ(c.entries[static_cast<size_t>(K0Effect::TORPEDO_RELOAD)], 1);
    EXPECT_EQ(c.python_reasons[static_cast<size_t>(K0Reason::Override)], 1);
    EXPECT_EQ(c.python_reasons[static_cast<size_t>(K0Reason::NoRow)], 1);
    // b: charge, depleted, the stop's two; p: the watcher's value (full, no
    // cooldown); t: two slot writes, the reload's slot, _num_ready.
    EXPECT_EQ(c.logged_writes, 4 + 1 + 4);
    a.w.k.reset_counts();
    EXPECT_EQ(a.w.k.counts().steps, 0);
    EXPECT_EQ(a.w.k.counts().logged_watch, 0);
    EXPECT_EQ(a.w.k.counts().entries[0], 0);
}

TEST(K0Charging, NoneChildHandsBackUnrepresentable) {
    // A None child: the mirror's id lists hold no -1 (set_ids refuses it),
    // so `_children` pushes None as -2 like any object it cannot name. The
    // kernel hands it back by position; the driver resolves it to None and
    // skips it, as step_every_weapon's `if emitter is None: continue`.
    Firing f;
    auto kids = f.w.m.get_ids(f.sys, Field::_children);
    EXPECT_THROW(
        {
            auto bad = kids;
            bad.insert(bad.begin(), -1);
            f.w.m.set_ids(f.sys, Field::_children, bad);
        },
        std::invalid_argument);
    kids.insert(kids.begin(), kRefUnrepresentable);
    f.w.m.set_ids(f.sys, Field::_children, kids);
    f.w.m.set_f(f.b, Field::_charge_level, 0.001);
    f.w.k.begin({f.ship}, kDt, kNow);
    const K0Record r = f.w.k.next();
    EXPECT_EQ(f.w.rec(r), "RUN_PYTHON -2 unrepresentable");
    EXPECT_EQ(r.ship_pos, 0);
    EXPECT_EQ(r.group, 0);
    EXPECT_EQ(r.index, 0);
    EXPECT_TRUE(r.writes.empty());
    EXPECT_EQ(f.w.entries(f.w.k.next()), (V{"LOOP_STOP b@4"}));
    f.w.k.end();
}

TEST(K0Charging, CountdownExactlyZeroOrNaNDrains) {
    // `_beam_on_countdown > 0.0` is false for 0.0 and NaN: the drain runs
    // (level 2 from 5.0, as DrainAtEachPowerLevel).
    for (double c : {0.0, -0.0, kNaN}) {
        Firing f;
        f.w.m.set_f(f.b, Field::_beam_on_countdown, c);
        const K0Step s = step_energy(f.w.m, f.b, kDt);
        EXPECT_FALSE(s.handback) << c;
        EXPECT_EQ(f.w.writes(f.b, s), (V{"b._charge_level=0x1.3eeeeeeeeeeefp+2"}))
            << c;
    }
}

TEST(K0Charging, TubeParentOffStillReloads) {
    // UpdateReload reads no IsOn() (WSM A11): an off parent's factor is used.
    Tube u;
    u.w.m.set_i(u.sys, Field::_is_on, 0);
    u.w.slots(u.t, {3.0}, {99.0}, 1, 0);
    EXPECT_EQ(u.step(), (V{"t._reload_timers[0]=0x1.0000000000000p+2",
                           "t._reload_advanced_at[0]=0x1.9000000000000p+6",
                           "t._reload_timers[0]=-0x1.0000000000000p+0",
                           "t._num_ready=1"}));
}

TEST(K0Charging, TubeNoParentFactorOneNoAmmoGate) {
    // parent None: factor 1.0 (not the system's 0.5), and _parent_ammo is
    // None, so the system's empty finite ammo denies nothing.
    Tube u;
    u.w.m.set_f(u.sys, Field::_power_factor, 0.5);
    const int64_t ammo = u.w.m.register_row(Kind::Ammo);
    u.w.m.set_i(ammo, Field::_unlimited, 0);
    u.w.m.set_i(ammo, Field::_available, 0);
    u.w.m.set_ids(u.sys, Field::_ammo_by_slot, {0, ammo});
    u.w.m.set_ref(u.t, Field::_parent_subsystem, -1);
    u.w.slots(u.t, {3.0}, {99.0}, 1, 0);
    EXPECT_EQ(u.step(), (V{"t._reload_timers[0]=0x1.0000000000000p+2",
                           "t._reload_advanced_at[0]=0x1.9000000000000p+6",
                           "t._reload_timers[0]=-0x1.0000000000000p+0",
                           "t._num_ready=1"}));
}

TEST(K0Charging, TubeParentHandsBack) {
    {   // A parent the mirror cannot name: before any write.
        Tube u;
        u.w.slots(u.t, {3.0}, {99.0}, 1, 0);
        u.w.m.set_ref(u.t, Field::_parent_subsystem, kRefUnrepresentable);
        const K0Step s = step_tube(u.w.m, u.t, kNow);
        ASSERT_TRUE(s.handback);
        EXPECT_EQ(*s.handback, K0Reason::Parent);
        EXPECT_TRUE(s.writes.empty());
    }
    {   // A weapon-system parent that is not a TorpedoSystem: its factor
        // serves the slot advance, but only Python answers its
        // GetCurrentAmmoType() -- the whole step is Python's.
        Tube u;
        u.w.m.set_i(u.sys, Field::weapon_kind, 1);
        u.w.slots(u.t, {3.0}, {99.0}, 1, 0);
        const K0Step s = step_tube(u.w.m, u.t, kNow);
        ASSERT_TRUE(s.handback);
        EXPECT_EQ(*s.handback, K0Reason::Parent);
        EXPECT_TRUE(s.writes.empty());
        // No reload due: the ammo gate is never reached.
        u.w.slots(u.t, {1.0}, {99.0}, 1, 0);
        EXPECT_EQ(u.step(), (V{"t._reload_timers[0]=0x1.0000000000000p+1",
                               "t._reload_advanced_at[0]=0x1.9000000000000p+6"}));
    }
}

TEST(K0Charging, TubeRoundsLoadedSumsEveryTubeSibling) {
    // _rounds_loaded_systemwide: GetNumReady() of every TorpedoTube among
    // the parent's _children -- a sibling stepped nowhere else counts, a
    // non-tube child does not.
    Tube u;
    const int64_t ammo = u.w.m.register_row(Kind::Ammo);
    u.w.m.set_i(ammo, Field::_unlimited, 0);
    u.w.m.set_i(ammo, Field::_available, 2);
    u.w.m.set_ids(u.sys, Field::_ammo_by_slot, {0, ammo});
    const int64_t o1 = u.w.weapon("o1", u.sys);  // a tube, 1 ready
    (void)o1;
    const int64_t bank = u.w.weapon("bank", u.sys);
    u.w.m.set_i(bank, Field::weapon_kind, 5);   // not a tube: not counted
    u.w.slots(u.t, {3.0}, {99.0}, 1, 0);
    EXPECT_EQ(step_tube(u.w.m, u.t, kNow).record, K0Kind::RELOADED);  // 2 > 1
    // A second loaded tube sibling: 2 <= 2, denied (the slot still advances).
    const int64_t o2 = u.w.m.register_row(Kind::Subsystem);
    u.w.m.set_i(o2, Field::weapon_kind, 8);
    u.w.m.set_i(o2, Field::_num_ready, 1);
    auto kids = u.w.m.get_ids(u.sys, Field::_children);
    kids.push_back(o2);
    u.w.m.set_ids(u.sys, Field::_children, kids);
    const K0Step s = step_tube(u.w.m, u.t, kNow);
    EXPECT_EQ(s.record, K0Kind::DONE);
    EXPECT_EQ(u.w.writes(u.t, s), (V{"t._reload_timers[0]=0x1.0000000000000p+2",
                                     "t._reload_advanced_at[0]=0x1.9000000000000p+6"}));
}

// ── TractorBeam.UpdateCharge (WS:3012): idle is the mixin's ────────────────

// A tractor recharging from 2.0 of 5.0 under a tractor system (kind 3).
struct Tractor {
    World w;
    int64_t ship, sys, tb;
    explicit Tractor(double pf = 0.8, double cond = 75.0) {
        ship = w.ship("ship");
        sys = w.system("tractors", ship, 3);
        w.m.set_f(sys, Field::_power_factor, pf);
        tb = w.weapon("tb", sys);
        w.m.set_f(tb, Field::_condition, cond);
        w.m.set_f(tb, Field::_charge_level, 2.0);
        w.m.set_f(tb, Field::_recharge_rate, 0.3);
    }
    // The session's records and every write they carry.
    V run() {
        w.k.begin({ship}, kDt, kNow);
        V out;
        for (int guard = 0; guard < 10; ++guard) {
            K0Record r = w.k.next();
            out.push_back(w.rec(r));
            for (const std::string& x : w.writes(r)) out.push_back(x);
            if (r.kind == K0Kind::DONE) {
                w.k.end();
                return out;
            }
        }
        ADD_FAILURE() << "no DONE";
        return out;
    }
};

TEST(K0Charging, IdleTractorRechargesNatively) {
    // `if self._firing: ...` false -> super().UpdateCharge(dt): the mixin's
    // recharge (the same formula and values as RechargeFormula).
    Tractor t;
    EXPECT_EQ(t.run(), (V{"DONE", "tb._charge_level=0x1.00624dd2f1aa0p+1"}));
    EXPECT_EQ(t.w.k.counts().steps, 1);
    EXPECT_EQ(t.w.k.counts().records[static_cast<size_t>(
                  K0Kind::RUN_PYTHON)], 0);
}

TEST(K0Charging, IdleTractorParentOffOrNone) {
    {   // Parent off: the mixin's IsOn() gate, nothing written.
        Tractor t;
        t.w.m.set_i(t.sys, Field::_is_on, 0);
        EXPECT_EQ(t.run(), (V{"DONE"}));
    }
    {   // Parent None: power factor 1.0.
        Tractor t;
        t.w.m.set_ref(t.tb, Field::_parent_subsystem, -1);
        EXPECT_EQ(t.run(), (V{"DONE", "tb._charge_level=0x1.007ae147ae148p+1"}));
    }
}

TEST(K0Charging, IdleTractorNaNConditionReadsFull) {
    Tractor t(0.8, kNaN);
    EXPECT_EQ(t.run(), (V{"DONE", "tb._charge_level=0x1.0083126e978d5p+1"}));
}

TEST(K0Charging, HoldingTractorPowerLossStops) {
    // TractorBeam.UpdateCharge's holding branch (fire control native only,
    // M4): no hand-back. Powered, it writes nothing (no discharge while
    // holding); its parent off -- or None -- stops it (the mixin's stop, then
    // LOOP_STOP); the charge is never touched.
    {
        Tractor t;
        t.w.m.set_i(t.tb, Field::_firing, 1);
        EXPECT_EQ(t.run(), (V{"DONE"}));
        EXPECT_EQ(t.w.k.counts().steps, 1);
        EXPECT_EQ(t.w.k.counts().logged_hold_stop, 0);
    }
    for (const bool none : {false, true}) {
        Tractor t;
        t.w.m.set_i(t.tb, Field::_firing, 1);
        if (none)
            t.w.m.set_ref(t.tb, Field::_parent_subsystem, -1);
        else
            t.w.m.set_i(t.sys, Field::_is_on, 0);
        t.w.k.begin({t.ship}, kDt, kNow);
        const K0Record r = t.w.k.next();
        EXPECT_EQ(t.w.rec(r), "DONE");
        EXPECT_EQ(t.w.writes(r),
                  (V{"tb._firing=False", "tb._beam_on_countdown=0x0.0p+0"}));
        EXPECT_EQ(t.w.entries(r), (V{"LOOP_STOP tb@2"}));
        t.w.k.end();
        EXPECT_EQ(t.w.m.get_i(t.tb, Field::_firing), 0);
        EXPECT_EQ(t.w.m.get_f(t.tb, Field::_charge_level), 2.0);
        EXPECT_EQ(t.w.k.counts().logged_hold_stop, 1);
    }
}

TEST(K0Charging, HoldingTractorStarvationStops) {
    // `parent.GetPowerPercentage() <= 0.0 and parent.GetNormalPowerWanted()
    // > 0.0`: _efficiency and _normal_power. Either side alone holds.
    struct C {
        double efficiency, normal;
        bool stops;
    };
    for (const C c : {C{0.0, 600.0, true}, C{-0.0, 600.0, true},
                      C{0.25, 600.0, false}, C{0.0, 0.0, false}}) {
        Tractor t;
        t.w.m.set_i(t.tb, Field::_firing, 1);
        t.w.m.set_f(t.sys, Field::_efficiency, c.efficiency);
        t.w.m.set_f(t.sys, Field::_normal_power, c.normal);
        t.run();
        EXPECT_EQ(t.w.m.get_i(t.tb, Field::_firing), c.stops ? 0 : 1)
            << c.efficiency << " " << c.normal;
    }
    {   // A parent the mirror cannot stand in for: Python's.
        Tractor t;
        t.w.m.set_i(t.tb, Field::_firing, 1);
        t.w.m.set_ref(t.tb, Field::_parent_subsystem, kRefUnrepresentable);
        EXPECT_EQ(t.run(), (V{"RUN_PYTHON tb parent", "DONE"}));
    }
}

TEST(K0Charging, IdleTractorObeysTheWeaponCheck) {
    Tractor t;
    t.w.k.set_weapon_check([&](int64_t h) { return h == t.tb; });
    EXPECT_EQ(t.run(), (V{"RUN_PYTHON tb override", "DONE"}));
}

TEST(K0Charging, Protocol) {
    World w;
    EXPECT_THROW(w.k.next(), std::logic_error);
    EXPECT_THROW(w.k.end(), std::logic_error);
    EXPECT_THROW(w.k.abandon(), std::logic_error);
    w.k.begin({}, kDt, kNow);
    EXPECT_TRUE(w.k.open());
    EXPECT_THROW(w.k.begin({}, kDt, kNow), std::logic_error);
    EXPECT_THROW(w.k.end(), std::logic_error);  // not DONE yet
    EXPECT_EQ(w.k.next().kind, K0Kind::DONE);
    EXPECT_THROW(w.k.next(), std::logic_error);  // past DONE
    w.k.end();
    EXPECT_FALSE(w.k.open());
    EXPECT_THROW(w.k.begin({1, 2}, kDt, kNow, {std::nullopt}), std::invalid_argument);
    EXPECT_FALSE(w.k.open());
    EXPECT_STREQ(k0_kind_name(K0Kind::RUN_PYTHON), "RUN_PYTHON");
    EXPECT_STREQ(k0_reason_name(K0Reason::NotWeaponSystem), "not_weapon_system");
    EXPECT_STREQ(k0_reason_name(K0Reason::SlotHeal), "slot_heal");
}

TEST(K0Charging, NextWhileDeliveringIsLost) {
    // A record's writes are a view of the session's log; the binding applies
    // them while running Python (wake hooks, setters). A next() from that
    // Python would clear the log under the view and step the walk on:
    // refused, with the log, the cursor and the mirror untouched, so the
    // delivery finishes on the same writes and the walk resumes after it.
    Pulse q(0.5);
    const int64_t tsys = q.w.system("tractors", q.ship, 3);
    const int64_t tb = q.w.weapon("tb", tsys);
    q.w.k.set_weapon_check([&](int64_t h) { return h == tb; });  // Python's
    const int64_t p2 = q.w.weapon("p2", q.sys);
    q.w.m.set_f(p2, Field::_cooldown_remaining, 0.5);
    // p2 joined the pulse group after the tractors were made, but the walk
    // order is the GROUP order: p, p2, then the tractor.
    q.w.m.set_ids(q.sys, Field::_children, {q.p});
    q.w.m.set_ids(tsys, Field::_children, {tb, p2});
    q.w.k.begin({q.ship}, kDt, kNow);
    const K0Record r = q.w.k.next();
    ASSERT_EQ(q.w.rec(r), "RUN_PYTHON tb override");  // not done: p2 to step
    const V delivered = q.w.writes(r);
    ASSERT_EQ(delivered.size(), 3u);
    q.w.k.set_delivering(true);
    EXPECT_TRUE(q.w.k.delivering());
    EXPECT_THROW(q.w.k.next(), std::logic_error);
    EXPECT_EQ(q.w.writes(r), delivered);
    EXPECT_EQ(q.w.m.get_f(p2, Field::_cooldown_remaining), 0.5);
    q.w.k.set_delivering(false);
    EXPECT_FALSE(q.w.k.delivering());
    const K0Record d = q.w.k.next();         // delivered: the walk goes on
    EXPECT_EQ(q.w.rec(d), "DONE");
    EXPECT_EQ(q.w.writes(d), (V{"p2._cooldown_remaining=0x1.eeeeeeeeeeeefp-2",
                                "p2._charge_watcher._value=0x1.0000000000000p+0"}));
    q.w.k.end();
}

}  // namespace

TEST(K0Charging, UndoRestoresAPulseStopsRefAndOffset) {
    // Review minor 3: a pulse cannon drained dry logs its StopFiring's
    // `_target = None` (Ref) and `_target_offset = None` (Null); a throw
    // later in the same call undoes both in the mirror, with the rest.
    Pulse q(0.0);
    q.w.m.set_i(q.p, Field::_firing, 1);
    q.w.m.set_ref(q.p, Field::_target, q.ship);
    q.w.m.set_fv(q.p, Field::_target_offset, {1.0, 2.0, 3.0});
    q.w.m.set_f(q.p, Field::_charge_level, 0.001);
    const int64_t p2 = q.w.weapon("p2", q.sys);
    q.w.k.set_weapon_check([&](int64_t h) -> bool {
        if (h == p2) throw std::runtime_error("check raised");
        return false;
    });
    q.w.k.begin({q.ship}, kDt, kNow);
    EXPECT_THROW(q.w.k.next(), std::runtime_error);
    EXPECT_EQ(q.w.m.get_i(q.p, Field::_firing), 1);
    EXPECT_EQ(q.w.m.get_i(q.p, Field::_depleted), 0);
    EXPECT_EQ(q.w.m.get_ref(q.p, Field::_target), q.ship);
    const SubsystemRow& r = *q.w.m.subsystem(q.p);
    EXPECT_TRUE(r.target_offset_set);
    EXPECT_EQ(r._target_offset, (Vec3{1.0, 2.0, 3.0}));
    EXPECT_EQ(q.w.m.get_f(q.p, Field::_charge_level), 0.001);
    q.w.k.abandon();
}
