// The K2 beam kernel -- see k2_beams.h. A resumable port of the `cb.phasers`
// loop of engine/host_loop.py _advance_combat_step (HL:1177-1322; K2M =
// docs/reference/engine/native-combat/k2-beams-map.md section 1.1). Each
// cursor state (enum St) is named after the Python line it stands for;
// Walker::run's switch reads top to bottom like the Python. Every float
// decision is made by beam_geometry / beam_trace / weapon_geometry /
// fire_gates / sensor_detect, the Python-exact ports; the inline literals here
// are the Python's, with their line.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/k2_beams.h"

#include <cmath>
#include <cstdint>
#include <iterator>
#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>

#include "dauntless/combat/beam_geometry.h"
#include "dauntless/combat/damage.h"
#include "dauntless/combat/fire_gates.h"
#include "dauntless/combat/part_pose.h"
#include "dauntless/combat/py_math.h"
#include "dauntless/combat/sensor_detect.h"
#include "dauntless/combat/stop_firing.h"
#include "dauntless/combat/weapon_geometry.h"
#include "geometry_internal.h"

namespace dauntless::combat {

namespace {

// Subsystem weapon_kind codes (mirror.h).
constexpr int64_t kPhaserSystem = 1, kPhaserBank = 5;

bool xform_ok(const Mirror& m, const ObjectRow& o) {
    if (o.xform_index < 0 || o.xform_gen < 0 ||
        o.xform_index > std::numeric_limits<uint32_t>::max() ||
        o.xform_gen > std::numeric_limits<uint32_t>::max())
        return false;
    return m.store().valid(static_cast<uint32_t>(o.xform_index),
                           static_cast<uint32_t>(o.xform_gen));
}

// A `_containing_set` value the walk can name: None or a live Set row.
bool set_ok(const Mirror& m, int64_t h) {
    return h == -1 || (h >= 0 && m.set(h) != nullptr);
}

bool positive_zero(double x) { return x == 0.0 && !std::signbit(x); }

[[noreturn]] void lost(const char* why) {
    throw std::logic_error(std::string("combat K2: ") + why);
}

}  // namespace

const char* k2_kind_name(K2Kind k) {
    static constexpr const char* kNames[] = {
        "DONE", "SYSTEM_STOP", "BANK_STOP", "CONTACT", "RUN_PYTHON", "ASK"};
    static_assert(std::size(kNames) == static_cast<size_t>(K2Kind::kCount));
    const auto i = static_cast<size_t>(k);
    return i < std::size(kNames) ? kNames[i] : "?";
}

const char* k2_why_name(K2Why w) {
    static constexpr const char* kNames[] = {
        "unslotted_ship", "not_ship_class", "overridden", "posed_ship",
        "part_stale",     "stale_row",      "stub_or_unplaced", "gate",
        "other"};
    static_assert(std::size(kNames) == static_cast<size_t>(K2Why::kCount));
    const auto i = static_cast<size_t>(w);
    return i < std::size(kNames) ? kNames[i] : "?";
}

const char* k2_query_name(K2Query q) {
    static constexpr const char* kNames[] = {
        "is_dead", "can_detect", "aim_point", "shields_block",
        "bubble",  "resolve_hit", "bank_step"};
    static_assert(std::size(kNames) == static_cast<size_t>(K2Query::kCount));
    const auto i = static_cast<size_t>(q);
    return i < std::size(kNames) ? kNames[i] : "?";
}

const char* k2_pulse_why_name(K2PulseWhy w) {
    static constexpr const char* kNames[] = {"not_ok", "unscanned", "level",
                                             "fallback", "python"};
    static_assert(std::size(kNames) ==
                  static_cast<size_t>(K2PulseWhy::kCount));
    const auto i = static_cast<size_t>(w);
    return i < std::size(kNames) ? kNames[i] : "?";
}

// ── The cursor ───────────────────────────────────────────────────────────────

enum class St : int32_t {
    SHIP_FOR,           // for ship in ships_list:
                        //   sys_ = ship.GetPhaserSystem() ...; if sys_ is None:
                        //   continue; if _is_offline(sys_) or not
                        //   sys_.IsOn(): sys_.StopFiring(); continue
                        //   for i in range(sys_.GetNumWeapons()):  (n, once)
    BANK_FOR,           //   bank = sys_.GetWeapon(i); if bank is None: continue
                        //   target = bank._target; if not bank.IsFiring():
                        //     dwell = bank.take_dwell(); if dwell <= 0.0 or
                        //     target is None or target.IsDead(): continue
                        //   else: if target is None or target.IsDead():
                        //     bank.StopFiring(); continue
    IDLE_DEAD_ANSWER,   //     (ASK is_dead answered, the take_dwell branch)
    FIRING_DEAD_ANSWER, //     (ASK is_dead answered, the IsFiring branch)
    DETECT,             //   if flush_dwell is None and not can_detect(ship,
                        //       target): bank.StopFiring(); continue
    DETECT_ANSWER,      //     (ASK can_detect answered)
    SAME_SET,           //   if not _same_set(ship, target):
                        //     if flush_dwell is None: bank.StopFiring()
                        //     continue
    AIM,                //   target_pos, target_sub = _phaser_aim_point(...)
    AIM_ANSWER,         //     (ASK aim_point answered)
    GEOMETRY,           //   emitter_pos = bank._strip_emit_position(...);
                        //   dist; aim_unit; arc_aim = _resolve_bank_aim_world(
                        //   bank, target_sub or target); if flush_dwell is
                        //   None: if not _emitter_in_arc(...): flush_dwell =
                        //   bank.take_dwell(); bank.StopFiring()
                        //   else: flush_dwell = bank.accumulate_dwell(dt)
    ARC_STOPPED,        //   (after the arc-fail StopFiring: on to the pulse)
    TRACE,              //   impact_point, impact_normal =
                        //       combat._resolve_hit_point(...)
    TRACE_ANSWER,       //     (ASK resolve_hit answered)
    SHIELDS,            //   bubble_entry = (... if (aim_unit is not None and
                        //       combat.shields_block(target)) else None)
    SHIELDS_ANSWER,     //     (ASK shields_block answered)
    BUBBLE,             //   combat.shield_bubble_entry(target, emitter_pos,
                        //       aim_unit, dist * 1.5); then the contact:
                        //   beam_contact / apply_hit (CONTACT)
    BUBBLE_ANSWER,      //     (ASK bubble answered)
    BANK_STEP_ANSWER,   //   (ASK bank_step answered: Python ran bank i)
    BANK_NEXT,          //   continue (the next i)
    SHIP_NEXT,          // continue (the next ship)
    DONE,               // returned DONE; only end() / abandon() may follow
};

// The mirror value one logged write replaced: a float (`_dwell`,
// `_beam_on_countdown`), an int (`_fire_held`, `_last_group_fired`,
// `_firing`), a ref (`_held_target`), a handle list (`_target_list`) or an
// offset (`_held_offset`).
struct K2Undo {
    enum class Type : int32_t { F, I, Ref, Ids, Offset } type = Type::F;
    int64_t h = -1;
    Field f = Field::_dwell;
    double d = 0.0;
    int64_t i = 0;
    std::vector<int64_t> ids;
    Vec3 v{0, 0, 0};
    bool set = false;
};

struct K2Kernel::Session {
    // Shared, so next()'s per-call backup of the session copies no list
    // (`rests` is moved aside for it, not copied).
    std::shared_ptr<const std::vector<int64_t>> ships;
    double dt = 0.0, now = 0.0, drift_now = 0.0;
    bool use_memo = false;
    St st = St::SHIP_FOR;

