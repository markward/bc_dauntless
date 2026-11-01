// The K1 fire-control kernel -- see k1_fire_control.h. A resumable port of
//   engine/host_loop.py            _pump_held_weapons            (HL:984)
//   engine/appc/weapon_subsystems.py WeaponSystem.update_weapons (WS:1651)
//                                    WeaponSystem.try_fire_weapon (WS:1573)
// and the decision half of PhaserBank.Fire (WS:2644, the mixin's WS:865),
// PulseWeapon.Fire (WS:2852) and TorpedoTube.Fire (WS:3324). Line numbers are
// the current Python's. Each cursor state (enum St) is named after the
// Python line it stands for; Walker::run's switch reads top to bottom like
// the Python. Every float decision is made by weapon_geometry / fire_gates /
// sensor_detect, the Python-exact ports of Tasks 2-3 and phase 1a.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/k1_fire_control.h"

#include <algorithm>
#include <cstdint>
#include <iterator>
#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>

#include "dauntless/combat/fire_gates.h"
#include "dauntless/combat/part_pose.h"
#include "dauntless/combat/sensor_detect.h"
#include "dauntless/combat/weapon_geometry.h"

namespace dauntless::combat {

namespace {

// Subsystem weapon_kind codes (mirror.h).
constexpr int64_t kPhaserSystem = 1, kPulseSystem = 2, kTorpedoSystem = 4,
                  kPhaserBank = 5, kPulseWeapon = 6, kTorpedoTube = 8;

// The leaf kind a system of `kind` owns (PhaserBank under PhaserSystem...).
int64_t leaf_kind_of(int64_t kind) {
    switch (kind) {
        case kPhaserSystem: return kPhaserBank;
        case kPulseSystem: return kPulseWeapon;
        case kTorpedoSystem: return kTorpedoTube;
        default: return -1;
    }
}

// Python `a % n` for n > 0 (the sign of the divisor).
int64_t py_mod(int64_t a, int64_t n) {
    const int64_t r = a % n;
    return r < 0 ? r + n : r;
}

// `int(mask) & (1 << (g - 1))` for g >= 1, on Python's unbounded ints.
bool group_bit(int64_t mask, int64_t g) {
    const int64_t k = g - 1;
    if (k >= 63) return mask < 0;  // bit k of a two's-complement int64
    return ((mask >> k) & 1) != 0;
}

bool xform_ok(const Mirror& m, const ObjectRow& o) {
    if (o.xform_index < 0 || o.xform_gen < 0 ||
        o.xform_index > std::numeric_limits<uint32_t>::max() ||
        o.xform_gen > std::numeric_limits<uint32_t>::max())
        return false;
    return m.store().valid(static_cast<uint32_t>(o.xform_index),
                           static_cast<uint32_t>(o.xform_gen));
}

// Why a Fire decision went to Python (ASK fire): the posed-part fallbacks
// by their type (part_pose.h), anything else Other.
K1Why fire_ask_why(const std::invalid_argument& e) {
    if (dynamic_cast<const PartStale*>(&e)) return K1Why::PartStale;
    if (dynamic_cast<const MountUnknown*>(&e)) return K1Why::MountUnknown;
    if (dynamic_cast<const NoMount*>(&e)) return K1Why::NoMount;
    if (dynamic_cast<const OffsetOffMount*>(&e)) return K1Why::OffsetOffMount;
    return K1Why::Other;
}

}  // namespace

const char* k1_kind_name(K1Kind k) {
    static constexpr const char* kNames[] = {
        "DONE",      "WALK_START",  "STOP_SYSTEM", "RUN_PYTHON", "BANK_STOP",
        "FIRE",      "FIRE_FAILED", "FIRE_DUMB",   "ASK"};
    static_assert(std::size(kNames) == static_cast<size_t>(K1Kind::kCount));
    const auto i = static_cast<size_t>(k);
    return i < std::size(kNames) ? kNames[i] : "?";
}

const char* k1_why_name(K1Why w) {
    static constexpr const char* kNames[] = {
        "self_managed",   "overridden",       "instance_patch",
        "posed_ship",     "posed_target",     "part_stale",
        "mount_unknown",  "no_mount",         "offset_off_mount",
        "stub_or_unplaced",
        "pulse_ship_target", "pulse_module",  "ammo_row",
        "stale_row",      "unslotted_ship",   "gate",
        "other"};
    static_assert(std::size(kNames) == static_cast<size_t>(K1Why::kCount));
    const auto i = static_cast<size_t>(w);
    return i < std::size(kNames) ? kNames[i] : "?";
}

// ── The cursor ───────────────────────────────────────────────────────────────

enum class St : int32_t {
    // host_loop._pump_held_weapons
    PUMP_FOR_GETTER,   // for ship in ships_list: for getter in (...):
                       //     sys_ = getattr(ship, getter)(); the gates
    PUMP_CONTINUE,     // continue  (the next getter, then the next ship)
    // StartFiring's `self.update_weapons(0.0)`
    SYSTEM_START,
    // WeaponSystem.update_weapons
    UW_DEAD_PRUNE,     // if ship ... ship.IsDead(): return False
                       // self._prune_targets(); target = self._target_list[0]
    UW_OFFSET,         // offset = self._live_held_offset(); groups = ...;
                       // working = ...; base_idx = ...; if self._single_fire:
                       //     lit = self._firing_weapon()
    UW_LIT_RETURN,     // self._force_update = False; return bool(lit.IsFiring())
    UW_WHILE,          // while True: self.SetGroupFireMode(working);
                       //     n = self.GetNumWeapons(); fired_this_group = False
    UW_FOR_DELTA,      // for delta in range(1, n + 1): idx = ...;
                       //     weapon = self.GetWeapon(idx); IsMemberOfGroup
    UW_MEMBER_ANSWER,  //     (ASK is_member answered)
    UW_STEP_ANSWER,    //     (ASK group_step answered)
    UW_TRIED,          //     if self.try_fire_weapon(...): ... else:
                       //         weapon._target = None; FireDumb
    UW_RESEED_ANSWER,  //     self._reseed_all_fire_timers() (ASK answered); break
    UW_NEXT_DELTA,     //     (after weapon.FireDumb(0, 1)) the next delta
    UW_DUMB_ANSWER,    //     (ASK is_dumb answered: the weapon's row is gone)
    UW_GROUP_ADVANCE,  // if fired_this_group or len(groups) <= 1: break;
                       // working = groups[...]; if working == start_group: ...
    UW_EXIT,           // self._force_update = False; return did_fire
    WALK_END,          // back to the pump, or the system session is done
    // WeaponSystem.try_fire_weapon
    TF_TIMER,          // _fire_timer = ...; if not IsFiring() and _fire_timer
                       // < FIRE_TIMER_THRESHOLD: return False; _fire_timer =
                       // 0.0; if not weapon.CanFire():
    TF_CANFIRE_ANSWER, //     (ASK can_fire answered)
    TF_STOPPED,        //     weapon.StopFiring(); return False
    TF_FIRE,           // result = weapon.Fire(target, offset)  [or entry]
    TF_FIRED,          // if self._weapon_did_fire(...): return True
    TF_FIRE_FALSE,     // (after FIRE_FAILED) Fire returned False
    TF_FIRE_ANSWER,    // (ASK fire answered) _weapon_did_fire's answer
    TF_NOT_FIRED,      // weapon._target = None; for entry in
                       // list(self._target_list):   [or the next entry]
    TF_RETRY_NEXT,     //     if entry is None or entry.IsDead(): continue;
                       //     result = weapon.Fire(entry, offset)
    TF_DEAD_ANSWER,    //     (ASK is_dead answered)
    TF_RETRY_ANSWER,   // (ASK retry answered) the whole retry loop's answer
    DONE,              // returned DONE; only end() / abandon() may follow
};

enum class Caller : int32_t { Lit, Delta };

// The mirror value one logged write replaced.
struct K1Undo {
    enum class Type : int32_t { F, I, Ref, Ids, Offset } type = Type::F;
    int64_t h = -1;
    Field f = Field::kCount;
    double d = 0.0;
    int64_t i = 0;
    std::vector<int64_t> ids;
    bool set = false;
    Vec3 v{0, 0, 0};
};

struct K1Kernel::Session {
    bool pump = false;
    // Shared, so next()'s per-call backup of the session copies no list.
    std::shared_ptr<const std::vector<int64_t>> ships;
    double dt = 0.0, now = 0.0, drift_now = 0.0;
    bool use_memo = false;
    St st = St::PUMP_FOR_GETTER;

