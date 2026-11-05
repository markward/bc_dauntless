// The K1 fire-control kernel -- see k1_fire_control.h: fire control's one
// copy of its rules. A port of
//   engine/host_loop.py            _pump_held_weapons            (HL:984)
//   engine/appc/weapon_subsystems.py WeaponSystem.update_weapons (WS:1651)
//                                    WeaponSystem.try_fire_weapon (WS:1573)
// and PhaserBank.Fire (WS:2644, the mixin's WS:865), PulseWeapon.Fire
// (WS:2852) and TorpedoTube.Fire (WS:3324), as that Python stood at
// 9c3db5ec6 (deleted since: fire control native only, M3). Line numbers are
// that Python's. Each cursor state (enum St) is named after the Python line
// it was ported from; Walker::run's switch reads top to bottom like it. Every
// float decision is made by weapon_geometry / fire_gates / sensor_detect,
// the Python-exact ports of Tasks 2-3 and phase 1a.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/k1_fire_control.h"

#include <algorithm>
#include <cmath>
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
#include "dauntless/combat/stop_firing.h"
#include "dauntless/combat/weapon_geometry.h"
#include "geometry_internal.h"

namespace dauntless::combat {

namespace {

// Subsystem weapon_kind codes (mirror.h).
constexpr int64_t kPhaserSystem = 1, kPulseSystem = 2, kTractorSystem = 3,
                  kTorpedoSystem = 4, kPhaserBank = 5, kPulseWeapon = 6,
                  kTractorBeam = 7, kTorpedoTube = 8;

// The leaf kind a system of `kind` owns (PhaserBank under PhaserSystem...).
int64_t leaf_kind_of(int64_t kind) {
    switch (kind) {
        case kPhaserSystem: return kPhaserBank;
        case kPulseSystem: return kPulseWeapon;
        case kTorpedoSystem: return kTorpedoTube;
        default: return -1;
    }
}

// weapon_subsystems._SLOT_LOADED: a tube slot holding a round.
constexpr double kSlotLoaded = -1.0;

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

// A TARGET's `hasattr(x, "IsDead") and x.IsDead()`: on an object whose class
// has no IsDead (a planet: AI or a script can SetTarget one) both are
// TGObject.__getattr__'s truthy _Stub, so it reads as dead -- held, the
// system stops; listed, it is pruned. Else ship_dead (a row it cannot read
// throws: a no-fire). Never for the firing ship, whose real IsDead the
// pre-scan requires.
bool object_dead(const Mirror& m, int64_t h) {
    if (h >= 0)
        if (const ObjectRow* o = m.object(h); o && !o->has_real_is_dead)
            return true;
    return ship_dead(m, h);
}

}  // namespace

const char* k1_kind_name(K1Kind k) {
    static constexpr const char* kNames[] = {"DONE"};
    static_assert(std::size(kNames) == static_cast<size_t>(K1Kind::kCount));
    const auto i = static_cast<size_t>(k);
    return i < std::size(kNames) ? kNames[i] : "?";
}

const char* k1_effect_name(K1Effect e) {
    static constexpr const char* kNames[] = {
        "FIRE_SOUND", "LOOP_STOP", "WEAPON_FIRED", "WEAPON_FIRE_FAILED",
        "SPAWN", "AMMO_CONSUMED", "TRACTOR_STARTED", "TRACTOR_STOPPED"};
    static_assert(std::size(kNames) == static_cast<size_t>(K1Effect::kCount));
    const auto i = static_cast<size_t>(e);
    return i < std::size(kNames) ? kNames[i] : "?";
}

static_assert(static_cast<size_t>(K1NoFire::kCount) <= 64,
              "Counts::no_fire_reported is one bit per K1NoFire");

const char* k1_no_fire_name(K1NoFire w) {
    static constexpr const char* kNames[] = {
        "tractor_row",    "stale_row",      "stub_or_unplaced",
        "pulse_ship_target", "pulse_module", "ammo_row",
        "part_stale",     "unslotted_ship", "gate",
        "structure",      "not_k1_system",  "can_fire",
        "decision",       "launch",         "walk",
        "reseed",         "retry",          "is_dead"};
    static_assert(std::size(kNames) == static_cast<size_t>(K1NoFire::kCount));
    const auto i = static_cast<size_t>(w);
    return i < std::size(kNames) ? kNames[i] : "?";
}

const char* k1_launch_why_name(K1LaunchWhy w) {
    static constexpr const char* kNames[] = {
        "launch_unresolved", "launch_uncached", "launch_other"};
    static_assert(std::size(kNames) ==
                  static_cast<size_t>(K1LaunchWhy::kCount));
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
    // TractorBeamSystem.StartFiring's engage (THE TRACTOR WALK)
    TRACTOR_START,
    // THE SDK ROUTES: Weapon.FireDumb(0, 1); weapon.Fire(target, offset)
    DUMB_START,
    FIRE_START,
    // WeaponSystem.update_weapons
    UW_DEAD_PRUNE,     // if ship ... ship.IsDead(): return False
                       // self._prune_targets(); target = self._target_list[0]
                       // offset = self._live_held_offset() (the value)
    UW_OFFSET,         // groups = ...; working = ...; base_idx = ...;
                       // if self._single_fire: lit = self._firing_weapon()
    UW_LIT_RETURN,     // self._force_update = False; return bool(lit.IsFiring())
    UW_WHILE,          // while True: self.SetGroupFireMode(working);
                       //     n = self.GetNumWeapons(); fired_this_group = False
    UW_FOR_DELTA,      // for delta in range(1, n + 1): idx = ...;
                       //     weapon = self.GetWeapon(idx); IsMemberOfGroup
    UW_TRIED,          //     if self.try_fire_weapon(...): ... else:
                       //         weapon._target = None; FireDumb
    UW_GROUP_ADVANCE,  // if fired_this_group or len(groups) <= 1: break;
                       // working = groups[...]; if working == start_group: ...
    UW_EXIT,           // self._force_update = False; return did_fire
    WALK_END,          // back to the pump, or the system session is done
    // WeaponSystem.try_fire_weapon
    TF_TIMER,          // _fire_timer = ...; if not IsFiring() and _fire_timer
                       // < FIRE_TIMER_THRESHOLD: return False; _fire_timer =
                       // 0.0; if not weapon.CanFire(): StopFiring; False
    TF_FIRE,           // result = weapon.Fire(target, offset)  [or entry]
    TF_FIRED,          // if self._weapon_did_fire(...): return True
    TF_NOT_FIRED,      // weapon._target = None; for entry in
                       // list(self._target_list):   [or the next entry]
    TF_RETRY_NEXT,     //     if entry is None or entry.IsDead(): continue;
                       //     result = weapon.Fire(entry, offset)
    DONE,              // returned DONE; only end() / abandon() may follow
};

enum class Caller : int32_t { Lit, Delta };

// The mirror value one logged write replaced.
struct K1Undo {
    // Slot: element `i` of a FloatList field, its old value `d`.
    // None: a write with no mirror row behind it (nothing to undo); every
    // logged write has one undo, so a rollback mark is both.
    enum class Type : int32_t { F, I, Ref, Ids, Offset, Slot, None } type =
        Type::F;
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

    // The session's write log, and, one for one, the mirror value each
    // write replaced (rolled back by a no-fire before the walk's first shot,
    // or by a throw).
    std::vector<K1Write> writes;
    std::vector<K1Undo> undo;
    // The session's queue entries (THE EFFECT QUEUE), each placed after the
    // writes logged before it. A throw drops them with the session restore
    // (next()); a walk's rollback drops its own.
    std::vector<K1Entry> entries;
    // The session's walk number (1, 2, ...), and per walk the Manual Aim
    // pick its offset came from (nullopt: the system's _held_offset; THE
    // WALK OFFSET), index walk - 1.
    int64_t walk_no = 0;
    std::vector<std::optional<Vec3>> walk_manual;
    // THE OFFSET SOURCE (mirror.h; phase 6 A3). Whether the walk's offset
    // OBJECT is the walked system's own `_held_offset` (a walk start_walk
    // began with no Manual Aim pick: materialise reads it; never a
    // begin_tractor / begin_fire walk, whose object is the driver's), and,
    // once a stamp naming the walk is logged, the system's
    // held_offset_stamp then -- the object materialise makes at that first
    // logged stamp and hands every later one -- with the stamp's log index
    // (a rollback past it forgets it).
    bool walk_from_held = false;
    std::optional<uint64_t> walk_stamp;
    size_t walk_stamp_pos = 0;
    // The walk being walked: where its writes and entries begin (its
    // rollback mark) and whether it has shot yet (NO FIRE).
    size_t walk_mark = 0, walk_entry_mark = 0;
    bool walk_shot = false;
    // begin_tractor's target.
    int64_t tractor_target = -1;
    // THE SDK ROUTES: the dumb-fired tube or the Fire's weapon (`weapon`
    // above), Fire's target (`fire_target`), the ship's GetTarget()
    // (nullopt: not read), and the session's result (K1Kernel::result).
    std::optional<int64_t> ship_target;
    int64_t result = 0;
};

static K1Undo undo_of(K1Undo::Type type, int64_t h, Field f) {
    K1Undo u;
    u.type = type;
    u.h = h;
    u.f = f;
    return u;
}

// Undo the session's logged writes from `mark` on, newest first, and drop
// them from the log: they never reach Python.
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
            case K1Undo::Type::Slot:
                m.set_float_at(u.h, u.f, static_cast<size_t>(u.i), u.d);
                break;
            case K1Undo::Type::None:
                break;
        }
        s.undo.pop_back();
    }
    s.writes.resize(mark);
    // The walk's first logged stamp is gone: materialise runs at its next.
    if (s.walk_stamp && s.walk_stamp_pos >= mark) s.walk_stamp.reset();
}