    // The loop's `ship` and `sys_`, `n` (GetNumWeapons, read once) and `i`.
    size_t ship_pos = 0;
    int64_t ship = -1, sys = -1;
    size_t n = 0, i = 0;
    bool ship_active = false;    // a ship is being walked
    bool ship_recorded = false;  // a record was returned for it
    size_t ship_mark = 0;        // writes.size() when it began
    size_t ship_entry_mark = 0;  // entries.size() when it began
    size_t ship_hit_mark = 0;    // hits.size() when it began

    // The bank's locals.
    bool in_bank = false;
    bool bank_recorded = false;
    size_t bank_mark = 0;
    size_t bank_entry_mark = 0;
    size_t bank_hit_mark = 0;
    int64_t bank = -1, target = -1;
    double dwell = 0.0;                 // the idle branch's take_dwell
    std::optional<double> flush_dwell;  // None on the IsFiring branch
    Vec3 target_pos{0, 0, 0};
    bool has_sub = false;  // target_sub is not None
    Vec3 emitter{0, 0, 0};
    double dist = 0.0;
    std::optional<Vec3> aim_unit;
    ResolvedHit hit;
    std::optional<bool> shields;
    bool shields_asked = false;  // `shields` is an ASK's answer
    std::optional<Vec3> bubble;

    // The write log since the last record, and, one for one, the value each
    // write replaced (rolled back if the writes never reach Python).
    std::vector<K2Write> writes;
    std::vector<K2Undo> undo;
    // The queue entries since the last record (THE EFFECT QUEUE, k2_beams.h:
    // a firing bank's LOOP_STOP), each placed after the writes before it;
    // rolled back with them.
    std::vector<K1Entry> entries;
    // The damage pulses applied since the last record (THE DAMAGE PULSE,
    // k2_beams.h), each placed among the writes and entries; rolled back
    // with them.
    std::vector<K2Hit> hits;
    // The resting contacts queued for the drain (RESTING CONTACTS,
    // k2_beams.h), in walk order.
    std::vector<K2Rest> rests;
    bool awaiting_answer = false, has_answer = false;
    K2Query pending = K2Query::kCount;
    K2Answer answer;
};

// Undo the session's logged writes from `mark` on, newest first, and drop
// them from the log, with the queue entries from `entry_mark` on and the
// damage pulses from `hit_mark` on (their own writes undone, newest first):
// they never reached Python. A pulse writes fields no logged write does
// (damage.h: conditions, threshold states, watcher values, faces), so the
// two undo in either order.
static void k2_roll_back(Mirror& m, K2Kernel::Session& s, size_t mark,
                         size_t entry_mark, size_t hit_mark) {
    while (s.hits.size() > hit_mark) {
        undo_damage(m, s.hits.back().out.undo);
        s.hits.pop_back();
    }
    s.entries.resize(entry_mark);
    while (s.undo.size() > mark) {
        const K2Undo& u = s.undo.back();
        switch (u.type) {
            case K2Undo::Type::F: m.set_f(u.h, u.f, u.d); break;
            case K2Undo::Type::I: m.set_i(u.h, u.f, u.i); break;
            case K2Undo::Type::Ref: m.set_ref(u.h, u.f, u.i); break;
            case K2Undo::Type::Ids: m.set_ids(u.h, u.f, u.ids); break;
            case K2Undo::Type::Offset:
                if (u.set)
                    m.set_fv(u.h, u.f, {u.v[0], u.v[1], u.v[2]});
                else
                    m.set_fv(u.h, u.f, {});
                break;
        }
        s.undo.pop_back();
    }
    s.writes.resize(mark);
}

namespace {

using Session = K2Kernel::Session;

// One next() call: runs the cursor to the next record.
class Walker {
public:
    Walker(Mirror& m, Session& s, const K2Context& ctx, K2Kernel::Counts& c)
        : m_(m), s_(s), ctx_(ctx), c_(c) {}

    K2Record run();

private:
    const SubsystemRow* subrow(int64_t h) const {
        return h < 0 ? nullptr : m_.subsystem(h);
    }
    const ObjectRow* objrow(int64_t h) const {
        return h < 0 ? nullptr : m_.object(h);
    }
    // ObjectClass.GetContainingSet: the handle, or a fall-back when the
    // mirror cannot name it.
    int64_t containing_set(int64_t obj) const {
        const ObjectRow* o = objrow(obj);
        if (!o) throw std::invalid_argument("combat K2: object row is gone");
        if (!set_ok(m_, o->_containing_set))
            throw std::invalid_argument("combat K2: _containing_set unnamed");
        return o->_containing_set;
    }

    // ── The write log ───────────────────────────────────────────────────────
    // `bank._dwell = v`, made in the mirror and logged. `idle`: take_dwell on
    // the not-firing branch, whose +0.0 over a +0.0 is elided.
    void write_dwell(int64_t bank, double v, bool idle) {
        const SubsystemRow* b = subrow(bank);
        if (!b) throw std::invalid_argument("combat K2: bank row is gone");
        const double old = b->_dwell;
        if (idle && positive_zero(old) && positive_zero(v)) return;
        write_f(bank, Field::_dwell, "_dwell", v);
    }
    // Each write reads the value it replaces (for the undo), writes the
    // mirror, then logs. The caller checked the row exists.
    void write_f(int64_t h, Field f, const char* name, double v) {
        K2Undo u;
        u.type = K2Undo::Type::F;
        u.h = h;
        u.f = f;
        u.d = m_.get_f(h, f);
        m_.set_f(h, f, v);
        s_.undo.push_back(std::move(u));
        s_.writes.push_back(K2Write{h, name, v});
    }
    void write_i(int64_t h, Field f, const char* name, int64_t v, K1Value lv) {
        K2Undo u;
        u.type = K2Undo::Type::I;
        u.h = h;
        u.f = f;
        u.i = m_.get_i(h, f);
        m_.set_i(h, f, v);
        s_.undo.push_back(std::move(u));
        s_.writes.push_back(K2Write{h, name, std::move(lv)});
    }
    // ── The effect queue: entries in walk order, after the writes before ──
    void enqueue(K1Effect kind, int64_t a) {
        s_.entries.push_back(K1Entry{kind, a, -1, s_.writes.size()});
        ++c_.entries[static_cast<size_t>(kind)];
    }