    // Pump cursor: ships[ship_pos], getter kGetters[getter].
    size_t ship_pos = 0;
    int getter = 0;

    // update_weapons' locals.
    int64_t sys = -1;
    int64_t ship = -1;  // self.GetParentShip()
    int64_t target = -1;
    std::optional<Vec3> offset;
    std::vector<int64_t> groups;
    int64_t working = 0, start_group = 0, base_idx = 0;
    bool did_fire = false, fired_this_group = false;
    int64_t n = 0, delta = 0, idx = 0, weapon = -1;

    // try_fire_weapon's locals.
    Caller caller = Caller::Delta;
    int64_t tf_weapon = -1;
    bool tf_result = false;
    bool in_retry = false;
    int64_t fire_target = -1;
    std::vector<int64_t> retry;
    size_t retry_pos = 0;

    // The write log since the last record, and, one for one, the mirror
    // value each write replaced (rolled back if the walk throws before the
    // writes reach Python).
    std::vector<K1Write> writes;
    std::vector<K1Undo> undo;
    bool awaiting_offset = false;
    bool awaiting_answer = false, has_answer = false;
    std::optional<int64_t> answer;
};

static void count_why(K1Kernel::Counts& c, bool pump, K1Why why) {
    (pump ? c.pump_why : c.system_why)[static_cast<size_t>(why)] += 1;
}

static K1Undo undo_of(K1Undo::Type type, int64_t h, Field f) {
    K1Undo u;
    u.type = type;
    u.h = h;
    u.f = f;
    return u;
}

// Undo the session's logged writes from `mark` on, newest first, and drop
// them from the log: they never reached Python.
static void k1_roll_back(Mirror& m, K1Kernel::Session& s, size_t mark) {
    while (s.undo.size() > mark) {
        const K1Undo& u = s.undo.back();
        switch (u.type) {
            case K1Undo::Type::F: m.set_f(u.h, u.f, u.d); break;
            case K1Undo::Type::I: m.set_i(u.h, u.f, u.i); break;
            case K1Undo::Type::Ref: m.set_ref(u.h, u.f, u.i); break;
            case K1Undo::Type::Ids: m.set_ids(u.h, u.f, u.ids); break;
            case K1Undo::Type::Offset:
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

using Session = K1Kernel::Session;

[[noreturn]] void lost(const char* why) {
    throw std::logic_error(std::string("combat K1: ") + why);
}

// One next() call: runs the cursor to the next record.
class Walker {
public:
    Walker(Mirror& m, Session& s, K1Kernel::Counts& c) : m_(m), s_(s), c_(c) {}

    K1Record run();

private:
    // ── Row access ──────────────────────────────────────────────────────────
    const SubsystemRow* subrow(int64_t h) const {
        return h < 0 ? nullptr : m_.subsystem(h);
    }
    const ObjectRow* objrow(int64_t h) const {
        return h < 0 ? nullptr : m_.object(h);
    }
    // The walked system's row; a system freed mid-walk cannot be followed.
    const SubsystemRow& sysrow() const {
        const SubsystemRow* r = subrow(s_.sys);
        if (!r) lost("the walked system's row is gone");
        return *r;
    }
    // A child the walk can drive natively: a live row of the system's leaf
    // kind.
    bool named_leaf(int64_t h) const {
        const SubsystemRow* r = subrow(h);
        return r && r->weapon_kind == leaf_kind_of(sysrow().weapon_kind);
    }

    // ── The write log: made in the mirror, logged for Python ───────────────
    void log(int64_t h, const char* field, K1Value v) {
        s_.writes.push_back(K1Write{h, field, std::move(v)});
    }
    // Every write reads the value it replaces first (a gone row throws there,
    // before anything is changed), writes the mirror, then logs.
    void write_timer(int64_t h, double v) {
        K1Undo u = undo_of(K1Undo::Type::F, h, Field::_fire_timer);
        u.d = m_.get_f(h, Field::_fire_timer);
        m_.set_f(h, Field::_fire_timer, v);
        s_.undo.push_back(std::move(u));
        log(h, "_fire_timer", v);
    }
    void write_i(int64_t h, Field f, const char* name, int64_t v, K1Value lv) {
        K1Undo u = undo_of(K1Undo::Type::I, h, f);
        u.i = m_.get_i(h, f);
        m_.set_i(h, f, v);
        s_.undo.push_back(std::move(u));
        log(h, name, std::move(lv));
    }
    void write_flag(int64_t h, Field f, const char* name, bool v) {
        write_i(h, f, name, v ? 1 : 0, v);
    }
    void write_int(int64_t h, Field f, const char* name, int64_t v) {
        write_i(h, f, name, v, v);
    }
    void write_target(int64_t h, int64_t t) {
        // A bank whose row a handler dropped mid-walk (an unencodable value)
        // is still Python's object, pinned by run_k1: the write goes to
        // Python only. There is no row to write, so nothing to undo.
        if (!subrow(h)) {
            log(h, "_target", t);
            return;
        }
        K1Undo u = undo_of(K1Undo::Type::Ref, h, Field::_target);
        u.i = m_.get_ref(h, Field::_target);  // a stale ref reads -1
        m_.set_ref(h, Field::_target, t);
        s_.undo.push_back(std::move(u));
        log(h, "_target", t);
    }
    void write_target_list(int64_t h, std::vector<int64_t> v) {
        K1Undo u = undo_of(K1Undo::Type::Ids, h, Field::_target_list);
        const SubsystemRow* r = subrow(h);
        if (!r) lost("the walked system's row is gone");
        u.ids = r->_target_list;  // raw: stale entries kept as they were
        m_.set_ids(h, Field::_target_list, v);
        s_.undo.push_back(std::move(u));
        log(h, "_target_list", std::move(v));
    }
    // `_target_offset = offset` (the walk's offset object, ruling P5) or None.
    void write_target_offset(int64_t h, bool walk_offset) {
        K1Undo u = undo_of(K1Undo::Type::Offset, h, Field::_target_offset);
        const SubsystemRow* r = subrow(h);
        if (!r) lost("bank row is gone");
        u.set = r->target_offset_set;
        u.v = r->_target_offset;
        s_.undo.push_back(std::move(u));
        if (walk_offset) {
            const Vec3& o = *s_.offset;
            m_.set_fv(h, Field::_target_offset, {o[0], o[1], o[2]});
            log(h, "_target_offset", std::string("walk_offset"));
        } else {
            m_.set_fv(h, Field::_target_offset, {});
            log(h, "_target_offset", std::monostate{});
        }
    }

    // ── Records ─────────────────────────────────────────────────────────────
    K1Record emit(K1Kind kind, St next, int64_t a = -1, int64_t b = -1,
                  int64_t c = -1) {
        K1Record r;
        r.kind = kind;
        r.a = a;
        r.b = b;
        r.c = c;
        r.writes = std::move(s_.writes);
        s_.writes.clear();
        s_.undo.clear();  // delivered: Python applies them
        s_.st = next;
        ++c_.records;
        if (kind == K1Kind::RUN_PYTHON) ++c_.python_systems;
        return r;
    }
    // A whole system handed to Python, counted by why (pump or system).
    K1Record run_python(K1Why why, St next, int64_t a, int64_t b, int64_t c) {
        count_why(c_, s_.pump, why);
        return emit(K1Kind::RUN_PYTHON, next, a, b, c);
    }
    K1Record ask(const char* query, std::vector<int64_t> args, St next) {
        K1Record r = emit(K1Kind::ASK, next);
        r.query = query;
        r.args = std::move(args);
        s_.awaiting_answer = true;
        s_.has_answer = false;
        ++c_.asks;
        return r;
    }
    int64_t take_answer() {
        const int64_t v = s_.answer.value_or(0);
        s_.answer.reset();
        return v;
    }

    // ── The pre-scan (ruling H, stage 1) ───────────────────────────────────
    // nullopt: the walk can run natively; else why it cannot.
    std::optional<K1Why> prescan(int64_t sys, int64_t pump_ship) const;
    // The pump's gates: true = StopFiring. Throws std::invalid_argument when
    // the mirror cannot answer (the system then runs in Python).
    bool pump_stops(int64_t sys, int64_t pump_ship);

    // ── Walk pieces ─────────────────────────────────────────────────────────
    std::vector<int64_t> active_chain_groups() const;
    void begin_try(int64_t weapon, Caller caller) {
        s_.tf_weapon = weapon;
        s_.caller = caller;
        s_.in_retry = false;
        s_.st = St::TF_TIMER;
    }
    void try_returns(bool result) {
        s_.tf_result = result;
        s_.st = s_.caller == Caller::Lit ? St::UW_LIT_RETURN : St::UW_TRIED;
    }
    void next_delta() {
        ++s_.delta;
        s_.st = St::UW_FOR_DELTA;
    }
    // The success branch of the delta loop; may emit ASK reseed.
    bool fired_bookkeeping(K1Record* out);

    struct Outcome {
        enum class What { Fire, FailedEvent, Fail } what = What::Fail;
        K1Decision d;
    };
    Outcome decide(int64_t bank, int64_t target);
    // A Fire decision aimed natively at a posed target's offset (the bank's
    // stored _target_offset) -- counted once its aim was made.
    void count_posed_aim(int64_t bank, int64_t target) {
        const ObjectRow* t = target == -1 ? nullptr : objrow(target);
        const SubsystemRow* b = subrow(bank);
        if (t && b && t->has_posed_parts && !t->_dead && b->target_offset_set)
            ++c_.posed_target_aims;
    }
    Outcome decide_beam(int64_t bank, int64_t target);
    Outcome decide_pulse(int64_t bank, int64_t target);
    Outcome decide_tube(int64_t bank, int64_t target);

    Mirror& m_;
    Session& s_;
    K1Kernel::Counts& c_;
};

// Everything the system's walk can read must be representable before its
// first write (plan P2 / ruling H): the system and every child row, the parent
// ship, every target-list entry (and, in the pump, the held target), a real
// IsDead on each, a current part slot for every leaf of a posed ship (its
// mount), the ammo rows, the pulse module, and the chain table. A posed
// target's offset aim is decided in the walk (an ASK fire if the mirror
// cannot: its slot went stale, its mount is unknown or none).
std::optional<K1Why> Walker::prescan(int64_t sys,
                                     int64_t pump_ship) const {
    const SubsystemRow* s = subrow(sys);
    if (!s) return K1Why::StaleRow;
    const int64_t kind = s->weapon_kind;
    // Phaser, pulse and torpedo walks only; a tractor manages itself.
    if (leaf_kind_of(kind) < 0 || s->pump_self_managed)
        return K1Why::SelfManaged;
    // A class overriding a method the kernel stands in for (Task 5 fix).
    if (s->k1_overridden) return K1Why::Overridden;

    // self.GetParentShip(): alive-testable, placed.
    int64_t ship;
    try {
        ship = climb_to_ship_of(m_, sys);
    } catch (const std::invalid_argument&) {
        return K1Why::StaleRow;
    }
    const ObjectRow* so = objrow(ship);
    if (!so) return K1Why::StaleRow;
    if (!so->has_real_is_dead) return K1Why::StubOrUnplaced;
    if (!xform_ok(m_, *so)) return K1Why::StubOrUnplaced;
    if (pump_ship != -1) {  // the pump's own `ship` (the range gate)
        const ObjectRow* po = objrow(pump_ship);
        if (!po) return K1Why::StaleRow;
        if (!xform_ok(m_, *po)) return K1Why::StubOrUnplaced;
        const int64_t held = s->_held_target;
        if (held != -1) {
            const ObjectRow* ho = objrow(held);
            if (!ho) return K1Why::StaleRow;
            if (!ho->has_real_is_dead || !xform_ok(m_, *ho))
                return K1Why::StubOrUnplaced;
            // The phaser range gate runs AFTER can_detect (which writes its
            // memo and latch): everything it reads must be answerable here,
            // so no gate can throw once a side-effecting one has run.
            // _same_set reads both containing sets.
            auto set_ok = [&](int64_t h) {
                return h == -1 || (h >= 0 && m_.set(h) != nullptr);
            };
            if (kind == kPhaserSystem &&
                (!set_ok(po->_containing_set) || !set_ok(ho->_containing_set)))
                return K1Why::StaleRow;
        }
    }

    // _target_list: every entry is a placed Object with a real IsDead. (A
    // pulse or torpedo aim at a posed target's offset is the walk's.)
    bool any_alive = false;
    for (const int64_t t : s->_target_list) {
        const ObjectRow* to = objrow(t);
        if (!to) return K1Why::StaleRow;
        if (!to->has_real_is_dead || !xform_ok(m_, *to))
            return K1Why::StubOrUnplaced;
        if (!to->_dead) any_alive = true;
    }
    // PulseWeapon.Fire(None) falls back to ship.GetTarget(), not mirrored.
    if (kind == kPulseSystem && !any_alive) return K1Why::PulseShipTarget;

    // GetFiringChains: the property (None reads []); group ids >= 0 (a
    // negative id raises in IsMemberOfGroup's shift).
    if (s->_property != -1) {
        const PropertyRow* p = m_.property(s->_property);
        if (!p) return K1Why::StaleRow;
        for (const auto& chain : p->_firing_chains)
            for (const int64_t g : chain)
                if (g < 0) return K1Why::Other;
    }

    // _children: rows of the system's leaf kind, under this system and ship.
    const int64_t leaf = leaf_kind_of(kind);
    for (const int64_t c : s->_children) {
        const SubsystemRow* w = subrow(c);
        if (!w) return K1Why::StaleRow;
        if (w->weapon_kind != leaf) return K1Why::Other;
        if (w->k1_overridden) return K1Why::Overridden;
        if (w->_parent_subsystem != sys) return K1Why::Other;
        try {
            if (climb_to_ship_of(m_, c) != ship) return K1Why::Other;
        } catch (const std::invalid_argument&) {
            return K1Why::StaleRow;
        }
        if (w->_property != -1 && !m_.property(w->_property))
            return K1Why::StaleRow;
        // A posed ship's leaf mount is read through its part slot
        // (mount_position): one that is not current is Python's.
        Vec3 local;
        if (so->has_posed_parts &&
            posed_local(m_, *so, *w, &local) == SlotState::stale)
            return K1Why::PartStale;
        if (leaf == kPulseWeapon &&
            (!w->module_ok || w->_power_setting < 0 || w->_power_setting > 2))
            return K1Why::PulseModule;
    }

    // TorpedoSystem._ammo_by_slot: [slot, Ammo handle, ...]; -1 is a slot
    // holding None, which the tube gate answers (never exhausted).
    if (kind == kTorpedoSystem) {
        const auto& slots = s->_ammo_by_slot;
        for (size_t i = 1; i < slots.size(); i += 2)
            if (slots[i] != -1 && !m_.ammo(slots[i])) return K1Why::AmmoRow;
    }
    return std::nullopt;
}

// host_loop._pump_held_weapons (HL:1006-1020), the gates after the
// self-managed hand-off, in order.
bool Walker::pump_stops(int64_t sys, int64_t pump_ship) {
    const SubsystemRow& s = *subrow(sys);
    // if _is_offline(sys_) or not sys_.IsOn(): sys_.StopFiring()
    if (weapon_system_offline(m_, sys) || !s._is_on) return true;
    const int64_t held = s._held_target;
    // if held is not None and (hasattr(held, "IsDead") and held.IsDead())
    if (held != -1 && ship_dead(m_, held)) return true;
    // if held is not None and _target_undetectable(sys_, held): the firing
    // ship is sys_.GetParentShip(); can_detect's drift clock is drift_now,
    // its occlusion clock the Utopia game time (the weapons' `now`).
    if (held != -1) {
        const int64_t ship = climb_to_ship_of(m_, sys);
        if (ship != -1 &&
            !can_detect(m_, ship, held, s_.drift_now, s_.use_memo,
                        std::nullopt, true, std::nullopt, s_.now))
            return true;
    }
    // if held is not None and hasattr(sys_, "_can_engage") and not
    // sys_._can_engage(ship, held): PhaserSystem's PHASER_MAX_RANGE_GU gate
    // on the PUMP's ship; PulseWeaponSystem's is True; TorpedoSystem has no
    // _can_engage (TGObject.__getattr__ refuses underscore names).
    if (held != -1 && s.weapon_kind == kPhaserSystem &&
        !_target_within_range_gu(m_, pump_ship, held,
                                 m_.globals().PHASER_MAX_RANGE_GU))
        return true;
    return false;
}

// WeaponSystem._active_chain_groups (WS:1386) via GetFiringChains (WS:1368).
std::vector<int64_t> Walker::active_chain_groups() const {
    const SubsystemRow& s = sysrow();
    const PropertyRow* p = s._property == -1 ? nullptr : m_.property(s._property);
    if (!p || p->_firing_chains.empty()) return {0};
    const auto& chains = p->_firing_chains;
    const auto& groups = chains[static_cast<size_t>(
        py_mod(s._firing_chain_mode, static_cast<int64_t>(chains.size())))];
    if (groups.empty()) return {0};
    return groups;
}

// update_weapons (WS:1700-1707): did_fire = fired_this_group = True;
// self._last_weapon_idx = idx; self._last_group_fired = working;
// if self._single_fire: self._reseed_all_fire_timers(); break.
// Returns true when it emitted a record into *out.
bool Walker::fired_bookkeeping(K1Record* out) {
    s_.did_fire = s_.fired_this_group = true;
    write_int(s_.sys, Field::_last_weapon_idx, "_last_weapon_idx", s_.idx);
    write_int(s_.sys, Field::_last_group_fired, "_last_group_fired", s_.working);
    if (!sysrow()._single_fire) {
        next_delta();
        return false;
    }
    // _reseed_all_fire_timers (WS:1620): every child's _fire_timer = 0.0.
    const std::vector<int64_t> kids = sysrow()._children;
    for (const int64_t c : kids) {
        if (!named_leaf(c)) {
            *out = ask("reseed", {s_.sys}, St::UW_RESEED_ANSWER);
            return true;
        }
    }
    for (const int64_t c : kids) write_timer(c, 0.0);
    s_.st = St::UW_GROUP_ADVANCE;  // break
    return false;
}

// ── The decision half of each Fire ───────────────────────────────────────────

Walker::Outcome Walker::decide(int64_t bank, int64_t target) {
    const SubsystemRow* b = subrow(bank);
    if (!b) throw std::invalid_argument("combat K1: bank row is gone");
    switch (b->weapon_kind) {
        case kPhaserBank: return decide_beam(bank, target);
        case kPulseWeapon: return decide_pulse(bank, target);
        case kTorpedoTube: return decide_tube(bank, target);
        default: throw std::invalid_argument("combat K1: not a K1 leaf");
    }
}

// PhaserBank.Fire (WS:2644) -> _EnergyWeaponFireMixin.Fire (WS:865):
// if not self.CanFire(): return False; if not self._aim_in_arc(target):
// return False. Decision: (was_firing,).
Walker::Outcome Walker::decide_beam(int64_t bank, int64_t target) {
    Outcome o;
    const CanFireResult cf = can_fire(m_, bank, s_.now);
    if (cf.clear_depleted) write_flag(bank, Field::_depleted, "_depleted", false);
    if (!cf.ok) return o;
    // _aim_in_arc (WS:800): the target CENTRE from the mount, else forward.
    const int64_t ship = climb_to_ship_of(m_, bank);
    const Vec3 aim = target != -1
                         ? _resolve_bank_aim_world(m_, bank, target, s_.use_memo)
                         : _resolve_aim_world(m_, ship, -1);
    if (!_emitter_in_arc(m_, bank, ship, aim)) return o;
    o.what = Outcome::What::Fire;
    o.d.shape = K1Decision::Shape::Beam;
    o.d.was_firing = subrow(bank)->_firing != 0;
    return o;
}

// PulseWeapon.Fire (WS:2852-2899), up to the spawn. Decision:
// (world_dir_xyz, target_used).
Walker::Outcome Walker::decide_pulse(int64_t bank, int64_t target) {
    Outcome o;
    // if not self.CanFire(): return False  (a reported latch clear is
    // written first, as decide_beam; the pulse gate never reports one today)
    const CanFireResult cf = can_fire(m_, bank, s_.now);
    if (cf.clear_depleted) write_flag(bank, Field::_depleted, "_depleted", false);
    if (!cf.ok) return o;
    // script / importlib.import_module(script): resolved by Python (P6); a
    // missing one prints an announcement only Python can make.
    if (!subrow(bank)->module_ok)
        throw std::invalid_argument("combat K1: pulse module unresolved");
    const int64_t ship = climb_to_ship_of(m_, bank);
    int64_t t = target;
    // if target is None: target = self._target
    if (t == -1) {
        t = subrow(bank)->_target;
        if (t == kRefUnrepresentable || (t >= 0 && !objrow(t)))
            throw std::invalid_argument("combat K1: cannon _target unnamed");
    }
    // if target is None and ship is not None and hasattr(ship, "GetTarget"):
    //     target = ship.GetTarget()     -- not mirrored
    if (t == -1 && ship != -1)
        throw std::invalid_argument("combat K1: ship.GetTarget() fallback");
    // if target is not None and hasattr(target, "IsDead") and target.IsDead()
    if (t != -1 && ship_dead(m_, t)) t = -1;
    if (t != -1) {
        // self._target = target; self._target_offset = offset if
        // isinstance(offset, TGPoint3) else None -- BEFORE the arc test.
        write_target(bank, t);
        write_target_offset(bank, s_.offset.has_value());
        const std::optional<Vec3> dir =
            _solve_pulse_launch_direction(m_, bank, ship, t, s_.use_memo);
        count_posed_aim(bank, t);
        if (!dir || !_emitter_in_arc(m_, bank, ship, *dir)) return o;
        o.d.world_dir = *dir;
    } else {
        // self._target = None; self._target_offset = None;
        // world_dir = _emitter_forward_world(self, ship)
        write_target(bank, -1);
        write_target_offset(bank, false);
        o.d.world_dir = _emitter_forward_world(m_, bank, ship);
    }
    o.what = Outcome::What::Fire;
    o.d.shape = K1Decision::Shape::Pulse;
    o.d.target_used = t;
    return o;
}

// TorpedoTube.Fire (WS:3324-3351), up to the stamp. Decision: (target_used,).
Walker::Outcome Walker::decide_tube(int64_t bank, int64_t target) {
    Outcome o;
    // As decide_beam (the tube gate never reports a latch clear today).
    const CanFireResult cf = can_fire(m_, bank, s_.now);
    if (cf.clear_depleted) write_flag(bank, Field::_depleted, "_depleted", false);
    if (!cf.ok) return o;
    if (target != -1) {
        // aim_point = _resolve_torpedo_aim_point(self, target): the tube's
        // STORED _target_offset (the previous shot's).
        const std::optional<Vec3> aim =
            _resolve_torpedo_aim_point(m_, bank, target);
        count_posed_aim(bank, target);
        if (!aim) {
            o.what = Outcome::What::FailedEvent;
            return o;
        }
        if (!_in_torpedo_cone(m_, bank, climb_to_ship_of(m_, bank), *aim,
                              s_.use_memo)) {
            o.what = Outcome::What::FailedEvent;
            return o;
        }
    }
    o.what = Outcome::What::Fire;
    o.d.shape = K1Decision::Shape::Tube;
    o.d.target_used = target;
    return o;
}

// ── The cursor loop ──────────────────────────────────────────────────────────

K1Record Walker::run() {
    for (;;) {
        switch (s_.st) {
        // ── host_loop._pump_held_weapons ──────────────────────────────────
        case St::PUMP_FOR_GETTER: {
            if (s_.ship_pos >= s_.ships->size())
                return emit(K1Kind::DONE, St::DONE);
            const int64_t ship = (*s_.ships)[s_.ship_pos];
            const int pos = static_cast<int>(s_.ship_pos);
            const ObjectRow* so = objrow(ship);
            // A ship the mirror cannot name: Python runs each getter's body.
            if (!so)
                return run_python(K1Why::UnslottedShip, St::PUMP_CONTINUE, -1,
                                  pos, s_.getter);
            // sys_ = getattr(ship, getter)() for getter in ("GetPhaserSystem",
            // "GetPulseWeaponSystem", "GetTractorBeamSystem",
            // "GetTorpedoSystem"); a stale ref reads None.
            int64_t sys = -1;
            switch (s_.getter) {
                case 0: sys = so->_phaser_system; break;
                case 1: sys = so->_pulse_weapon_system; break;
                case 2: sys = so->_tractor_beam_system; break;
                default: sys = so->_torpedo_system; break;
            }
            if (sys == kRefUnrepresentable)
                return run_python(K1Why::StaleRow, St::PUMP_CONTINUE, sys, pos,
                                  s_.getter);
            const SubsystemRow* sr = subrow(sys);
            // if sys_ is None or not getattr(sys_, "_fire_held", False): continue
            if (!sr || !sr->_fire_held) {
                s_.st = St::PUMP_CONTINUE;
                break;
            }
            // if getattr(sys_, "_pump_self_managed", False): update_weapons
            // -- and anything the walk could not represent: Python, whole.
            if (sr->pump_self_managed)
                return run_python(K1Why::SelfManaged, St::PUMP_CONTINUE, sys,
                                  pos, s_.getter);
            if (const std::optional<K1Why> why = prescan(sys, ship))
                return run_python(*why, St::PUMP_CONTINUE, sys, pos,
                                  s_.getter);
            bool stop;
            try {
                stop = pump_stops(sys, ship);
            } catch (const std::invalid_argument&) {
                return run_python(K1Why::Gate, St::PUMP_CONTINUE, sys, pos,
                                  s_.getter);
            }
            if (stop) return emit(K1Kind::STOP_SYSTEM, St::PUMP_CONTINUE, sys);
            // sys_.update_weapons(dt)
            s_.sys = sys;
            s_.st = St::UW_DEAD_PRUNE;
            break;
        }
        case St::PUMP_CONTINUE:
            if (++s_.getter == 4) {
                s_.getter = 0;
                ++s_.ship_pos;
            }
            s_.st = St::PUMP_FOR_GETTER;
            break;

        case St::SYSTEM_START:
            if (const std::optional<K1Why> why = prescan(s_.sys, -1))
                return run_python(*why, St::WALK_END, s_.sys, -1, -1);
            s_.st = St::UW_DEAD_PRUNE;
            break;

        // ── WeaponSystem.update_weapons ───────────────────────────────────
        case St::UW_DEAD_PRUNE: {
            s_.did_fire = false;
            // ship = self.GetParentShip()
            s_.ship = climb_to_ship_of(m_, s_.sys);
            if (const ObjectRow* so = objrow(s_.ship); so && so->has_posed_parts)
                ++c_.posed_walks;
            // if ship is not None and hasattr(ship, "IsDead") and
            //     ship.IsDead(): return False      (_force_update stays set)
            if (ship_dead(m_, s_.ship)) {
                s_.st = St::WALK_END;
                break;
            }
            // self._prune_targets(): a NEW list of the live entries.
            std::vector<int64_t> kept;
            for (const int64_t t : sysrow()._target_list)
                if (!ship_dead(m_, t)) kept.push_back(t);
            // target = self._target_list[0] if self._target_list else None
            s_.target = kept.empty() ? -1 : kept.front();
            write_target_list(s_.sys, std::move(kept));
            // offset = self._live_held_offset(): Python's object (ruling P5).
            s_.offset.reset();
            s_.awaiting_offset = true;
            return emit(K1Kind::WALK_START, St::UW_OFFSET, s_.sys);
        }
        case St::UW_OFFSET: {
            // groups = self._active_chain_groups()
            s_.groups = active_chain_groups();
            // working = self._resolve_working_group() (WS:1395)
            const int64_t last = sysrow()._last_group_fired;
            const bool resume =
                last != -1 &&
                std::find(s_.groups.begin(), s_.groups.end(), last) !=
                    s_.groups.end();
            s_.working = resume ? last : s_.groups.front();
            s_.start_group = s_.working;
            // base_idx = self._last_weapon_idx   (captured once)
            s_.base_idx = sysrow()._last_weapon_idx;
            // if self._single_fire: lit = self._firing_weapon()
            if (sysrow()._single_fire) {
                int64_t lit = -1;
                for (const int64_t c : sysrow()._children) {
                    // The pre-scan named every child, and nothing ran in
                    // Python between it and here but WALK_START's offset
                    // reply (no effect, no handler).
                    if (!named_leaf(c))
                        lost("a child became unnamed before the first effect");
                    if (subrow(c)->_firing) {
                        lit = c;
                        break;
                    }
                }
                if (lit != -1) {
                    // self.try_fire_weapon(lit, dt, target, offset)
                    begin_try(lit, Caller::Lit);
                    break;
                }
            }
            s_.st = St::UW_WHILE;
            break;
        }
        case St::UW_LIT_RETURN:
            // self._force_update = False; return bool(lit.IsFiring())
            write_flag(s_.sys, Field::_force_update, "_force_update", false);
            s_.st = St::WALK_END;
            break;
        case St::UW_WHILE:
            // self.SetGroupFireMode(working)
            write_int(s_.sys, Field::_group_fire_mode, "_group_fire_mode",
                      s_.working);
            // n = self.GetNumWeapons()   (re-read per group)
            s_.n = static_cast<int64_t>(sysrow()._children.size());
            s_.fired_this_group = false;
            s_.delta = 1;
            s_.st = St::UW_FOR_DELTA;
            break;
        case St::UW_FOR_DELTA: {
            // for delta in range(1, n + 1):
            if (s_.delta > s_.n) {
                s_.st = St::UW_GROUP_ADVANCE;
                break;
            }
            // idx = (base_idx + delta) % n if n else 0
            s_.idx = s_.n ? py_mod(s_.base_idx + s_.delta, s_.n) : 0;
            // weapon = self.GetWeapon(idx): None past the live list's end
            const std::vector<int64_t>& kids = sysrow()._children;
            if (s_.idx >= static_cast<int64_t>(kids.size())) {
                next_delta();  // weapon is None: continue
                break;
            }
            s_.weapon = kids[static_cast<size_t>(s_.idx)];
            if (!named_leaf(s_.weapon))  // a handler swapped the children
                return ask("group_step",
                           {s_.sys, s_.idx, s_.working, s_.target},
                           St::UW_STEP_ANSWER);
            // if ... not weapon.IsMemberOfGroup(working): continue
            if (s_.working != 0) {
                const int64_t p = subrow(s_.weapon)->_property;
                int64_t mask = 0;  // a None property: mask 0
                if (p != -1) {
                    const PropertyRow* pr = m_.property(p);
                    if (!pr)
                        return ask("is_member", {s_.weapon, s_.working},
                                   St::UW_MEMBER_ANSWER);
                    mask = pr->_groups;
                }
                if (!group_bit(mask, s_.working)) {
                    next_delta();
                    break;
                }
            }
            // if self.try_fire_weapon(weapon, dt, target, offset):
            begin_try(s_.weapon, Caller::Delta);
            break;
        }
        case St::UW_MEMBER_ANSWER:
            if (take_answer())
                begin_try(s_.weapon, Caller::Delta);
            else
                next_delta();
            break;
        case St::UW_STEP_ANSWER: {
            // 0: skipped, 1: fired, 2: failed (ClearTarget and dumb fire done)
            const int64_t a = take_answer();
            if (a == 1) {
                K1Record r;
                if (fired_bookkeeping(&r)) return r;
            } else {
                next_delta();
            }
            break;
        }
        case St::UW_TRIED: {
            if (s_.tf_result) {
                K1Record r;
                if (fired_bookkeeping(&r)) return r;
                break;
            }
            // weapon._target = None      (ClearTarget, NOT a timer reset)
            write_target(s_.weapon, -1);
            // if self.GetNumTargets() == 0 and weapon.IsDumbFire():
            //     weapon.FireDumb(0, 1)      (only TorpedoTube is dumb-capable)
            if (sysrow()._target_list.empty()) {
                const SubsystemRow* wr = subrow(s_.weapon);
                if (!wr)  // dropped by an effect's handler: Python answers
                    return ask("is_dumb", {s_.weapon}, St::UW_DUMB_ANSWER);
                if (wr->weapon_kind == kTorpedoTube)
                    return emit(K1Kind::FIRE_DUMB, St::UW_NEXT_DELTA,
                                s_.weapon);
            }
            next_delta();
            break;
        }
        case St::UW_DUMB_ANSWER:
            if (take_answer())
                return emit(K1Kind::FIRE_DUMB, St::UW_NEXT_DELTA, s_.weapon);
            next_delta();
            break;
        case St::UW_RESEED_ANSWER:
            take_answer();
            s_.st = St::UW_GROUP_ADVANCE;  // break
            break;
        case St::UW_NEXT_DELTA:
            next_delta();
            break;
        case St::UW_GROUP_ADVANCE: {
            // if fired_this_group or len(groups) <= 1: break
            if (s_.fired_this_group || s_.groups.size() <= 1) {
                s_.st = St::UW_EXIT;
                break;
            }
            // working = groups[(groups.index(working) + 1) % len(groups)]
            const auto it =
                std::find(s_.groups.begin(), s_.groups.end(), s_.working);
            if (it == s_.groups.end()) lost("working group left the chain");
            const size_t at = static_cast<size_t>(it - s_.groups.begin());
            s_.working = s_.groups[(at + 1) % s_.groups.size()];
            // if working == start_group: self._last_group_fired = -1; break
            if (s_.working == s_.start_group) {
                write_int(s_.sys, Field::_last_group_fired, "_last_group_fired",
                          -1);
                s_.st = St::UW_EXIT;
                break;
            }
            s_.st = St::UW_WHILE;
            break;
        }
        case St::UW_EXIT:
            // self._force_update = False    (one-tick bypass, consumed)
            write_flag(s_.sys, Field::_force_update, "_force_update", false);
            s_.st = St::WALK_END;
            break;
        case St::WALK_END:
            if (s_.pump) {
                s_.st = St::PUMP_CONTINUE;
                break;
            }
            return emit(K1Kind::DONE, St::DONE);

        // ── WeaponSystem.try_fire_weapon ──────────────────────────────────
        case St::TF_TIMER: {
            const int64_t w = s_.tf_weapon;
            // Every begin_try names a live leaf in the same call, except after
            // ASK is_member, where only the stock (pure) IsMemberOfGroup ran.
            if (!named_leaf(w)) lost("the tried weapon's row is gone");
            const double threshold = m_.globals().FIRE_TIMER_THRESHOLD;
            // if self._force_update: weapon._fire_timer = FIRE_TIMER_THRESHOLD
            // else: weapon._fire_timer = getattr(weapon, "_fire_timer", 0.0) + dt
            const double timer = sysrow()._force_update
                                     ? threshold
                                     : subrow(w)->_fire_timer + s_.dt;
            write_timer(w, timer);
            // if not weapon.IsFiring() and weapon._fire_timer < THRESHOLD:
            //     return False
            if (!subrow(w)->_firing && timer < threshold) {
                try_returns(false);
                break;
            }
            // weapon._fire_timer = 0.0      (after every passed gate)
            write_timer(w, 0.0);
            // if not weapon.CanFire():
            CanFireResult cf;
            try {
                cf = can_fire(m_, w, s_.now);
            } catch (const std::invalid_argument&) {
                return ask("can_fire", {w}, St::TF_CANFIRE_ANSWER);
            }
            // _charge_gate's `self._depleted = False`, written even when a
            // later gate refuses (Task 3 ruling).
            if (cf.clear_depleted)
                write_flag(w, Field::_depleted, "_depleted", false);
            if (!cf.ok) return emit(K1Kind::BANK_STOP, St::TF_STOPPED, w);
            s_.fire_target = s_.target;
            s_.st = St::TF_FIRE;
            break;
        }
        case St::TF_CANFIRE_ANSWER:
            if (!take_answer())
                return emit(K1Kind::BANK_STOP, St::TF_STOPPED, s_.tf_weapon);
            s_.fire_target = s_.target;
            s_.st = St::TF_FIRE;
            break;
        case St::TF_STOPPED:
            // weapon.StopFiring(); return False
            try_returns(false);
            break;
        case St::TF_FIRE: {
            // result = weapon.Fire(target, offset) -- its decision half. A
            // throw undoes the decision's own writes and asks Python to run
            // the whole Fire.
            const int64_t w = s_.tf_weapon;
            const size_t mark = s_.writes.size();
            Outcome o;
            try {
                o = decide(w, s_.fire_target);
            } catch (const std::invalid_argument& e) {
                k1_roll_back(m_, s_, mark);
                ++c_.fire_ask_why[static_cast<size_t>(fire_ask_why(e))];
                return ask("fire", {s_.sys, w, s_.fire_target},
                           St::TF_FIRE_ANSWER);
            }
            switch (o.what) {
                case Outcome::What::Fire: {
                    K1Record r =
                        emit(K1Kind::FIRE, St::TF_FIRED, w, s_.fire_target);
                    r.decision = o.d;
                    return r;
                }
                case Outcome::What::FailedEvent:
                    // self._broadcast_weapon_fire_failed(); return False
                    return emit(K1Kind::FIRE_FAILED, St::TF_FIRE_FALSE, w);
                case Outcome::What::Fail:
                    s_.st = St::TF_NOT_FIRED;
                    break;
            }
            break;
        }
        case St::TF_FIRED:
            // _weapon_did_fire: the effect returned True
            try_returns(true);
            break;
        case St::TF_FIRE_FALSE:
            s_.st = St::TF_NOT_FIRED;
            break;
        case St::TF_FIRE_ANSWER:
            if (take_answer())
                try_returns(true);
            else
                s_.st = St::TF_NOT_FIRED;
            break;
        case St::TF_NOT_FIRED: {
            if (s_.in_retry) {  // the next entry
                ++s_.retry_pos;
                s_.st = St::TF_RETRY_NEXT;
                break;
            }
            // weapon._target = None
            write_target(s_.tf_weapon, -1);
            // for entry in list(self._target_list): the LIVE list, now
            std::vector<int64_t> snap = sysrow()._target_list;
            for (const int64_t e : snap) {
                const ObjectRow* eo = objrow(e);
                if (!eo || !eo->has_real_is_dead)
                    return ask("retry", {s_.sys, s_.tf_weapon},
                               St::TF_RETRY_ANSWER);
            }
            s_.retry = std::move(snap);
            s_.retry_pos = 0;
            s_.in_retry = true;
            s_.st = St::TF_RETRY_NEXT;
            break;
        }
        case St::TF_RETRY_NEXT: {
            if (s_.retry_pos >= s_.retry.size()) {
                try_returns(false);  // return False
                break;
            }
            const int64_t e = s_.retry[s_.retry_pos];
            // if entry is None or (hasattr(entry, "IsDead") and
            //     entry.IsDead()): continue
            bool dead;
            try {
                dead = ship_dead(m_, e);
            } catch (const std::invalid_argument&) {
                return ask("is_dead", {e}, St::TF_DEAD_ANSWER);
            }
            if (dead) {
                ++s_.retry_pos;
                break;
            }
            // result = weapon.Fire(entry, offset)
            s_.fire_target = e;
            s_.st = St::TF_FIRE;
            break;
        }
        case St::TF_DEAD_ANSWER:
            if (take_answer()) {
                ++s_.retry_pos;
                s_.st = St::TF_RETRY_NEXT;
            } else {
                s_.fire_target = s_.retry[s_.retry_pos];
                s_.st = St::TF_FIRE;
            }
            break;
        case St::TF_RETRY_ANSWER:
            try_returns(take_answer() != 0);
            break;

        case St::DONE:
            lost("the session already returned DONE");
        }
    }
}

}  // namespace

// ── K1Kernel ─────────────────────────────────────────────────────────────────

K1Kernel::K1Kernel(Mirror& m) : m_(m) {}
K1Kernel::~K1Kernel() = default;

void K1Kernel::clear() { sessions_.clear(); }

void K1Kernel::begin_pump(std::vector<int64_t> ships, double dt, double now,
                          bool use_memo, double drift_now) {
    auto s = std::make_unique<Session>();
    s->pump = true;
    s->ships = std::make_shared<const std::vector<int64_t>>(std::move(ships));
    s->dt = dt;
    s->now = now;
    s->use_memo = use_memo;
    s->drift_now = drift_now;
    s->st = St::PUMP_FOR_GETTER;
    sessions_.push_back(std::move(s));
}

void K1Kernel::begin_system(int64_t system, double dt, double now,
                            bool use_memo, double drift_now) {
    auto s = std::make_unique<Session>();
    s->pump = false;
    s->sys = system;
    s->dt = dt;
    s->now = now;
    s->use_memo = use_memo;
    s->drift_now = drift_now;
    s->st = St::SYSTEM_START;
    sessions_.push_back(std::move(s));
}

K1Record K1Kernel::next() {
    if (sessions_.empty()) lost("no session is open");
    Session& s = *sessions_.back();
    if (s.awaiting_offset) lost("WALK_START has no offset (combat_k1_set_offset)");
    if (s.awaiting_answer && !s.has_answer)
        lost("ASK has no answer (combat_k1_answer)");
    // A throw must leave the session and the mirror as they were: the
    // pending answer kept, every unflushed write undone (mirror == Python),
    // so abandon() -- or a retry -- starts from a consistent state.
    Session before = s;
    s.awaiting_answer = false;
    s.has_answer = false;
    try {
        Walker w(m_, s, counts_);
        return w.run();
    } catch (...) {
        k1_roll_back(m_, s, 0);
        s = std::move(before);
        throw;
    }
}

void K1Kernel::set_offset(std::optional<Vec3> xyz) {
    if (sessions_.empty() || !sessions_.back()->awaiting_offset)
        lost("no WALK_START is waiting for its offset");
    Session& s = *sessions_.back();
    s.offset = xyz;
    s.awaiting_offset = false;
}

void K1Kernel::answer(std::optional<int64_t> v) {
    if (sessions_.empty() || !sessions_.back()->awaiting_answer ||
        sessions_.back()->has_answer)
        lost("no ASK is waiting for an answer");
    Session& s = *sessions_.back();
    s.answer = v;
    s.has_answer = true;
}

void K1Kernel::skip_walk() {
    if (sessions_.empty() || !sessions_.back()->awaiting_offset)
        lost("skip_walk: no WALK_START is waiting for a reply");
    Session& s = *sessions_.back();
    s.awaiting_offset = false;
    s.st = St::WALK_END;  // Python ran update_weapons; nothing to write
    ++counts_.python_systems;
    count_why(counts_, s.pump, K1Why::InstancePatch);
}

bool K1Kernel::answer_pending() const {
    return !sessions_.empty() && sessions_.back()->awaiting_answer &&
           sessions_.back()->has_answer;
}

void K1Kernel::end() {
    if (sessions_.empty()) lost("no session is open");
    if (sessions_.back()->st != St::DONE) lost("the session has not returned DONE");
    sessions_.pop_back();
}

void K1Kernel::abandon() {
    if (sessions_.empty()) lost("no session is open");
    sessions_.pop_back();
}

K1Kernel& k1_kernel() {
    static K1Kernel k(mirror());
    return k;
}

}  // namespace dauntless::combat
