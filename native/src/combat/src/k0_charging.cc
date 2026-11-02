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
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>

#include "dauntless/combat/fire_gates.h"
#include "dauntless/combat/py_math.h"
#include "dauntless/combat/sensor_detect.h"

namespace dauntless::combat {

namespace {

// Subsystem weapon_kind codes (mirror.h).
constexpr int64_t kPhaserSystem = 1, kTorpedoSystem = 4, kPhaserBank = 5,
                  kPulseWeapon = 6, kTractorBeam = 7, kTorpedoTube = 8;

// weapon_subsystems._SLOT_LOADED.
constexpr double kSlotLoaded = -1.0;

bool is_system_kind(int64_t k) { return k >= 1 && k <= 4; }

K0Step hand_back(K0Reason r) {
    K0Step s;
    s.handback = r;
    return s;
}

void push_float(K0Step& s, Field f, double v) {
    K0FieldWrite w;
    w.type = K0FieldWrite::Type::Float;
    w.field = f;
    w.d = v;
    s.writes.push_back(w);
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
        case K0Kind::kCount: break;
    }
    return "?";
}

const char* k0_reason_name(K0Reason r) {
    switch (r) {
        case K0Reason::Tractor: return "tractor";
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
        case K0Reason::kCount: break;
    }
    return "?";
}

// ── The pure steps ─────────────────────────────────────────────────────────

// _EnergyWeaponFireMixin.UpdateCharge (WS:957).
K0Step step_energy(const Mirror& m, int64_t weapon, double dt) {
    const SubsystemRow* w = weapon < 0 ? nullptr : m.subsystem(weapon);
    if (w == nullptr) return hand_back(K0Reason::StaleRow);
    K0Step s;
    if (w->_firing) {
        if (w->_beam_on_countdown > 0.0) {
            // self._beam_on_countdown -= dt; return
            push_float(s, Field::_beam_on_countdown, w->_beam_on_countdown - dt);
            return s;
        }
        // self._discharge_rate_per_second(): PhaserBank's table; the mixin's
        // _normal_discharge_rate for a pulse cannon.
        double rate = w->_normal_discharge_rate;
        if (w->weapon_kind == kPhaserBank) {
            const Rate r = phaser_discharge(m, *w);
            if (r.handback) return hand_back(*r.handback);
            rate = r.value;
        }
        // self._charge_level = max(0.0, self._charge_level - rate * dt)
        const double charge = py_max(0.0, w->_charge_level - rate * dt);
        push_float(s, Field::_charge_level, charge);
        if (charge <= 0.0) {
            // self._depleted = True; self.StopFiring() (Python's: the record)
            K0FieldWrite d;
            d.type = K0FieldWrite::Type::Flag;
            d.field = Field::_depleted;
            d.i = 1;
            s.writes.push_back(d);
            s.record = K0Kind::DEPLETE_STOP;
        }
        return s;
    }
    // if self._max_charge - self._charge_level <= 0.0: return
    if (w->_max_charge - w->_charge_level <= 0.0) return s;
    const Parent p = powered_parent(m, *w);
    if (!p.ok) return hand_back(K0Reason::Parent);
    if (p.row == nullptr || p.row->_is_on) {  // parent is None or IsOn()
        // max(0.0, parent.GetNormalPowerPercentage() if parent else 1.0)
        const double power_factor =
            py_max(0.0, p.row != nullptr ? p.row->_power_factor : 1.0);
        double condition_factor;  // self.GetConditionPercentage()
        try {
            condition_factor = condition_percentage(m, *w);
        } catch (const std::invalid_argument&) {
            return hand_back(K0Reason::Unrepresentable);
        }
        const double headroom = w->_max_charge - w->_charge_level;
        if (headroom > 0.0) {
            const double want = py_min(
                w->_recharge_rate * power_factor * condition_factor * dt,
                headroom);
            push_float(s, Field::_charge_level, w->_charge_level + want);
        }
    }
    return s;
}

// PulseWeapon.UpdateCharge (WS:2970), up to the watcher line.
K0Step step_pulse(const Mirror& m, int64_t weapon, double dt) {
    const SubsystemRow* w = weapon < 0 ? nullptr : m.subsystem(weapon);
    if (w == nullptr) return hand_back(K0Reason::StaleRow);
    K0Step s;
    if (w->_cooldown_remaining > 0.0)
        push_float(s, Field::_cooldown_remaining,
                   py_max(0.0, w->_cooldown_remaining - dt));
    // _EnergyWeaponFireMixin.UpdateCharge(self, dt): reads no cooldown.
    K0Step e = step_energy(m, weapon, dt);
    if (e.handback) return e;
    s.writes.insert(s.writes.end(), e.writes.begin(), e.writes.end());
    s.record = e.record;
    return s;
}

// self._charge_watcher._update(self.GetChargePercentage()) (WS:2980).
K0Step pulse_watch(const Mirror& m, int64_t weapon) {
    const SubsystemRow* w = weapon < 0 ? nullptr : m.subsystem(weapon);
    K0Step s;
    // FloatRangeWatcher._update: with checks, the crossings (Python's).
    if (w == nullptr || w->_watch_checks != 0) {
        s.record = K0Kind::WATCH;
        return s;
    }
    // PulseWeapon.GetChargePercentage (WS:2841); _update: self._value =
    // float(new_value).
    K0FieldWrite x;
    x.type = K0FieldWrite::Type::Watcher;
    x.d = (w->_max_charge <= 0.0) ? 0.0 : w->_charge_level / w->_max_charge;
    s.writes.push_back(x);
    return s;
}

// TorpedoTube.UpdateReload (WS:3589) + ReloadTorpedo (WS:3652).
K0Step step_tube(const Mirror& m, int64_t tube, double now) {
    const SubsystemRow* t = tube < 0 ? nullptr : m.subsystem(tube);
    if (t == nullptr) return hand_back(K0Reason::StaleRow);
    // self._ensure_slots(): a length mismatch rebinds both lists (Python's).
    const auto max_ready = t->_max_ready;
    if (static_cast<int64_t>(t->_reload_timers.size()) != max_ready ||
        static_cast<int64_t>(t->_reload_advanced_at.size()) != max_ready)
        return hand_back(K0Reason::SlotHeal);
    K0Step s;
    if (t->_num_ready >= max_ready) return s;
    // factor = parent.GetNormalPowerPercentage() if parent is not None
    //          else 1.0; non-number or < 0.0 -> 0.0 (NaN passes).
    const Parent p = powered_parent(m, *t);
    if (!p.ok) return hand_back(K0Reason::Parent);
    double factor = p.row != nullptr ? p.row->_power_factor : 1.0;
    if (factor < 0.0) factor = 0.0;
    std::vector<double> timers = t->_reload_timers;
    std::vector<double> advanced = t->_reload_advanced_at;
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
    if (!reload) return s;
    // ReloadTorpedo: _ensure_slots() (lengths unchanged) and the NumReady
    // check (unchanged since UpdateReload's) pass; then the ammo gate.
    K0Reason why = K0Reason::Unrepresentable;
    const std::optional<bool> denied = reload_denied_by_ammo(m, p.row, &why);
    if (!denied) return hand_back(why);
    if (*denied) return s;
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
    if (oldest_i < 0) return s;
    push_slot(s, Field::_reload_timers, oldest_i, kSlotLoaded);
    K0FieldWrite n;  // self._num_ready += 1
    n.type = K0FieldWrite::Type::Int;
    n.field = Field::_num_ready;
    n.i = t->_num_ready + 1;
    s.writes.push_back(n);
    s.record = K0Kind::RELOADED;  // self._broadcast_reload() (Python's)
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

// The mirror value one logged write replaced.
struct K0Undo {
    enum class Type : int32_t { F, I, Floats } type = Type::F;
    int64_t h = -1;
    Field f = Field::kCount;
    double d = 0.0;
    int64_t i = 0;
    std::vector<double> floats;
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
    // The pulse cannon at the cursor returned DEPLETE_STOP: its watcher line
    // runs at the next next().
    bool pending_watch = false;
    bool done = false;
    // The write log since the last record, and, one for one where the
    // mirror holds the field, the value each write replaced.
    std::vector<LoggedWrite> writes;
    std::vector<K0Undo> undo;
};

K0Session::K0Session(Mirror& m) : m_(m) {}
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
    Walker(Mirror& m, K0Session::State& s, K0Session::Counts& c,
           const K0WeaponCheck& check)
        : m_(m), s_(s), c_(c), check_(check) {}

    K0Record run();

private:
    // Make one step's writes in the mirror and log them.
    void apply(int64_t h, const K0Step& st) {
        for (const K0FieldWrite& w : st.writes) {
            K0Undo u;
            u.h = h;
            u.f = w.field;
            switch (w.type) {
                case K0FieldWrite::Type::Float:
                    u.type = K0Undo::Type::F;
                    u.d = m_.get_f(h, w.field);
                    m_.set_f(h, w.field, w.d);
                    s_.undo.push_back(std::move(u));
                    log(h, field_name(w.field), w.d);
                    break;
                case K0FieldWrite::Type::Flag:
                    u.type = K0Undo::Type::I;
                    u.i = m_.get_i(h, w.field);
                    m_.set_i(h, w.field, w.i);
                    s_.undo.push_back(std::move(u));
                    log(h, field_name(w.field), w.i != 0);
                    break;
                case K0FieldWrite::Type::Int:
                    u.type = K0Undo::Type::I;
                    u.i = m_.get_i(h, w.field);
                    m_.set_i(h, w.field, w.i);
                    s_.undo.push_back(std::move(u));
                    log(h, field_name(w.field), w.i);
                    break;
                case K0FieldWrite::Type::Slot: {
                    u.type = K0Undo::Type::Floats;
                    u.floats = m_.get_floats(h, w.field);
                    std::vector<double> v = u.floats;
                    v.at(static_cast<size_t>(w.index)) = w.d;
                    m_.set_floats(h, w.field, v);
                    s_.undo.push_back(std::move(u));
                    log(h, field_name(w.field), SlotWrite{w.index, w.d});
                    break;
                }
                case K0FieldWrite::Type::Watcher:
                    // Not mirrored: nothing to undo.
                    log(h, "_charge_watcher", WatcherWrite{w.d});
                    break;
            }
        }
    }
    void log(int64_t h, const char* field, LoggedValue v) {
        s_.writes.push_back(LoggedWrite{h, field, std::move(v)});
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
        c_.logged_writes += static_cast<int64_t>(s_.writes.size());
        r.writes = std::move(s_.writes);
        s_.writes.clear();
        s_.undo.clear();  // delivered: Python applies them
        c_.records[static_cast<size_t>(kind)] += 1;
        if (reason) c_.python_reasons[static_cast<size_t>(*reason)] += 1;
        return r;
    }

    Mirror& m_;
    K0Session::State& s_;
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
            if (s_.pending_watch) {  // the depleted pulse cannon's last line
                s_.pending_watch = false;
                ++s_.weapon_pos;
                const K0Step w = pulse_watch(m_, h);
                apply(h, w);
                if (w.record == K0Kind::WATCH)
                    return emit(K0Kind::WATCH, h, pos, e.group, e.index);
                continue;
            }
            if (h == kRefUnrepresentable) return python(K0Reason::Unrepresentable);
            const SubsystemRow* row = h < 0 ? nullptr : m_.subsystem(h);
            if (row == nullptr) return python(K0Reason::StaleRow);
            const int64_t kind = row->weapon_kind;
            // Neither a TorpedoTube nor an _EnergyWeaponFireMixin: skipped.
            if (is_system_kind(kind)) {
                ++s_.weapon_pos;
                continue;
            }
            if (kind == kTractorBeam) return python(K0Reason::Tractor);
            if (kind != kPhaserBank && kind != kPulseWeapon && kind != kTorpedoTube)
                return python(K0Reason::UnknownKind);
            if (check_ && check_(h)) return python(K0Reason::Override);
            const K0Step st = kind == kPhaserBank   ? step_energy(m_, h, s_.dt)
                              : kind == kPulseWeapon ? step_pulse(m_, h, s_.dt)
                                                     : step_tube(m_, h, s_.now);
            if (st.handback) return python(*st.handback);
            ++c_.steps;
            apply(h, st);
            if (kind == kPulseWeapon) {
                if (st.record == K0Kind::DEPLETE_STOP) {
                    s_.pending_watch = true;  // the cursor stays on it
                    return emit(K0Kind::DEPLETE_STOP, h, pos, e.group, e.index);
                }
                const K0Step w = pulse_watch(m_, h);
                apply(h, w);
                ++s_.weapon_pos;
                if (w.record == K0Kind::WATCH)
                    return emit(K0Kind::WATCH, h, pos, e.group, e.index);
                continue;
            }
            ++s_.weapon_pos;
            if (st.record != K0Kind::DONE)
                return emit(st.record, h, pos, e.group, e.index);
        }
        ++s_.ship_pos;
        s_.weapon_pos = 0;
    }
    s_.done = true;
    return emit(K0Kind::DONE, -1, -1, -1, -1);
}

// Undo the logged writes not yet returned, newest first.
void roll_back(Mirror& m, K0Session::State& s) {
    while (!s.undo.empty()) {
        const K0Undo& u = s.undo.back();
        switch (u.type) {
            case K0Undo::Type::F: m.set_f(u.h, u.f, u.d); break;
            case K0Undo::Type::I: m.set_i(u.h, u.f, u.i); break;
            case K0Undo::Type::Floats: m.set_floats(u.h, u.f, u.floats); break;
        }
        s.undo.pop_back();
    }
    s.writes.clear();
}

}  // namespace

K0Record K0Session::next() {
    if (!s_) lost("no session is open");
    if (s_->done) lost("the session already returned DONE");
    // A throw must leave the session, the counters and the mirror as they
    // were: every unreturned write undone (mirror == Python), so abandon()
    // -- or a retry -- starts from a consistent state. The log is empty here
    // (every record carries all writes before it), so the copy is cheap.
    State before = *s_;
    const Counts counts_before = counts_;
    try {
        Walker w(m_, *s_, counts_, check_);
        return w.run();
    } catch (...) {
        roll_back(m_, *s_);
        *s_ = std::move(before);
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