    // `bank.StopFiring()` on a live phaser bank: its class's writes in its
    // order (stop_firing.h, the one encoding K1 and K0 write too), then, if
    // it was firing, its loop sound's LOOP_STOP (THE EFFECT QUEUE). False
    // (nothing written) for a row gone or a kind with no stop.
    bool write_stop(int64_t h) {
        const SubsystemRow* r = subrow(h);
        if (!r) return false;
        const std::optional<StopFiring> stop = stop_firing_of(r->weapon_kind);
        if (!stop) return false;
        const bool firing = r->_firing != 0;  // `was_firing = self._firing`
        for (size_t i = 0; i < stop->n; ++i) {
            switch (stop->writes[i]) {
                case StopWrite::FiringFalse:
                    write_i(h, Field::_firing, "_firing", 0, false);
                    break;
                case StopWrite::BeamOnCountdownZero:
                    write_f(h, Field::_beam_on_countdown, "_beam_on_countdown",
                            0.0);
                    break;
                case StopWrite::TargetNone: {
                    K2Undo u;
                    u.type = K2Undo::Type::Ref;
                    u.h = h;
                    u.f = Field::_target;
                    u.i = m_.get_ref(h, Field::_target);
                    m_.set_ref(h, Field::_target, -1);
                    s_.undo.push_back(std::move(u));
                    s_.writes.push_back(K2Write{h, "_target", int64_t{-1}});
                    break;
                }
                case StopWrite::TargetOffsetNone: {
                    const SubsystemRow* b = subrow(h);
                    K2Undo u;
                    u.type = K2Undo::Type::Offset;
                    u.h = h;
                    u.f = Field::_target_offset;
                    u.set = b->target_offset_set;
                    u.v = b->_target_offset;
                    m_.set_fv(h, Field::_target_offset, {});
                    s_.undo.push_back(std::move(u));
                    s_.writes.push_back(
                        K2Write{h, "_target_offset", std::monostate{}});
                    break;
                }
            }
        }
        if (firing && stop->loop_stop) enqueue(K1Effect::LOOP_STOP, h);
        return true;
    }

    // The walk's `bank.StopFiring()` on its FIRING bank (combat fire events
    // §4.3): logged (write_stop) and true; false keeps the BANK_STOP record
    // (a row gone: the documented fallback, k2_beams.h RECORDS).
    bool bank_stop(int64_t bank) {
        if (!write_stop(bank)) return false;
        ++c_.logged_bank_stop;
        return true;
    }

    // `sys_.StopFiring()` (THE OFFLINE STOP, k2_beams.h): the logged writes
    // and true -- a firing bank's LOOP_STOP after its own writes. A child
    // that is not a live phaser bank: false, and nothing written (the
    // caller emits SYSTEM_STOP).
    bool offline_stop(int64_t sys) {
        // for i in range(self.GetNumWeapons()): w = self.GetWeapon(i) --
        // the children cannot change: no Python runs in between.
        const std::vector<int64_t> kids = subrow(sys)->_children;
        bool any_firing = false;
        for (const int64_t k : kids) {
            const SubsystemRow* b = subrow(k);
            if (!b || b->weapon_kind != kPhaserBank)
                return false;
            any_firing = any_firing || b->_firing != 0;
        }
        // WeaponSystem.StopFiring (WS:1540-1549)
        write_i(sys, Field::_fire_held, "_fire_held", 0, false);
        {
            K2Undo u;
            u.type = K2Undo::Type::Ref;
            u.h = sys;
            u.f = Field::_held_target;
            u.i = m_.get_ref(sys, Field::_held_target);
            m_.set_ref(sys, Field::_held_target, -1);
            s_.undo.push_back(std::move(u));
            s_.writes.push_back(K2Write{sys, "_held_target", int64_t{-1}});
        }
        {
            const SubsystemRow* r = subrow(sys);
            K2Undo u;
            u.type = K2Undo::Type::Offset;
            u.h = sys;
            u.f = Field::_held_offset;
            u.set = r->held_offset_set;
            u.v = r->_held_offset;
            m_.set_fv(sys, Field::_held_offset, {});
            s_.undo.push_back(std::move(u));
            s_.writes.push_back(K2Write{sys, "_held_offset", std::monostate{}});
        }
        {
            K2Undo u;
            u.type = K2Undo::Type::Ids;
            u.h = sys;
            u.f = Field::_target_list;
            u.ids = subrow(sys)->_target_list;  // raw: stale entries kept
            m_.set_ids(sys, Field::_target_list, {});
            s_.undo.push_back(std::move(u));
            s_.writes.push_back(
                K2Write{sys, "_target_list", std::vector<int64_t>{}});
        }
        write_i(sys, Field::_last_group_fired, "_last_group_fired", -1,
                int64_t{-1});
        // w.StopFiring(): _EnergyWeaponFireMixin.StopFiring (WS:920), a
        // firing bank's loop sound stopped after its writes.
        for (const int64_t k : kids)
            if (!write_stop(k)) lost("an offline stop's bank row is gone");
        ++c_.logged_system_stop;
        if (any_firing) ++c_.logged_firing_system_stop;
        return true;
    }

