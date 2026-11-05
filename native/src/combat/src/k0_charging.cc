// The K0 charging kernel -- see k0_charging.h. Each pure step ports the
// Python method of the same name (file:line in its comment) statement by
// statement and in the same order: keep them in step. WS =
// engine/appc/weapon_subsystems.py; WSM = docs/reference/engine/
// native-combat/weapon-state-map.md.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/k0_charging.h"

#include <cstddef>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>

#include "dauntless/combat/fire_gates.h"
#include "dauntless/combat/py_math.h"
#include "dauntless/combat/sensor_detect.h"
#include "dauntless/combat/stop_firing.h"

namespace dauntless::combat {

namespace {

// Subsystem weapon_kind codes (mirror.h).
constexpr int64_t kPhaserSystem = 1, kTorpedoSystem = 4, kPhaserBank = 5,
                  kPulseWeapon = 6, kTractorBeam = 7, kTorpedoTube = 8;

// weapon_subsystems._SLOT_LOADED.
constexpr double kSlotLoaded = -1.0;

bool is_system_kind(int64_t k) { return k >= 1 && k <= 4; }

// The step hands the weapon to Python: nothing it computed is written.
void hand_back(K0Step& s, K0Reason r) {
    s.writes.clear();
    s.record = K0Kind::DONE;
    s.loop_stop = false;
    s.handback = r;
}

// `s` empty, keeping its storage (the session reuses one per kind).
void reset(K0Step& s) {
    s.handback.reset();
    s.record = K0Kind::DONE;
    s.loop_stop = false;
    s.watch_old = s.watch_new = 0.0;
    s.writes.clear();
}

void push_float(K0Step& s, Field f, double v) {
    K0FieldWrite w;
    w.type = K0FieldWrite::Type::Float;
    w.field = f;
    w.d = v;
    s.writes.push_back(w);
}

void push_flag(K0Step& s, Field f, bool v) {
    K0FieldWrite w;
    w.type = K0FieldWrite::Type::Flag;
    w.field = f;
    w.i = v ? 1 : 0;
    s.writes.push_back(w);
}

// `self.StopFiring()` on `w` (stop_firing.h): its class's writes, in its
// order. False: not a leaf whose stop K0 writes (nothing pushed).
bool push_stop(K0Step& s, const SubsystemRow& w) {
    const std::optional<StopFiring> stop = stop_firing_of(w.weapon_kind);
    if (!stop) return false;
    for (size_t i = 0; i < stop->n; ++i) {
        K0FieldWrite x;
        switch (stop->writes[i]) {
            case StopWrite::FiringFalse:
                push_flag(s, Field::_firing, false);
                continue;
            case StopWrite::BeamOnCountdownZero:
                push_float(s, Field::_beam_on_countdown, 0.0);
                continue;
            case StopWrite::TargetNone:
                x.type = K0FieldWrite::Type::Ref;
                x.field = Field::_target;
                x.i = -1;
                break;
            case StopWrite::TargetOffsetNone:
                x.type = K0FieldWrite::Type::Null;
                x.field = Field::_target_offset;
                break;
        }
        s.writes.push_back(x);
    }
    s.loop_stop = stop->loop_stop;
    return true;
}

void push_slot(K0Step& s, Field f, int64_t index, double v) {
    K0FieldWrite w;
    w.type = K0FieldWrite::Type::Slot;
    w.field = f;
    w.index = index;
    w.d = v;
    s.writes.push_back(w);
}

// `self.GetParentSubsystem()` where the caller goes on to call a
// PoweredSubsystem method on it (IsOn, GetNormalPowerPercentage): None, or
// a weapon system row. ok == false: the mirror cannot stand in for it
// (unnamed, gone, or a class whose methods only Python knows).
struct Parent {
    bool ok = true;
    const SubsystemRow* row = nullptr;  // nullptr: None
};

Parent powered_parent(const Mirror& m, const SubsystemRow& w) {
    const int64_t ref = w._parent_subsystem;
    if (ref == -1) return Parent{};
    const SubsystemRow* p = ref < 0 ? nullptr : m.subsystem(ref);
    if (p == nullptr || !is_system_kind(p->weapon_kind)) return Parent{false};
    return Parent{true, p};
}

// PhaserBank._discharge_rate_per_second (WS:2660):
//   level = parent.GetPowerLevel() if hasattr(parent, "GetPowerLevel") else 1
//   PHASER_DISCHARGE_BY_POWER_LEVEL[level]   (IndexError/TypeError -> 0.0)
// Answered only where the tuple index lands on a pushed entry 0..2 (ruling
// W5); hasattr is vacuously true on any engine object, so a parent that is
// not a PhaserSystem is Python's.
struct Rate {
    std::optional<K0Reason> handback;
    double value = 0.0;
};

Rate phaser_discharge(const Mirror& m, const SubsystemRow& w) {
    int64_t level = 1;  // hasattr(None, "GetPowerLevel") is false
    const int64_t ref = w._parent_subsystem;
    if (ref != -1) {
        const SubsystemRow* p = ref < 0 ? nullptr : m.subsystem(ref);
        if (p == nullptr || p->weapon_kind != kPhaserSystem)
            return Rate{K0Reason::Parent};
        level = p->_power_level;  // PhaserSystem.GetPowerLevel
    }
    const Globals& g = m.globals();
    const int64_t len = g.PHASER_DISCHARGE_LEN;
    const int64_t pushed = len < 3 ? len : 3;
    int64_t index = -1;
    if (level >= 0 && level < pushed)
        index = level;
    else if (level < 0 && level >= -len && level + len < pushed)
        index = level + len;  // a negative tuple index
    switch (index) {
        case 0: return Rate{std::nullopt, g.PHASER_DISCHARGE_0};
        case 1: return Rate{std::nullopt, g.PHASER_DISCHARGE_1};
        case 2: return Rate{std::nullopt, g.PHASER_DISCHARGE_2};
        default: return Rate{K0Reason::PowerLevel};
    }
}

// TorpedoTube._reload_denied_by_ammo (WS:3345) for a tube under `parent`
// (nullptr: None). nullopt: the mirror cannot answer (`why`).
std::optional<bool> reload_denied_by_ammo(const Mirror& m,
                                          const SubsystemRow* parent,
                                          K0Reason* why) {
    // _parent_ammo: None without a parent; else parent.GetCurrentAmmoType(),
    // which only a TorpedoSystem answers natively.
    if (parent == nullptr) return false;
    if (parent->weapon_kind != kTorpedoSystem) {
        *why = K0Reason::Parent;
        return std::nullopt;
    }
    const AmmoRow* ammo;
    try {
        ammo = current_ammo_type(m, *parent);
    } catch (const std::invalid_argument&) {
        *why = K0Reason::Unrepresentable;
        return std::nullopt;
    }
    // finite = ammo is not None and not getattr(ammo, "_unlimited", True)
    if (ammo == nullptr || ammo->_unlimited) return false;
    // _rounds_loaded_systemwide (WS:3324): GetNumReady() over the parent's
    // _children that are TorpedoTubes.
    int64_t total = 0;
    for (const int64_t c : parent->_children) {
        const SubsystemRow* r = c < 0 ? nullptr : m.subsystem(c);
        if (r == nullptr) {
            *why = K0Reason::Unrepresentable;
            return std::nullopt;
        }
        if (r->weapon_kind == kTorpedoTube) total += r->_num_ready;
    }
    return ammo->_available <= total;
}

[[noreturn]] void lost(const char* why) {
    throw std::logic_error(std::string("combat K0: ") + why);
}

}  // namespace

const char* k0_kind_name(K0Kind k) {
    switch (k) {
        case K0Kind::DONE: return "DONE";
        case K0Kind::DEPLETE_STOP: return "DEPLETE_STOP";
        case K0Kind::RELOADED: return "RELOADED";
        case K0Kind::WATCH: return "WATCH";
        case K0Kind::RUN_PYTHON: return "RUN_PYTHON";
        case K0Kind::HOLD_STOP: return "HOLD_STOP";
        case K0Kind::kCount: break;
    }
    return "?";
}

const char* k0_reason_name(K0Reason r) {
    switch (r) {
        case K0Reason::NoRow: return "no_row";
        case K0Reason::NotWeaponSystem: return "not_weapon_system";
        case K0Reason::StaleRow: return "stale_row";
        case K0Reason::SlotHeal: return "slot_heal";
        case K0Reason::Override: return "override";
        case K0Reason::Audit: return "audit";
        case K0Reason::PowerLevel: return "power_level";
        case K0Reason::Parent: return "parent";
        case K0Reason::Unrepresentable: return "unrepresentable";
        case K0Reason::UnknownKind: return "unknown_kind";
        case K0Reason::Watcher: return "watcher";
        case K0Reason::kCount: break;
    }
    return "?";
}

const char* k0_effect_name(K0Effect e) {
    switch (e) {
        case K0Effect::LOOP_STOP: return "LOOP_STOP";
        case K0Effect::TORPEDO_RELOAD: return "TORPEDO_RELOAD";
        case K0Effect::WATCH: return "WATCH";
        case K0Effect::kCount: break;
    }
    return "?";
}

// ── The pure steps ─────────────────────────────────────────────────────────
// Each is written once, appending to a K0Step the caller owns (the session
// passes its reused buffers, so a steady walk allocates nothing); the public
// step_* / pulse_watch wrap them in a fresh one.

namespace {

// _EnergyWeaponFireMixin.UpdateCharge (WS:957).
void energy_into(const Mirror& m, int64_t weapon, double dt, K0Step& s) {
    const SubsystemRow* w = weapon < 0 ? nullptr : m.subsystem(weapon);
    if (w == nullptr) return hand_back(s, K0Reason::StaleRow);
    // TractorBeam.UpdateCharge (WS:3291): a holding tractor (fire control
    // native only, M4). Its stop's `_firing` applies through the beam's
    // NativeThawParentWakeField setter, so the parent's power program still
    // thaws. An idle one is `super().UpdateCharge(dt)`, this mixin step
    // (ruling W6).
    if (w->weapon_kind == kTractorBeam && w->_firing) {
        // parent = self.GetParentSubsystem()
        const Parent p = powered_parent(m, *w);
        if (!p.ok) return hand_back(s, K0Reason::Parent);
        // if parent is None or not parent.IsOn(): self.StopFiring()
        // elif parent.GetPowerPercentage() <= 0.0 and
        //      parent.GetNormalPowerWanted() > 0.0: self.StopFiring()
        // (the starvation gate) -- else no discharge while holding.
        if (p.row == nullptr || !p.row->_is_on ||
            (p.row->_efficiency <= 0.0 && p.row->_normal_power > 0.0)) {
            push_stop(s, *w);
            s.record = K0Kind::HOLD_STOP;
        }
        return;
    }
    if (w->_firing) {
        if (w->_beam_on_countdown > 0.0) {
            // self._beam_on_countdown -= dt; return
            push_float(s, Field::_beam_on_countdown, w->_beam_on_countdown - dt);
            return;
        }
        // self._discharge_rate_per_second(): PhaserBank's table; the mixin's
        // _normal_discharge_rate for a pulse cannon.
        double rate = w->_normal_discharge_rate;
        if (w->weapon_kind == kPhaserBank) {
            const Rate r = phaser_discharge(m, *w);
            if (r.handback) return hand_back(s, *r.handback);
            rate = r.value;
        }
        // self._charge_level = max(0.0, self._charge_level - rate * dt)
        const double charge = py_max(0.0, w->_charge_level - rate * dt);
        push_float(s, Field::_charge_level, charge);
        if (charge <= 0.0) {
            // self._depleted = True; self.StopFiring(): the stop's writes,
            // then (a phaser bank) its loop sound's LOOP_STOP, which the
            // session queues (THE EFFECT QUEUE). A firing tractor never gets
            // here (handed back above): a kind with no stop is Python's.
            push_flag(s, Field::_depleted, true);
            if (!push_stop(s, *w)) return hand_back(s, K0Reason::UnknownKind);
            s.record = K0Kind::DEPLETE_STOP;
        }
        return;
    }
    // if self._max_charge - self._charge_level <= 0.0: return
    if (w->_max_charge - w->_charge_level <= 0.0) return;
    const Parent p = powered_parent(m, *w);
    if (!p.ok) return hand_back(s, K0Reason::Parent);
    if (p.row == nullptr || p.row->_is_on) {  // parent is None or IsOn()
        // max(0.0, parent.GetNormalPowerPercentage() if parent else 1.0)
        const double power_factor =
            py_max(0.0, p.row != nullptr ? p.row->_power_factor : 1.0);
        double condition_factor;  // self.GetConditionPercentage()
        try {
            condition_factor = condition_percentage(m, *w);
        } catch (const std::invalid_argument&) {
            return hand_back(s, K0Reason::Unrepresentable);
        }
        const double headroom = w->_max_charge - w->_charge_level;
        if (headroom > 0.0) {
            const double want = py_min(
                w->_recharge_rate * power_factor * condition_factor * dt,
                headroom);
            push_float(s, Field::_charge_level, w->_charge_level + want);
        }
    }
}

// PulseWeapon.UpdateCharge (WS:2970), up to the watcher line.
void pulse_into(const Mirror& m, int64_t weapon, double dt, K0Step& s) {
    const SubsystemRow* w = weapon < 0 ? nullptr : m.subsystem(weapon);
    if (w == nullptr) return hand_back(s, K0Reason::StaleRow);
    // A watcher the weapon does not own (WATCH_ALWAYS) runs its own
    // `_update` at the step's last line: the whole step is Python's.
    if (w->_watch_checks < 0) return hand_back(s, K0Reason::Watcher);
    if (w->_cooldown_remaining > 0.0)
        push_float(s, Field::_cooldown_remaining,
                   py_max(0.0, w->_cooldown_remaining - dt));
    // _EnergyWeaponFireMixin.UpdateCharge(self, dt): reads no cooldown.
    // Its writes follow the cooldown's; its hand-back discards both.
    energy_into(m, weapon, dt, s);
}

// self._charge_watcher._update(self.GetChargePercentage()) (WS:3020), the
// owned FloatRangeWatcher's (float_range_watcher.py) inside the effect
// queue's deferral: `self._value = float(new_value)`, and with checks
// WATCH(self, old, new) for delivery to fire the crossings.
void watch_into(const Mirror& m, int64_t weapon, K0Step& s) {
    const SubsystemRow* w = weapon < 0 ? nullptr : m.subsystem(weapon);
    if (w == nullptr) return hand_back(s, K0Reason::StaleRow);
    if (w->_watch_checks < 0) return hand_back(s, K0Reason::Watcher);
    // PulseWeapon.GetChargePercentage (WS:2841).
    const double value =
        (w->_max_charge <= 0.0) ? 0.0 : w->_charge_level / w->_max_charge;
    K0FieldWrite x;
    x.type = K0FieldWrite::Type::Watcher;
    x.field = Field::_watch_value;  // the mirror's copy of `_value`
    x.d = value;
    s.writes.push_back(x);
    if (w->_watch_checks > 0) {
        s.record = K0Kind::WATCH;
        s.watch_old = w->_watch_value;
        s.watch_new = value;
    }
}

// TorpedoTube.UpdateReload (WS:3589) + ReloadTorpedo (WS:3652). `timers`
// and `advanced`: scratch for the slot lists' new values.
void tube_into(const Mirror& m, int64_t tube, double now, K0Step& s,
               std::vector<double>& timers, std::vector<double>& advanced) {
    const SubsystemRow* t = tube < 0 ? nullptr : m.subsystem(tube);
    if (t == nullptr) return hand_back(s, K0Reason::StaleRow);
    // self._ensure_slots(): a length mismatch rebinds both lists (Python's).
    const auto max_ready = t->_max_ready;
    if (static_cast<int64_t>(t->_reload_timers.size()) != max_ready ||
        static_cast<int64_t>(t->_reload_advanced_at.size()) != max_ready)
        return hand_back(s, K0Reason::SlotHeal);
    if (t->_num_ready >= max_ready) return;
    // factor = parent.GetNormalPowerPercentage() if parent is not None
    //          else 1.0; non-number or < 0.0 -> 0.0 (NaN passes).
    const Parent p = powered_parent(m, *t);
    if (!p.ok) return hand_back(s, K0Reason::Parent);
    double factor = p.row != nullptr ? p.row->_power_factor : 1.0;
    if (factor < 0.0) factor = 0.0;
    timers.assign(t->_reload_timers.begin(), t->_reload_timers.end());
    advanced.assign(t->_reload_advanced_at.begin(),
                    t->_reload_advanced_at.end());
    for (size_t i = 0; i < timers.size(); ++i) {
        const double prog = timers[i];
        if (prog == kSlotLoaded) continue;
        double game_dt = now - advanced[i];
        if (game_dt < 0.0) game_dt = 0.0;
        timers[i] = prog + factor * game_dt;
        advanced[i] = now;
        push_slot(s, Field::_reload_timers, static_cast<int64_t>(i), timers[i]);
        push_slot(s, Field::_reload_advanced_at, static_cast<int64_t>(i), now);
    }
    bool reload = false;
    for (const double prog : timers) {
        if (prog != kSlotLoaded && prog >= t->_reload_delay) {
            reload = true;  // self.ReloadTorpedo(); return  (one per call)
            break;
        }
    }
    if (!reload) return;
    // ReloadTorpedo: _ensure_slots() (lengths unchanged) and the NumReady
    // check (unchanged since UpdateReload's) pass; then the ammo gate.
    K0Reason why = K0Reason::Unrepresentable;
    const std::optional<bool> denied = reload_denied_by_ammo(m, p.row, &why);
    if (!denied) return hand_back(s, why);
    if (*denied) return;
    // The largest progress, strict `>`: the first index wins ties, and a
    // NaN first seen is never beaten.
    int64_t oldest_i = -1;
    double oldest_t = 0.0;
    for (size_t i = 0; i < timers.size(); ++i) {
        const double v = timers[i];
        if (v == kSlotLoaded) continue;
        if (oldest_i < 0 || v > oldest_t) {
            oldest_i = static_cast<int64_t>(i);
            oldest_t = v;
        }
    }
    if (oldest_i < 0) return;
    push_slot(s, Field::_reload_timers, oldest_i, kSlotLoaded);
    K0FieldWrite n;  // self._num_ready += 1
    n.type = K0FieldWrite::Type::Int;
    n.field = Field::_num_ready;
    n.i = t->_num_ready + 1;
    s.writes.push_back(n);
    s.record = K0Kind::RELOADED;  // self._broadcast_reload() (Python's)
}

}  // namespace

K0Step step_energy(const Mirror& m, int64_t weapon, double dt) {
    K0Step s;
    energy_into(m, weapon, dt, s);
    return s;
}

K0Step step_pulse(const Mirror& m, int64_t weapon, double dt) {
    K0Step s;
    pulse_into(m, weapon, dt, s);
    return s;
}

K0Step pulse_watch(const Mirror& m, int64_t weapon) {
    K0Step s;
    watch_into(m, weapon, s);
    return s;
}

K0Step step_tube(const Mirror& m, int64_t tube, double now) {
    K0Step s;
    std::vector<double> timers, advanced;
    tube_into(m, tube, now, s, timers, advanced);
    return s;
}

// ── The session ────────────────────────────────────────────────────────────

namespace {

struct Entry {
    int64_t handle = -1;
    int32_t group = 0;
    int64_t index = 0;
};

struct ShipPlan {
    int64_t ship = -1;
    std::optional<K0Reason> handback;
    std::vector<Entry> weapons;
};

// The mirror value one logged write replaced. Floats: a slot list as it was
// before its step's first element write, `floats[from, from + n)` of the
// log's undo_floats.
struct K0Undo {
    enum class Type : int32_t { F, I, Floats, Ref, Offset } type = Type::F;
    int64_t h = -1;
    Field f = Field::kCount;
    double d = 0.0;
    int64_t i = 0;
    size_t from = 0, n = 0;
    Vec3 v{0, 0, 0};   // Offset
    bool set = false;  // Offset
};

ShipPlan plan_ship(const Mirror& m, int64_t ship,
                   const std::optional<K0Reason>& handback) {
    ShipPlan sp;
    sp.ship = ship;
    if (handback) {
        sp.handback = handback;
        return sp;
    }
    const ObjectRow* o = ship < 0 ? nullptr : m.object(ship);
    if (o == nullptr) {
        sp.handback = K0Reason::NoRow;
        return sp;
    }
    if (!o->is_ship_class) {
        sp.handback = K0Reason::NotWeaponSystem;
        return sp;
    }
    // The group order of passive_weapons._groups.
    const int64_t refs[4] = {o->_phaser_system, o->_pulse_weapon_system,
                             o->_tractor_beam_system, o->_torpedo_system};
    for (int32_t g = 0; g < 4; ++g) {
        const int64_t ref = refs[g];
        if (ref == -1) continue;  // `if group is None: continue`
        const SubsystemRow* sys = ref < 0 ? nullptr : m.subsystem(ref);
        if (sys == nullptr || !is_system_kind(sys->weapon_kind)) {
            sp.weapons.clear();
            sp.handback = K0Reason::NotWeaponSystem;
            return sp;
        }
        // GetWeapon(i) for i in range(GetNumWeapons()): `_children`, raw (a
        // stale entry keeps its index; it hands back at its turn).
        for (size_t i = 0; i < sys->_children.size(); ++i)
            sp.weapons.push_back(
                Entry{sys->_children[i], g, static_cast<int64_t>(i)});
    }
    return sp;
}

}  // namespace

struct K0Session::State {
    // Shared, so next()'s per-call backup of the state copies no list.
    std::shared_ptr<const std::vector<ShipPlan>> plan;
    double dt = 0.0, now = 0.0;
    size_t ship_pos = 0, weapon_pos = 0;
    bool done = false;
};

// The write log since the last record and, one for one where the mirror
// holds the field (one per slot list per step), the value each write
// replaced. Owned by the session, not the cursor: cleared at each next(),
// never freed, so its storage is reused across calls and sessions.
struct K0Session::Log {
    std::vector<K0Write> writes;
    // The queue entries since the last record (THE EFFECT QUEUE), dropped
    // with the writes on a throw.
    std::vector<K0Entry> entries;
    std::vector<K0Undo> undo;
    std::vector<double> undo_floats;
    // The steps' scratch: a weapon's step, a pulse cannon's watcher line,
    // a tube's new slot lists.
    K0Step step, watch;
    std::vector<double> timers, advanced;
    void clear() {
        writes.clear();
        entries.clear();
        undo.clear();
        undo_floats.clear();
    }
};

K0Session::K0Session(Mirror& m) : m_(m), log_(std::make_unique<Log>()) {
    log_->writes.reserve(1024);
    log_->undo.reserve(1024);
}
K0Session::~K0Session() = default;

bool K0Session::open() const { return s_ != nullptr; }

void K0Session::begin(std::vector<int64_t> ships, double dt, double now,
                      std::vector<std::optional<K0Reason>> ship_handback) {
    if (s_) lost("a session is already open");
    if (!ship_handback.empty() && ship_handback.size() != ships.size())
        throw std::invalid_argument(
            "combat K0: ship_handback needs one entry per ship");
    auto plan = std::make_shared<std::vector<ShipPlan>>();
    plan->reserve(ships.size());
    for (size_t i = 0; i < ships.size(); ++i)
        plan->push_back(plan_ship(
            m_, ships[i],
            ship_handback.empty() ? std::nullopt : ship_handback[i]));
    auto s = std::make_unique<State>();
    s->plan = std::move(plan);
    s->dt = dt;
    s->now = now;
    s_ = std::move(s);
}

namespace {

// One next() call: runs the cursor to the next record.
class Walker {
public:
    Walker(Mirror& m, K0Session::State& s, K0Session::Log& log,
           K0Session::Counts& c, const K0WeaponCheck& check)
        : m_(m), s_(s), log_(log), c_(c), check_(check) {}