namespace {

using Session = K1Kernel::Session;

[[noreturn]] void lost(const char* why) {
    throw std::logic_error(std::string("combat K1: ") + why);
}

// One next() call: runs the session to its end.
class Walker {
public:
    Walker(Mirror& m, Session& s, K1Kernel::Counts& c)
        : m_(m), s_(s), c_(c) {}

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
    void write_float(int64_t h, Field f, const char* name, double v) {
        K1Undo u = undo_of(K1Undo::Type::F, h, f);
        u.d = m_.get_f(h, f);
        m_.set_f(h, f, v);
        s_.undo.push_back(std::move(u));
        log(h, name, v);
    }
    void write_timer(int64_t h, double v) {
        write_float(h, Field::_fire_timer, "_fire_timer", v);
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
        // A bank with no row (named by the walk, freed since: no Python runs
        // in a session, so never seen) is still the driver's pinned object:
        // the write goes to Python only, with nothing to undo.
        if (!subrow(h)) {
            s_.undo.push_back(undo_of(K1Undo::Type::None, h, Field::_target));
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
    // The walk's object is stamped whatever it is (a beam stamps it raw); the
    // mirror reads it as the pushed OFFSET would: unset unless a TGPoint3.
    void write_target_offset(int64_t h, bool walk_offset) {
        K1Undo u = undo_of(K1Undo::Type::Offset, h, Field::_target_offset);
        const SubsystemRow* r = subrow(h);
        if (!r) lost("bank row is gone");
        u.set = r->target_offset_set;
        u.v = r->_target_offset;
        s_.undo.push_back(std::move(u));
        if (walk_offset) {
            if (s_.offset) {
                const Vec3& o = *s_.offset;
                m_.set_fv(h, Field::_target_offset, {o[0], o[1], o[2]});
            } else {
                m_.set_fv(h, Field::_target_offset, {});
            }
            log(h, "_target_offset", K1WalkOffset{s_.walk_no, s_.sys});
            // THE OFFSET SOURCE: the bank now holds the walk's object (the
            // set_fv above made its source unknown).
            if (s_.walk_from_held) {
                if (const SubsystemRow* sr = subrow(s_.sys)) {
                    if (!s_.walk_stamp) {
                        s_.walk_stamp = sr->held_offset_stamp;
                        s_.walk_stamp_pos = s_.writes.size() - 1;
                    }
                    m_.set_target_offset_source(h, s_.sys, *s_.walk_stamp);
                }
            }
        } else {
            m_.set_fv(h, Field::_target_offset, {});
            log(h, "_target_offset", std::monostate{});
        }
    }

    // Whether `_target_offset = <the walk's offset object>` on bank `h`
    // would change nothing in Python (THE OFFSET SOURCE): the walk's object
    // is the walked system's `_held_offset` -- the one its first logged
    // stamp made, else the one materialise would make now -- and the bank
    // already holds that very object (its source: this system, at that
    // object's stamp). Identity, never a value: a new TGPoint3 of the same
    // value is a new stamp.
    bool holds_walk_offset(int64_t h) const {
        if (!s_.walk_from_held) return false;
        const SubsystemRow* b = subrow(h);
        const SubsystemRow* sr = subrow(s_.sys);
        if (!b || !sr || b->target_offset_src != s_.sys) return false;
        const uint64_t stamp =
            s_.walk_stamp ? *s_.walk_stamp : sr->held_offset_stamp;
        return b->target_offset_src_stamp == stamp;
    }

    // `sys_.StopFiring()`'s `_held_target = None` and `_held_offset = None`
    // (the walked system's row is checked by the caller).
    void write_held_target_none(int64_t h) {
        K1Undo u = undo_of(K1Undo::Type::Ref, h, Field::_held_target);
        u.i = m_.get_ref(h, Field::_held_target);
        m_.set_ref(h, Field::_held_target, -1);
        s_.undo.push_back(std::move(u));
        log(h, "_held_target", int64_t{-1});
    }
    void write_held_offset_none(int64_t h) {
        K1Undo u = undo_of(K1Undo::Type::Offset, h, Field::_held_offset);
        const SubsystemRow& r = *subrow(h);
        u.set = r.held_offset_set;
        u.v = r._held_offset;
        m_.set_fv(h, Field::_held_offset, {});
        s_.undo.push_back(std::move(u));
        log(h, "_held_offset", std::monostate{});
    }

    // `obj.<field>[index] = v` in place: a tube's slot list (the write the
    // launch's _start_slot_cooldown makes).
    void write_slot(int64_t h, Field f, const char* name, size_t index,
                    double v) {
        K1Undo u = undo_of(K1Undo::Type::Slot, h, f);
        u.i = static_cast<int64_t>(index);
        u.d = m_.get_floats(h, f).at(index);
        m_.set_float_at(h, f, index, v);
        s_.undo.push_back(std::move(u));
        log(h, name, SlotWrite{static_cast<int64_t>(index), WriteScalar{v}});
    }

    // ── The effect queue: entries in walk order, after the writes before ──
    void enqueue(K1Effect kind, int64_t a, int64_t b = -1) {
        s_.entries.push_back(K1Entry{kind, a, b, s_.writes.size(), {}});
        ++c_.entries[static_cast<size_t>(kind)];
    }

    // ── Launches at the boundary (k1_fire_control.h) ──────────────────────
    // Everything a tube launch reads, read before any of its writes.
    struct LaunchPlan {
        K1Spawn spawn;
        int64_t parent = -1;   // the TorpedoSystem
        int64_t slot = -1;     // _start_slot_cooldown's first loaded slot
        bool debit = false;    // a finite magazine: AddAvailable(-1)
        int64_t available = 0;
    };
    std::optional<LaunchPlan> plan_launch(int64_t tube, int64_t target,
                                          K1Spawn::Kind kind,
                                          K1LaunchWhy* why);
    // _spawn_projectile's fire-time reads into `s` (_launch_reads and the
    // spawn position): `world_dir` a cannon's led direction, nullopt for a
    // tube's forward (skewed). Throws std::invalid_argument for anything it
    // cannot read.
    void launch_reads(K1Spawn& s, int64_t launcher, int64_t target,
                      const std::optional<Vec3>& world_dir, double speed);
    // A cannon's launch: everything it reads, before any of its writes.
    struct PulsePlan {
        K1Spawn spawn;
        double charge = 0.0;    // max(0.0, _charge_level - _shot_cost())
        double cooldown = 0.0;  // GetCooldownTime()
    };
    std::optional<PulsePlan> plan_pulse_launch(int64_t cannon,
                                               const K1Decision& d,
                                               K1LaunchWhy* why);
    void log_pulse_launch(int64_t cannon, const PulsePlan& p);
    void log_launch(int64_t tube, int64_t target, const LaunchPlan& p);
    // Weapon.FireDumb(0, 1): nullopt when decided (launched or refused);
    // else why it cannot be (a decision or a launch the mirror cannot
    // make), its own writes rolled back and its launch why counted.
    std::optional<K1NoFire> dumb_fire(int64_t tube);
    // How weapon.Fire(target, offset) ended once decided (fire_effect).
    enum class FireEnd {
        Fired,     // its effect is logged (writes, entries): Fire is True
        Refused,   // a FIRE_FAILED queued: Fire is False
        NotFired,  // the decision refused: Fire is False
        NoLaunch,  // a launch the kernel cannot make (launch_why counted):
                   // nothing of the effect written; a no-fire
    };
    struct Outcome;
    // The effect half of weapon.Fire(target, offset), after its decision
    // `o` (the walk's try-fire, THE TRACTOR WALK and THE SDK ROUTES share
    // it): a beam's sustain or edge (a TractorBeam posts no WEAPON_FIRED), a
    // tube's or a cannon's launch, a tube's refused aim. Fired and Refused
    // mark the walk shot (NO FIRE).
    FireEnd fire_effect(int64_t w, int64_t target, const Outcome& o);
    FireEnd fire_effect_of(int64_t w, int64_t target, const Outcome& o);

    // `weapon.StopFiring()` is its class's writes, logged in its order
    // (round trips §4.3; the one encoding, stop_firing.h), and for a FIRING
    // energy bank the loop sound's LOOP_STOP(bank) after them (spec
    // 2026-11-02-combat-fire-events §4.3; `was_firing = self._firing` is
    // read first). True; a row gone (or not a K1 leaf): false, nothing
    // written (the caller's no-fire).
    bool bank_stop(int64_t h) {
        const SubsystemRow* r = subrow(h);
        if (!r) return false;
        const std::optional<StopFiring> stop = stop_firing_of(r->weapon_kind);
        if (!stop) return false;
        const bool firing = r->_firing != 0;
        for (size_t i = 0; i < stop->n; ++i) {
            switch (stop->writes[i]) {
                case StopWrite::FiringFalse:
                    write_flag(h, Field::_firing, "_firing", false);
                    break;
                case StopWrite::BeamOnCountdownZero:
                    write_float(h, Field::_beam_on_countdown,
                                "_beam_on_countdown", 0.0);
                    break;
                case StopWrite::TargetNone:
                    write_target(h, -1);
                    break;
                case StopWrite::TargetOffsetNone:
                    write_target_offset(h, false);
                    break;
            }
        }
        if (firing && stop->loop_stop) enqueue(K1Effect::LOOP_STOP, h);
        ++(firing ? c_.logged_firing_bank_stop : c_.logged_idle_bank_stop);
        return true;
    }

    // The pump's `sys_.StopFiring()`: WeaponSystem.StopFiring (WS:1564) --
    // `_fire_held = False; _held_target = None; _held_offset = None;
    // _target_list = []; _last_group_fired = -1`, then `w.StopFiring()` for
    // each child in order (bank_stop). The pre-scan ran in this same call
    // (every child a live leaf).
    void system_stop(int64_t sys) {
        const std::vector<int64_t> kids = subrow(sys)->_children;
        write_flag(sys, Field::_fire_held, "_fire_held", false);
        write_held_target_none(sys);
        write_held_offset_none(sys);
        write_target_list(sys, {});
        write_int(sys, Field::_last_group_fired, "_last_group_fired", -1);
        // for i in range(self.GetNumWeapons()): self.GetWeapon(i).StopFiring()
        for (const int64_t k : kids)
            if (!bank_stop(k)) lost("a stopped system's child is not a leaf");
        ++c_.logged_system_stop;
    }

    // ── The record ──────────────────────────────────────────────────────────
    // DONE: the session's writes and entries, and the no-fire whys counted
    // for the first time since the counts were reset.
    K1Record done() {
        K1Record r;
        r.kind = K1Kind::DONE;
        r.writes = std::move(s_.writes);
        s_.writes.clear();
        r.entries = std::move(s_.entries);
        s_.entries.clear();
        s_.undo.clear();  // delivered: Python applies them
        s_.st = St::DONE;
        uint64_t seen = 0;
        for (size_t i = 0; i < c_.no_fire.size(); ++i)
            if (c_.no_fire[i] != 0) seen |= uint64_t{1} << i;
        r.no_fire_new = seen & ~c_.no_fire_reported;
        c_.no_fire_reported |= seen;
        ++c_.records;
        return r;
    }

    // ── NO FIRE (k1_fire_control.h) ─────────────────────────────────────────
    void count_no_fire(K1NoFire why) {
        ++c_.no_fire[static_cast<size_t>(why)];
    }
    // The walk's writes and entries since its mark, undone and dropped.
    void roll_back_walk() {
        k1_roll_back(m_, s_, s_.walk_mark);
        for (size_t i = s_.walk_entry_mark; i < s_.entries.size(); ++i)
            --c_.entries[static_cast<size_t>(s_.entries[i].kind)];
        s_.entries.resize(s_.walk_entry_mark);
    }
    // A failure the mirror cannot answer, in the walk: counted; before the
    // walk's first shot its writes are rolled back, after it what happened
    // is kept; either way the walk ends (does not fire that tick).
    void walk_no_fire(K1NoFire why) {
        count_no_fire(why);
        if (!s_.walk_shot) roll_back_walk();
        s_.st = St::WALK_END;
    }

    // ── The pre-scan ────────────────────────────────────────────────────────
    // nullopt: the walk can run natively; else why it does not fire. Two
    // halves: what the pump's gates (and the StopFiring they lead to) read,
    // checked BEFORE the gates, and what only the walk reads, checked after
    // them -- so a system a gate stops is stopped even when its walk could
    // not be read (host_loop._pump_held_system ran the gates, then
    // update_weapons). `prescan` is both, for a walk with no gates.
    std::optional<K1NoFire> gate_prescan(int64_t sys, int64_t pump_ship) const;
    std::optional<K1NoFire> walk_prescan(int64_t sys) const;
    std::optional<K1NoFire> prescan(int64_t sys, int64_t pump_ship) const {
        if (std::optional<K1NoFire> why = gate_prescan(sys, pump_ship))
            return why;
        return walk_prescan(sys);
    }
    // The pump's gates: true = StopFiring. Throws std::invalid_argument when
    // the mirror cannot answer (a no-fire).
    bool pump_stops(int64_t sys, int64_t pump_ship);
    // A walk's start: its number, its offset (THE WALK OFFSET) and where
    // its writes begin.
    void start_walk(int64_t sys, int64_t ship);

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
    // The success branch of the delta loop.
    void fired_bookkeeping();

    // ── THE TRACTOR WALK (k1_fire_control.h) ───────────────────────────────
    // A tractor walk, guarded: rolled back whole (no fire, counted) when
    // the mirror cannot read it. `start`: begin_tractor's engage, else the
    // pump's update_weapons(dt).
    void tractor_walk(int64_t sys, bool start);
    void tractor_update(int64_t sys);
    void tractor_start(int64_t sys);
    // The system's projectors: live tractor-beam rows (else the walk throws).
    std::vector<int64_t> tractor_beams(int64_t sys) const;
    bool tractor_any_firing(int64_t sys) const;
    bool tractor_can_engage(int64_t ship, int64_t target) const;
    bool tractor_bears(int64_t beam, int64_t ship, int64_t target);
    void tractor_engage(int64_t sys, int64_t ship, int64_t target);
    void tractor_fire(int64_t beam, int64_t target);
    void tractor_stop(int64_t sys);
    void tractor_sync(int64_t sys);

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
// first write (NO FIRE): the system and every child row, the parent ship,
// every target-list entry (and, in the pump, the held target), a real IsDead
// on each, a current part slot for every leaf of a posed ship (its mount),
// the ammo rows, the pulse module, and the chain table. A posed target's
// offset aim is decided in the walk (a Decision no-fire if the mirror
// cannot: its slot went stale, its mount is unknown).
//
// The gates' half: the system and its parent ship, the pump's ship and the
// held target (the IsDead, can_detect and range gates read them), and every
// child a row of the system's leaf kind (StopFiring stops each).
std::optional<K1NoFire> Walker::gate_prescan(int64_t sys,
                                             int64_t pump_ship) const {
    const SubsystemRow* s = subrow(sys);
    if (!s) return K1NoFire::StaleRow;
    const int64_t kind = s->weapon_kind;
    // Phaser, pulse and torpedo walks only (a tractor's is its own).
    if (leaf_kind_of(kind) < 0) return K1NoFire::NotK1System;

    // self.GetParentShip(): alive-testable, placed.
    int64_t ship;
    try {
        ship = climb_to_ship_of(m_, sys);
    } catch (const std::invalid_argument&) {
        return K1NoFire::StaleRow;
    }
    const ObjectRow* so = objrow(ship);
    if (!so) return K1NoFire::StaleRow;
    if (!so->has_real_is_dead) return K1NoFire::StubOrUnplaced;
    if (!xform_ok(m_, *so)) return K1NoFire::StubOrUnplaced;
    if (pump_ship != -1) {  // the pump's own `ship` (the range gate)
        const ObjectRow* po = objrow(pump_ship);
        if (!po) return K1NoFire::StaleRow;
        if (!xform_ok(m_, *po)) return K1NoFire::StubOrUnplaced;
        const int64_t held = s->_held_target;
        const ObjectRow* ho = held == -1 ? nullptr : objrow(held);
        if (held != -1 && !ho) return K1NoFire::StaleRow;
        // No real IsDead: the IsDead gate reads it as dead (object_dead) and
        // stops the system before anything else of it is read.
        if (ho && ho->has_real_is_dead) {
            if (!xform_ok(m_, *ho)) return K1NoFire::StubOrUnplaced;
            // The phaser range gate runs AFTER can_detect (which writes its
            // memo and latch): everything it reads must be answerable here,
            // so no gate can throw once a side-effecting one has run.
            // _same_set reads both containing sets.
            auto set_ok = [&](int64_t h) {
                return h == -1 || (h >= 0 && m_.set(h) != nullptr);
            };
            if (kind == kPhaserSystem &&
                (!set_ok(po->_containing_set) || !set_ok(ho->_containing_set)))
                return K1NoFire::StaleRow;
        }
    }

    // _children: rows of the system's leaf kind (WeaponSystem.StopFiring
    // calls each one's StopFiring).
    const int64_t leaf = leaf_kind_of(kind);
    for (const int64_t c : s->_children) {
        const SubsystemRow* w = subrow(c);
        if (!w) return K1NoFire::StaleRow;
        if (w->weapon_kind != leaf) return K1NoFire::Structure;
    }
    return std::nullopt;
}

// The walk's half: the target list, the chain table, each child's place,
// property, part slot and pulse module, and the ammo rows.
std::optional<K1NoFire> Walker::walk_prescan(int64_t sys) const {
    const SubsystemRow* s = subrow(sys);
    const int64_t kind = s->weapon_kind;
    const int64_t ship = climb_to_ship_of(m_, sys);  // gate_prescan climbed it
    const ObjectRow* so = objrow(ship);

    // _target_list: every entry is a placed Object with a real IsDead. (A
    // pulse or torpedo aim at a posed target's offset is the walk's.)
    bool any_alive = false;
    for (const int64_t t : s->_target_list) {
        const ObjectRow* to = objrow(t);
        if (!to) return K1NoFire::StaleRow;
        if (!to->has_real_is_dead) continue;   // pruned: dead (object_dead)
        if (!xform_ok(m_, *to)) return K1NoFire::StubOrUnplaced;
        if (!to->_dead) any_alive = true;
    }
    // PulseWeapon.Fire(None) falls back to ship.GetTarget(), not mirrored.
    if (kind == kPulseSystem && !any_alive) return K1NoFire::PulseShipTarget;

    // GetFiringChains: the property (None reads []); group ids >= 0 (a
    // negative id raises in IsMemberOfGroup's shift).
    if (s->_property != -1) {
        const PropertyRow* p = m_.property(s->_property);
        if (!p) return K1NoFire::StaleRow;
        for (const auto& chain : p->_firing_chains)
            for (const int64_t g : chain)
                if (g < 0) return K1NoFire::Structure;
    }

    // _children (each a row of the leaf kind: gate_prescan): under this
    // system and ship.
    const int64_t leaf = leaf_kind_of(kind);
    for (const int64_t c : s->_children) {
        const SubsystemRow* w = subrow(c);
        if (w->_parent_subsystem != sys) return K1NoFire::Structure;
        try {
            if (climb_to_ship_of(m_, c) != ship) return K1NoFire::Structure;
        } catch (const std::invalid_argument&) {
            return K1NoFire::StaleRow;
        }
        if (w->_property != -1 && !m_.property(w->_property))
            return K1NoFire::StaleRow;
        // A posed ship's leaf mount is read through its part slot
        // (mount_position): one that is not current is Python's.
        Vec3 local;
        if (so->has_posed_parts &&
            posed_local(m_, *so, *w, &local) == SlotState::stale)
            return K1NoFire::PartStale;
        if (leaf == kPulseWeapon &&
            (!w->module_ok || w->_power_setting < 0 || w->_power_setting > 2))
            return K1NoFire::PulseModule;
    }

    // TorpedoSystem._ammo_by_slot: [slot, Ammo handle, ...]; -1 is a slot
    // holding None, which the tube gate answers (never exhausted).
    if (kind == kTorpedoSystem) {
        const auto& slots = s->_ammo_by_slot;
        for (size_t i = 1; i < slots.size(); i += 2)
            if (slots[i] != -1 && !m_.ammo(slots[i])) return K1NoFire::AmmoRow;
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
    if (held != -1 && object_dead(m_, held)) return true;
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
void Walker::fired_bookkeeping() {
    s_.did_fire = s_.fired_this_group = true;
    write_int(s_.sys, Field::_last_weapon_idx, "_last_weapon_idx", s_.idx);
    write_int(s_.sys, Field::_last_group_fired, "_last_group_fired", s_.working);
    if (!sysrow()._single_fire) {
        next_delta();
        return;
    }
    // _reseed_all_fire_timers (WS:1620): every child's _fire_timer = 0.0. A
    // child the mirror cannot name: the reseed is skipped, the shot kept
    // (NO FIRE, after a shot).
    const std::vector<int64_t> kids = sysrow()._children;
    bool named = true;
    for (const int64_t c : kids) named = named && named_leaf(c);
    if (named)
        for (const int64_t c : kids) write_timer(c, 0.0);
    else
        count_no_fire(K1NoFire::Reseed);
    s_.st = St::UW_GROUP_ADVANCE;  // break
}

// update_weapons' walk start (WS:1655-1660, after the prune): the walk's
// number, `offset = self._live_held_offset()` from the mirror and where its
// Manual Aim pick came from (THE WALK OFFSET), and its rollback mark.
void Walker::start_walk(int64_t sys, int64_t ship) {
    ++s_.walk_no;
    s_.offset = k1_live_held_offset(m_, sys, ship);
    s_.walk_manual.resize(static_cast<size_t>(s_.walk_no));
    s_.walk_manual.back() = k1_manual_offset(m_, ship);
    s_.walk_from_held = !s_.walk_manual.back().has_value();
    s_.walk_stamp.reset();
    s_.walk_shot = false;
}


// ── THE TRACTOR WALK (k1_fire_control.h) ─────────────────────────────────────
// weapon_subsystems.TractorBeamSystem at 23b3845d5: update_weapons (WS:2786),
// StartFiring (WS:2718), _engage_beam (WS:2843), StopFiring (WS:2879),
// _sync_firing_event (WS:2746), _can_engage (WS:2780).

void Walker::tractor_walk(int64_t sys, bool start) {
    const size_t mark = s_.writes.size();
    const size_t emark = s_.entries.size();
    try {
        if (start)
            tractor_start(sys);
        else
            tractor_update(sys);
    } catch (const std::invalid_argument&) {
        k1_roll_back(m_, s_, mark);
        for (size_t i = emark; i < s_.entries.size(); ++i)
            --c_.entries[static_cast<size_t>(s_.entries[i].kind)];
        s_.entries.resize(emark);
        ++c_.no_fire[static_cast<size_t>(K1NoFire::TractorRow)];
    }
}

std::vector<int64_t> Walker::tractor_beams(int64_t sys) const {
    const SubsystemRow* r = subrow(sys);
    if (!r || r->weapon_kind != kTractorSystem)
        detail::fall_back("the tractor system's row cannot be read");
    for (const int64_t k : r->_children) {
        const SubsystemRow* kr = subrow(k);
        if (!kr || kr->weapon_kind != kTractorBeam)
            detail::fall_back("a projector cannot be named");
    }
    return r->_children;
}

// _any_child_firing (WS:2690)
bool Walker::tractor_any_firing(int64_t sys) const {
    for (const int64_t k : subrow(sys)->_children)
        if (subrow(k)->_firing) return true;
    return false;
}

// _can_engage: _target_within_range_gu(ship, target, TRACTOR_MAX_RANGE_GU)
// and target is not None.
bool Walker::tractor_can_engage(int64_t ship, int64_t target) const {
    return _target_within_range_gu(m_, ship, target,
                                   m_.globals().TRACTOR_MAX_RANGE_GU) &&
           target != -1;
}

// aim_world = _resolve_bank_aim_world(emitter, target);
// _emitter_in_arc(emitter, ship, aim_world)
bool Walker::tractor_bears(int64_t beam, int64_t ship, int64_t target) {
    const Vec3 aim = _resolve_bank_aim_world(m_, beam, target, s_.use_memo);
    return _emitter_in_arc(m_, beam, ship, aim);
}

// emitter.Fire(target, offset): the mixin's _fire_decide (CanFire, then the
// arc from the beam's own ship), then _fire_effect -- `_firing = True;
// _target = target; _target_offset = offset`, and on the was-not-firing
// edge `_beam_on_countdown = BEAM_ON_DELAY_S; _dwell = 0.0` and FIRE_SOUND
// (a TractorBeam posts no ET_WEAPON_FIRED). Its return value is unused.
void Walker::tractor_fire(int64_t beam, int64_t target) {
    fire_effect(beam, target, decide_beam(beam, target));
}

// _engage_beam(target, offset, ship): the offset is the walk's (s_.offset,
// K1WalkOffset).
void Walker::tractor_engage(int64_t sys, int64_t ship, int64_t target) {
    const std::vector<int64_t> kids = tractor_beams(sys);
    const auto n = static_cast<int64_t>(kids.size());
    if (n == 0) return;
    // `hasattr(emitter, "CanFire") and emitter.CanFire()`: its latch clear
    // is written whatever it answers (Task 3 ruling).
    auto can_fire_now = [&](int64_t beam) {
        const CanFireResult cf = can_fire(m_, beam, s_.now);
        if (cf.clear_depleted)
            write_flag(beam, Field::_depleted, "_depleted", false);
        return cf.ok;
    };
    if (subrow(sys)->_single_fire) {
        const int64_t start = py_mod(subrow(sys)->_next_emitter_index, n);
        for (int64_t delta = 0; delta < n; ++delta) {
            const int64_t idx = (start + delta) % n;
            const int64_t beam = kids[static_cast<size_t>(idx)];
            if (!tractor_bears(beam, ship, target)) continue;
            if (can_fire_now(beam)) {
                tractor_fire(beam, target);
                write_int(sys, Field::_next_emitter_index,
                          "_next_emitter_index", (idx + 1) % n);
                return;
            }
        }
        return;
    }
    for (const int64_t beam : kids) {
        if (!tractor_bears(beam, ship, target)) continue;
        if (can_fire_now(beam)) tractor_fire(beam, target);
    }
}

// TractorBeamSystem.StopFiring: `self._engage_state = None`, then
// WeaponSystem.StopFiring (the five system writes, each projector's stop),
// then the sync.
void Walker::tractor_stop(int64_t sys) {
    const std::vector<int64_t> kids = tractor_beams(sys);
    write_i(sys, Field::engage_kind, "_engage_state", 0, std::monostate{});
    write_flag(sys, Field::_fire_held, "_fire_held", false);
    write_held_target_none(sys);
    write_held_offset_none(sys);
    write_target_list(sys, {});
    write_int(sys, Field::_last_group_fired, "_last_group_fired", -1);
    for (const int64_t k : kids)
        if (!bank_stop(k)) lost("a tractor projector has no stop");
    tractor_sync(sys);
}

// _sync_firing_event: on an edge, with a parent ship, `_was_firing = now`
// and the event's entry (source the system, destination the ship).
void Walker::tractor_sync(int64_t sys) {
    const bool now = tractor_any_firing(sys);
    if (now == (subrow(sys)->_was_firing != 0)) return;
    const int64_t ship = climb_to_ship_of(m_, sys);
    if (ship == -1) return;  // nowhere to send it: the edge stays unseen
    write_flag(sys, Field::_was_firing, "_was_firing", now);
    enqueue(now ? K1Effect::TRACTOR_STARTED : K1Effect::TRACTOR_STOPPED, sys,
            ship);
}

// The pump's `sys_.update_weapons(dt)` on a tractor system.
void Walker::tractor_update(int64_t sys) {
    s_.sys = sys;
    const std::vector<int64_t> kids = tractor_beams(sys);
    const SubsystemRow& r = *subrow(sys);
    // if not self._fire_held or self._held_target is None: return False
    const int64_t target = r._held_target;
    if (!r._fire_held || target == -1) return;
    if (target < 0 || !objrow(target))
        detail::fall_back("the held target cannot be named");
    ++c_.logged_tractor_walk;
    // if not self.IsOn(): self._sync_firing_event(); return False
    if (!r._is_on) {
        tractor_sync(sys);
        return;
    }
    // if _is_offline(self): self.StopFiring()
    if (weapon_system_offline(m_, sys)) {
        tractor_stop(sys);
        return;
    }
    const int64_t ship = climb_to_ship_of(m_, sys);
    // if hasattr(target, "IsDead") and target.IsDead(): self.StopFiring()
    if (object_dead(m_, target)) {
        tractor_stop(sys);
        return;
    }
    const bool engageable = tractor_can_engage(ship, target);
    // Drop every firing projector that can no longer hold (range, arc).
    // `(not engageable) or (not _emitter_in_arc(...))`: out of range the
    // aim is never resolved (Python short-circuits).
    for (const int64_t k : kids) {
        if (!subrow(k)->_firing) continue;
        if (!engageable || !tractor_bears(k, ship, target))
            if (!bank_stop(k)) lost("a tractor projector has no stop");
    }
    if (!engageable || tractor_any_firing(sys)) {
        tractor_sync(sys);
        return;
    }
    // fired = self._engage_beam(target, self._live_held_offset(), ship)
    start_walk(sys, ship);
    tractor_engage(sys, ship, target);
    tractor_sync(sys);
}

// TractorBeamSystem.StartFiring after its gates and intent writes:
// `if self._can_engage(ship, target): self._engage_beam(target, offset,
// ship)`, then the sync. The walk (1) and its offset are begin_tractor's.
void Walker::tractor_start(int64_t sys) {
    s_.sys = sys;
    tractor_beams(sys);
    const int64_t target = s_.tractor_target;
    if (target == kRefUnrepresentable || (target >= 0 && !objrow(target)))
        detail::fall_back("the StartFiring target cannot be named");
    ++c_.logged_tractor_start;
    const int64_t ship = climb_to_ship_of(m_, sys);
    if (tractor_can_engage(ship, target)) tractor_engage(sys, ship, target);
    tractor_sync(sys);
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
    //     target = ship.GetTarget()     -- not mirrored: a Fire session
    //     (THE SDK ROUTES) carries it, read by Python
    if (t == -1 && ship != -1) {
        if (!s_.ship_target)
            throw std::invalid_argument("combat K1: ship.GetTarget() fallback");
        t = *s_.ship_target;
        if (t == kRefUnrepresentable || (t >= 0 && !objrow(t)))
            throw std::invalid_argument("combat K1: ship target unnamed");
    }
    // if target is not None and hasattr(target, "IsDead") and target.IsDead()
    if (t != -1 && object_dead(m_, t)) t = -1;
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

// ── Launches at the boundary (spec 2026-11-02-combat-launch-deferral) ───────
// The Python they stand in for, CHANGE BOTH: TorpedoTube._fire_effect (from
// its stamps), _start_slot_cooldown, _spawn_torpedo (the ammo debit, the
// script's module), TorpedoAmmoType.AddAvailable, _spawn_projectile's fire-
// time reads (_emitter_world_position, _emitter_forward_world(skew=True),
// the launch velocity and the homing stamps) and Weapon.FireDumb.

// Every read of the launch, before any write; nullopt (and why) when the
// kernel cannot make it (a no-fire: K1NoFire::Launch).
std::optional<Walker::LaunchPlan> Walker::plan_launch(int64_t tube,
                                                      int64_t target,
                                                      K1Spawn::Kind kind,
                                                      K1LaunchWhy* why) {
    try {
        LaunchPlan p;
        const SubsystemRow& tr = detail::sub(m_, tube);
        // parent = self.GetParentSubsystem() (the pre-scan named it).
        p.parent = tr._parent_subsystem;
        const SubsystemRow& sys = detail::sub(m_, p.parent);
        // ammo = parent.GetCurrentAmmoType(); its script's module. With no
        // ammo type, `parent.GetProperty().GetTorpedoScript(0)`: the slot-0
        // script's launch, cached on the property's row (THE SDK ROUTES,
        // M8.2; native_combat.push_slot0_launch), and no debit.
        const int64_t ammo_h = current_ammo_handle(m_, sys);
        int64_t state = 0;
        double speed = 0.0;
        int64_t module_row = ammo_h;
        const AmmoRow* ammo = ammo_h == -1 ? nullptr : m_.ammo(ammo_h);
        if (ammo != nullptr) {
            state = ammo->ammo_launch_state;
            speed = ammo->ammo_launch_speed;
        } else {
            // parent_prop is None: _spawn_torpedo returns (state 2: no
            // module), as does a property with no slot-0 script.
            module_row = sys._property;
            const PropertyRow* prop =
                module_row < 0 ? nullptr : m_.property(module_row);
            if (module_row == kRefUnrepresentable ||
                (module_row >= 0 && prop == nullptr))
                detail::fall_back("the torpedo property cannot be named");
            state = prop == nullptr ? 2 : prop->slot0_launch_state;
            speed = prop == nullptr ? 0.0 : prop->slot0_launch_speed;
        }
        switch (state) {
            case 1: break;
            case 2: *why = K1LaunchWhy::Unresolved; return std::nullopt;
            default: *why = K1LaunchWhy::Uncached; return std::nullopt;
        }
        // _start_slot_cooldown(now): _ensure_slots() rebuilds lists whose
        // length is not MaxReady (not here), then the first loaded slot.
        const auto n = static_cast<int64_t>(tr._reload_timers.size());
        if (n != tr._max_ready ||
            static_cast<int64_t>(tr._reload_advanced_at.size()) != n) {
            *why = K1LaunchWhy::Other;
            return std::nullopt;
        }
        for (int64_t i = 0; i < n; ++i)
            if (tr._reload_timers[static_cast<size_t>(i)] == kSlotLoaded) {
                p.slot = i;
                break;
            }
        // `if ammo is not None and not getattr(ammo, "_unlimited", True):
        // ammo.AddAvailable(-1)`: max(0, min(available - 1, max)).
        if (ammo != nullptr && !ammo->_unlimited) {
            p.debit = true;
            p.available = std::max<int64_t>(
                0, std::min<int64_t>(ammo->_available + -1,
                                     ammo->_max_torpedoes));
        }
        K1Spawn& s = p.spawn;
        s.kind = kind;
        s.ammo = module_row;
        launch_reads(s, tube, target, std::nullopt, speed);
        return p;
    } catch (const std::invalid_argument&) {
        *why = K1LaunchWhy::Other;
        return std::nullopt;
    }
}

void Walker::launch_reads(K1Spawn& s, int64_t launcher, int64_t target,
                          const std::optional<Vec3>& world_dir, double speed) {
    const SubsystemRow& lr = detail::sub(m_, launcher);
    // torp._source_ship = emitter._climb_to_ship()
    s.ship = climb_to_ship_of(m_, launcher);
    const ObjectRow& so = detail::obj(m_, s.ship);
    // register: source.GetContainingSet()
    s.set = so._containing_set;
    if (s.set == kRefUnrepresentable || (s.set >= 0 && !m_.set(s.set)))
        detail::fall_back("the ship's set is unnamed");
    // spawn_pos = emitter._emitter_world_position()
    s.position = subsystem_world_position(m_, launcher, -1, s_.use_memo);
    // A cannon's world_dir is its led direction (the decision's); a tube's
    // is _emitter_forward_world(emitter, source_ship, skew=True):
    // Direction, + 0.033 x Right when IsSkewFire, then
    // MultMatrixLeft(ship.GetWorldRotation()).
    Vec3 dir;
    if (world_dir) {
        dir = *world_dir;
    } else {
        Vec3 local = lr._direction;
        if (lr._skew_fire)
            local = {local[0] + 0.033 * lr._right[0],
                     local[1] + 0.033 * lr._right[1],
                     local[2] + 0.033 * lr._right[2]};
        dir = detail::mult_matrix_left(detail::xform(m_, so).rot, local);
    }
    // length = world_dir.Length(); ship_vel = GetVelocityTG();
    // `if length > 1e-6: torp._velocity = unit * launch_speed + vel`.
    const double length = detail::length(dir);
    if (length > 1e-6) {
        const Vec3& v = so._velocity;
        s.has_velocity = true;
        s.velocity = {dir[0] / length * speed + v[0],
                      dir[1] / length * speed + v[1],
                      dir[2] / length * speed + v[2]};
    }
    // target_ship = emitter._target (the stamp): alive -> its homing, then
    // SetTargetOffset(emitter._target_offset), the walk's offset (a TGPoint3
    // copy, else None), steered at as it is (no bake: M5).
    if (target != -1 && !object_dead(m_, target)) {
        s.target = target;
        if (s_.offset) {
            s.has_offset = true;
            s.offset = *s_.offset;
        }
    }
    // drf_override = self.GetDamageRadiusFactor()
    s.drf_override = lr._damage_radius_factor;
}

// PulseWeapon._fire_effect inside the deferral (CHANGE BOTH): _defer_spawn
// with the decision's led direction, GetDamageRadiusFactor(),
// GetDamageScale() and the target the shot used; the module's launch speed
// is the cannon's own (ruling P6, the lead solve's). Every read before any
// write; nullopt (and why) when the kernel cannot make it (a no-fire).
std::optional<Walker::PulsePlan> Walker::plan_pulse_launch(
    int64_t cannon, const K1Decision& d, K1LaunchWhy* why) {
    try {
        PulsePlan p;
        const SubsystemRow& cr = detail::sub(m_, cannon);
        K1Spawn& s = p.spawn;
        s.kind = K1Spawn::Kind::Pulse;
        s.ammo = cannon;
        launch_reads(s, cannon, d.target_used, d.world_dir, cr.launch_speed);
        s.damage_scale = pulse_damage_scale(m_, cr);
        s.fired_at = d.target_used;
        // `max(0.0, x)` is 0.0 unless x > 0.0 (a NaN, -0.0: 0.0).
        const double x = cr._charge_level - pulse_shot_cost(m_, cr);
        p.charge = x > 0.0 ? x : 0.0;
        p.cooldown = cr._cooldown_time;
        return p;
    } catch (const std::invalid_argument&) {
        *why = K1LaunchWhy::Other;
        return std::nullopt;
    }
}

// The launch's entry and writes, in PulseWeapon._fire_effect's order: the
// SPAWN (_defer_spawn), the drain, the cooldown. Its ET_WEAPON_FIRED is the
// delivery's, once the bolt exists (M4): no entry here.
void Walker::log_pulse_launch(int64_t cannon, const PulsePlan& p) {
    s_.entries.push_back(
        K1Entry{K1Effect::SPAWN, cannon, -1, s_.writes.size(), p.spawn});
    ++c_.entries[static_cast<size_t>(K1Effect::SPAWN)];
    write_float(cannon, Field::_charge_level, "_charge_level", p.charge);
    write_float(cannon, Field::_cooldown_remaining, "_cooldown_remaining",
                p.cooldown);
}

// The launch's writes and entries, in TorpedoTube._fire_effect's order.
void Walker::log_launch(int64_t tube, int64_t target, const LaunchPlan& p) {
    // if target is not None: _target = target; _target_offset = offset
    // else: _target = None; _target_offset = None
    write_target(tube, target);
    write_target_offset(tube, target != -1);
    write_flag(tube, Field::_firing, "_firing", true);
    // now = _game_time(); _num_ready -= 1; _last_fire_time = now;
    // parent._last_system_fire_time = now; _start_slot_cooldown(now)
    write_int(tube, Field::_num_ready, "_num_ready",
              subrow(tube)->_num_ready - 1);
    write_float(tube, Field::_last_fire_time, "_last_fire_time", s_.now);
    write_float(p.parent, Field::_last_system_fire_time,
                "_last_system_fire_time", s_.now);
    if (p.slot >= 0) {
        const auto i = static_cast<size_t>(p.slot);
        write_slot(tube, Field::_reload_timers, "_reload_timers", i, 0.0);
        write_slot(tube, Field::_reload_advanced_at, "_reload_advanced_at", i,
                   s_.now);
    }
    // _spawn_torpedo: the ammo debit, then the spawn (its ET_TORPEDO_FIRED
    // is posted by the SPAWN's delivery); _broadcast_weapon_fired(target);
    // _broadcast_ammo_consumed_if_player()
    if (p.debit)
        write_int(p.spawn.ammo, Field::_available, "_available", p.available);
    s_.entries.push_back(
        K1Entry{K1Effect::SPAWN, tube, -1, s_.writes.size(), p.spawn});
    ++c_.entries[static_cast<size_t>(K1Effect::SPAWN)];
    enqueue(K1Effect::WEAPON_FIRED, tube, target);
    enqueue(K1Effect::AMMO_CONSUMED, tube);
    // Discrete-shot: auto-stop after launch.
    write_flag(tube, Field::_firing, "_firing", false);
}

// Weapon.FireDumb(0, 1) (WS:1231): `if _dewarp_blocks_fire(self): return;
// self.Fire(target=None, offset=None)` -- TorpedoTube.Fire's decision
// (CanFire; no aim, no cone) and, when it fires, the launch with no target.
std::optional<K1NoFire> Walker::dumb_fire(int64_t tube) {
    const size_t mark = s_.writes.size();
    Outcome o;
    try {
        // _dewarp_blocks_fire: the parent ship sliding onto its warp-in
        // placement (warp_state.is_arriving, pushed as `arriving`).
        const ObjectRow* so = objrow(climb_to_ship_of(m_, tube));
        if (so != nullptr && so->arriving) {
            ++c_.logged_dumb_refused;
            return std::nullopt;
        }
        o = decide_tube(tube, -1);
    } catch (const std::invalid_argument&) {
        k1_roll_back(m_, s_, mark);
        return K1NoFire::Decision;
    }
    if (o.what != Outcome::What::Fire) {
        ++c_.logged_dumb_refused;
        return std::nullopt;
    }
    K1LaunchWhy why = K1LaunchWhy::Other;
    if (std::optional<LaunchPlan> p =
            plan_launch(tube, -1, K1Spawn::Kind::Dumb, &why)) {
        log_launch(tube, -1, *p);
        ++c_.logged_dumb_launch;
        s_.walk_shot = true;
        return std::nullopt;
    }
    ++c_.launch_why[static_cast<size_t>(why)];
    k1_roll_back(m_, s_, mark);
    return K1NoFire::Launch;
}

Walker::FireEnd Walker::fire_effect(int64_t w, int64_t target,
                                    const Outcome& o) {
    const FireEnd end = fire_effect_of(w, target, o);
    if (end == FireEnd::Fired || end == FireEnd::Refused) s_.walk_shot = true;
    return end;
}

Walker::FireEnd Walker::fire_effect_of(int64_t w, int64_t target,
                                       const Outcome& o) {
    switch (o.what) {
        case Outcome::What::Fire: {
            if (o.d.shape == K1Decision::Shape::Beam && o.d.was_firing) {
                // _fire_effect on a beam already firing: three writes, no
                // sound, no event (WS:895-898). Each is logged only when it
                // changes something in Python (phase 6 A3): `_firing` not
                // already True (a bank that is firing is never asleep --
                // passive sleep needs `not _firing`, and any `_firing`
                // write wakes it -- so the WakeField's wake is a no-op),
                // `_target` not this live handle (one object per row), the
                // offset not the very object the bank holds.
                const SubsystemRow* br = subrow(w);
                if (br && br->_firing == 1)
                    ++c_.logged_beam_sustain_skips;
                else
                    write_flag(w, Field::_firing, "_firing", true);
                if (target >= 0 && br && m_.get_ref(w, Field::_target) == target)
                    ++c_.logged_beam_sustain_skips;
                else
                    write_target(w, target);
                if (holds_walk_offset(w))
                    ++c_.logged_beam_sustain_skips;
                else
                    write_target_offset(w, true);
                ++c_.logged_beam_sustain;
                return FireEnd::Fired;
            }
            if (o.d.shape == K1Decision::Shape::Beam) {
                // The was-not-firing edge (WS:898-916, then
                // PhaserBank._fire_effect): the mixin's writes, its
                // FIRE_SOUND, then ET_WEAPON_FIRED at the target (not a
                // TractorBeam's: the mixin's _fire_effect is its whole).
                write_flag(w, Field::_firing, "_firing", true);
                write_target(w, target);
                write_target_offset(w, true);
                write_float(w, Field::_beam_on_countdown, "_beam_on_countdown",
                            m_.globals().BEAM_ON_DELAY_S);
                write_float(w, Field::_dwell, "_dwell", 0.0);
                enqueue(K1Effect::FIRE_SOUND, w);
                if (subrow(w)->weapon_kind != kTractorBeam)
                    enqueue(K1Effect::WEAPON_FIRED, w, target);
                ++c_.logged_beam_edge;
                return FireEnd::Fired;
            }
            if (o.d.shape == K1Decision::Shape::Tube) {
                // The tube's launch (LAUNCHES AT THE BOUNDARY): logged writes
                // and a SPAWN, unless the kernel cannot make it (a no-fire,
                // its why counted).
                K1LaunchWhy why = K1LaunchWhy::Other;
                if (std::optional<LaunchPlan> p =
                        plan_launch(w, target, K1Spawn::Kind::Tube, &why)) {
                    log_launch(w, target, *p);
                    ++c_.logged_tube_launch;
                    return FireEnd::Fired;
                }
                ++c_.launch_why[static_cast<size_t>(why)];
            }
            if (o.d.shape == K1Decision::Shape::Pulse) {
                // The cannon's launch, likewise (Task 3).
                K1LaunchWhy why = K1LaunchWhy::Other;
                if (std::optional<PulsePlan> p =
                        plan_pulse_launch(w, o.d, &why)) {
                    log_pulse_launch(w, *p);
                    ++c_.logged_pulse_launch;
                    return FireEnd::Fired;
                }
                ++c_.launch_why[static_cast<size_t>(why)];
            }
            return FireEnd::NoLaunch;
        }
        case Outcome::What::FailedEvent:
            // self._broadcast_weapon_fire_failed(); return False
            enqueue(K1Effect::WEAPON_FIRE_FAILED, w);
            ++c_.logged_fire_failed;
            return FireEnd::Refused;
        case Outcome::What::Fail:
            break;
    }
    return FireEnd::NotFired;
}

// ── The cursor loop ──────────────────────────────────────────────────────────

K1Record Walker::run() {
    for (;;) {
        switch (s_.st) {
        // ── host_loop._pump_held_weapons ──────────────────────────────────
        case St::PUMP_FOR_GETTER: {
            if (s_.ship_pos >= s_.ships->size()) return done();
            const int64_t ship = (*s_.ships)[s_.ship_pos];
            const ObjectRow* so = objrow(ship);
            // A ship the mirror cannot name: none of its systems fires
            // (counted once per pump, at its first getter).
            if (!so) {
                if (s_.getter == 0) count_no_fire(K1NoFire::UnslottedShip);
                s_.st = St::PUMP_CONTINUE;
                break;
            }
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
            if (sys == kRefUnrepresentable) {
                count_no_fire(s_.getter == 2 ? K1NoFire::TractorRow
                                             : K1NoFire::StaleRow);
                s_.st = St::PUMP_CONTINUE;
                break;
            }
            const SubsystemRow* sr = subrow(sys);
            // if sys_ is None or not getattr(sys_, "_fire_held", False): continue
            if (!sr || !sr->_fire_held) {
                s_.st = St::PUMP_CONTINUE;
                break;
            }
            // A tractor: its own walk (THE TRACTOR WALK).
            if (sr->weapon_kind == kTractorSystem) {
                tractor_walk(sys, false);
                s_.st = St::PUMP_CONTINUE;
                break;
            }
            // Anything the gates could not read: no fire.
            if (const std::optional<K1NoFire> why = gate_prescan(sys, ship)) {
                count_no_fire(*why);
                s_.st = St::PUMP_CONTINUE;
                break;
            }
            bool stop;
            try {
                stop = pump_stops(sys, ship);
            } catch (const std::invalid_argument&) {
                count_no_fire(K1NoFire::Gate);
                s_.st = St::PUMP_CONTINUE;
                break;
            }
            if (stop) {
                // sys_.StopFiring(); continue
                system_stop(sys);
                s_.st = St::PUMP_CONTINUE;
                break;
            }
            // Anything the walk could not represent: no fire.
            if (const std::optional<K1NoFire> why = walk_prescan(sys)) {
                count_no_fire(*why);
                s_.st = St::PUMP_CONTINUE;
                break;
            }
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
            if (const std::optional<K1NoFire> why = prescan(s_.sys, -1)) {
                count_no_fire(*why);
                s_.st = St::WALK_END;
                break;
            }
            s_.st = St::UW_DEAD_PRUNE;
            break;
        case St::TRACTOR_START:
            tractor_walk(s_.sys, true);
            s_.st = St::WALK_END;
            break;

        // ── THE SDK ROUTES (k1_fire_control.h) ───────────────────────────
        case St::DUMB_START: {
            // Weapon.FireDumb(0, 1) (WS:1415) on one tube.
            ++c_.logged_sdk_dumb_fire;
            if (const std::optional<K1NoFire> why = dumb_fire(s_.weapon))
                count_no_fire(*why);
            s_.st = St::WALK_END;
            break;
        }
        case St::FIRE_START: {
            // weapon.Fire(target, offset): the decision (a TractorBeam's is
            // the mixin's, decide_beam), then its effect. A decision or a
            // launch the mirror cannot make writes nothing (rolled back):
            // Fire returns False, a counted no-fire.
            const int64_t w = s_.weapon;
            const int64_t t = s_.fire_target;
            const size_t mark = s_.writes.size();
            s_.result = 0;
            s_.st = St::WALK_END;
            Outcome o;
            try {
                const SubsystemRow* wr = subrow(w);
                if (!wr) detail::fall_back("the fired weapon has no row");
                if (t == kRefUnrepresentable || (t >= 0 && !objrow(t)))
                    detail::fall_back("Fire's target cannot be named");
                o = wr->weapon_kind == kTractorBeam ? decide_beam(w, t)
                                                    : decide(w, t);
            } catch (const std::invalid_argument&) {
                k1_roll_back(m_, s_, mark);
                count_no_fire(K1NoFire::Decision);
                break;
            }
            ++c_.logged_sdk_fire;
            switch (fire_effect(w, t, o)) {
                case FireEnd::Fired: s_.result = 1; break;
                case FireEnd::Refused:
                case FireEnd::NotFired: break;
                case FireEnd::NoLaunch:
                    k1_roll_back(m_, s_, mark);
                    count_no_fire(K1NoFire::Launch);
                    break;
            }
            break;
        }

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
            // The walk's rollback mark: before its first write (NO FIRE).
            s_.walk_mark = s_.writes.size();
            s_.walk_entry_mark = s_.entries.size();
            // self._prune_targets(): a NEW list of the live entries.
            std::vector<int64_t> kept;
            for (const int64_t t : sysrow()._target_list)
                if (!object_dead(m_, t)) kept.push_back(t);
            // target = self._target_list[0] if self._target_list else None
            s_.target = kept.empty() ? -1 : kept.front();
            // Logged on EVERY walk, unchanged or not: Python's list is a NEW
            // object each time (AddTarget appends in place).
            write_target_list(s_.sys, std::move(kept));
            // offset = self._live_held_offset(): from the mirror (THE WALK
            // OFFSET); Python makes the object when a write names it.
            start_walk(s_.sys, s_.ship);
            ++c_.logged_walk_start;
            s_.st = St::UW_OFFSET;
            break;
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
                    // The pre-scan named every child, in this same call.
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
            if (!named_leaf(s_.weapon)) {
                walk_no_fire(K1NoFire::Walk);
                break;
            }
            // if ... not weapon.IsMemberOfGroup(working): continue
            if (s_.working != 0) {
                const int64_t p = subrow(s_.weapon)->_property;
                int64_t mask = 0;  // a None property: mask 0
                if (p != -1) {
                    const PropertyRow* pr = m_.property(p);
                    if (!pr) {
                        walk_no_fire(K1NoFire::Walk);
                        break;
                    }
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
        case St::UW_TRIED: {
            if (s_.tf_result) {
                fired_bookkeeping();
                break;
            }
            // weapon._target = None      (ClearTarget, NOT a timer reset)
            write_target(s_.weapon, -1);
            // if self.GetNumTargets() == 0 and weapon.IsDumbFire():
            //     weapon.FireDumb(0, 1)      (only TorpedoTube is dumb-capable)
            if (sysrow()._target_list.empty()) {
                const SubsystemRow* wr = subrow(s_.weapon);
                if (!wr) {
                    walk_no_fire(K1NoFire::Walk);
                    break;
                }
                if (wr->weapon_kind == kTorpedoTube) {
                    if (const std::optional<K1NoFire> why =
                            dumb_fire(s_.weapon)) {
                        walk_no_fire(*why);
                        break;
                    }
                }
            }
            next_delta();
            break;
        }
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
            return done();

        // ── WeaponSystem.try_fire_weapon ──────────────────────────────────
        case St::TF_TIMER: {
            const int64_t w = s_.tf_weapon;
            // Every begin_try names a live leaf in the same call.
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
                walk_no_fire(K1NoFire::CanFire);
                break;
            }
            // _charge_gate's `self._depleted = False`, written even when a
            // later gate refuses (Task 3 ruling).
            if (cf.clear_depleted)
                write_flag(w, Field::_depleted, "_depleted", false);
            if (!cf.ok) {
                // weapon.StopFiring(); return False
                if (!bank_stop(w)) {
                    walk_no_fire(K1NoFire::Walk);
                    break;
                }
                try_returns(false);
                break;
            }
            s_.fire_target = s_.target;
            s_.st = St::TF_FIRE;
            break;
        }
        case St::TF_FIRE: {
            // result = weapon.Fire(target, offset). A decision the mirror
            // cannot make undoes its own writes and is a no-fire; so is a
            // launch the kernel cannot make.
            const int64_t w = s_.tf_weapon;
            const size_t mark = s_.writes.size();
            Outcome o;
            try {
                o = decide(w, s_.fire_target);
            } catch (const std::invalid_argument&) {
                k1_roll_back(m_, s_, mark);
                walk_no_fire(K1NoFire::Decision);
                break;
            }
            switch (fire_effect(w, s_.fire_target, o)) {
                case FireEnd::Fired: s_.st = St::TF_FIRED; break;
                case FireEnd::Refused:
                case FireEnd::NotFired: s_.st = St::TF_NOT_FIRED; break;
                case FireEnd::NoLaunch:
                    k1_roll_back(m_, s_, mark);
                    walk_no_fire(K1NoFire::Launch);
                    break;
            }
            break;
        }
        case St::TF_FIRED:
            // _weapon_did_fire: the effect returned True
            try_returns(true);
            break;
        case St::TF_NOT_FIRED: {
            if (s_.in_retry) {  // the next entry
                ++s_.retry_pos;
                s_.st = St::TF_RETRY_NEXT;
                break;
            }
            // weapon._target = None
            write_target(s_.tf_weapon, -1);
            // for entry in list(self._target_list): the LIVE list, now. An
            // entry the mirror cannot read is treated as gone (NO FIRE,
            // after a shot).
            std::vector<int64_t> snap;
            bool unread = false;
            for (const int64_t e : sysrow()._target_list) {
                const ObjectRow* eo = objrow(e);
                if (!eo)
                    unread = true;
                else
                    snap.push_back(e);
            }
            if (unread) count_no_fire(K1NoFire::Retry);
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
            //     entry.IsDead()): continue -- an IsDead the mirror cannot
            // answer is treated as gone (NO FIRE, after a shot).
            bool dead;
            try {
                dead = object_dead(m_, e);
            } catch (const std::invalid_argument&) {
                count_no_fire(K1NoFire::IsDead);
                dead = true;
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

void K1Kernel::begin_tractor(int64_t system, int64_t target,
                             std::optional<Vec3> offset, double now,
                             bool use_memo, double drift_now) {
    auto s = std::make_unique<Session>();
    s->pump = false;
    s->sys = system;
    s->tractor_target = target;
    s->offset = offset;
    s->walk_no = 1;
    s->now = now;
    s->use_memo = use_memo;
    s->drift_now = drift_now;
    s->st = St::TRACTOR_START;
    sessions_.push_back(std::move(s));
}

void K1Kernel::begin_dumb(int64_t tube, double now, bool use_memo,
                          double drift_now) {
    auto s = std::make_unique<Session>();
    s->pump = false;
    s->weapon = tube;
    s->now = now;
    s->use_memo = use_memo;
    s->drift_now = drift_now;
    s->st = St::DUMB_START;
    sessions_.push_back(std::move(s));
}

void K1Kernel::begin_fire(int64_t weapon, int64_t target,
                          std::optional<Vec3> offset,
                          std::optional<int64_t> ship_target, double now,
                          bool use_memo, double drift_now) {
    auto s = std::make_unique<Session>();
    s->pump = false;
    s->weapon = weapon;
    s->fire_target = target;
    s->ship_target = ship_target;
    // The walk's offset is Fire's own (walk 1, materialised by the driver
    // with that object), named after the weapon's parent system.
    s->offset = offset;
    s->walk_no = 1;
    if (const SubsystemRow* r = m_.subsystem(weapon)) s->sys = r->_parent_subsystem;
    s->now = now;
    s->use_memo = use_memo;
    s->drift_now = drift_now;
    s->st = St::FIRE_START;
    sessions_.push_back(std::move(s));
}

CanFireResult K1Kernel::sdk_can_fire(int64_t weapon, double now) {
    const CanFireResult r = can_fire(m_, weapon, now);
    ++counts_.logged_sdk_can_fire;
    return r;
}

int64_t K1Kernel::result() const {
    if (sessions_.empty()) lost("no session is open");
    return sessions_.back()->result;
}

std::optional<Vec3> K1Kernel::walk_manual_offset(int64_t walk) const {
    if (sessions_.empty()) lost("no session is open");
    const Session& s = *sessions_.back();
    if (walk < 1 || walk > static_cast<int64_t>(s.walk_manual.size()))
        lost("walk_manual_offset: the session started no such walk");
    return s.walk_manual[static_cast<size_t>(walk - 1)];
}

K1Record K1Kernel::next() {
    if (sessions_.empty()) lost("no session is open");
    Session& s = *sessions_.back();
    // A throw must leave the session and the mirror as they were: every
    // unflushed write undone (mirror == Python), so abandon() -- or a retry
    // -- starts from a consistent state.
    Session before = s;
    try {
        Walker w(m_, s, counts_);
        return w.run();
    } catch (...) {
        k1_roll_back(m_, s, 0);
        s = std::move(before);
        throw;
    }
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

// ShipClass.is_using_target_offset (SHIPS:1805): bool(self._use_target_offset
// and self._manual_target_offset is not None), and GetTargetOffsetTG's copy of
// the manual pick. Only a ShipClass has the probe. The OFFSET mirror type
// reads "unset" for anything that is not a TGPoint3; ShipClass only ever
// stores a TGPoint3 or None there.
std::optional<Vec3> k1_manual_offset(const Mirror& m, int64_t ship) {
    if (const ObjectRow* so = ship < 0 ? nullptr : m.object(ship);
        so && so->is_ship_class && so->_use_target_offset &&
        so->manual_offset_set)
        return so->_manual_target_offset;
    return std::nullopt;
}

// WeaponSystem._live_held_offset (WS:1551-1564, deleted since):
//   if ship.is_using_target_offset(): return ship.GetTargetOffsetTG()
//   return getattr(self, "_held_offset", None)
std::optional<Vec3> k1_live_held_offset(const Mirror& m, int64_t system,
                                        int64_t ship) {
    if (std::optional<Vec3> manual = k1_manual_offset(m, ship)) return manual;
    const SubsystemRow* r = system < 0 ? nullptr : m.subsystem(system);
    if (!r) throw std::logic_error("combat K1: no row for the walked system");
    if (r->held_offset_set) return r->_held_offset;
    return std::nullopt;
}

K1Kernel& k1_kernel() {
    static K1Kernel k(mirror());
    return k;
}

}  // namespace dauntless::combat