    // ── Records ─────────────────────────────────────────────────────────────
    K2Record emit(K2Kind kind, St next, int64_t a = -1, int64_t b = -1) {
        K2Record r;
        r.kind = kind;
        r.a = a;
        r.b = b;
        r.writes = std::move(s_.writes);
        s_.writes.clear();
        r.entries = std::move(s_.entries);
        s_.entries.clear();
        r.hits = std::move(s_.hits);
        s_.hits.clear();
        s_.undo.clear();  // delivered: Python applies them
        s_.st = next;
        s_.ship_recorded = true;
        if (s_.in_bank) s_.bank_recorded = true;
        ++c_.records;
        return r;
    }
    // The ship handed to Python whole, before any record for it: its own
    // undelivered writes are undone (Python makes them itself).
    K2Record run_python(K2Why why) {
        k2_roll_back(m_, s_, s_.ship_mark, s_.ship_entry_mark,
                     s_.ship_hit_mark);
        ++c_.python_ships;
        ++c_.why[static_cast<size_t>(why)];
        return emit(K2Kind::RUN_PYTHON, St::SHIP_NEXT, s_.ship,
                    static_cast<int64_t>(s_.ship_pos));
    }
    K2Record ask(K2Query q, std::vector<K2Arg> args, St next) {
        K2Record r = emit(K2Kind::ASK, next);
        r.query = q;
        r.args = std::move(args);
        s_.awaiting_answer = true;
        s_.has_answer = false;
        s_.pending = q;
        ++c_.asks;
        ++c_.queries[static_cast<size_t>(q)];
        return r;
    }
    K2Answer take_answer() {
        K2Answer a = s_.answer;
        s_.answer = K2Answer{};
        s_.pending = K2Query::kCount;
        return a;
    }
    // Bank i cannot be walked natively: the whole ship to Python before its
    // first record, else the one bank (nothing delivered for it yet).
    K2Record bank_fallback(K2Why why) {
        if (!s_.ship_recorded) return run_python(why);
        k2_roll_back(m_, s_, s_.bank_mark, s_.bank_entry_mark,
                     s_.bank_hit_mark);
        return ask(K2Query::bank_step,
                   {s_.ship, s_.sys, static_cast<int64_t>(s_.i)},
                   St::BANK_STEP_ANSWER);
    }
    // A native evaluation threw where no ASK stands in for it.
    K2Record unexpected(const std::exception& e) {
        if (s_.ship_active && !s_.ship_recorded)
            return run_python(K2Why::Other);
        if (s_.in_bank && !s_.bank_recorded) return bank_fallback(K2Why::Other);
        throw std::logic_error(
            std::string("combat K2: a bank whose body has started can no "
                        "longer be walked (protocol invariant, k2_beams.h): ") +
            e.what());
    }

    // The ship row a subsystem belongs to, or null (also for a chain the
    // mirror cannot climb: the aim_point ASK's). A subsystem attached
    // straight to its ship answers from `_parent_ship` with no climb.
    const ObjectRow* owner_row(int64_t sub_h) const {
        const SubsystemRow* sr = subrow(sub_h);
        if (sr && sr->_parent_ship != -1) {
            if (const ObjectRow* direct = objrow(sr->_parent_ship))
                return direct;
        }
        try {
            const int64_t ls = climb_to_ship_of(m_, sub_h);
            return ls == -1 ? nullptr : objrow(ls);
        } catch (const std::invalid_argument&) {
            return nullptr;
        }
    }

    // ── The pre-scan (ruling H, stage 1) ───────────────────────────────────
    std::optional<K2Why> ship_why() const;
    std::optional<K2Why> child_why(int64_t bank) const;
    std::optional<K2Why> prescan() const;

    K2Record contact();
    bool queue_contact();
    bool pulse();

