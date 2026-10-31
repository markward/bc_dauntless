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
#include "dauntless/combat/fire_gates.h"
#include "dauntless/combat/py_math.h"
#include "dauntless/combat/sensor_detect.h"
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
        "stale_row",      "stub_or_unplaced", "gate",     "other"};
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

// The mirror value one logged `_dwell` write replaced.
struct K2Undo {
    int64_t bank = -1;
    double value = 0.0;
};

struct K2Kernel::Session {
    // Shared, so next()'s per-call backup of the session copies no list.
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

    // The bank's locals.
    bool in_bank = false;
    bool bank_recorded = false;
    size_t bank_mark = 0;
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
    std::optional<Vec3> bubble;

    // The write log since the last record, and, one for one, the value each
    // write replaced (rolled back if the writes never reach Python).
    std::vector<K2Write> writes;
    std::vector<K2Undo> undo;
    bool awaiting_answer = false, has_answer = false;
    K2Query pending = K2Query::kCount;
    K2Answer answer;
};

// Undo the session's logged writes from `mark` on, newest first, and drop
// them from the log: they never reached Python.
static void k2_roll_back(Mirror& m, K2Kernel::Session& s, size_t mark) {
    while (s.undo.size() > mark) {
        const K2Undo& u = s.undo.back();
        m.set_f(u.bank, Field::_dwell, u.value);
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
        s_.undo.push_back(K2Undo{bank, old});
        m_.set_f(bank, Field::_dwell, v);
        s_.writes.push_back(K2Write{bank, "_dwell", v});
    }

    // ── Records ─────────────────────────────────────────────────────────────
    K2Record emit(K2Kind kind, St next, int64_t a = -1, int64_t b = -1) {
        K2Record r;
        r.kind = kind;
        r.a = a;
        r.b = b;
        r.writes = std::move(s_.writes);
        s_.writes.clear();
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
        k2_roll_back(m_, s_, s_.ship_mark);
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
        k2_roll_back(m_, s_, s_.bank_mark);
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

    // ── The pre-scan (ruling H, stage 1) ───────────────────────────────────
    std::optional<K2Why> ship_why() const;
    std::optional<K2Why> child_why(int64_t bank) const;
    std::optional<K2Why> prescan() const;

    K2Record contact();

    Mirror& m_;
    Session& s_;
    const K2Context& ctx_;
    K2Kernel::Counts& c_;
};

// What every bank's walk reads of the ship and the system: a placed ShipClass
// at its NIF pose (the strip centre and the arc mount carry its pose), in a
// nameable set, and the system's row.
std::optional<K2Why> Walker::ship_why() const {
    const ObjectRow* so = objrow(s_.ship);
    if (!so) return K2Why::StaleRow;
    if (!so->is_ship_class) return K2Why::NotShipClass;
    if (!xform_ok(m_, *so)) return K2Why::StubOrUnplaced;
    if (so->has_posed_parts) return K2Why::PosedShip;
    if (!set_ok(m_, so->_containing_set)) return K2Why::StaleRow;
    if (!subrow(s_.sys)) return K2Why::StaleRow;
    return std::nullopt;
}

// One child: a live, unoverridden PhaserBank of this ship, and its `_target`
// None or a placed Object in a nameable set. The target's IsDead, its lock,
// its shields and its instance are per-bank ASKs, not fallbacks.
std::optional<K2Why> Walker::child_why(int64_t bank) const {
    const SubsystemRow* b = subrow(bank);
    if (!b) return K2Why::StaleRow;
    if (b->weapon_kind != kPhaserBank) return K2Why::Other;
    if (b->k1_overridden) return K2Why::Overridden;
    try {
        if (climb_to_ship_of(m_, bank) != s_.ship) return K2Why::Other;
    } catch (const std::invalid_argument&) {
        return K2Why::StaleRow;
    }
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

// The bank's CONTACT: everything beam_contact / apply_hit take that the
// kernel decided. Python does the damage arithmetic.
K2Record Walker::contact() {
    K2Contact c;
    c.bank = s_.bank;
    c.target = s_.target;
    c.ship = s_.ship;
    c.system = s_.sys;
    c.emitter = s_.emitter;
    c.target_pos = s_.target_pos;
    c.dist = s_.dist;
    c.aim_unit = s_.aim_unit;
    c.hit = s_.hit;
    c.bubble = s_.bubble;
    c.shields_block = s_.shields;
    c.flush_dwell = *s_.flush_dwell;
    K2Record r = emit(K2Kind::CONTACT, St::BANK_NEXT);
    r.contact = std::move(c);
    return r;
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
                if (sr->k1_overridden) return run_python(K2Why::Overridden);
                s_.sys = sys;
                // if _is_offline(sys_) or not sys_.IsOn():
                //     sys_.StopFiring(); continue      (EVERY tick)
                bool stop;
                try {
                    stop = weapon_system_offline(m_, sys) || !sr->_is_on;
                } catch (const std::invalid_argument&) {
                    return run_python(K2Why::Gate);
                }
                if (stop)
                    return emit(K2Kind::SYSTEM_STOP, St::SHIP_NEXT, sys);
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
                if (s_.target == -1)
                    return emit(K2Kind::BANK_STOP, St::BANK_NEXT, bank);
                bool dead;
                try {
                    dead = ship_dead(m_, s_.target);
                } catch (const std::invalid_argument&) {
                    return ask(K2Query::is_dead, {s_.target},
                               St::FIRING_DEAD_ANSWER);
                }
                if (dead) return emit(K2Kind::BANK_STOP, St::BANK_NEXT, bank);
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
                if (take_answer().flag)
                    return emit(K2Kind::BANK_STOP, St::BANK_NEXT, s_.bank);
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
                if (!ok) return emit(K2Kind::BANK_STOP, St::BANK_NEXT, s_.bank);
                s_.st = St::SAME_SET;
                break;
            }
            case St::DETECT_ANSWER:
                if (!take_answer().flag)
                    return emit(K2Kind::BANK_STOP, St::BANK_NEXT, s_.bank);
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
                    if (!s_.flush_dwell)
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
                        return emit(K2Kind::BANK_STOP, St::ARC_STOPPED, s_.bank);
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
                    if (!objrow(s_.target)->is_ship_class)
                        return ask(K2Query::bubble, args, St::BUBBLE_ANSWER);
                    try {
                        s_.bubble = shield_bubble_entry(
                            m_, s_.target, s_.emitter, *s_.aim_unit,
                            s_.dist * 1.5);
                    } catch (const std::invalid_argument&) {
                        return ask(K2Query::bubble, args, St::BUBBLE_ANSWER);
                    }
                }
                return contact();
            }
            case St::BUBBLE_ANSWER: {
                const K2Answer a = take_answer();
                if (a.none)
                    s_.bubble.reset();
                else
                    s_.bubble = a.point;
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
                     bool use_memo, double drift_now, K2Context ctx) {
    if (session_) lost("a session is already open");
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
    // so abandon() -- or a retry -- starts from a consistent state.
    Session before = s;
    s.awaiting_answer = false;
    s.has_answer = false;
    try {
        Walker w(m_, s, ctx_, counts_);
        return w.run();
    } catch (...) {
        k2_roll_back(m_, s, 0);
        s = std::move(before);
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

K2Kernel& k2_kernel() {
    static K2Kernel k(mirror());
    return k;
}

}  // namespace dauntless::combat