    K0Record run();

private:
    // Make one step's writes in the mirror and log them.
    void apply(int64_t h, const K0Step& st) {
        // The slot lists this step has already snapshotted (one undo per
        // list per step: the state before its first element write).
        bool snapped_timers = false, snapped_advanced = false;
        for (const K0FieldWrite& w : st.writes) {
            K0Undo u;
            u.h = h;
            u.f = w.field;
            switch (w.type) {
                case K0FieldWrite::Type::Float:
                    u.type = K0Undo::Type::F;
                    u.d = m_.get_f(h, w.field);
                    m_.set_f(h, w.field, w.d);
                    log_.undo.push_back(u);
                    break;
                case K0FieldWrite::Type::Flag:
                case K0FieldWrite::Type::Int:
                    u.type = K0Undo::Type::I;
                    u.i = m_.get_i(h, w.field);
                    m_.set_i(h, w.field, w.i);
                    log_.undo.push_back(u);
                    break;
                case K0FieldWrite::Type::Slot: {
                    bool& snapped = w.field == Field::_reload_timers
                                        ? snapped_timers
                                        : snapped_advanced;
                    if (!snapped) {
                        const SubsystemRow* r = m_.subsystem(h);
                        if (r == nullptr) lost("a slot write's row is gone");
                        const std::vector<double>& list =
                            w.field == Field::_reload_timers
                                ? r->_reload_timers
                                : r->_reload_advanced_at;
                        u.type = K0Undo::Type::Floats;
                        u.from = log_.undo_floats.size();
                        u.n = list.size();
                        log_.undo_floats.insert(log_.undo_floats.end(),
                                                list.begin(), list.end());
                        log_.undo.push_back(u);
                        snapped = true;
                    }
                    m_.set_float_at(h, w.field, static_cast<size_t>(w.index),
                                    w.d);
                    break;
                }
                case K0FieldWrite::Type::Watcher: {
                    // The watcher is not mirrored; its value is, on the
                    // weapon's row (`_watch_value`, WATCH's old value).
                    // The same bits are not logged (Counts::
                    // identical_writes): the owned watcher already holds
                    // that float. The step's WATCH entry is queued anyway.
                    const double was = m_.get_f(h, Field::_watch_value);
                    if (std::memcmp(&was, &w.d, sizeof was) == 0) {
                        ++c_.identical_writes;
                        continue;
                    }
                    u.type = K0Undo::Type::F;
                    u.f = Field::_watch_value;
                    u.d = was;
                    m_.set_f(h, Field::_watch_value, w.d);
                    log_.undo.push_back(u);
                    break;
                }
                case K0FieldWrite::Type::Ref:
                    u.type = K0Undo::Type::Ref;
                    u.i = m_.get_ref(h, w.field);
                    m_.set_ref(h, w.field, w.i);
                    log_.undo.push_back(u);
                    break;
                case K0FieldWrite::Type::Null: {  // `_target_offset = None`
                    const SubsystemRow* r = m_.subsystem(h);
                    if (r == nullptr) lost("a stop's row is gone");
                    u.type = K0Undo::Type::Offset;
                    u.set = r->target_offset_set;
                    u.v = r->_target_offset;
                    m_.set_fv(h, w.field, {});
                    log_.undo.push_back(u);
                    break;
                }
            }
            log_.writes.push_back(K0Write{h, w});
        }
        // The effect the step ends with, after its writes (THE EFFECT QUEUE).
        switch (st.record) {
            case K0Kind::DEPLETE_STOP:
                ++c_.logged_deplete_stop;
                if (st.loop_stop) enqueue(K0Effect::LOOP_STOP, h);
                break;
            case K0Kind::HOLD_STOP:
                ++c_.logged_hold_stop;
                if (st.loop_stop) enqueue(K0Effect::LOOP_STOP, h);
                break;
            case K0Kind::RELOADED:
                ++c_.logged_reload;
                enqueue(K0Effect::TORPEDO_RELOAD, h);
                break;
            case K0Kind::WATCH:
                ++c_.logged_watch;
                enqueue(K0Effect::WATCH, h, st.watch_old, st.watch_new);
                break;
            default:
                break;
        }
    }