    Mirror& m_;
    Session& s_;
    const K2Context& ctx_;
    K2Kernel::Counts& c_;
};

// What every bank's walk reads of the ship and the system: a placed
// ShipClass in a nameable set, the system's row, and -- for the aim point at
// a subsystem lock (_phaser_aim_point, not under Manual Aim) on a posed ship
// -- a current part slot for the lock's mount on its own ship. A lock the
// mirror cannot name is the aim_point ASK's, not a fallback.
std::optional<K2Why> Walker::ship_why() const {
    const ObjectRow* so = objrow(s_.ship);
    if (!so) return K2Why::StaleRow;
    if (!so->is_ship_class) return K2Why::NotShipClass;
    if (!xform_ok(m_, *so)) return K2Why::StubOrUnplaced;
    if (!set_ok(m_, so->_containing_set)) return K2Why::StaleRow;
    if (!subrow(s_.sys)) return K2Why::StaleRow;
    const bool manual_aim = so->_use_target_offset != 0 && so->manual_offset_set;
    if (!manual_aim && so->_target_subsystem >= 0) {
        if (const SubsystemRow* lock = subrow(so->_target_subsystem)) {
            const ObjectRow* lo = owner_row(so->_target_subsystem);
            Vec3 local;
            if (lo && lo->has_posed_parts &&
                posed_local(m_, *lo, *lock, &local) == SlotState::stale)
                return K2Why::PartStale;
        }
    }
    return std::nullopt;
}

// One child: a live PhaserBank of this ship, and its `_target`
// None or a placed Object in a nameable set. The target's IsDead, its lock,
// its shields and its instance are per-bank ASKs, not fallbacks.
std::optional<K2Why> Walker::child_why(int64_t bank) const {
    const SubsystemRow* b = subrow(bank);
    if (!b) return K2Why::StaleRow;
    if (b->weapon_kind != kPhaserBank) return K2Why::Other;
    try {
        if (climb_to_ship_of(m_, bank) != s_.ship) return K2Why::Other;
    } catch (const std::invalid_argument&) {
        return K2Why::StaleRow;
    }
    // A posed ship's bank mount (the strip centre, the arc origin) is read
    // through its part slot: one that is not current is Python's.
    const ObjectRow* so = objrow(s_.ship);
    Vec3 local;
    if (so && so->has_posed_parts &&
        posed_local(m_, *so, *b, &local) == SlotState::stale)
        return K2Why::PartStale;
    const int64_t t = b->_target;
    if (t != -1) {
        const ObjectRow* to = objrow(t);
        if (!to) return K2Why::StaleRow;
        if (!xform_ok(m_, *to)) return K2Why::StubOrUnplaced;
        if (!set_ok(m_, to->_containing_set)) return K2Why::StaleRow;
    }
    return std::nullopt;
}

std::optional<K2Why> Walker::prescan() const {
    if (std::optional<K2Why> why = ship_why()) return why;
    for (const int64_t c : subrow(s_.sys)->_children)
        if (std::optional<K2Why> why = child_why(c)) return why;
    return std::nullopt;
}

// The bank's contact as Python's _phaser_contact takes it: everything
// beam_contact / apply_hit take that the kernel decided.
static K2Contact make_contact(const K2Kernel::Session& s) {
    K2Contact c;
    c.bank = s.bank;
    c.target = s.target;
    c.ship = s.ship;
    c.system = s.sys;
    c.emitter = s.emitter;
    c.target_pos = s.target_pos;
    c.dist = s.dist;
    c.aim_unit = s.aim_unit;
    c.hit = s.hit;
    c.bubble = s.bubble;
    c.shields_block = s.shields;
    c.shields_asked = s.shields_asked;
    c.flush_dwell = *s.flush_dwell;
    return c;
}

// A RESTING contact (`flush_dwell <= 0.0`: beam_contact, presentation only)
// is queued for the drain with what its presentation reads, as it is now
// (RESTING CONTACTS, k2_beams.h), and the walk goes on: true. A damage
// pulse: false (the caller emits CONTACT).
bool Walker::queue_contact() {
    if (!(*s_.flush_dwell <= 0.0)) return false;
    K2Rest e;
    e.contact = make_contact(s_);
    // No aim unit: the loop never asked shields_block; beam_contact would.
    // Natively when the mirror can answer, else unknown (no ASK).
    if (!e.contact.shields_block) {
        try {
            e.contact.shields_block = shields_block(
                m_, s_.target, ctx_.npc_shields_off, ctx_.player);
        } catch (const std::invalid_argument&) {
        }
    }
    // _phaser_level(sys_): sys_.GetPowerLevel(), a PhaserSystem (pre-scan).
    const SubsystemRow* y = subrow(s_.sys);
    if (!y) throw std::invalid_argument("combat K2: system row is gone");
    e.level = y->_power_level;
    const auto it = ctx_.iids.find(s_.target);
    if (it != ctx_.iids.end() && !it->second.bad) e.iid = it->second.id;
    const ObjectRow* t = objrow(s_.target);
    if (t && set_ok(m_, t->_containing_set)) {
        const auto vo = ctx_.view_offsets.find(t->_containing_set);
        if (vo != ctx_.view_offsets.end()) {
            e.view_known = true;
            e.view_offset = vo->second;
        }
    }
    s_.rests.push_back(std::move(e));
    ++c_.batched_contacts;
    // The bank's body has run in full and the ship's has started: a later
    // bank that cannot be walked is a bank_step, never the whole ship again.
    s_.ship_recorded = true;
    s_.bank_recorded = true;
    s_.st = St::BANK_NEXT;
    return true;
}

// A damage pulse the kernel could not apply (THE DAMAGE PULSE): the CONTACT
// record, and Python runs _phaser_contact.
K2Record Walker::contact() {
    K2Record r = emit(K2Kind::CONTACT, St::BANK_NEXT);
    r.contact = make_contact(s_);
    return r;
}

// A damage pulse (`flush_dwell > 0.0`), host_loop._phaser_contact's damage
// branch, applied in the walk (THE DAMAGE PULSE, k2_beams.h): true, and the
// walk goes on. False keeps the CONTACT record (counted by why), with the
// mirror untouched.
bool Walker::pulse() {
    const K2PulseCtx& p = ctx_.pulse;
    auto python = [this](K2PulseWhy why) {
        ++c_.pulse_why[static_cast<size_t>(why)];
        return false;
    };
    if (!p.ok) return python(K2PulseWhy::not_ok);
    if (p.clean.count(s_.target) == 0) return python(K2PulseWhy::unscanned);
    if (p.python_banks.count(s_.bank)) return python(K2PulseWhy::python);
    const SubsystemRow* b = subrow(s_.bank);
    const SubsystemRow* y = subrow(s_.sys);
    if (!b || !y) return python(K2PulseWhy::fallback);
    // PHASER_INTENSITY_SCALE[level]: a 3-tuple, indexed as Python indexes
    // (-3..2; anything else raises IndexError in Python).
    const int64_t level = y->_power_level;
    const int64_t index = level < 0 ? level + 3 : level;
    if (index < 0 || index >= 3) return python(K2PulseWhy::level);
    // _phaser_damage_for_tick(max_damage=bank.GetMaxDamage(),
    //     max_damage_distance=bank.GetMaxDamageDistance(), dist=dist,
    //     dt=flush_dwell) * PHASER_INTENSITY_SCALE[level]     (HL:1286-1291)
    const double md = b->_max_damage, mdd = b->_max_damage_distance;
    const double dt = *s_.flush_dwell;
    double damage;
    if (mdd <= 0.0)
        damage = 0.0;
    else if (s_.dist <= mdd)
        damage = md * dt;
    else
        damage = md * (mdd / s_.dist) * dt;
    damage = damage * p.intensity[static_cast<size_t>(index)];
    if (damage > 0) {
        // damage_hull = sys_.GetPowerLevel() != sys_.PP_LOW
        // combat.apply_hit(target, damage, impact_point, source=ship,
        //     normal=impact_normal, ship_instances=..., weapon_type="phaser",
        //     hardpoint_weapon=bank, damage_hull=..., shield_point=bubble)
        HitInput in;
        in.ship = s_.target;
        in.source = s_.ship;
        in.damage = damage;
        in.point = s_.hit.point;
        in.has_normal = s_.hit.normal.has_value();
        if (in.has_normal) in.normal = *s_.hit.normal;
        // weapon_splash_radius(bank, None): the bank's DRF if > 0, else the
        // default.
        const double drf = b->_damage_radius_factor;
        in.r_hit = drf > 0.0 ? drf : p.default_radius;
        in.damage_hull = level != p.pp_low;
        // shield_bubble_entry makes its own point: never the impact point.
        in.has_shield_point = s_.bubble.has_value();
        if (in.has_shield_point) in.shield_point = *s_.bubble;
        in.hit_weapon = p.hit_weapon;
        in.weapon_hit_type = p.weapon_hit_type;
        in.has_instances = p.has_instances;
        K2Hit h;
        h.at_write = s_.writes.size();
        h.at_entry = s_.entries.size();
        h.source = s_.ship;
        h.bank = s_.bank;
        h.target = s_.target;
        h.tier = s_.hit.tier;
        // combat.apply_hit: step_memo.forget() on the way in and out.
        memo_clear(m_);
        try {
            apply_hit(m_, in, p.dc, h.out);
        } catch (const std::invalid_argument&) {
            return python(K2PulseWhy::fallback);  // the mirror is as it was
        }
        memo_clear(m_);
        s_.hits.push_back(std::move(h));
        ++c_.native_pulses;
    }
    // The bank's body has run in full and the ship's has started (as after a
    // resting contact): a later bank that cannot be walked is a bank_step.
    s_.ship_recorded = true;
    s_.bank_recorded = true;
    s_.st = St::BANK_NEXT;
    return true;
}

// ── The cursor loop ──────────────────────────────────────────────────────────

K2Record Walker::run() {
    for (;;) {
        try {
            switch (s_.st) {
            // for ship in ships_list:
            case St::SHIP_FOR: {
                if (s_.ship_pos >= s_.ships->size())
                    return emit(K2Kind::DONE, St::DONE);
                s_.ship = (*s_.ships)[s_.ship_pos];
                s_.sys = -1;
                s_.ship_active = true;
                s_.ship_recorded = false;
                s_.ship_mark = s_.writes.size();
                s_.ship_entry_mark = s_.entries.size();
                s_.ship_hit_mark = s_.hits.size();
                s_.in_bank = false;
                const ObjectRow* so = objrow(s_.ship);
                if (!so) return run_python(K2Why::UnslottedShip);
                if (ctx_.python_ships.count(s_.ship))
                    return run_python(K2Why::Overridden);
                // hasattr(ship, "GetPhaserSystem") is vacuous on a stub.
                if (!so->is_ship_class) return run_python(K2Why::NotShipClass);
                // sys_ = ship.GetPhaserSystem(); if sys_ is None: continue
                const int64_t sys = so->_phaser_system;
                if (sys == -1) {
                    s_.st = St::SHIP_NEXT;
                    break;
                }
                const SubsystemRow* sr = subrow(sys);
                if (!sr) return run_python(K2Why::StaleRow);
                if (sr->weapon_kind != kPhaserSystem)
                    return run_python(K2Why::Other);
                s_.sys = sys;
                // if _is_offline(sys_) or not sys_.IsOn():
                //     sys_.StopFiring(); continue      (EVERY tick)
                bool stop;
                try {
                    stop = weapon_system_offline(m_, sys) || !sr->_is_on;
                } catch (const std::invalid_argument&) {
                    return run_python(K2Why::Gate);
                }
                if (stop) {
                    // Every bank idle: logged writes, no record.
                    if (offline_stop(sys)) {
                        s_.st = St::SHIP_NEXT;
                        break;
                    }
                    return emit(K2Kind::SYSTEM_STOP, St::SHIP_NEXT, sys);
                }
                if (std::optional<K2Why> why = prescan())
                    return run_python(*why);
                // for i in range(sys_.GetNumWeapons()): read ONCE
                s_.n = subrow(sys)->_children.size();
                s_.i = 0;
                s_.st = St::BANK_FOR;
                break;
            }

            case St::BANK_FOR: {
                if (s_.i >= s_.n) {
                    s_.st = St::SHIP_NEXT;
                    break;
                }
                s_.in_bank = true;
                s_.bank_recorded = false;
                s_.bank_mark = s_.writes.size();
                s_.bank_entry_mark = s_.entries.size();
                s_.bank_hit_mark = s_.hits.size();
                if (std::optional<K2Why> why = ship_why())
                    return bank_fallback(*why);
                // bank = sys_.GetWeapon(i): the LIVE children; None past
                // their end.
                const std::vector<int64_t>& kids = subrow(s_.sys)->_children;
                if (s_.i >= kids.size()) {
                    s_.st = St::BANK_NEXT;  // if bank is None: continue
                    break;
                }
                const int64_t bank = kids[s_.i];
                if (std::optional<K2Why> why = child_why(bank))
                    return bank_fallback(*why);
                s_.bank = bank;
                // target = bank._target          (read BEFORE IsFiring)
                s_.target = subrow(bank)->_target;
                s_.flush_dwell.reset();
                // if not bank.IsFiring():         (_firing, not IsBeamOn)
                if (!subrow(bank)->_firing) {
                    // dwell = bank.take_dwell(): `_dwell = 0.0` on every
                    // idle bank, every tick
                    const DwellResult d = take_dwell(m_, bank);
                    write_dwell(bank, d.new_dwell, /*idle=*/true);
                    s_.dwell = d.flushed;
                    // if dwell <= 0.0 or target is None or (hasattr(target,
                    //     "IsDead") and target.IsDead()): continue
                    if (s_.dwell <= 0.0 || s_.target == -1) {
                        s_.st = St::BANK_NEXT;
                        break;
                    }
                    bool dead;
                    try {
                        dead = ship_dead(m_, s_.target);
                    } catch (const std::invalid_argument&) {
                        return ask(K2Query::is_dead, {s_.target},
                                   St::IDLE_DEAD_ANSWER);
                    }
                    if (dead) {
                        s_.st = St::BANK_NEXT;
                        break;
                    }
                    // flush_dwell = dwell: no can_detect, no arc test
                    s_.flush_dwell = s_.dwell;
                    s_.st = St::SAME_SET;
                    break;
                }
                // else: if target is None or target.IsDead():
                //     bank.StopFiring(); continue
                if (s_.target == -1) {
                    if (bank_stop(bank)) {
                        s_.st = St::BANK_NEXT;
                        break;
                    }
                    return emit(K2Kind::BANK_STOP, St::BANK_NEXT, bank);
                }
                bool dead;
                try {
                    dead = ship_dead(m_, s_.target);
                } catch (const std::invalid_argument&) {
                    return ask(K2Query::is_dead, {s_.target},
                               St::FIRING_DEAD_ANSWER);
                }
                if (dead) {
                    if (bank_stop(bank)) {
                        s_.st = St::BANK_NEXT;
                        break;
                    }
                    return emit(K2Kind::BANK_STOP, St::BANK_NEXT, bank);
                }
                s_.st = St::DETECT;  // flush_dwell = None
                break;
            }
            case St::IDLE_DEAD_ANSWER:
                if (take_answer().flag) {
                    s_.st = St::BANK_NEXT;
                    break;
                }
                s_.flush_dwell = s_.dwell;
                s_.st = St::SAME_SET;
                break;
            case St::FIRING_DEAD_ANSWER:
                if (take_answer().flag) {
                    if (bank_stop(s_.bank)) {
                        s_.st = St::BANK_NEXT;
                        break;
                    }
                    return emit(K2Kind::BANK_STOP, St::BANK_NEXT, s_.bank);
                }
                s_.st = St::DETECT;
                break;

            // if flush_dwell is None and not can_detect(ship, target):
            //     bank.StopFiring(); continue
            // (only the IsFiring branch reaches here). The memo condition
            // and the two clocks are K1's (the Python's own native call).
            case St::DETECT: {
                bool ok;
                try {
                    ok = can_detect(m_, s_.ship, s_.target, s_.drift_now,
                                    s_.use_memo, std::nullopt, true,
                                    std::nullopt, s_.now);
                } catch (const std::invalid_argument&) {
                    return ask(K2Query::can_detect, {s_.ship, s_.target},
                               St::DETECT_ANSWER);
                }
                if (!ok) {
                    if (bank_stop(s_.bank)) {
                        s_.st = St::BANK_NEXT;
                        break;
                    }
                    return emit(K2Kind::BANK_STOP, St::BANK_NEXT, s_.bank);
                }
                s_.st = St::SAME_SET;
                break;
            }
            case St::DETECT_ANSWER:
                if (!take_answer().flag) {
                    if (bank_stop(s_.bank)) {
                        s_.st = St::BANK_NEXT;
                        break;
                    }
                    return emit(K2Kind::BANK_STOP, St::BANK_NEXT, s_.bank);
                }
                s_.st = St::SAME_SET;
                break;

            // if not _same_set(ship, target):   (weapon_subsystems.py:2248)
            //     if flush_dwell is None: bank.StopFiring()
            //     continue                      (a banked dwell is DROPPED)
            case St::SAME_SET: {
                const int64_t set_a = containing_set(s_.ship);
                const bool same =
                    set_a != -1 && set_a == containing_set(s_.target);
                if (!same) {
                    if (!s_.flush_dwell && !bank_stop(s_.bank))
                        return emit(K2Kind::BANK_STOP, St::BANK_NEXT, s_.bank);
                    s_.st = St::BANK_NEXT;
                    break;
                }
                s_.st = St::AIM;
                break;
            }

            // target_pos, target_sub = _phaser_aim_point(ship, target)
            case St::AIM: {
                try {
                    const AimPoint ap =
                        phaser_aim_point(m_, s_.ship, s_.target, s_.use_memo);
                    s_.target_pos = ap.point;
                    s_.has_sub = ap.target_sub != -1;
                    if (s_.has_sub) {
                        const ObjectRow* lo = owner_row(ap.target_sub);
                        if (lo && lo->has_posed_parts) ++c_.posed_lock_aims;
                    }
                } catch (const std::invalid_argument&) {
                    return ask(K2Query::aim_point, {s_.ship, s_.target},
                               St::AIM_ANSWER);
                }
                s_.st = St::GEOMETRY;
                break;
            }
            case St::AIM_ANSWER: {
                const K2Answer a = take_answer();
                s_.target_pos = a.point;
                s_.has_sub = a.flag;
                s_.st = St::GEOMETRY;
                break;
            }

            case St::GEOMETRY: {
                // emitter_pos = bank._strip_emit_position(target_pos)
                s_.emitter = strip_emit_position(m_, s_.bank, s_.target_pos,
                                                 s_.use_memo);
                if (objrow(s_.ship)->has_posed_parts) ++c_.posed_banks;
                // HL:1239-1243: dist = (dx*dx + dy*dy + dz*dz) ** 0.5;
                // aim_unit = TGPoint3(dx/dist, ...) if dist > 1e-6 else None
                const double dx = s_.target_pos[0] - s_.emitter[0];
                const double dy = s_.target_pos[1] - s_.emitter[1];
                const double dz = s_.target_pos[2] - s_.emitter[2];
                s_.dist = py_pow(dx * dx + dy * dy + dz * dz, 0.5);
                if (s_.dist > 1e-6)
                    s_.aim_unit = Vec3{dx / s_.dist, dy / s_.dist, dz / s_.dist};
                else
                    s_.aim_unit.reset();
                // arc_aim = _resolve_bank_aim_world(bank, target_sub or
                // target): computed on the flush path too (unused there).
                // A subsystem is always truthy; its GetWorldLocation is the
                // same pure call that made target_pos. With no lock it is the
                // TARGET's centre (Manual Aim's offset point is not).
                const Vec3 arc_point =
                    s_.has_sub ? s_.target_pos
                               : detail::world_location(
                                     m_, detail::obj(m_, s_.target));
                const Vec3 arc_aim = _resolve_bank_aim_world_at(
                    m_, s_.bank, arc_point, s_.use_memo);
                if (!s_.flush_dwell) {
                    // if not _emitter_in_arc(bank, ship, arc_aim):
                    if (!_emitter_in_arc(m_, s_.bank, s_.ship, arc_aim)) {
                        // flush_dwell = bank.take_dwell(); bank.StopFiring()
                        // -- and the partial pulse is still delivered.
                        const DwellResult d = take_dwell(m_, s_.bank);
                        write_dwell(s_.bank, d.new_dwell, /*idle=*/false);
                        s_.flush_dwell = d.flushed;
                        if (!bank_stop(s_.bank))
                            return emit(K2Kind::BANK_STOP, St::ARC_STOPPED,
                                        s_.bank);
                        s_.st = St::TRACE;  // the partial pulse, this tick
                        break;
                    }
                    // else: flush_dwell = bank.accumulate_dwell(dt)
                    const DwellResult d = accumulate_dwell(m_, s_.bank, s_.dt);
                    if (d.wrote) write_dwell(s_.bank, d.new_dwell, false);
                    s_.flush_dwell = d.flushed;
                }
                s_.st = St::TRACE;
                break;
            }
            case St::ARC_STOPPED:
                s_.st = St::TRACE;
                break;

            // impact_point, impact_normal = combat._resolve_hit_point(
            //     ship_instances=..., ship=target, ray_origin=emitter_pos,
            //     ray_direction=(aim_unit if dist > 1e-6 else None),
            //     max_dist=(dist * 1.5 if dist > 1e-6 else 0.0),
            //     fallback_point=target_pos)          -- BEFORE shields_block
            case St::TRACE: {
                static const TraceHooks kNoHost;
                const std::optional<Vec3>& dir = s_.aim_unit;  // HL:1266
                const double max_dist = s_.dist > 1e-6 ? s_.dist * 1.5 : 0.0;
                std::optional<InstanceId> iid;
                std::optional<Vec3> off;
                const TraceHooks* hooks = &ctx_.hooks;
                if (dir) {
                    const auto it = ctx_.iids.find(s_.target);
                    if (it != ctx_.iids.end()) {
                        // to_view = frames.view_offset(frames.containing_set(
                        //     ship)): only for a target with an instance.
                        const auto vo =
                            ctx_.view_offsets.find(containing_set(s_.target));
                        if (vo == ctx_.view_offsets.end())
                            return ask(K2Query::resolve_hit,
                                       {s_.target, s_.emitter, *dir, max_dist,
                                        s_.target_pos},
                                       St::TRACE_ANSWER);
                        off = vo->second;
                        iid = it->second.id;
                        // Not an InstanceId: host_io raises inside the try
                        // (or returns None with no host) -> the sphere tier.
                        if (it->second.bad) hooks = &kNoHost;
                    }
                }
                try {
                    s_.hit = resolve_hit_point(m_, *hooks, s_.target, iid,
                                               s_.emitter, dir, max_dist,
                                               s_.target_pos, off);
                } catch (const std::invalid_argument&) {
                    return ask(K2Query::resolve_hit,
                               {s_.target, s_.emitter,
                                dir ? K2Arg(*dir) : K2Arg(std::monostate{}),
                                max_dist, s_.target_pos},
                               St::TRACE_ANSWER);
                }
                s_.st = St::SHIELDS;
                break;
            }
            case St::TRACE_ANSWER: {
                const K2Answer a = take_answer();
                s_.hit.tier = a.tier;
                s_.hit.point = a.point;
                s_.hit.normal = a.normal;
                s_.st = St::SHIELDS;
                break;
            }

            // `aim_unit is not None and combat.shields_block(target)`
            case St::SHIELDS:
                s_.shields.reset();
                s_.shields_asked = false;
                if (s_.aim_unit) {
                    try {
                        s_.shields = shields_block(m_, s_.target,
                                                   ctx_.npc_shields_off,
                                                   ctx_.player);
                    } catch (const std::invalid_argument&) {
                        return ask(K2Query::shields_block, {s_.target},
                                   St::SHIELDS_ANSWER);
                    }
                }
                s_.st = St::BUBBLE;
                break;
            case St::SHIELDS_ANSWER:
                s_.shields = take_answer().flag;
                s_.shields_asked = true;
                s_.st = St::BUBBLE;
                break;

            // combat.shield_bubble_entry(target, emitter_pos, aim_unit,
            //     dist * 1.5)                         (HL:1277: 1.5)
            case St::BUBBLE: {
                s_.bubble.reset();
                if (s_.aim_unit && *s_.shields) {
                    const std::vector<K2Arg> args{s_.target, s_.emitter,
                                                  *s_.aim_unit, s_.dist * 1.5};
                    // _hull_box_for of anything but a ShipClass is Python's.
                    // detail::obj: the row may have gone while Python
                    // answered the shields_block ASK (unexpected()).
                    if (!detail::obj(m_, s_.target).is_ship_class)
                        return ask(K2Query::bubble, args, St::BUBBLE_ANSWER);
                    try {
                        s_.bubble = shield_bubble_entry(
                            m_, s_.target, s_.emitter, *s_.aim_unit,
                            s_.dist * 1.5);
                    } catch (const std::invalid_argument&) {
                        return ask(K2Query::bubble, args, St::BUBBLE_ANSWER);
                    }
                }
                if (queue_contact() || pulse()) break;
                return contact();
            }
            case St::BUBBLE_ANSWER: {
                const K2Answer a = take_answer();
                if (a.none)
                    s_.bubble.reset();
                else
                    s_.bubble = a.point;
                if (queue_contact() || pulse()) break;
                return contact();
            }

            case St::BANK_STEP_ANSWER:
                take_answer();
                s_.st = St::BANK_NEXT;
                break;
            case St::BANK_NEXT:
                ++s_.i;
                s_.in_bank = false;
                s_.st = St::BANK_FOR;
                break;
            case St::SHIP_NEXT:
                ++s_.ship_pos;
                s_.ship_active = false;
                s_.in_bank = false;
                s_.st = St::SHIP_FOR;
                break;
            case St::DONE:
                lost("the session already returned DONE");
            }
        } catch (const std::invalid_argument& e) {
            return unexpected(e);
        }
    }
}

}  // namespace

// ── K2Kernel ─────────────────────────────────────────────────────────────────

K2Kernel::K2Kernel(Mirror& m) : m_(m) {}
K2Kernel::~K2Kernel() = default;

void K2Kernel::clear() { session_.reset(); }

void K2Kernel::begin(std::vector<int64_t> ships, double dt, double now,
                     bool use_memo, double drift_now, K2Context ctx,
                     bool keep_iids) {
    if (session_) lost("a session is already open");
    if (keep_iids) ctx.iids = std::move(ctx_.iids);
    auto s = std::make_unique<Session>();
    s->ships = std::make_shared<const std::vector<int64_t>>(std::move(ships));
    s->dt = dt;
    s->now = now;
    s->use_memo = use_memo;
    s->drift_now = drift_now;
    s->st = St::SHIP_FOR;
    ctx_ = std::move(ctx);
    session_ = std::move(s);
}

void K2Kernel::set_context(K2Context ctx) { ctx_ = std::move(ctx); }

K2Record K2Kernel::next() {
    if (!session_) lost("no session is open");
    Session& s = *session_;
    if (s.awaiting_answer && !s.has_answer)
        lost("ASK has no answer (combat_k2_answer)");
    // A throw must leave the session and the mirror as they were: the
    // pending answer kept, every unflushed write undone (mirror == Python),
    // the queue cut back to what earlier calls queued, so abandon() -- or a
    // retry -- starts from a consistent state. The queue grows all step:
    // the backup leaves it out (moved aside), so it is never copied.
    const size_t rest_mark = s.rests.size();
    std::vector<K2Rest> rests = std::move(s.rests);
    s.rests.clear();
    Session before = s;
    s.rests = std::move(rests);
    s.awaiting_answer = false;
    s.has_answer = false;
    try {
        Walker w(m_, s, ctx_, counts_);
        K2Record r = w.run();
        hits_returned_ += static_cast<int64_t>(r.hits.size());
        return r;
    } catch (...) {
        k2_roll_back(m_, s, 0, 0, 0);
        rests = std::move(s.rests);
        rests.resize(rest_mark);
        s = std::move(before);
        s.rests = std::move(rests);
        throw;
    }
}

K2Query K2Kernel::awaiting() const {
    if (!session_ || !session_->awaiting_answer || session_->has_answer)
        return K2Query::kCount;
    return session_->pending;
}

void K2Kernel::answer(const K2Answer& a) {
    if (!session_ || !session_->awaiting_answer || session_->has_answer)
        lost("no ASK is waiting for an answer");
    session_->answer = a;
    session_->has_answer = true;
}

void K2Kernel::end() {
    if (!session_) lost("no session is open");
    if (session_->st != St::DONE) lost("the session has not returned DONE");
    session_.reset();
}

void K2Kernel::abandon() {
    if (!session_) lost("no session is open");
    session_.reset();
}

const std::vector<K2Rest>& K2Kernel::rests() const {
    static const std::vector<K2Rest> kNone;
    return session_ ? session_->rests : kNone;
}

std::vector<K2Rest> K2Kernel::take_rests() {
    if (!session_) return {};
    if (session_->st != St::DONE) lost("the session has not returned DONE");
    return std::exchange(session_->rests, {});
}

K2Kernel& k2_kernel() {
    static K2Kernel k(mirror());
    return k;
}

}  // namespace dauntless::combat
