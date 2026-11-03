// The K2 beam kernel (k2_beams.h) on hand-built mirror rows with a FAKE trace:
// the record sequence of the `cb.phasers` walk, the `_dwell` write log, the
// fallbacks and the unwind. The native-vs-Python differentials run from
// tests/unit/test_native_k2_dispatch.py and the host-level K2 differential
// (Tasks 5 and 6).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "dauntless/combat/beam_geometry.h"
#include "dauntless/combat/beam_trace.h"
#include "dauntless/combat/k2_beams.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/combat/py_math.h"
#include "dauntless/combat/sensor_detect.h"
#include "dauntless/combat/weapon_geometry.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr double kDt = 1.0 / 60.0;

// A fake host: the instance {1, 1} is live at the origin and its trace
// returns `hit` (or nothing); any other id is stale. Every call is counted.
struct FakeHost {
    std::optional<TraceHit> hit;
    int calls = 0;
    bool throw_foreign = false;  // throw a non-std exception (an unwind test)

    TraceHooks hooks() {
        TraceHooks h;
        h.translation = [](InstanceId id) -> std::optional<Vec3> {
            if (id.index != 1 || id.generation != 1) return std::nullopt;
            return Vec3{0.0, 0.0, 0.0};
        };
        h.trace = [this](InstanceId id, const float*, const float*,
                         float) -> std::optional<TraceHit> {
            ++calls;
            if (throw_foreign) throw 42;
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
    K2Kernel k{m};
    FakeHost host;
    int64_t set = -1;
    int64_t next_id = 1;
    std::map<int64_t, std::string> names;

    World() {
        m.set_global_f(Global::BEAM_DWELL_FLUSH_S, 0.5);
        m.set_global_f(Global::SHIELD_ELLIPSOID_AXIS_SCALE, std::sqrt(3.0));
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

    // A placed DamageableObject in the one set, alive.
    int64_t object(const std::string& name, double x, double y, double z) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, x, y, z);
        const int64_t h = m.register_row(Kind::Object, i, g, next_id++);
        m.set_i(h, Field::has_real_is_dead, 1);
        m.set_f(h, Field::_life_time, 1.0e9);
        m.set_ref(h, Field::_containing_set, set);
        m.set_f(h, Field::o_radius, 5.0);
        m.set_f(h, Field::_scale, 1.0);
        names[h] = name;
        return h;
    }
    // A ShipClass (no sensor subsystem: the sensorless dial, 2000 GU).
    int64_t ship(const std::string& name, double x = 0.0, double y = 0.0,
                 double z = 0.0) {
        const int64_t h = object(name, x, y, z);
        m.set_i(h, Field::is_ship_class, 1);
        m.set_i(h, Field::has_real_get_shields, 1);
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
    // A powered, healthy phaser system on `ship_h`.
    int64_t system(const std::string& name, int64_t ship_h) {
        const int64_t s = m.register_row(Kind::Subsystem);
        names[s] = name;
        m.set_i(s, Field::weapon_kind, 1);
        m.set_i(s, Field::_is_on, 1);
        m.set_i(s, Field::has_parent_ship_getter, 1);
        m.set_ref(s, Field::_parent_ship, ship_h);
        m.set_f(s, Field::_max_condition, 100.0);
        m.set_f(s, Field::_condition, 100.0);
        m.set_f(s, Field::_disabled_percentage, 0.25);
        m.set_ref(ship_h, Field::_phaser_system, s);
        return s;
    }
    // A point phaser bank (Length 0) at the ship's origin facing +y, aimed
    // at `target`; `firing` lit with its beam on (countdown 0).
    int64_t bank(const std::string& name, int64_t sys, int64_t target,
                 bool firing, double dwell = 0.0) {
        const int64_t b = m.register_row(Kind::Subsystem);
        names[b] = name;
        m.set_i(b, Field::weapon_kind, 5);
        m.set_i(b, Field::has_parent_ship_getter, 1);
        m.set_ref(b, Field::_parent_subsystem, sys);
        m.set_f(b, Field::_max_condition, 100.0);
        m.set_f(b, Field::_condition, 100.0);
        m.set_f(b, Field::_disabled_percentage, 0.25);
        m.set_fv(b, Field::_position, {0.0, 0.0, 0.0});
        m.set_fv(b, Field::_direction, {0.0, 1.0, 0.0});
        m.set_fv(b, Field::_up, {0.0, 0.0, 1.0});
        m.set_fv(b, Field::_right, {1.0, 0.0, 0.0});
        m.set_f(b, Field::_arc_width_lo, -3.0);
        m.set_f(b, Field::_arc_width_hi, 3.0);
        m.set_i(b, Field::_firing, firing ? 1 : 0);
        m.set_f(b, Field::_beam_on_countdown, 0.0);
        m.set_f(b, Field::_dwell, dwell);
        m.set_ref(b, Field::_target, target);
        auto kids = m.get_ids(sys, Field::_children);
        kids.push_back(b);
        m.set_ids(sys, Field::_children, kids);
        return b;
    }
    // A ship + system + one bank at a target 50 GU ahead.
    struct Scene {
        int64_t ship, sys, target, bank;
    };
    Scene scene(bool firing, double dwell = 0.0) {
        Scene s;
        s.ship = ship("ship");
        s.sys = system("sys", s.ship);
        s.target = ship("t", 0.0, 50.0, 0.0);
        s.bank = bank("b0", s.sys, s.target, firing, dwell);
        return s;
    }

    void begin(std::vector<int64_t> ships, bool use_memo = true) {
        K2Context ctx;
        ctx.hooks = host.hooks();
        ctx.view_offsets[set] = std::nullopt;
        k.begin(std::move(ships), kDt, 10.0, use_memo, 0.0, std::move(ctx));
    }

    std::string name(int64_t h) const {
        auto it = names.find(h);
        return it == names.end() ? std::to_string(h) : it->second;
    }
    static std::string num(double d) {
        char buf[64];
        std::snprintf(buf, sizeof buf, "%.17g", d);
        return buf;
    }
    std::string value(const K1Value& v) const {
        if (std::holds_alternative<std::monostate>(v)) return "None";
        if (const bool* b = std::get_if<bool>(&v)) return *b ? "True" : "False";
        if (const int64_t* i = std::get_if<int64_t>(&v))
            return std::to_string(*i);
        if (const double* d = std::get_if<double>(&v)) return num(*d);
        if (const auto* ids = std::get_if<std::vector<int64_t>>(&v)) {
            std::string out = "[";
            for (const int64_t h : *ids)
                out += (out.size() > 1 ? "," : "") + name(h);
            return out + "]";
        }
        return "walk_offset";
    }
    std::vector<std::string> writes(const K2Record& r) const {
        std::vector<std::string> out;
        for (const K2Write& w : r.writes)
            out.push_back(name(w.handle) + "." + std::string(w.field) + "=" + value(w.value));
        return out;
    }
    // A record's queue entries (k2_beams.h, THE EFFECT QUEUE): "KIND bank@at".
    std::vector<std::string> entries(const K2Record& r) const {
        std::vector<std::string> out;
        for (const K1Entry& e : r.entries)
            out.push_back(std::string(k1_effect_name(e.kind)) + " " +
                          name(e.a) + "@" + std::to_string(e.at));
        return out;
    }
    // The kernel's records as the driver acts on them (run_k2): each record
    // with its writes; at DONE, the resting contacts queued for the drain
    // (rests(), in walk order) first, each as a CONTACT -- the first one
    // carrying DONE's writes, which the driver applies before it drains --
    // then DONE. The raw record is in `raw`, the drained queue in `drained`.
    std::deque<K2Record> pending;
    K2Record raw;
    std::vector<K2Rest> drained;
    K2Record next() {
        if (pending.empty()) {
            raw = k.next();
            K2Record r = raw;
            if (r.kind == K2Kind::DONE) {
                drained = k.rests();
                for (const K2Rest& q : drained) {
                    K2Record c;
                    c.kind = K2Kind::CONTACT;
                    c.contact = q.contact;
                    if (pending.empty()) c.writes = std::move(r.writes);
                    pending.push_back(std::move(c));
                }
                if (!drained.empty()) r.writes.clear();
            }
            pending.push_back(std::move(r));
        }
        K2Record r = std::move(pending.front());
        pending.pop_front();
        return r;
    }
    // "KIND a" for a quick sequence check.
    std::string brief(const K2Record& r) const {
        std::string s = k2_kind_name(r.kind);
        switch (r.kind) {
            case K2Kind::DONE: break;
            case K2Kind::CONTACT:
                s += " " + name(r.contact.bank) + "@" + name(r.contact.target) +
                     " flush=" + num(r.contact.flush_dwell);
                break;
            case K2Kind::ASK: s += std::string(" ") + k2_query_name(r.query); break;
            case K2Kind::RUN_PYTHON:
                s += " " + (r.a < 0 ? std::to_string(r.a) : name(r.a)) + " " +
                     std::to_string(r.b);
                break;
            default: s += " " + name(r.a); break;
        }
        return s;
    }
    // Every record up to and including DONE (no ASK expected).
    std::vector<std::string> run_to_done() {
        std::vector<std::string> out;
        for (int guard = 0; guard < 200; ++guard) {
            const K2Record r = next();
            out.push_back(brief(r));
            if (r.kind == K2Kind::DONE) break;
        }
        return out;
    }
    // Raw records up to DONE (no ASK expected), the session left open so
    // the test reads rests().
    void finish_to_done_raw() {
        for (int guard = 0; guard < 200; ++guard)
            if (k.next().kind == K2Kind::DONE) break;
    }
    // Run the rest of the session (no ASK expected) and end it.
    void finish() {
        for (int guard = 0; guard < 200; ++guard)
            if (next().kind == K2Kind::DONE) break;
        k.end();
    }
    using V = std::vector<std::string>;
};

}  // namespace

TEST(K2, KindsAndNames) {
    EXPECT_STREQ(k2_kind_name(K2Kind::DONE), "DONE");
    EXPECT_STREQ(k2_kind_name(K2Kind::SYSTEM_STOP), "SYSTEM_STOP");
    EXPECT_STREQ(k2_kind_name(K2Kind::BANK_STOP), "BANK_STOP");
    EXPECT_STREQ(k2_kind_name(K2Kind::CONTACT), "CONTACT");
    EXPECT_STREQ(k2_kind_name(K2Kind::RUN_PYTHON), "RUN_PYTHON");
    EXPECT_STREQ(k2_kind_name(K2Kind::ASK), "ASK");
    EXPECT_STREQ(k2_query_name(K2Query::resolve_hit), "resolve_hit");
    EXPECT_STREQ(k2_query_name(K2Query::bank_step), "bank_step");
    EXPECT_STREQ(k2_why_name(K2Why::PosedShip), "posed_ship");
    EXPECT_STREQ(k2_why_name(K2Why::PartStale), "part_stale");
}

TEST(K2, SystemGateStopsEveryTick) {
    // `if _is_offline(sys_) or not sys_.IsOn(): sys_.StopFiring(); continue`
    // -- every tick, even for a system already stopped, and its banks are
    // never walked (a dirty idle dwell is NOT taken). The stop is logged
    // writes (OfflineStopIsLoggedWrites); the bank firing on the first tick
    // also queues its loop sound's LOOP_STOP (combat fire events §4.3).
    for (int gate = 0; gate < 2; ++gate) {
        World w;
        const auto s = w.scene(true, 0.25);
        if (gate == 0) w.m.set_i(s.sys, Field::_is_on, 0);
        // WeaponSystem.IsDisabled aggregates: every child disabled.
        if (gate == 1) w.m.set_f(s.bank, Field::_condition, 10.0);
        for (int tick = 0; tick < 2; ++tick) {
            w.begin({s.ship});
            const K2Record r = w.next();
            EXPECT_EQ(w.brief(r), "DONE") << gate << " " << tick;
            EXPECT_EQ(w.writes(r).size(), 7u);
            EXPECT_EQ(w.entries(r), tick == 0 ? World::V{"LOOP_STOP b0@7"}
                                              : World::V{})
                << gate;
            w.k.end();
        }
        EXPECT_EQ(w.m.get_f(s.bank, Field::_dwell), 0.25);
        EXPECT_EQ(w.m.get_i(s.bank, Field::_firing), 0);
        EXPECT_EQ(w.k.counts().logged_system_stop, 2);
        EXPECT_EQ(w.k.counts().logged_firing_system_stop, 1);
        EXPECT_EQ(w.k.counts().entries[static_cast<size_t>(
                      K1Effect::LOOP_STOP)], 1);
    }
}

TEST(K2, ShipWithNoPhaserSystemIsSkipped) {
    World w;
    const int64_t a = w.ship("a");
    w.begin({a});
    EXPECT_EQ(w.run_to_done(), (World::V{"DONE"}));
    w.k.end();
    EXPECT_EQ(w.k.counts().records, 1);
}

TEST(K2, IdleBankTakesDwellElided) {
    World w;
    const auto s = w.scene(false, 0.0);  // idle, +0.0 over +0.0: elided
    const int64_t b1 = w.bank("b1", s.sys, -1, false, 0.3);  // None target
    const int64_t b2 = w.bank("b2", s.sys, s.target, false, -0.0);  // signed
    w.begin({s.ship});
    const K2Record r = w.next();
    EXPECT_EQ(w.brief(r), "DONE");
    EXPECT_EQ(w.writes(r), (World::V{"b1._dwell=0", "b2._dwell=0"}));
    EXPECT_FALSE(std::signbit(std::get<double>(r.writes[1].value)));
    EXPECT_EQ(w.m.get_f(b1, Field::_dwell), 0.0);
    EXPECT_FALSE(std::signbit(w.m.get_f(b2, Field::_dwell)));
    w.k.end();
}

TEST(K2, DeadOrNoneTargetStops) {
    World w;
    const auto s = w.scene(true);
    w.m.set_ref(s.bank, Field::_target, -1);  // firing at None
    const int64_t dead = w.ship("dead", 0.0, 40.0, 0.0);
    w.m.set_i(dead, Field::_dead, 1);
    w.bank("b1", s.sys, dead, true);
    const int64_t b2 = w.bank("b2", s.sys, dead, false, 0.4);  // idle: no stop
    w.begin({s.ship});
    // `bank.StopFiring()` on a firing bank: its writes, then LOOP_STOP.
    const K2Record r = w.next();
    EXPECT_EQ(w.brief(r), "DONE");
    EXPECT_EQ(w.writes(r),
              (World::V{"b0._firing=False", "b0._beam_on_countdown=0",
                        "b1._firing=False", "b1._beam_on_countdown=0",
                        "b2._dwell=0"}));
    EXPECT_EQ(w.entries(r), (World::V{"LOOP_STOP b0@2", "LOOP_STOP b1@4"}));
    EXPECT_EQ(w.m.get_f(b2, Field::_dwell), 0.0);
    EXPECT_EQ(w.m.get_i(s.bank, Field::_firing), 0);
    w.k.end();
    EXPECT_EQ(w.k.counts().logged_bank_stop, 2);
    EXPECT_EQ(w.k.counts().records, 1);
}

TEST(K2, StubIsDeadAsks) {
    // A target with no real IsDead: Python's stub decides (ASK is_dead).
    World w;
    const auto s = w.scene(true);
    w.m.set_i(s.target, Field::has_real_is_dead, 0);
    w.begin({s.ship});
    const K2Record r = w.next();
    ASSERT_EQ(w.brief(r), "ASK is_dead");
    ASSERT_EQ(r.args.size(), 1u);
    EXPECT_EQ(std::get<int64_t>(r.args[0]), s.target);
    EXPECT_EQ(w.k.awaiting(), K2Query::is_dead);
    K2Answer a;
    a.flag = true;  // the stub is truthy: dead
    w.k.answer(a);
    const K2Record d = w.next();
    EXPECT_EQ(w.brief(d), "DONE");
    EXPECT_EQ(w.entries(d), (World::V{"LOOP_STOP b0@2"}));
    w.k.end();
    EXPECT_EQ(w.k.counts().asks, 1);
    EXPECT_EQ(w.k.counts().queries[static_cast<size_t>(K2Query::is_dead)], 1);
}

TEST(K2, UndetectableStops) {
    World w;
    const auto s = w.scene(true);
    w.cloak(s.target);
    w.begin({s.ship});
    const K2Record d = w.next();
    EXPECT_EQ(w.brief(d), "DONE");
    EXPECT_EQ(w.entries(d), (World::V{"LOOP_STOP b0@2"}));
    w.k.end();
    // can_detect ran through the native memo (use_memo).
    EXPECT_FALSE(w.m.sensor_state().memo.empty());
}

TEST(K2, CrossSetStopsOrDropsDwell) {
    World w;
    const auto s = w.scene(true);
    const int64_t other = w.m.register_row(Kind::Set);
    w.m.set_ref(s.target, Field::_containing_set, other);
    const int64_t b1 = w.bank("b1", s.sys, s.target, false, 0.4);
    // A setless pair shares nothing either.
    const int64_t setless = w.ship("setless", 0.0, 30.0, 0.0);
    w.m.set_ref(setless, Field::_containing_set, -1);
    w.bank("b2", s.sys, setless, true);
    w.begin({s.ship});
    // b1's banked dwell is taken and DROPPED: no stop, no contact.
    const K2Record r = w.next();
    EXPECT_EQ(w.brief(r), "DONE");
    EXPECT_EQ(w.writes(r),
              (World::V{"b0._firing=False", "b0._beam_on_countdown=0",
                        "b1._dwell=0", "b2._firing=False",
                        "b2._beam_on_countdown=0"}));
    EXPECT_EQ(w.entries(r), (World::V{"LOOP_STOP b0@2", "LOOP_STOP b2@5"}));
    EXPECT_EQ(w.m.get_f(b1, Field::_dwell), 0.0);
    w.k.end();
}

TEST(K2, WindupContactsEveryTick) {
    // Lit but inside the beam-on delay: the whole geometry runs and contacts
    // (accumulate_dwell returns 0.0 and writes nothing).
    World w;
    const auto s = w.scene(true, 0.0);
    w.m.set_f(s.bank, Field::_beam_on_countdown, 0.3);
    for (int tick = 0; tick < 2; ++tick) {
        w.begin({s.ship});
        const K2Record r = w.next();
        EXPECT_EQ(w.brief(r), "CONTACT b0@t flush=0");
        EXPECT_TRUE(r.writes.empty());
        EXPECT_EQ(r.contact.system, s.sys);
        EXPECT_EQ(r.contact.ship, s.ship);
        EXPECT_EQ(w.brief(w.next()), "DONE");
        w.k.end();
    }
    EXPECT_EQ(w.m.get_f(s.bank, Field::_dwell), 0.0);
}

TEST(K2, BeamOnAccumulatesAndFlushes) {
    World w;
    const auto s = w.scene(true, 0.25);
    w.begin({s.ship});
    K2Record r = w.next();
    EXPECT_EQ(w.brief(r), "CONTACT b0@t flush=0");
    EXPECT_EQ(w.writes(r), (World::V{"b0._dwell=" + World::num(0.25 + kDt)}));
    EXPECT_EQ(w.brief(w.next()), "DONE");
    w.k.end();
    // Past the threshold: the flush tick counts its own dt.
    w.m.set_f(s.bank, Field::_dwell, 0.6);
    w.begin({s.ship});
    r = w.next();
    EXPECT_EQ(w.brief(r), "CONTACT b0@t flush=" + World::num(0.6 + kDt));
    EXPECT_EQ(w.writes(r), (World::V{"b0._dwell=0"}));
    EXPECT_EQ(w.brief(w.next()), "DONE");
    w.k.end();
}

TEST(K2, ArcFailStopsThenFlushes) {
    // Swept off: take_dwell, then StopFiring, and the partial pulse is still
    // delivered on the same tick with this tick's aim.
    World w;
    const auto s = w.scene(true, 0.2);
    w.store.set_position(static_cast<uint32_t>(w.m.get_i(s.target, Field::xform_index)),
                         static_cast<uint32_t>(w.m.get_i(s.target, Field::xform_gen)),
                         0.0, -50.0, 0.0);  // astern
    w.begin({s.ship});
    // `flush_dwell = bank.take_dwell(); bank.StopFiring()`: the dwell write,
    // the stop's writes and its LOOP_STOP ride the damage pulse's CONTACT.
    const K2Record c = w.next();
    EXPECT_EQ(w.brief(c), "CONTACT b0@t flush=0.20000000000000001");
    EXPECT_EQ(w.writes(c), (World::V{"b0._dwell=0", "b0._firing=False",
                                     "b0._beam_on_countdown=0"}));
    EXPECT_EQ(w.entries(c), (World::V{"LOOP_STOP b0@3"}));
    EXPECT_EQ(c.contact.target_pos, (Vec3{0.0, -50.0, 0.0}));
    EXPECT_EQ(w.brief(w.next()), "DONE");
    w.k.end();
}

TEST(K2, FlushPathSkipsDetectAndArc) {
    // A stopped bank with dwell banked: no can_detect, no arc test -- out of
    // arc AND cloaked, it still delivers its partial pulse.
    World w;
    const auto s = w.scene(false, 0.3);
    w.cloak(s.target);
    w.store.set_position(static_cast<uint32_t>(w.m.get_i(s.target, Field::xform_index)),
                         static_cast<uint32_t>(w.m.get_i(s.target, Field::xform_gen)),
                         0.0, -50.0, 0.0);
    w.begin({s.ship});
    const K2Record c = w.next();
    EXPECT_EQ(w.brief(c), "CONTACT b0@t flush=0.29999999999999999");
    EXPECT_EQ(w.writes(c), (World::V{"b0._dwell=0"}));
    EXPECT_EQ(w.brief(w.next()), "DONE");
    w.k.end();
    EXPECT_TRUE(w.m.sensor_state().memo.empty());
}

TEST(K2, NumWeaponsReadOnce) {
    // `range(sys_.GetNumWeapons())` is evaluated once; GetWeapon(i) live.
    // b0 pulses (a CONTACT record: its handlers run between the banks).
    World w;
    const auto s = w.scene(true, 0.6);
    const int64_t b1 = w.bank("b1", s.sys, s.target, true);
    const std::string pulse = "CONTACT b0@t flush=" + World::num(0.6 + kDt);
    w.begin({s.ship});
    EXPECT_EQ(w.brief(w.next()), pulse);
    // A handler appends a bank: not walked this tick.
    const int64_t b2 = w.bank("b2", s.sys, s.target, true);
    EXPECT_EQ(w.brief(w.next()), "CONTACT b1@t flush=0");
    EXPECT_EQ(w.brief(w.next()), "DONE");
    w.k.end();
    // ... and a handler that removes one: GetWeapon(i) past the end is None.
    w.m.set_f(s.bank, Field::_dwell, 0.6);
    w.begin({s.ship});
    EXPECT_EQ(w.brief(w.next()), pulse);
    w.m.set_ids(s.sys, Field::_children, {s.bank, b2});
    EXPECT_EQ(w.brief(w.next()), "CONTACT b2@t flush=0");
    EXPECT_EQ(w.brief(w.next()), "DONE");
    w.k.end();
    (void)b1;
}

TEST(K2, PrescanRunsPythonBeforeAnyRecord) {
    World w;
    const auto a = w.scene(false, 0.4);  // ship a: an idle dirty bank
    w.m.set_ref(a.bank, Field::_target, -1);  // ... at None: no contact
    const int64_t b = w.ship("B", 100.0, 0.0, 0.0);
    const int64_t bsys = w.system("bsys", b);
    const int64_t bb = w.bank("bb", bsys, a.target, false, 0.7);
    // B is posed and its bank's part slot was never resolved (stamp 0).
    w.m.set_i(b, Field::has_posed_parts, 1);
    w.begin({a.ship, b, -1});
    const K2Record r = w.next();
    // a's write rides on the record; none of B's was made.
    EXPECT_EQ(w.brief(r), "RUN_PYTHON B 1");
    EXPECT_EQ(w.writes(r), (World::V{"b0._dwell=0"}));
    EXPECT_EQ(w.m.get_f(bb, Field::_dwell), 0.7);
    EXPECT_EQ(w.brief(w.next()), "RUN_PYTHON -1 2");
    EXPECT_EQ(w.brief(w.next()), "DONE");
    w.k.end();
    const auto& c = w.k.counts();
    EXPECT_EQ(c.python_ships, 2);
    // Was K2Why::PosedShip before posed parts went native.
    EXPECT_EQ(c.why[static_cast<size_t>(K2Why::PartStale)], 1);
    EXPECT_EQ(c.why[static_cast<size_t>(K2Why::PosedShip)], 0);
    EXPECT_EQ(c.why[static_cast<size_t>(K2Why::UnslottedShip)], 1);
}

TEST(K2, PrescanReasons) {
    // (Case 1, a bank class overriding a K1 method, went with K1's override
    // guard: fire control native only, M8.7.)
    for (int c : {0, 2, 3, 4, 5}) {
        World w;
        const auto s = w.scene(true);
        K2Why want = K2Why::Other;
        switch (c) {
            case 0:  // a bank's target the mirror cannot name
                w.m.set_ref(s.bank, Field::_target, kRefUnrepresentable);
                want = K2Why::StaleRow;
                break;
            case 2:  // not a ShipClass
                w.m.set_i(s.ship, Field::is_ship_class, 0);
                want = K2Why::NotShipClass;
                break;
            case 3:  // a child that is not a phaser bank
                w.m.set_i(s.bank, Field::weapon_kind, 7);
                want = K2Why::Other;
                break;
            case 4:  // the system's row is gone
                w.m.set_ref(s.ship, Field::_phaser_system, kRefUnrepresentable);
                want = K2Why::StaleRow;
                break;
            case 5:  // the driver lists the ship
                want = K2Why::Overridden;
                break;
        }
        K2Context ctx;
        ctx.hooks = w.host.hooks();
        ctx.view_offsets[w.set] = std::nullopt;
        if (c == 5) ctx.python_ships.insert(s.ship);
        w.k.begin({s.ship}, kDt, 10.0, true, 0.0, std::move(ctx));
        EXPECT_EQ(w.brief(w.next()), "RUN_PYTHON ship 0") << c;
        EXPECT_EQ(w.brief(w.next()), "DONE") << c;
        w.k.end();
        EXPECT_EQ(w.k.counts().why[static_cast<size_t>(want)], 1) << c;
    }
}

TEST(K2, UnnameableLockAsks) {
    // The ship-wide lock is a subsystem the mirror cannot name: the aim
    // point is Python's. The arc aims at that same point. (Was
    // LockShipPosedAsks, a lock on a posed ship, before posed parts went
    // native: see LockOnPosedShipIsNative.)
    World w;
    const auto s = w.scene(true);
    w.m.set_ref(s.ship, Field::_target_subsystem, kRefUnrepresentable);
    w.begin({s.ship});
    const K2Record r = w.next();
    ASSERT_EQ(w.brief(r), "ASK aim_point");
    ASSERT_EQ(r.args.size(), 2u);
    EXPECT_EQ(std::get<int64_t>(r.args[0]), s.ship);
    EXPECT_EQ(std::get<int64_t>(r.args[1]), s.target);
    K2Answer a;
    a.point = {0.0, 70.0, 1.0};
    a.flag = true;
    w.k.answer(a);
    const K2Record c = w.next();
    EXPECT_EQ(w.brief(c), "CONTACT b0@t flush=0");
    EXPECT_EQ(c.contact.target_pos, (Vec3{0.0, 70.0, 1.0}));
    EXPECT_EQ(c.contact.hit.tier, ResolvedHit::Tier::Fallback);
    EXPECT_EQ(c.contact.hit.point, (Vec3{0.0, 70.0, 1.0}));
    EXPECT_EQ(w.brief(w.next()), "DONE");
    w.k.end();

    // With the answer's point behind the bank, the arc test fails on it.
    w.m.set_f(s.bank, Field::_dwell, 0.1);
    w.begin({s.ship});
    ASSERT_EQ(w.brief(w.next()), "ASK aim_point");
    a.point = {0.0, -70.0, 0.0};
    w.k.answer(a);
    const K2Record stopped = w.next();
    EXPECT_EQ(w.brief(stopped), "CONTACT b0@t flush=0.10000000000000001");
    EXPECT_EQ(w.entries(stopped), (World::V{"LOOP_STOP b0@3"}));
    w.finish();
}

TEST(K2, ManualAimArcUsesTheHullCentre) {
    // Manual Aim: the beam lands on the offset point, but `target_sub or
    // target` is the TARGET, so the arc aims at the hull centre.
    World w;
    const auto s = w.scene(true);
    w.m.set_i(s.ship, Field::_use_target_offset, 1);
    w.m.set_fv(s.ship, Field::_manual_target_offset, {0.0, -100.0, 0.0});
    w.begin({s.ship});
    const K2Record c = w.next();
    // The offset point (0, -50, 0) is astern, the centre ahead: in arc.
    EXPECT_EQ(w.brief(c), "CONTACT b0@t flush=0");
    EXPECT_EQ(c.contact.target_pos, (Vec3{0.0, -50.0, 0.0}));
    w.finish();
}

TEST(K2, ContactMatchesTheGeometry) {
    World w;
    const auto s = w.scene(true, 0.1);
    w.m.set_f(s.bank, Field::_length, 2.0);
    w.m.set_fv(s.bank, Field::_position, {0.5, 1.0, 0.25});
    const int64_t lock = w.m.register_row(Kind::Subsystem);
    w.m.set_ref(lock, Field::_parent_ship, s.target);
    w.m.set_fv(lock, Field::_position, {3.0, -2.0, 1.0});
    w.m.set_ref(s.ship, Field::_target_subsystem, lock);
    w.begin({s.ship}, false);
    const K2Record c = w.next();
    ASSERT_EQ(c.kind, K2Kind::CONTACT);
    const AimPoint ap = phaser_aim_point(w.m, s.ship, s.target, false);
    const Vec3 e = strip_emit_position(w.m, s.bank, ap.point, false);
    const double dx = ap.point[0] - e[0], dy = ap.point[1] - e[1],
                 dz = ap.point[2] - e[2];
    const double dist = py_pow(dx * dx + dy * dy + dz * dz, 0.5);
    EXPECT_EQ(c.contact.target_pos, ap.point);
    EXPECT_EQ(c.contact.emitter, e);
    EXPECT_EQ(c.contact.dist, dist);
    ASSERT_TRUE(c.contact.aim_unit.has_value());
    EXPECT_EQ(*c.contact.aim_unit, (Vec3{dx / dist, dy / dist, dz / dist}));
    EXPECT_EQ(c.contact.shields_block, std::optional<bool>(false));
    EXPECT_FALSE(c.contact.bubble.has_value());
    w.finish();
}

TEST(K2, TraceBeforeShieldsBlockAndOnlyWithAimUnit) {
    // A target the mirror cannot answer shields_block for: the ASK comes
    // AFTER the trace, and only when there is an aim unit.
    World w;
    const auto s = w.scene(true);
    w.m.set_i(s.target, Field::is_ship_class, 0);
    K2Context ctx;
    ctx.hooks = w.host.hooks();
    ctx.view_offsets[w.set] = std::nullopt;
    ctx.iids[s.target] = K2Context::Iid{false, InstanceId{1, 1}};
    w.k.begin({s.ship}, kDt, 10.0, true, 0.0, ctx);
    const K2Record r = w.next();
    ASSERT_EQ(w.brief(r), "ASK shields_block");
    EXPECT_EQ(w.host.calls, 1);  // the trace ran first
    K2Answer a;
    a.flag = true;
    w.k.answer(a);
    // shields up: the bubble of a non-ShipClass is Python's too.
    const K2Record b = w.next();
    ASSERT_EQ(w.brief(b), "ASK bubble");
    ASSERT_EQ(b.args.size(), 4u);
    EXPECT_EQ(std::get<double>(b.args[3]), 50.0 * 1.5);
    K2Answer none;
    none.none = true;
    w.k.answer(none);
    const K2Record c = w.next();
    EXPECT_EQ(w.brief(c), "CONTACT b0@t flush=0");
    EXPECT_EQ(c.contact.shields_block, std::optional<bool>(true));
    EXPECT_FALSE(c.contact.bubble.has_value());
    // A live miss falls to the sphere tier (radius 5, 45 GU along).
    EXPECT_EQ(c.contact.hit.tier, ResolvedHit::Tier::Sphere);
    EXPECT_EQ(c.contact.hit.point, (Vec3{0.0, 45.0, 0.0}));
    w.finish();

    // dist 0: no aim unit, no trace, no shields_block -- no ASK at all.
    w.store.set_position(static_cast<uint32_t>(w.m.get_i(s.target, Field::xform_index)),
                         static_cast<uint32_t>(w.m.get_i(s.target, Field::xform_gen)),
                         0.0, 0.0, 0.0);
    w.host.calls = 0;
    w.k.begin({s.ship}, kDt, 10.0, true, 0.0, ctx);
    const K2Record z = w.next();
    EXPECT_EQ(w.brief(z), "CONTACT b0@t flush=0");
    EXPECT_FALSE(z.contact.aim_unit.has_value());
    EXPECT_FALSE(z.contact.shields_block.has_value());
    EXPECT_EQ(z.contact.hit.tier, ResolvedHit::Tier::Fallback);
    EXPECT_EQ(w.host.calls, 0);
    w.finish();
}

TEST(K2, BubbleAfterShieldsAskWithTheTargetRowGone) {
    // The target's row is freed while Python answers the shields_block ASK:
    // the bubble's "is it a ShipClass" read must fall back (detail::obj
    // throws invalid_argument, handled by unexpected()), never dereference
    // a missing row. The bank's body has started (its trace ran), so the
    // session cannot walk it any further: next() raises.
    World w;
    const auto s = w.scene(true);
    w.m.set_i(s.target, Field::is_ship_class, 0);
    K2Context ctx;
    ctx.hooks = w.host.hooks();
    ctx.view_offsets[w.set] = std::nullopt;
    w.k.begin({s.ship}, kDt, 10.0, true, 0.0, ctx);
    ASSERT_EQ(w.brief(w.next()), "ASK shields_block");
    w.m.unregister_row(s.target);
    K2Answer a;
    a.flag = true;
    w.k.answer(a);
    EXPECT_THROW(w.next(), std::logic_error);
    w.k.abandon();
}

TEST(K2, InstanceOutcomes) {
    // Absent: the fallback point. Bad (not an InstanceId) and stale: the
    // sphere tier. Live hit: the mesh. No view offset for the set: ASK.
    World w;
    const auto s = w.scene(true);
    w.host.hit = TraceHit{{0.0f, 48.0f, 0.0f}, {0.0f, -1.0f, 0.0f}, 48.0f};
    struct Case {
        std::optional<K2Context::Iid> iid;
        ResolvedHit::Tier tier;
        Vec3 point;
    };
    const Case cases[] = {
        {std::nullopt, ResolvedHit::Tier::Fallback, {0.0, 50.0, 0.0}},
        {K2Context::Iid{true, {}}, ResolvedHit::Tier::Sphere, {0.0, 45.0, 0.0}},
        {K2Context::Iid{false, {1, 2}}, ResolvedHit::Tier::Sphere, {0.0, 45.0, 0.0}},
        {K2Context::Iid{false, {1, 1}}, ResolvedHit::Tier::Mesh, {0.0, 48.0, 0.0}},
    };
    for (const Case& cs : cases) {
        K2Context ctx;
        ctx.hooks = w.host.hooks();
        ctx.view_offsets[w.set] = std::nullopt;
        if (cs.iid) ctx.iids[s.target] = *cs.iid;
        w.k.begin({s.ship}, kDt, 10.0, true, 0.0, ctx);
        const K2Record c = w.next();
        ASSERT_EQ(c.kind, K2Kind::CONTACT);
        EXPECT_EQ(c.contact.hit.tier, cs.tier);
        EXPECT_EQ(c.contact.hit.point, cs.point);
        w.finish();
    }
    // The set has no view offset: Python resolves the hit.
    K2Context ctx;
    ctx.hooks = w.host.hooks();
    ctx.iids[s.target] = K2Context::Iid{false, {1, 1}};
    w.k.begin({s.ship}, kDt, 10.0, true, 0.0, ctx);
    const K2Record r = w.next();
    ASSERT_EQ(w.brief(r), "ASK resolve_hit");
    ASSERT_EQ(r.args.size(), 5u);
    EXPECT_EQ(std::get<int64_t>(r.args[0]), s.target);
    EXPECT_EQ(std::get<Vec3>(r.args[2]), (Vec3{0.0, 1.0, 0.0}));
    EXPECT_EQ(std::get<double>(r.args[3]), 75.0);
    EXPECT_EQ(std::get<Vec3>(r.args[4]), (Vec3{0.0, 50.0, 0.0}));
    K2Answer a;
    a.point = {0.0, 49.0, 0.0};
    a.normal = Vec3{0.0, -1.0, 0.0};
    a.tier = ResolvedHit::Tier::Mesh;
    w.k.answer(a);
    const K2Record c = w.next();
    EXPECT_EQ(c.contact.hit.tier, ResolvedHit::Tier::Mesh);
    EXPECT_EQ(c.contact.hit.point, (Vec3{0.0, 49.0, 0.0}));
    w.finish();
    // The context re-sent mid-session (after a record's effect: the first
    // contact is a pulse) is read live.
    w.m.set_f(s.bank, Field::_dwell, 0.6);
    w.k.begin({s.ship, s.ship}, kDt, 10.0, true, 0.0, ctx);
    ASSERT_EQ(w.brief(w.next()), "ASK resolve_hit");
    w.k.answer(a);
    const K2Record pulse = w.next();
    ASSERT_EQ(pulse.kind, K2Kind::CONTACT);
    ASSERT_GT(pulse.contact.flush_dwell, 0.0);
    K2Context ctx2 = w.k.context();
    ctx2.view_offsets[w.set] = std::nullopt;
    w.k.set_context(ctx2);
    const K2Record c2 = w.next();
    ASSERT_EQ(c2.kind, K2Kind::CONTACT);
    EXPECT_EQ(c2.contact.hit.point, (Vec3{0.0, 48.0, 0.0}));
    w.finish();
}

TEST(K2, BeginKeepsTheIidsWhenAsked) {
    // The driver sends the ship -> instance table only when it changed: a
    // begin told to keep it carries the last session's table over (and
    // replaces everything else); a plain begin takes the context as given.
    World w;
    const auto s = w.scene(true);
    w.host.hit = TraceHit{{0.0f, 48.0f, 0.0f}, {0.0f, -1.0f, 0.0f}, 48.0f};
    auto ctx = [&w] {
        K2Context c;
        c.hooks = w.host.hooks();
        c.view_offsets[w.set] = std::nullopt;
        return c;
    };
    K2Context first = ctx();
    first.iids[s.target] = K2Context::Iid{false, {1, 1}};
    w.k.begin({s.ship}, kDt, 10.0, true, 0.0, first);
    ASSERT_EQ(w.next().contact.hit.tier, ResolvedHit::Tier::Mesh);
    w.finish();
    // Kept: still the mesh, though this context names no instance.
    w.k.begin({s.ship}, kDt, 10.0, true, 0.0, ctx(), /*keep_iids=*/true);
    EXPECT_EQ(w.k.context().iids.size(), 1u);
    ASSERT_EQ(w.next().contact.hit.tier, ResolvedHit::Tier::Mesh);
    w.finish();
    // Not kept: no instance, the fallback point.
    w.k.begin({s.ship}, kDt, 10.0, true, 0.0, ctx());
    EXPECT_TRUE(w.k.context().iids.empty());
    ASSERT_EQ(w.next().contact.hit.tier, ResolvedHit::Tier::Fallback);
    w.finish();
    // A begin refused (a session is open) keeps nothing away from it.
    w.k.begin({s.ship}, kDt, 10.0, true, 0.0, first);
    EXPECT_THROW(w.k.begin({s.ship}, kDt, 10.0, true, 0.0, ctx(), true),
                 std::logic_error);
    EXPECT_EQ(w.k.context().iids.size(), 1u);
    w.finish();
}

TEST(K2, CanDetectThrowAsks) {
    // The native can_detect cannot answer (an unnamed sensor ref): Python's
    // own fallback answers.
    World w;
    const auto s = w.scene(true);
    w.m.set_ref(s.ship, Field::_sensor_subsystem, kRefUnrepresentable);
    w.begin({s.ship});
    const K2Record r = w.next();
    ASSERT_EQ(w.brief(r), "ASK can_detect");
    EXPECT_EQ(std::get<int64_t>(r.args[0]), s.ship);
    EXPECT_EQ(std::get<int64_t>(r.args[1]), s.target);
    K2Answer a;
    a.flag = false;
    w.k.answer(a);
    const K2Record d = w.next();
    EXPECT_EQ(w.brief(d), "DONE");
    EXPECT_EQ(w.entries(d), (World::V{"LOOP_STOP b0@2"}));
    w.k.end();
}

TEST(K2, ResumeReadsLiveMirror) {
    World w;
    const auto s = w.scene(true, 0.6);  // b0 pulses: a record, a handler
    const int64_t b1 = w.bank("b1", s.sys, s.target, true);
    const int64_t t2 = w.ship("t2", 10.0, 60.0, 0.0);
    w.begin({s.ship});
    EXPECT_EQ(w.brief(w.next()),
              "CONTACT b0@t flush=" + World::num(0.6 + kDt));
    // The effect's handlers retarget bank 1 and move ship 2.
    w.m.set_ref(b1, Field::_target, t2);
    const K2Record c = w.next();
    EXPECT_EQ(w.brief(c), "CONTACT b1@t2 flush=0");
    EXPECT_EQ(c.contact.target_pos, (Vec3{10.0, 60.0, 0.0}));
    EXPECT_EQ(w.brief(w.next()), "DONE");
    w.k.end();
}

TEST(K2, BankStepAfterAHandlerDropsARow) {
    World w;
    const auto s = w.scene(true, 0.6);  // b0 pulses: a record, a handler
    const int64_t b1 = w.bank("b1", s.sys, s.target, true, 0.0);
    w.bank("b2", s.sys, s.target, true);
    w.begin({s.ship});
    EXPECT_EQ(w.brief(w.next()),
              "CONTACT b0@t flush=" + World::num(0.6 + kDt));
    w.m.unregister_row(b1);  // a value the mirror cannot encode
    const K2Record r = w.next();
    ASSERT_EQ(w.brief(r), "ASK bank_step");
    ASSERT_EQ(r.args.size(), 3u);
    EXPECT_EQ(std::get<int64_t>(r.args[0]), s.ship);
    EXPECT_EQ(std::get<int64_t>(r.args[1]), s.sys);
    EXPECT_EQ(std::get<int64_t>(r.args[2]), 1);
    w.k.answer(K2Answer{});
    EXPECT_EQ(w.brief(w.next()), "CONTACT b2@t flush=0");
    EXPECT_EQ(w.brief(w.next()), "DONE");
    w.k.end();
}

TEST(K2, UnwindLeavesMirrorEqual) {
    World w;
    const auto s = w.scene(true, 0.25);  // beam on: accumulates
    const int64_t idle = w.bank("idle", s.sys, -1, false, 0.4);
    // Move the idle bank first so its write precedes the throw.
    w.m.set_ids(s.sys, Field::_children, {idle, s.bank});
    K2Context ctx;
    ctx.hooks = w.host.hooks();
    ctx.view_offsets[w.set] = std::nullopt;
    ctx.iids[s.target] = K2Context::Iid{false, {1, 1}};
    w.host.throw_foreign = true;
    w.k.begin({s.ship}, kDt, 10.0, true, 0.0, ctx);
    EXPECT_ANY_THROW(w.next());
    // Both undelivered writes undone: the mirror equals Python.
    EXPECT_EQ(w.m.get_f(idle, Field::_dwell), 0.4);
    EXPECT_EQ(w.m.get_f(s.bank, Field::_dwell), 0.25);
    // The session was restored: a retry reaches the same point.
    EXPECT_ANY_THROW(w.next());
    EXPECT_EQ(w.m.get_f(idle, Field::_dwell), 0.4);
    w.k.abandon();
    EXPECT_FALSE(w.k.open());
    // A healthy run afterwards.
    w.host.throw_foreign = false;
    w.k.begin({s.ship}, kDt, 10.0, true, 0.0, ctx);
    const K2Record c = w.next();
    EXPECT_EQ(w.writes(c),
              (World::V{"idle._dwell=0", "b0._dwell=" + World::num(0.25 + kDt)}));
    w.finish();
}

TEST(K2, ProtocolErrors) {
    World w;
    EXPECT_THROW(w.next(), std::logic_error);
    const auto s = w.scene(true);
    w.m.set_i(s.target, Field::has_real_is_dead, 0);
    w.begin({s.ship});
    EXPECT_THROW(w.begin({s.ship}), std::logic_error);
    ASSERT_EQ(w.next().kind, K2Kind::ASK);
    EXPECT_THROW(w.next(), std::logic_error);  // no answer yet
    EXPECT_THROW(w.k.end(), std::logic_error);   // not DONE
    w.k.abandon();
    EXPECT_THROW(w.k.answer(K2Answer{}), std::logic_error);
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

TEST(K2, PosedShipBeamsNatively) {
    // The firing ship is posed and its bank's slot is current: the strip
    // centre is the posed mount. A generation bump makes the slot stale:
    // the ship is Python's, part_stale -- never posed_ship.
    World w;
    const auto s = w.scene(true);
    w.m.set_i(s.ship, Field::has_posed_parts, 1);
    w.m.set_part_poses(s.ship, {shift_pose()});
    w.m.set_part_slot(s.bank, 0, w.m.part_gen());
    w.begin({s.ship});
    const K2Record c = w.next();
    ASSERT_EQ(c.kind, K2Kind::CONTACT);
    EXPECT_EQ(c.contact.emitter, (Vec3{0.25, 0.0, 0.0}));
    w.finish();
    EXPECT_EQ(w.k.counts().python_ships, 0);
    EXPECT_EQ(w.k.counts().posed_banks, 1);

    w.m.set_part_gen(w.m.part_gen() + 1);
    w.k.reset_counts();
    w.begin({s.ship});
    EXPECT_EQ(w.brief(w.next()), "RUN_PYTHON ship 0");
    w.finish();
    const auto& n = w.k.counts();
    EXPECT_EQ(n.why[static_cast<size_t>(K2Why::PartStale)], 1);
    EXPECT_EQ(n.why[static_cast<size_t>(K2Why::PosedShip)], 0);
}

TEST(K2, LockOnPosedShipIsNative) {
    // The ship-wide lock is a subsystem on ANOTHER ship that is posed, its
    // slot current: the aim point is the posed mount, no ASK. A stale slot
    // sends the FIRING ship to Python (part_stale) before any record.
    World w;
    const auto s = w.scene(true);
    const int64_t other = w.ship("other", 0.0, 80.0, 0.0);
    const int64_t lock = w.m.register_row(Kind::Subsystem);
    w.m.set_ref(lock, Field::_parent_ship, other);
    w.m.set_fv(lock, Field::_position, {0.0, 0.0, 0.0});
    w.m.set_ref(s.ship, Field::_target_subsystem, lock);
    w.m.set_i(other, Field::has_posed_parts, 1);
    w.m.set_part_poses(other, {shift_pose()});
    w.m.set_part_slot(lock, 0, w.m.part_gen());
    w.begin({s.ship});
    const K2Record c = w.next();
    ASSERT_EQ(c.kind, K2Kind::CONTACT);
    EXPECT_EQ(c.contact.target_pos, (Vec3{0.25, 80.0, 0.0}));
    w.finish();
    EXPECT_EQ(w.k.counts().asks, 0);
    EXPECT_EQ(w.k.counts().posed_lock_aims, 1);

    w.m.set_part_gen(w.m.part_gen() + 1);
    w.k.reset_counts();
    w.begin({s.ship});
    EXPECT_EQ(w.brief(w.next()), "RUN_PYTHON ship 0");
    w.finish();
    EXPECT_EQ(w.k.counts().why[static_cast<size_t>(K2Why::PartStale)], 1);
    EXPECT_EQ(w.k.counts().asks, 0);
}

// ── Round trips (spec 2026-11-01 §4.4-4.5) ──────────────────────────────────

TEST(K2, RestingContactsQueueForTheDrain) {
    // b0 and b1 rest (beams on, dwell under the flush), b2 pulses, b3 rests:
    // the pulse is the only CONTACT record, every write rides a record, and
    // the three resting contacts wait, in walk order, for the drain after
    // DONE (rests()).
    World w;
    const auto s = w.scene(true, 0.1);
    w.bank("b1", s.sys, s.target, true, 0.2);
    w.bank("b2", s.sys, s.target, true, 0.6);
    w.bank("b3", s.sys, s.target, true, 0.3);
    w.begin({s.ship});
    const K2Record r = w.k.next();
    ASSERT_EQ(r.kind, K2Kind::CONTACT);
    EXPECT_EQ(w.name(r.contact.bank), "b2");
    EXPECT_EQ(r.contact.flush_dwell, 0.6 + kDt);
    EXPECT_EQ(w.writes(r),
              (World::V{"b0._dwell=" + World::num(0.1 + kDt),
                        "b1._dwell=" + World::num(0.2 + kDt), "b2._dwell=0"}));
    const K2Record d = w.k.next();
    ASSERT_EQ(d.kind, K2Kind::DONE);
    EXPECT_EQ(w.writes(d), (World::V{"b3._dwell=" + World::num(0.3 + kDt)}));
    const std::vector<K2Rest>& q = w.k.rests();
    ASSERT_EQ(q.size(), 3u);
    EXPECT_EQ(w.name(q[0].contact.bank), "b0");
    EXPECT_EQ(w.name(q[1].contact.bank), "b1");
    EXPECT_EQ(w.name(q[2].contact.bank), "b3");
    for (const K2Rest& e : q) {
        EXPECT_EQ(e.contact.flush_dwell, 0.0);
        EXPECT_EQ(e.contact.target, s.target);
        EXPECT_EQ(e.contact.ship, s.ship);
        EXPECT_EQ(e.contact.system, s.sys);
    }
    w.k.end();
    EXPECT_EQ(w.k.counts().batched_contacts, 3);
    EXPECT_EQ(w.k.counts().records, 2);
}

TEST(K2, RestCarriesTheShieldsAnswer) {
    // shields_block answered by Python (ASK): the rest carries the answer
    // itself (false here), marked asked -- presented later, a re-evaluation
    // could read shields a later pulse changed. A native answer: carried.
    World w;
    const auto s = w.scene(true);
    w.m.set_i(s.target, Field::is_ship_class, 0);
    w.begin({s.ship});
    ASSERT_EQ(w.brief(w.k.next()), "ASK shields_block");
    K2Answer a;
    a.flag = false;
    w.k.answer(a);
    ASSERT_EQ(w.k.next().kind, K2Kind::DONE);
    ASSERT_EQ(w.k.rests().size(), 1u);
    EXPECT_TRUE(w.k.rests()[0].contact.shields_asked);
    EXPECT_EQ(w.k.rests()[0].contact.shields_block, std::optional<bool>(false));
    w.k.end();
    w.m.set_i(s.target, Field::is_ship_class, 1);
    w.begin({s.ship});
    ASSERT_EQ(w.k.next().kind, K2Kind::DONE);
    ASSERT_EQ(w.k.rests().size(), 1u);
    EXPECT_FALSE(w.k.rests()[0].contact.shields_asked);
    EXPECT_EQ(w.k.rests()[0].contact.shields_block, std::optional<bool>(false));
    w.k.end();
}

TEST(K2, RestCarriesLevelIidAndViewOffset) {
    // b0 rests, b1 pulses, b2 rests. Each rest carries the system's
    // `_power_level` as it was when the walk reached it (the pulse's handler
    // changes it in between, and the drain reads only the entry), the
    // target's instance and its set's view offset from the context.
    World w;
    const auto s = w.scene(true, 0.1);
    w.bank("b1", s.sys, s.target, true, 0.6);
    w.bank("b2", s.sys, s.target, true, 0.2);
    w.m.set_i(s.sys, Field::_power_level, 2);
    w.host.hit = TraceHit{{0.0f, 48.0f, 0.0f}, {0.0f, -1.0f, 0.0f}, 48.0f};
    K2Context ctx;
    ctx.hooks = w.host.hooks();
    ctx.view_offsets[w.set] = Vec3{0.0, 0.0, 0.0};
    ctx.iids[s.target] = K2Context::Iid{false, InstanceId{1, 1}};
    w.k.begin({s.ship}, kDt, 10.0, true, 0.0, ctx);
    const K2Record pulse = w.k.next();
    ASSERT_EQ(w.name(pulse.contact.bank), "b1");
    w.m.set_i(s.sys, Field::_power_level, 0);   // the pulse's handler
    ASSERT_EQ(w.k.next().kind, K2Kind::DONE);
    w.m.set_i(s.sys, Field::_power_level, 1);   // after DONE: not read
    {
        const std::vector<K2Rest>& q = w.k.rests();
        ASSERT_EQ(q.size(), 2u);
        EXPECT_EQ(q[0].level, 2);
        EXPECT_EQ(q[1].level, 0);
        for (const K2Rest& e : q) {
            ASSERT_TRUE(e.iid.has_value());
            EXPECT_EQ(e.iid->index, 1u);
            EXPECT_EQ(e.iid->generation, 1u);
            EXPECT_TRUE(e.view_known);
            EXPECT_EQ(e.view_offset, std::optional<Vec3>(Vec3{0.0, 0.0, 0.0}));
        }
    }
    w.k.end();

    // No instance (and a value that is not an InstanceId): no iid. The set
    // known with no shift (None) is known; a set with no entry is not.
    for (const bool bad : {false, true}) {
        K2Context c2;
        c2.hooks = w.host.hooks();
        c2.view_offsets[w.set] = std::nullopt;
        if (bad) c2.iids[s.target] = K2Context::Iid{true, {}};
        w.m.set_f(s.bank, Field::_dwell, 0.1);
        w.k.begin({s.ship}, kDt, 10.0, true, 0.0, c2);
        w.finish_to_done_raw();
        ASSERT_EQ(w.k.rests().size(), 3u);   // b1 rests too (flushed)
        for (const K2Rest& e : w.k.rests()) {
            EXPECT_FALSE(e.iid.has_value());
            EXPECT_TRUE(e.view_known);
            EXPECT_FALSE(e.view_offset.has_value());
        }
        w.k.end();
    }
    K2Context c3;
    c3.hooks = w.host.hooks();
    w.k.begin({s.ship}, kDt, 10.0, true, 0.0, c3);
    w.finish_to_done_raw();
    ASSERT_FALSE(w.k.rests().empty());
    for (const K2Rest& e : w.k.rests()) {
        EXPECT_FALSE(e.view_known);
        EXPECT_FALSE(e.view_offset.has_value());
    }
    w.k.end();
}

TEST(K2, NoAimRestEvaluatesShieldsNatively) {
    // dist 0: the loop has no aim unit and never evaluates shields_block.
    // The rest still carries the answer, evaluated natively for the drain
    // (shields up: true) -- never an ASK; a target the mirror cannot answer
    // for leaves it unknown (the drain's Python evaluates its own).
    World w;
    const auto s = w.scene(true);
    w.store.set_position(static_cast<uint32_t>(w.m.get_i(s.target, Field::xform_index)),
                         static_cast<uint32_t>(w.m.get_i(s.target, Field::xform_gen)),
                         0.0, 0.0, 0.0);
    const int64_t sh = w.m.register_row(Kind::Subsystem);
    w.m.set_i(sh, Field::has_shields, 1);
    w.m.set_i(sh, Field::_is_on, 1);
    w.m.set_f(sh, Field::_max_condition, 100.0);
    w.m.set_f(sh, Field::_condition, 100.0);
    w.m.set_f(sh, Field::_disabled_percentage, 0.25);
    w.m.set_ref(s.target, Field::_shield_subsystem, sh);
    w.begin({s.ship});
    ASSERT_EQ(w.k.next().kind, K2Kind::DONE);
    ASSERT_EQ(w.k.rests().size(), 1u);
    EXPECT_FALSE(w.k.rests()[0].contact.aim_unit.has_value());
    EXPECT_EQ(w.k.rests()[0].contact.shields_block, std::optional<bool>(true));
    EXPECT_FALSE(w.k.rests()[0].contact.shields_asked);
    w.k.end();
    w.m.set_i(s.target, Field::is_ship_class, 0);
    w.begin({s.ship});
    ASSERT_EQ(w.k.next().kind, K2Kind::DONE);   // no ASK
    ASSERT_EQ(w.k.rests().size(), 1u);
    EXPECT_FALSE(w.k.rests()[0].contact.shields_block.has_value());
    EXPECT_FALSE(w.k.rests()[0].contact.shields_asked);
    w.k.end();
    EXPECT_EQ(w.k.counts().asks, 0);
}

TEST(K2, QueueClearedOnBeginEndAbandon) {
    // The queue belongs to the session: end() drops it, an abandoned walk
    // drops what it queued, and a new session starts with none.
    World w;
    const auto s = w.scene(true, 0.1);
    const int64_t b1 = w.bank("b1", s.sys, s.target, true, 0.6);
    EXPECT_TRUE(w.k.rests().empty());
    w.m.set_f(b1, Field::_dwell, 0.6);   // b1 pulses each session
    w.begin({s.ship});
    ASSERT_EQ(w.k.next().kind, K2Kind::CONTACT);   // b0 queued, b1 pulses
    EXPECT_EQ(w.k.rests().size(), 1u);
    EXPECT_THROW(w.k.take_rests(), std::logic_error);  // not DONE yet
    EXPECT_EQ(w.k.rests().size(), 1u);
    w.k.abandon();
    EXPECT_TRUE(w.k.rests().empty());
    w.m.set_f(b1, Field::_dwell, 0.6);   // b1 pulses each session
    w.begin({s.ship});
    EXPECT_TRUE(w.k.rests().empty());
    ASSERT_EQ(w.k.next().kind, K2Kind::CONTACT);
    ASSERT_EQ(w.k.next().kind, K2Kind::DONE);
    EXPECT_EQ(w.k.rests().size(), 1u);
    w.k.end();
    EXPECT_TRUE(w.k.rests().empty());
    // take_rests() hands the queue over and leaves it empty.
    w.m.set_f(b1, Field::_dwell, 0.6);   // b1 pulses each session
    w.begin({s.ship});
    ASSERT_EQ(w.k.next().kind, K2Kind::CONTACT);
    ASSERT_EQ(w.k.next().kind, K2Kind::DONE);
    const std::vector<K2Rest> taken = w.k.take_rests();
    EXPECT_EQ(taken.size(), 1u);
    EXPECT_TRUE(w.k.rests().empty());
    w.k.end();
}

TEST(K2, ThrowAfterAQueuedContactRestoresTheQueue) {
    // b0 is queued, then b1's trace throws a foreign exception: next()
    // undoes both writes and restores the session (an empty queue), so a
    // retry queues b0 exactly once.
    World w;
    const auto s = w.scene(true, 0.1);
    const int64_t t2 = w.ship("t2", 0.0, 60.0, 0.0);
    w.bank("b1", s.sys, t2, true, 0.2);
    K2Context ctx;
    ctx.hooks = w.host.hooks();
    ctx.view_offsets[w.set] = std::nullopt;
    ctx.iids[t2] = K2Context::Iid{false, {1, 1}};  // only b1 traces
    w.host.throw_foreign = true;
    w.k.begin({s.ship}, kDt, 10.0, true, 0.0, ctx);
    EXPECT_ANY_THROW(w.k.next());
    EXPECT_EQ(w.m.get_f(s.bank, Field::_dwell), 0.1);
    EXPECT_TRUE(w.k.rests().empty());
    EXPECT_EQ(w.k.counts().batched_contacts, 1);  // counted, then undone
    w.host.throw_foreign = false;
    const K2Record d = w.k.next();
    ASSERT_EQ(d.kind, K2Kind::DONE);
    const std::vector<K2Rest>& q = w.k.rests();
    ASSERT_EQ(q.size(), 2u);
    EXPECT_EQ(w.name(q[0].contact.bank), "b0");
    EXPECT_EQ(w.name(q[1].contact.bank), "b1");
    EXPECT_EQ(q[1].contact.hit.tier, ResolvedHit::Tier::Sphere);
    w.k.end();
}

TEST(K2, ThrowKeepsRestsQueuedByEarlierRecords) {
    // b0 rests, b1 pulses (a record: b0's rest is queued before it), b2
    // rests, then b3's trace throws: the throw drops only what that next()
    // queued (b2), never a rest an earlier call queued (b0). A retry queues
    // b2 again, once.
    World w;
    const auto s = w.scene(true, 0.1);
    w.bank("b1", s.sys, s.target, true, 0.6);
    w.bank("b2", s.sys, s.target, true, 0.2);
    const int64_t t2 = w.ship("t2", 0.0, 60.0, 0.0);
    w.bank("b3", s.sys, t2, true, 0.3);
    K2Context ctx;
    ctx.hooks = w.host.hooks();
    ctx.view_offsets[w.set] = std::nullopt;
    ctx.iids[t2] = K2Context::Iid{false, {1, 1}};  // only b3 traces
    w.k.begin({s.ship}, kDt, 10.0, true, 0.0, ctx);
    const K2Record pulse = w.k.next();
    ASSERT_EQ(w.name(pulse.contact.bank), "b1");
    ASSERT_EQ(w.k.rests().size(), 1u);
    w.host.throw_foreign = true;
    EXPECT_ANY_THROW(w.k.next());
    ASSERT_EQ(w.k.rests().size(), 1u);
    EXPECT_EQ(w.name(w.k.rests()[0].contact.bank), "b0");
    w.host.throw_foreign = false;
    ASSERT_EQ(w.k.next().kind, K2Kind::DONE);
    const std::vector<K2Rest>& q = w.k.rests();
    ASSERT_EQ(q.size(), 3u);
    EXPECT_EQ(w.name(q[0].contact.bank), "b0");
    EXPECT_EQ(w.name(q[1].contact.bank), "b2");
    EXPECT_EQ(w.name(q[2].contact.bank), "b3");
    w.k.end();
}

TEST(K2, OfflineStopIsLoggedWrites) {
    // An off system whose banks are all idle: WeaponSystem.StopFiring's
    // writes, then each bank's _EnergyWeaponFireMixin.StopFiring writes, in
    // order, every tick -- the `_target_list = []` too when it is already
    // empty (Python builds a new list) -- and no record.
    World w;
    const auto s = w.scene(false, 0.25);
    const int64_t b1 = w.bank("b1", s.sys, -1, false);
    w.m.set_i(s.sys, Field::_is_on, 0);
    w.m.set_i(s.sys, Field::_fire_held, 1);
    w.m.set_ref(s.sys, Field::_held_target, s.target);
    w.m.set_fv(s.sys, Field::_held_offset, {1.0, 2.0, 3.0});
    w.m.set_ids(s.sys, Field::_target_list, {s.target});
    w.m.set_i(s.sys, Field::_last_group_fired, 2);
    w.m.set_f(b1, Field::_beam_on_countdown, 0.4);
    const World::V want{"sys._fire_held=False", "sys._held_target=-1",
                        "sys._held_offset=None", "sys._target_list=[]",
                        "sys._last_group_fired=-1", "b0._firing=False",
                        "b0._beam_on_countdown=0", "b1._firing=False",
                        "b1._beam_on_countdown=0"};
    for (int tick = 0; tick < 2; ++tick) {
        w.begin({s.ship});
        const K2Record r = w.k.next();
        EXPECT_EQ(w.brief(r), "DONE") << tick;
        EXPECT_EQ(w.writes(r), want) << tick;
        w.k.end();
    }
    const SubsystemRow& sr = *w.m.subsystem(s.sys);
    EXPECT_EQ(sr._fire_held, 0);
    EXPECT_EQ(sr._held_target, -1);
    EXPECT_FALSE(sr.held_offset_set);
    EXPECT_TRUE(sr._target_list.empty());
    EXPECT_EQ(sr._last_group_fired, -1);
    EXPECT_EQ(w.m.get_f(b1, Field::_beam_on_countdown), 0.0);
    EXPECT_EQ(w.m.get_f(s.bank, Field::_dwell), 0.25);  // banks not walked
    EXPECT_EQ(w.k.counts().logged_system_stop, 2);
    EXPECT_EQ(w.k.counts().records, 2);  // the two DONEs
}

TEST(K2, OfflineStopOfAFiringBankQueuesItsLoopStop) {
    // WeaponSystem.StopFiring with a bank firing (combat fire events §4.3):
    // the system's writes, then each bank's StopFiring in GetWeapon order --
    // the firing one's LOOP_STOP right after its own writes -- and no
    // record.
    World w;
    const auto s = w.scene(false);
    const int64_t b1 = w.bank("b1", s.sys, -1, true);
    w.bank("b2", s.sys, -1, false);
    w.m.set_i(s.sys, Field::_is_on, 0);
    w.begin({s.ship});
    const K2Record r = w.k.next();
    EXPECT_EQ(w.brief(r), "DONE");
    EXPECT_EQ(w.writes(r),
              (World::V{"sys._fire_held=False", "sys._held_target=-1",
                        "sys._held_offset=None", "sys._target_list=[]",
                        "sys._last_group_fired=-1", "b0._firing=False",
                        "b0._beam_on_countdown=0", "b1._firing=False",
                        "b1._beam_on_countdown=0", "b2._firing=False",
                        "b2._beam_on_countdown=0"}));
    EXPECT_EQ(w.entries(r), (World::V{"LOOP_STOP b1@9"}));
    EXPECT_EQ(w.m.get_i(b1, Field::_firing), 0);
    w.k.end();
    EXPECT_EQ(w.k.counts().logged_system_stop, 1);
    EXPECT_EQ(w.k.counts().logged_firing_system_stop, 1);
}

TEST(K2, OfflineStopKeepsTheRecordUnlessEveryBankIsStock) {
    // A child that is not a phaser bank, a child row gone: SYSTEM_STOP,
    // nothing written, nothing queued. (A bank class overriding a K1 method
    // is no case since K1's override guard went: fire control native only,
    // M8.7.)
    for (int c = 2; c < 4; ++c) {
        World w;
        const auto s = w.scene(false);
        const int64_t b1 = w.bank("b1", s.sys, -1, false);
        w.m.set_i(s.sys, Field::_is_on, 0);
        w.m.set_i(s.sys, Field::_fire_held, 1);
        w.m.set_i(s.bank, Field::_firing, 1);  // b0 firing: no entry either
        switch (c) {
            case 2: w.m.set_i(b1, Field::weapon_kind, 8); break;
            case 3: w.m.unregister_row(b1); break;
        }
        w.begin({s.ship});
        const K2Record r = w.k.next();
        EXPECT_EQ(w.brief(r), "SYSTEM_STOP sys") << c;
        EXPECT_TRUE(r.writes.empty()) << c;
        EXPECT_TRUE(r.entries.empty()) << c;
        EXPECT_EQ(w.brief(w.k.next()), "DONE") << c;
        w.k.end();
        EXPECT_EQ(w.m.get_i(s.sys, Field::_fire_held), 1) << c;
        EXPECT_EQ(w.k.counts().logged_system_stop, 0) << c;
    }
}

TEST(K2, UnwindUndoesOfflineStopWrites) {
    // Ship A's offline stop is logged, then ship B's trace throws: every
    // field the stop wrote is back as it was, and a retry logs it again.
    World w;
    const auto a = w.scene(false, 0.0);
    w.m.set_i(a.sys, Field::_is_on, 0);
    w.m.set_i(a.sys, Field::_fire_held, 1);
    w.m.set_ref(a.sys, Field::_held_target, a.target);
    w.m.set_fv(a.sys, Field::_held_offset, {1.0, 2.0, 3.0});
    w.m.set_ids(a.sys, Field::_target_list, {a.target});
    w.m.set_i(a.sys, Field::_last_group_fired, 2);
    w.m.set_f(a.bank, Field::_beam_on_countdown, 0.4);
    const int64_t b = w.ship("B", 100.0, 0.0, 0.0);
    const int64_t bsys = w.system("bsys", b);
    w.bank("bb", bsys, a.target, true);
    K2Context ctx;
    ctx.hooks = w.host.hooks();
    ctx.view_offsets[w.set] = std::nullopt;
    ctx.iids[a.target] = K2Context::Iid{false, {1, 1}};
    w.host.throw_foreign = true;
    w.k.begin({a.ship, b}, kDt, 10.0, true, 0.0, ctx);
    EXPECT_ANY_THROW(w.k.next());
    const SubsystemRow& sr = *w.m.subsystem(a.sys);
    EXPECT_EQ(sr._fire_held, 1);
    EXPECT_EQ(sr._held_target, a.target);
    EXPECT_TRUE(sr.held_offset_set);
    EXPECT_EQ(sr._held_offset, (Vec3{1.0, 2.0, 3.0}));
    EXPECT_EQ(sr._target_list, (std::vector<int64_t>{a.target}));
    EXPECT_EQ(sr._last_group_fired, 2);
    EXPECT_EQ(w.m.get_f(a.bank, Field::_beam_on_countdown), 0.4);
    w.host.throw_foreign = false;
    const K2Record d = w.k.next();
    ASSERT_EQ(d.kind, K2Kind::DONE);
    const World::V got = w.writes(d);
    ASSERT_EQ(got.size(), 8u);  // A's stop, then B's bank accumulates
    EXPECT_EQ(got.front(), "sys._fire_held=False");
    EXPECT_EQ(got[6], "b0._beam_on_countdown=0");
    EXPECT_EQ(got[7], "bb._dwell=" + World::num(kDt));
    w.k.end();
}

TEST(K2, ThrowDropsTheCallsLoopStops) {
    // Ship A's firing bank is stopped (logged, LOOP_STOP queued), then ship
    // B's trace throws: the stop's writes are undone and its entry dropped
    // with them; the retry stops it again, once.
    World w;
    const auto a = w.scene(true);
    w.m.set_ref(a.bank, Field::_target, -1);  // firing at None: a stop
    const int64_t b = w.ship("B", 100.0, 0.0, 0.0);
    const int64_t bsys = w.system("bsys", b);
    w.bank("bb", bsys, a.target, true);
    K2Context ctx;
    ctx.hooks = w.host.hooks();
    ctx.view_offsets[w.set] = std::nullopt;
    ctx.iids[a.target] = K2Context::Iid{false, {1, 1}};
    w.host.throw_foreign = true;
    w.k.begin({a.ship, b}, kDt, 10.0, true, 0.0, ctx);
    EXPECT_ANY_THROW(w.k.next());
    EXPECT_EQ(w.m.get_i(a.bank, Field::_firing), 1);
    w.host.throw_foreign = false;
    const K2Record r = w.k.next();
    EXPECT_EQ(w.entries(r), (World::V{"LOOP_STOP b0@2"}));
    w.k.abandon();
}

// ── THE DAMAGE PULSE (native damage, Task 4) ────────────────────────────────

namespace {

// A target the hit can damage: hurtable, stood in for, a critical hull of
// 1000 and no shield generator; no other subsystem (an empty mount order).
int64_t damageable(World& w, int64_t target, double hull_max = 1000.0) {
    w.m.set_i(target, Field::dmg_ship, 1);
    w.m.set_i(target, Field::_hurtable, 1);
    const int64_t hull = w.m.register_row(Kind::Subsystem);
    w.names[hull] = w.name(target) + ".hull";
    w.m.set_f(hull, Field::_max_condition, hull_max);
    w.m.set_f(hull, Field::_condition, hull_max);
    w.m.set_f(hull, Field::_disabled_percentage, 0.5);
    w.m.set_ref(hull, Field::_parent_ship, target);
    w.m.set_i(hull, Field::dmg_class, kDmgLeaf);
    w.m.set_i(hull, Field::_critical, 1);
    w.m.set_ref(target, Field::_hull, hull);
    w.m.set_mount_order(target, {});
    return hull;
}

// The bank's pulse inputs (a PhaserProperty's MaxDamage and
// MaxDamageDistance; DamageRadiusFactor 0 = the default radius).
void arm(World& w, int64_t bank, double md, double mdd, double drf = 0.0) {
    w.m.set_f(bank, Field::_max_damage, md);
    w.m.set_f(bank, Field::_max_damage_distance, mdd);
    w.m.set_f(bank, Field::_damage_radius_factor, drf);
}

// What the driver sends (host_loop.PHASER_INTENSITY_SCALE, combat.
// PHASER_DEFAULT_DAMAGE_RADIUS, PhaserSystem.PP_LOW, the phaser codes).
K2PulseCtx pulse_ctx(std::initializer_list<int64_t> clean) {
    K2PulseCtx p;
    p.ok = true;
    p.intensity = {0.25, 0.5, 0.5};
    p.default_radius = 0.15;
    p.pp_low = 0;
    p.hit_weapon = 1;
    p.weapon_hit_type = 0;
    p.clean = clean;
    return p;
}

void begin_pulse(World& w, std::vector<int64_t> ships, K2PulseCtx p) {
    K2Context ctx;
    ctx.hooks = w.host.hooks();
    ctx.view_offsets[w.set] = std::nullopt;
    ctx.pulse = std::move(p);
    w.k.begin(std::move(ships), kDt, 10.0, true, 0.0, std::move(ctx));
}

std::vector<DamageKind> hit_kinds(const K2Hit& h) {
    std::vector<DamageKind> k;
    for (const DamageEntry& e : h.out.entries) k.push_back(e.kind);
    return k;
}

const DamageEntry& entry(const K2Hit& h, DamageKind kind) {
    for (const DamageEntry& e : h.out.entries)
        if (e.kind == kind) return e;
    throw std::logic_error("no such entry");
}

double cond(const World& w, int64_t s) {
    return w.m.get_f(s, Field::_condition);
}

}  // namespace

TEST(K2Pulse, NamesItsReasons) {
    EXPECT_STREQ(k2_pulse_why_name(K2PulseWhy::not_ok), "not_ok");
    EXPECT_STREQ(k2_pulse_why_name(K2PulseWhy::unscanned), "unscanned");
    EXPECT_STREQ(k2_pulse_why_name(K2PulseWhy::level), "level");
    EXPECT_STREQ(k2_pulse_why_name(K2PulseWhy::fallback), "fallback");
    EXPECT_STREQ(k2_pulse_why_name(K2PulseWhy::python), "python");
}

TEST(K2Pulse, ADamagePulseIsAppliedInTheWalk) {
    World w;
    const auto s = w.scene(true, 0.6);  // flushes 0.6 + dt this tick
    const int64_t hull = damageable(w, s.target);
    arm(w, s.bank, 100.0, 60.0);        // dist 50: the plateau
    w.m.set_i(s.sys, Field::_power_level, 1);
    begin_pulse(w, {s.ship}, pulse_ctx({s.target}));
    const K2Record r = w.k.next();
    ASSERT_EQ(r.kind, K2Kind::DONE);    // no CONTACT record
    EXPECT_EQ(w.writes(r), (World::V{"b0._dwell=0"}));
    ASSERT_EQ(r.hits.size(), 1u);
    const K2Hit& h = r.hits[0];
    EXPECT_EQ(h.at_write, 1u);
    EXPECT_EQ(h.at_entry, 0u);
    EXPECT_EQ(h.source, s.ship);
    // _phaser_damage_for_tick(100, 60, 50, 0.6 + dt) * SCALE[1]
    const double damage = 100.0 * (0.6 + kDt) * 0.5;
    EXPECT_EQ(cond(w, hull), 1000.0 - damage);
    EXPECT_EQ(hit_kinds(h), (std::vector<DamageKind>{
                                DamageKind::REPAIR_ADD,
                                DamageKind::HIT_PRESENT,
                                DamageKind::WEAPON_HIT}));
    const DamageEntry& p = entry(h, DamageKind::HIT_PRESENT);
    EXPECT_EQ(p.ops[0].handle, s.target);
    EXPECT_EQ(p.ops[1].type, DamageOperand::Type::Held);
    EXPECT_EQ(p.ops[1].handle, s.ship);
    EXPECT_EQ(p.ops[10].number, damage);
    EXPECT_EQ(p.ops[16].integer, 1);      // the phaser's HitWeapon
    EXPECT_EQ(p.ops[17].number, 0.15);    // no DRF: the default radius
    EXPECT_TRUE(p.ops[19].boolean);       // damage_hull: not PP_LOW
    EXPECT_FALSE(p.ops[20].boolean);      // no bubble entry
    const DamageEntry& wh = entry(h, DamageKind::WEAPON_HIT);
    EXPECT_EQ(wh.ops[12].integer, 0);     // WeaponHitEvent.PHASER
    EXPECT_EQ(w.k.counts().native_pulses, 1);
    EXPECT_EQ(w.k.take_hits(), 1);
    EXPECT_EQ(w.k.take_hits(), 0);
    w.k.end();
}

TEST(K2Pulse, BeyondItsDistanceItFallsOffAndLowPowerSparesTheHull) {
    World w;
    const auto s = w.scene(true, 0.6);
    const int64_t hull = damageable(w, s.target);
    arm(w, s.bank, 100.0, 25.0, 0.375);  // dist 50 > 25: R/d
    w.m.set_i(s.sys, Field::_power_level, 0);  // PP_LOW
    begin_pulse(w, {s.ship}, pulse_ctx({s.target}));
    const K2Record r = w.k.next();
    ASSERT_EQ(r.kind, K2Kind::DONE);
    ASSERT_EQ(r.hits.size(), 1u);
    const double damage = 100.0 * (25.0 / 50.0) * (0.6 + kDt) * 0.25;
    EXPECT_EQ(cond(w, hull), 1000.0);    // damage_hull False
    const DamageEntry& p = entry(r.hits[0], DamageKind::HIT_PRESENT);
    EXPECT_EQ(p.ops[10].number, damage);
    EXPECT_EQ(p.ops[14].number, damage);  // absorbed_hull, unwritten
    EXPECT_EQ(p.ops[17].number, 0.375);   // the bank's DRF
    EXPECT_FALSE(p.ops[19].boolean);
    w.k.end();
}

TEST(K2Pulse, TheNextBankOnTheSameTargetSeesThePulseAndTheTargetLives) {
    // Ruling P1 by construction, and M5: the first pulse zeroes the
    // critical hull, the second bank still fires at the target (no death in
    // the walk) and its write starts from 0 -- a crossing only the first
    // reports as crossed.
    World w;
    const auto s = w.scene(true, 0.6);
    const int64_t b1 = w.bank("b1", s.sys, s.target, true, 0.6);
    const int64_t hull = damageable(w, s.target, 10.0);
    arm(w, s.bank, 100.0, 60.0);
    arm(w, b1, 100.0, 60.0);
    w.m.set_i(s.sys, Field::_power_level, 2);
    begin_pulse(w, {s.ship}, pulse_ctx({s.target}));
    const K2Record r = w.k.next();
    ASSERT_EQ(r.kind, K2Kind::DONE);
    EXPECT_EQ(w.writes(r), (World::V{"b0._dwell=0", "b1._dwell=0"}));
    ASSERT_EQ(r.hits.size(), 2u);
    EXPECT_EQ(r.hits[1].at_write, 2u);
    EXPECT_EQ(cond(w, hull), 0.0);
    EXPECT_EQ(w.m.get_i(s.target, Field::_dead), 0);
    EXPECT_EQ(w.m.get_i(b1, Field::_firing), 1);  // not stopped
    const DamageEntry& z0 = entry(r.hits[0], DamageKind::ZERO_CROSS);
    const DamageEntry& z1 = entry(r.hits[1], DamageKind::ZERO_CROSS);
    EXPECT_TRUE(z0.ops[2].boolean);
    EXPECT_FALSE(z1.ops[2].boolean);   // the second read the first's 0
    w.k.end();
}

TEST(K2Pulse, AnArcFailPartialPulseLandsAfterItsStop) {
    World w;
    const auto s = w.scene(true, 0.2);
    w.store.set_position(
        static_cast<uint32_t>(w.m.get_i(s.target, Field::xform_index)),
        static_cast<uint32_t>(w.m.get_i(s.target, Field::xform_gen)), 0.0,
        -50.0, 0.0);  // astern
    const int64_t hull = damageable(w, s.target);
    arm(w, s.bank, 100.0, 60.0);
    w.m.set_i(s.sys, Field::_power_level, 1);
    begin_pulse(w, {s.ship}, pulse_ctx({s.target}));
    const K2Record r = w.k.next();
    ASSERT_EQ(r.kind, K2Kind::DONE);
    EXPECT_EQ(w.writes(r), (World::V{"b0._dwell=0", "b0._firing=False",
                                     "b0._beam_on_countdown=0"}));
    EXPECT_EQ(w.entries(r), (World::V{"LOOP_STOP b0@3"}));
    ASSERT_EQ(r.hits.size(), 1u);
    EXPECT_EQ(r.hits[0].at_write, 3u);
    EXPECT_EQ(r.hits[0].at_entry, 1u);
    EXPECT_EQ(cond(w, hull), 1000.0 - 100.0 * 0.2 * 0.5);
    w.k.end();
}

TEST(K2Pulse, WhatTheKernelCannotApplyStaysACONTACT) {
    struct Case {
        const char* why;
        K2PulseWhy reason;
    };
    for (const Case c : {Case{"not_ok", K2PulseWhy::not_ok},
                         Case{"unscanned", K2PulseWhy::unscanned},
                         Case{"level", K2PulseWhy::level},
                         Case{"fallback", K2PulseWhy::fallback},
                         Case{"python", K2PulseWhy::python}}) {
        SCOPED_TRACE(c.why);
        World w;
        const auto s = w.scene(true, 0.6);
        const int64_t hull = damageable(w, s.target);
        arm(w, s.bank, 100.0, 60.0);
        w.m.set_i(s.sys, Field::_power_level, 1);
        K2PulseCtx p = pulse_ctx({s.target});
        if (c.reason == K2PulseWhy::not_ok) p.ok = false;
        if (c.reason == K2PulseWhy::unscanned) p.clean.clear();
        if (c.reason == K2PulseWhy::level)
            w.m.set_i(s.sys, Field::_power_level, 3);  // IndexError
        if (c.reason == K2PulseWhy::fallback)
            w.m.set_i(s.target, Field::dmg_ship, 0);   // a class Python owns
        if (c.reason == K2PulseWhy::python)
            p.python_banks = {s.bank};  // it shadows a name the pulse reads
        begin_pulse(w, {s.ship}, p);
        const K2Record r = w.k.next();
        EXPECT_EQ(w.brief(r),
                  "CONTACT b0@t flush=" + World::num(0.6 + kDt));
        EXPECT_TRUE(r.hits.empty());
        EXPECT_EQ(cond(w, hull), 1000.0);
        EXPECT_EQ(w.k.counts().pulse_why[static_cast<size_t>(c.reason)], 1);
        EXPECT_EQ(w.k.counts().native_pulses, 0);
        EXPECT_EQ(w.brief(w.k.next()), "DONE");
        w.k.end();
    }
}

TEST(K2Pulse, ANegativeLevelIndexesFromTheEndAsPython) {
    World w;
    const auto s = w.scene(true, 0.6);
    const int64_t hull = damageable(w, s.target);
    arm(w, s.bank, 100.0, 60.0);
    w.m.set_i(s.sys, Field::_power_level, -3);  // SCALE[-3] == SCALE[0]
    begin_pulse(w, {s.ship}, pulse_ctx({s.target}));
    const K2Record r = w.k.next();
    ASSERT_EQ(r.kind, K2Kind::DONE);
    ASSERT_EQ(r.hits.size(), 1u);
    EXPECT_EQ(cond(w, hull), 1000.0 - 100.0 * (0.6 + kDt) * 0.25);
    w.k.end();
}

TEST(K2Pulse, AZeroDamagePulseDoesNothing) {
    World w;
    const auto s = w.scene(true, 0.6);
    const int64_t hull = damageable(w, s.target);
    arm(w, s.bank, 100.0, 0.0);  // MaxDamageDistance 0: no damage
    begin_pulse(w, {s.ship}, pulse_ctx({s.target}));
    const K2Record r = w.k.next();
    ASSERT_EQ(r.kind, K2Kind::DONE);
    EXPECT_TRUE(r.hits.empty());
    EXPECT_EQ(cond(w, hull), 1000.0);
    EXPECT_EQ(w.k.counts().native_pulses, 0);
    w.k.end();
}

TEST(K2Pulse, APulseClearsTheStepMemoAroundItsHit) {
    World w;
    const auto s = w.scene(true, 0.6);
    damageable(w, s.target);
    arm(w, s.bank, 100.0, 60.0);
    begin_pulse(w, {s.ship}, pulse_ctx({s.target}));
    w.k.next();
    // The walk's can_detect filled the memo before the pulse; the pulse's
    // forget (combat.apply_hit's, DM H13) leaves it empty.
    EXPECT_TRUE(w.m.sensor_state().memo.empty());
    EXPECT_TRUE(w.m.sensor_state().mounts.empty());
    w.k.end();
}

TEST(K2Pulse, AThrowLaterInTheCallUndoesThePulse) {
    World w;
    const auto s = w.scene(true, 0.6);
    const int64_t hull = damageable(w, s.target);
    arm(w, s.bank, 100.0, 60.0);
    w.m.set_i(s.sys, Field::_power_level, 1);
    // A second ship whose bank traces through the host: the throw.
    const int64_t b = w.ship("B", 100.0, 0.0, 0.0);
    const int64_t bsys = w.system("bsys", b);
    const int64_t t2 = w.ship("t2", 100.0, 50.0, 0.0);
    w.bank("bb", bsys, t2, true);
    K2Context ctx;
    ctx.hooks = w.host.hooks();
    ctx.view_offsets[w.set] = std::nullopt;
    ctx.iids[t2] = K2Context::Iid{false, {1, 1}};
    ctx.pulse = pulse_ctx({s.target});
    w.host.throw_foreign = true;
    w.k.begin({s.ship, b}, kDt, 10.0, true, 0.0, ctx);
    EXPECT_ANY_THROW(w.k.next());
    EXPECT_EQ(cond(w, hull), 1000.0);
    EXPECT_EQ(w.m.get_i(hull, Field::_threshold_state), 0);
    EXPECT_EQ(w.m.get_f(s.bank, Field::_dwell), 0.6);
    w.host.throw_foreign = false;
    const K2Record r = w.k.next();
    ASSERT_EQ(r.kind, K2Kind::DONE);
    ASSERT_EQ(r.hits.size(), 1u);  // applied again, once
    EXPECT_EQ(cond(w, hull), 1000.0 - 100.0 * (0.6 + kDt) * 0.5);
    w.k.end();
}

TEST(K2Pulse, TheNextRecordCarriesThePulse) {
    // A pulse is not a record: it rides the next one -- here an ASK on the
    // next bank -- which the binding applies and appends before Python
    // answers.
    World w;
    const auto s = w.scene(true, 0.6);
    const int64_t hull = damageable(w, s.target);
    arm(w, s.bank, 100.0, 60.0);
    w.m.set_i(s.sys, Field::_power_level, 1);
    const int64_t stub = w.ship("stub", 0.0, 80.0, 0.0);
    w.m.set_i(stub, Field::has_real_is_dead, 0);  // is_dead is Python's
    w.bank("b1", s.sys, stub, true);
    begin_pulse(w, {s.ship}, pulse_ctx({s.target}));
    const K2Record r = w.k.next();
    ASSERT_EQ(w.brief(r), "ASK is_dead");
    ASSERT_EQ(r.hits.size(), 1u);
    EXPECT_EQ(r.hits[0].at_write, 1u);
    EXPECT_EQ(cond(w, hull), 1000.0 - 100.0 * (0.6 + kDt) * 0.5);
    EXPECT_EQ(w.k.take_hits(), 1);
    K2Answer a;
    a.flag = false;
    w.k.answer(a);
    const K2Record d = w.k.next();
    EXPECT_EQ(d.kind, K2Kind::DONE);
    EXPECT_TRUE(d.hits.empty());
    EXPECT_EQ(w.k.take_hits(), 0);
    w.k.end();
}