    void enqueue(K0Effect kind, int64_t a, double old_value = 0.0,
                 double new_value = 0.0) {
        log_.entries.push_back(
            K0Entry{kind, a, old_value, new_value, log_.writes.size()});
        ++c_.entries[static_cast<size_t>(kind)];
    }

    K0Record emit(K0Kind kind, int64_t a, int64_t ship_pos, int32_t group,
                  int64_t index, std::optional<K0Reason> reason = std::nullopt) {
        K0Record r;
        r.kind = kind;
        r.a = a;
        r.ship_pos = ship_pos;
        r.group = group;
        r.index = index;
        r.reason = reason;
        c_.logged_writes += static_cast<int64_t>(log_.writes.size());
        r.writes = std::span<const K0Write>(log_.writes.data(),
                                            log_.writes.size());
        r.entries = std::span<const K0Entry>(log_.entries.data(),
                                             log_.entries.size());
        log_.undo.clear();  // delivered: Python applies them
        log_.undo_floats.clear();
        c_.records[static_cast<size_t>(kind)] += 1;
        if (reason) c_.python_reasons[static_cast<size_t>(*reason)] += 1;
        return r;
    }

    Mirror& m_;
    K0Session::State& s_;
    K0Session::Log& log_;
    K0Session::Counts& c_;
    const K0WeaponCheck& check_;
};

K0Record Walker::run() {
    const std::vector<ShipPlan>& plan = *s_.plan;
    while (s_.ship_pos < plan.size()) {
        const ShipPlan& sp = plan[s_.ship_pos];
        const int64_t pos = static_cast<int64_t>(s_.ship_pos);
        if (sp.handback) {
            ++s_.ship_pos;
            s_.weapon_pos = 0;
            return emit(K0Kind::RUN_PYTHON, sp.ship, pos, -1, -1, sp.handback);
        }
        while (s_.weapon_pos < sp.weapons.size()) {
            const Entry& e = sp.weapons[s_.weapon_pos];
            const int64_t h = e.handle;
            auto python = [&](K0Reason why) {
                ++s_.weapon_pos;
                return emit(K0Kind::RUN_PYTHON, h, pos, e.group, e.index, why);
            };
            if (h == kRefUnrepresentable) return python(K0Reason::Unrepresentable);
            const SubsystemRow* row = h < 0 ? nullptr : m_.subsystem(h);
            if (row == nullptr) return python(K0Reason::StaleRow);
            const int64_t kind = row->weapon_kind;
            // Neither a TorpedoTube nor an _EnergyWeaponFireMixin: skipped.
            if (is_system_kind(kind)) {
                ++s_.weapon_pos;
                continue;
            }
            if (kind != kPhaserBank && kind != kPulseWeapon &&
                kind != kTorpedoTube && kind != kTractorBeam)
                return python(K0Reason::UnknownKind);
            if (check_ && check_(h)) return python(K0Reason::Override);
            K0Step& st = log_.step;
            reset(st);
            if (kind == kPulseWeapon)
                pulse_into(m_, h, s_.dt, st);
            else if (kind == kTorpedoTube)
                tube_into(m_, h, s_.now, st, log_.timers, log_.advanced);
            else
                energy_into(m_, h, s_.dt, st);
            if (st.handback) return python(*st.handback);
            ++c_.steps;
            apply(h, st);  // its writes, then its entry (a stop, a reload)
            if (kind == kPulseWeapon) {
                // The watcher line, on the mirror the step just wrote (no
                // Python ran since: it cannot hand back now).
                K0Step& w = log_.watch;
                reset(w);
                watch_into(m_, h, w);
                if (w.handback) lost("a stepped pulse cannon's watcher line");
                apply(h, w);
            }
            ++s_.weapon_pos;
        }
        ++s_.ship_pos;
        s_.weapon_pos = 0;
    }
    s_.done = true;
    return emit(K0Kind::DONE, -1, -1, -1, -1);
}

// Undo the logged writes not yet returned, newest first.
void roll_back(Mirror& m, K0Session::Log& log) {
    while (!log.undo.empty()) {
        const K0Undo& u = log.undo.back();
        switch (u.type) {
            case K0Undo::Type::F: m.set_f(u.h, u.f, u.d); break;
            case K0Undo::Type::I: m.set_i(u.h, u.f, u.i); break;
            case K0Undo::Type::Ref: m.set_ref(u.h, u.f, u.i); break;
            case K0Undo::Type::Offset:
                if (u.set)
                    m.set_fv(u.h, u.f, {u.v[0], u.v[1], u.v[2]});
                else
                    m.set_fv(u.h, u.f, {});
                break;
            case K0Undo::Type::Floats: {
                const auto first = log.undo_floats.begin() +
                                   static_cast<std::ptrdiff_t>(u.from);
                m.set_floats(u.h, u.f,
                             std::vector<double>(
                                 first, first + static_cast<std::ptrdiff_t>(u.n)));
                break;
            }
        }
        log.undo.pop_back();
    }
    log.clear();
}

}  // namespace

K0Record K0Session::next() {
    if (delivering_)
        lost("next() while the previous record's writes are being "
             "delivered (re-entered from the Python they run)");
    if (!s_) lost("no session is open");
    if (s_->done) lost("the session already returned DONE");
    // The previous record's writes were delivered (its view ends here).
    log_->clear();
    // A throw must leave the session, the counters and the mirror as they
    // were: every unreturned write undone (mirror == Python), so abandon()
    // -- or a retry -- starts from a consistent state. The cursor holds no
    // list (the plan is shared, the log is the session's), so the copy is
    // cheap.
    const State before = *s_;
    const Counts counts_before = counts_;
    try {
        Walker w(m_, *s_, *log_, counts_, check_);
        return w.run();
    } catch (...) {
        roll_back(m_, *log_);
        *s_ = before;
        counts_ = counts_before;
        throw;
    }
}

void K0Session::end() {
    if (!s_) lost("no session is open");
    if (!s_->done) lost("the session has not returned DONE");
    s_.reset();
}

void K0Session::abandon() {
    if (!s_) lost("no session is open");
    s_.reset();
}

K0Session& k0_session() {
    static K0Session k(mirror());
    return k;
}

}  // namespace dauntless::combat
