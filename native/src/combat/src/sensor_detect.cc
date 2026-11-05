// The native sensor-detection kernel -- see sensor_detect.h. Each function
// below ports the Python function of the same name (file:line in its
// comment), statement by statement and in the same order: keep them in step.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/sensor_detect.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

#include "dauntless/combat/nebula_density.h"
#include "dauntless/combat/profile_eval.h"
#include "dauntless/combat/published_poses.h"
#include "dauntless/combat/py_math.h"

namespace dauntless::combat {

// ── Native-owned state ──────────────────────────────────────────────────────

void SensorState::clear() {
    latch.clear();
    memo.clear();
    walking_probes = false;
    tick_time_set = false;
    tick_time = 0.0;
    rock_cache.clear();
    pair_cache.clear();
    mounts.clear();
}

void SensorState::drop_object(int64_t h) {
    // Python's latch is weak on both sides: a dead observer's or target's
    // entries vanish with it. The memo is keyed the same way.
    std::erase_if(latch, [h](const HandlePair& p) { return p.a == h || p.b == h; });
    std::erase_if(memo, [h](const auto& kv) {
        return kv.first.a == h || kv.first.b == h;
    });
    // The mount memo's ship_arg is an Object handle.
    std::erase_if(mounts, [h](const auto& kv) { return kv.first.b == h; });
}

void SensorState::drop_mounts_of(int64_t h) {
    std::erase_if(mounts, [h](const auto& kv) { return kv.first.a == h; });
}

void SensorState::drop_set(int64_t h) {
    // sensor_occlusion's caches are WeakKeyDictionaries keyed by the set.
    rock_cache.erase(h);
    pair_cache.erase(h);
}

namespace {

// CloakingSubsystem.CLOAK_CLOAKED (engine/appc/subsystems.py:3014).
constexpr int64_t kCloakCloaked = 2;
// engine/appc/objects.py DYING_THRESHOLD: IsDying reads _life_time below it.
constexpr double kDyingThreshold = 1.0e6;

[[noreturn]] void fall_back(const char* why) {
    throw std::invalid_argument(std::string("combat sensor_detect: ") + why +
                                " -- answer in Python");
}

// ── Row and ref access: -1 is None, -2 / a gone row falls back ──────────────

const ObjectRow& obj(const Mirror& m, int64_t h) {
    const ObjectRow* r = m.object(h);
    if (!r) fall_back("object handle is stale, freed or not an Object");
    return *r;
}

// A set list entry (ships / nebulae): the typed row holds raw handles.
const ObjectRow& list_entry(const Mirror& m, int64_t h) {
    if (h == kRefUnrepresentable) fall_back("set list holds an unnamed object");
    const ObjectRow* r = m.object(h);
    if (!r) fall_back("set list holds a freed object");
    return *r;
}

// A Subsystem ref field's referent, or nullptr for None.
const SubsystemRow* sub_ref(const Mirror& m, int64_t ref, const char* field) {
    if (ref == -1) return nullptr;
    if (ref == kRefUnrepresentable) fall_back(field);
    const SubsystemRow* r = m.subsystem(ref);
    if (!r) fall_back(field);
    return r;
}

// An Object ref field's referent handle (checked), or -1 for None.
int64_t obj_ref(const Mirror& m, int64_t ref, const char* field) {
    if (ref == -1) return -1;
    if (ref == kRefUnrepresentable || !m.object(ref)) fall_back(field);
    return ref;
}

// ObjectClass.GetContainingSet (objects.py:329): the set's handle (checked)
// or -1. Identity (`is`) between sets is handle equality.
int64_t GetContainingSet(const Mirror& m, const ObjectRow& o) {
    const int64_t h = o._containing_set;
    if (h == -1) return -1;
    if (h == kRefUnrepresentable || !m.set(h)) fall_back("_containing_set");
    return h;
}

// subsystems._get_xyz (subsystems.py:3332) for an ObjectClass: GetTranslate,
// the TransformStore slot (GetWorldLocation reads the same one); the
// published pose inside the read window (read_pose).
std::array<double, 3> _get_xyz(const Mirror& m, const ObjectRow& o) {
    if (o.xform_index < 0 || o.xform_gen < 0 ||
        o.xform_index > std::numeric_limits<uint32_t>::max() ||
        o.xform_gen > std::numeric_limits<uint32_t>::max())
        fall_back("object has no transform");
    const auto xi = static_cast<uint32_t>(o.xform_index);
    const auto xg = static_cast<uint32_t>(o.xform_gen);
    if (!m.store().valid(xi, xg)) fall_back("object transform is invalid");
    const auto& t = read_pose(m.store(), xi, xg);
    return {t.pos[0], t.pos[1], t.pos[2]};
}

// ── Subsystem surface (engine/appc/subsystems.py) ───────────────────────────

// ShipSubsystem.IsDisabled (subsystems.py:1186). Reads _max_condition, NOT
// GetMaxCondition (CDM §9.9).
bool IsDisabled(const SubsystemRow& s) {
    if (s._max_condition <= 0.0) return false;
    const double threshold = s._disabled_percentage * s._max_condition;
    return s._condition <= threshold;
}

// ShipSubsystem.IsDestroyed (subsystems.py:1213).
bool IsDestroyed(const SubsystemRow& s) {
    if (s._destroyed) return true;
    if (s._max_condition > 0.0 && s._condition <= 0.0) return true;
    return false;
}

// ShipSubsystem._climb_to_ship (subsystems.py:940).
int64_t _climb_to_ship(const Mirror& m, const SubsystemRow& s) {
    if (s._parent_ship != -1) return obj_ref(m, s._parent_ship, "_parent_ship");
    std::vector<int64_t> seen;
    int64_t node = s._parent_subsystem;  // self.GetParentSubsystem()
    while (node != -1) {
        const SubsystemRow* n = sub_ref(m, node, "_parent_subsystem");
        if (std::find(seen.begin(), seen.end(), node) != seen.end()) break;
        seen.push_back(node);
        if (n->_parent_ship != -1)  // getattr(node, "_parent_ship", None)
            return obj_ref(m, n->_parent_ship, "_parent_ship");
        node = n->_parent_subsystem;  // node.GetParentSubsystem()
    }
    return -1;
}

// ShipSubsystem.GetParentShip (subsystems.py:668).
int64_t GetParentShip(const Mirror& m, const SubsystemRow& s) {
    if (s._parent_ship != -1) return obj_ref(m, s._parent_ship, "_parent_ship");
    return _climb_to_ship(m, s);
}

// ship_death._out_of_action (ship_death.py:58).
bool _out_of_action(const Mirror& m, int64_t ship) {
    if (ship == -1) return false;
    const ObjectRow& o = obj(m, ship);
    // implements(ship, "IsDying") / ("IsDead"): DamageableObject surface.
    // The mirror can prove it only for a ShipClass (has_sensor_getter:
    // GetSensorSubsystem is ShipClass's alone, and ShipClass is a
    // DamageableObject). Any other parent goes to the Python.
    if (!o.has_sensor_getter) fall_back("parent ship is not a ShipClass row");
    // DamageableObject.IsDying (objects.py:886) / IsDead (objects.py:912).
    const bool dying = (o._dying != 0) || (o._life_time < kDyingThreshold);
    const bool dead = o._dead != 0;
    return dying || dead;
}

}  // namespace

// subsystems._is_offline (subsystems.py:139) after its IsDisabled/IsDestroyed
// test: the radiation outage on the subsystem or its parent system, then the
// parent ship out of action. Shared with the weapon fire gates, whose
// IsDisabled/IsDestroyed are the WeaponSystem aggregates (fire_gates.cc).
bool is_offline_after_condition(const Mirror& m, const SubsystemRow& sub) {
    // `_radiation_out is True` (IS_TRUE: 1 only for the literal True).
    if (sub._radiation_out) return true;
    const SubsystemRow* parent =
        sub_ref(m, sub._parent_subsystem, "_parent_subsystem");
    if (parent && parent->_radiation_out) return true;
    if (sub.has_parent_ship_getter) {
        if (_out_of_action(m, GetParentShip(m, sub))) return true;
    }
    return false;
}

namespace {

// subsystems._is_offline (subsystems.py:139).
bool _is_offline(const Mirror& m, const SubsystemRow* sub) {
    if (!sub) return false;
    if (IsDisabled(*sub) || IsDestroyed(*sub)) return true;
    return is_offline_after_condition(m, *sub);
}

// ShipSubsystem.GetMaxCondition (subsystems.py:732): the property template's
// MaxCondition when set and > 0, else _max_condition.
double GetMaxCondition(const Mirror& m, const SubsystemRow& s) {
    if (s._property != -1) {
        if (s._property == kRefUnrepresentable) fall_back("_property");
        const PropertyRow* p = m.property(s._property);
        if (!p) fall_back("_property");
        if (p->MaxCondition_set && p->MaxCondition > 0.0) return p->MaxCondition;
    }
    return s._max_condition;
}

}  // namespace

// ShipSubsystem.GetConditionPercentage (subsystems.py:809).
double condition_percentage(const Mirror& m, const SubsystemRow& s) {
    const double mx = GetMaxCondition(m, s);
    if (mx <= 0) return 0.0;
    return py_max(0.0, py_min(1.0, s._condition / mx));
}

namespace {

double GetConditionPercentage(const Mirror& m, const SubsystemRow& s) {
    return condition_percentage(m, s);
}

// SensorSubsystem.IsObjectKnown (subsystems.py:1541).
bool IsObjectKnown(const SubsystemRow& sensors, const ObjectRow& obj_row) {
    return std::binary_search(sensors._known_objects.begin(),
                              sensors._known_objects.end(), obj_row.obj_id);
}

// ShipClass.GetSensorSubsystem behind `implements(ship, ...)`.
const SubsystemRow* GetSensorSubsystem(const Mirror& m, const ObjectRow& o) {
    if (!o.has_sensor_getter) return nullptr;
    return sub_ref(m, o._sensor_subsystem, "_sensor_subsystem");
}

// ── sensor_detection.py ─────────────────────────────────────────────────────

// sensor_detection._latched (sensor_detection.py:150)
bool _latched(const Mirror& m, int64_t observer, int64_t target) {
    return m.sensor_state().latch.count({observer, target}) != 0;
}

// sensor_detection._set_latched (sensor_detection.py:161)
void _set_latched(Mirror& m, int64_t observer, int64_t target, bool broken) {
    auto& latch = m.sensor_state().latch;
    if (broken)
        latch.insert({observer, target});
    else
        latch.erase({observer, target});
}

// sensor_detection._cloak_subsystem (sensor_detection.py:188)
const SubsystemRow* _cloak_subsystem(const Mirror& m, const ObjectRow& target) {
    if (!target.has_cloak_getter) return nullptr;  // getattr(type(target), ...)
    return sub_ref(m, target._cloaking_subsystem, "_cloaking_subsystem");
}

// sensor_detection._sensorless_range (sensor_detection.py:217)
double _sensorless_range(const Mirror& m) {
    return m.globals().sensorless_range_gu;
}

// MetaNebula.GetSeed (nebula.py): the cached seed, else seed_for(the first
// sphere's centre), else seed_for(0, 0, 0). The Python caches what it derives
// and native never writes that cache back, so the two differ in one case: a
// nebula queried BEFORE its first sphere caches seed_for(0, 0, 0) in Python,
// while native later derives from the first sphere. Accepted as ruling R10
// (spec §9.1; no stock SDK path does it).
std::array<double, 3> GetSeed(const ObjectRow& neb) {
    if (neb.seed_set) return {neb._seed[0], neb._seed[1], neb._seed[2]};
    double cx = 0.0, cy = 0.0, cz = 0.0;
    if (!neb.spheres.empty()) {
        cx = neb.spheres[0].x;
        cy = neb.spheres[0].y;
        cz = neb.spheres[0].z;
    }
    std::array<double, 3> out{};
    seed_for(cx, cy, cz, out.data());
    return out;
}

// sensor_detection._local_concealment (sensor_detection.py:254)
double _local_concealment(const Mirror& m, int64_t ship, double now) {
    const ObjectRow& o = obj(m, ship);
    const int64_t pSet = GetContainingSet(m, o);
    if (pSet == -1) return 0.0;
    const auto loc = _get_xyz(m, o);  // GetWorldLocation
    const double t = now;             // _game_time()
    double best = 0.0;
    for (int64_t e : m.set(pSet)->nebulae) {  // contact_index.nebulae_in
        const ObjectRow& neb = list_entry(m, e);
        if (!neb.is_meta_nebula) continue;  // App.MetaNebula_Cast -> None
        if (!neb.fbm_set) fall_back("MetaNebula has no _fbm");
        const double freq = neb._fbm[0], gain = neb._fbm[1],
                     density_floor = neb._fbm[2];
        const auto seed = GetSeed(neb);
        const double d =
            density(loc[0], loc[1], loc[2], neb.spheres.data(),
                    neb.spheres.size(), seed.data(), freq, gain, density_floor,
                    t * 0.01);
        if (d > best) best = d;
    }
    return best;
}

// sensor_detection._profile_concealment_cap (sensor_detection.py:305)
double _profile_concealment_cap(const Mirror& m) {
    const Globals& g = m.globals();
    if (g.dev_mode) return g.conceal_cap;
    return g.PROFILE_CONCEALMENT_CAP;
}

// sensor_detection._same_set (sensor_detection.py:348)
bool _same_set(const Mirror& m, int64_t observer, int64_t target) {
    const ObjectRow& o = obj(m, observer);
    const ObjectRow& t = obj(m, target);
    const int64_t oset = GetContainingSet(m, o);
    if (oset == -1) return false;
    return oset == GetContainingSet(m, t);
}

// MetaNebula.IsObjectInNebula (nebula.py:56)
bool IsObjectInNebula(const Mirror& m, const ObjectRow& neb, int64_t obj_h) {
    const auto loc = _get_xyz(m, obj(m, obj_h));  // obj.GetWorldLocation()
    const double px = loc[0], py = loc[1], pz = loc[2];
    for (const Sphere& s : neb.spheres) {
        const double dx = px - s.x, dy = py - s.y, dz = pz - s.z;
        if (dx * dx + dy * dy + dz * dz <= s.r * s.r) return true;
    }
    return false;
}

// sensor_detection._beyond_range_reach (sensor_detection.py:556)
bool _beyond_range_reach(const Mirror& m, int64_t observer, int64_t target,
                         bool cloaked) {
    if (cloaked || !_same_set(m, observer, target)) return false;
    const SubsystemRow* sensors = GetSensorSubsystem(m, obj(m, observer));
    if (!sensors) return false;
    // implements(sensors, "GetNormalPowerPercentage"): a SensorSubsystem is
    // a PoweredSubsystem.
    const bool boosted =
        sensors->_power_factor > m.globals().overboost_threshold;
    if (!boosted) {
        const bool known = IsObjectKnown(*sensors, obj(m, target));
        if (!known) return false;
    }
    return !jammed(m, observer, target);
}

// sensor_detection._live_probes (sensor_detection.py:586) via
// SensorSubsystem.probes(): ids resolving to no registered object are
// skipped. probes() prunes them from _probe_ids in Python; that prune is
// idempotent and stays Python's (CDM §5).
std::vector<int64_t> _live_probes(const Mirror& m, int64_t observer) {
    const SubsystemRow* sensors = GetSensorSubsystem(m, obj(m, observer));
    if (!sensors) return {};
    std::vector<int64_t> live;
    for (int64_t oid : sensors->_probe_ids) {
        const int64_t h = m.find_by_obj_id(oid);
        if (h != -1) live.push_back(h);
    }
    return live;
}

// `_walking_probes = True` ... `finally: _walking_probes = False`
struct WalkingProbes {
    SensorState& st;
    explicit WalkingProbes(SensorState& s) : st(s) { st.walking_probes = true; }
    ~WalkingProbes() { st.walking_probes = false; }
    WalkingProbes(const WalkingProbes&) = delete;
    WalkingProbes& operator=(const WalkingProbes&) = delete;
};

// sensor_detection._probe_reach (sensor_detection.py:595)
bool _probe_reach(Mirror& m, int64_t observer, int64_t target, double now,
                  double occ_now, bool use_memo, bool apply_concealment,
                  std::optional<double> concealment) {
    if (m.sensor_state().walking_probes || !_same_set(m, observer, target))
        return false;
    const std::vector<int64_t> probes = _live_probes(m, observer);
    if (probes.empty()) return false;
    if (apply_concealment && !concealment)
        concealment = concealment_at(m, target, now);
    const int64_t oset = GetContainingSet(m, obj(m, observer));
    WalkingProbes guard(m.sensor_state());
    for (int64_t probe : probes) {
        if (GetContainingSet(m, obj(m, probe)) == oset &&
            can_detect(m, probe, target, now, use_memo, std::nullopt,
                       apply_concealment, concealment, occ_now))
            return true;
    }
    return false;
}

// sensor_detection._probe_in_reach (sensor_detection.py:632)
bool _probe_in_reach(Mirror& m, int64_t observer, int64_t target) {
    if (m.sensor_state().walking_probes || !_same_set(m, observer, target))
        return false;
    const std::vector<int64_t> probes = _live_probes(m, observer);
    if (probes.empty()) return false;
    const int64_t oset = GetContainingSet(m, obj(m, observer));
    WalkingProbes guard(m.sensor_state());
    for (int64_t probe : probes) {
        if (GetContainingSet(m, obj(m, probe)) == oset &&
            in_reach(m, probe, target))
            return true;
    }
    return false;
}

// ── sensor_occlusion.py ─────────────────────────────────────────────────────

// Python compares cache signatures with tuple ==, whose identity shortcut
// makes a float equal to ITSELF even when NaN (the game time, tick time and
// dial are the same float objects from call to call). So: == or both NaN.
bool same_float(double a, double b) { return a == b || (a != a && b != b); }

bool same_tick(const SensorState& st, bool tick_set, double tick) {
    return st.tick_time_set == tick_set &&
           (!tick_set || same_float(st.tick_time, tick));
}

// rocks.rock.effective_radius (rock.py:59)
double effective_radius(const Mirror& m, const ObjectRow& rock) {
    double base = rock._radius;  // float(rock.GetBaseRadius()); GetRadius() is base x scale
    if (base <= 0.0) {
        const SubsystemRow* hull = sub_ref(m, rock._hull, "_hull");
        base = hull ? hull->_radius : 0.0;
    }
    return base * rock._scale;  // * float(rock.GetScale())
}

// sensor_occlusion._major_rocks (sensor_occlusion.py:93)
const std::vector<FrozenRock>& _major_rocks(Mirror& m, int64_t pset,
                                            double now) {
    SensorState& st = m.sensor_state();
    const SetRow& set = *m.set(pset);
    const std::vector<int64_t>& ships = set.ships;  // contact_index.ships_in
    const double min_r = m.globals().min_blocker_radius_gu;
    // sig = (now, _tick_time, len(ships), min_r)
    auto hit = st.rock_cache.find(pset);
    if (hit != st.rock_cache.end()) {
        const RockCacheEntry& e = hit->second;
        if (same_float(e.now, now) &&
            same_tick(st, e.tick_set, e.tick) && e.n_ships == ships.size() &&
            same_float(e.min_r, min_r))
            return e.rocks;
    }
    std::vector<FrozenRock> rocks;
    for (int64_t s : ships) {
        const ObjectRow& row = list_entry(m, s);
        if (row.is_rock) {  // isinstance(s, RockClass)
            const double r = effective_radius(m, row);
            if (r >= min_r) {
                const auto xyz = _get_xyz(m, row);
                rocks.push_back({s, xyz[0], xyz[1], xyz[2], r});
            }
        }
    }
    RockCacheEntry& e = st.rock_cache[pset];
    e = RockCacheEntry{now, st.tick_time_set, st.tick_time, ships.size(),
                       min_r, std::move(rocks)};
    return e.rocks;
}

}  // namespace

// ── Public surface ──────────────────────────────────────────────────────────

// sensor_detection.effective_sensor_range (sensor_detection.py:227)
double effective_sensor_range(const Mirror& m, int64_t ship) {
    const SubsystemRow* sensors = GetSensorSubsystem(m, obj(m, ship));
    if (!sensors) return _sensorless_range(m);
    if (_is_offline(m, sensors)) return 0.0;
    const double base = sensors->_base_sensor_range;
    if (base <= 0.0) return _sensorless_range(m);
    return base * GetConditionPercentage(m, *sensors) * sensors->_power_factor;
}

// sensor_detection.concealment_at (sensor_detection.py:290), with
// profile.locate (profile.py:78) over the set's mirrored, resolved frame.
double concealment_at(const Mirror& m, int64_t ship, double now) {
    const double local = _local_concealment(m, ship, now);
    // _profile.locate(ship): frames.system_position -> frame_of(set)
    const ObjectRow& o = obj(m, ship);
    const int64_t pSet = GetContainingSet(m, o);
    if (pSet == -1) return local;  // frame_of(None) is None
    const SetRow& set = *m.set(pSet);
    if (set.profile == kRefUnrepresentable) fall_back("set frame unresolved");
    if (set.profile == -1) return local;  // unmapped, or map.profile is None
    const ProfileRowSet* prof = m.profile(set.profile);
    if (!prof) fall_back("set frame's profile row is gone");
    const auto xyz = _get_xyz(m, o);  // frames._xyz: GetWorldLocation
    const double pos[3] = {xyz[0] + set.anchor[0], xyz[1] + set.anchor[1],
                           xyz[2] + set.anchor[2]};
    const double star[3] = {set.star[0], set.star[1], set.star[2]};
    const double r = dist3(pos, star);  // math.dist(pos[1:], star.position_gu)
    const double profile_term =
        evaluate_sensors(prof->rows.data(), prof->rows.size(), r) *
        prof->full_concealment;
    return py_max(local, py_min(profile_term, _profile_concealment_cap(m)));
}

// sensor_detection.is_hidden_by_cloak (sensor_detection.py:315)
bool is_hidden_by_cloak(const Mirror& m, int64_t target) {
    const SubsystemRow* cloak = _cloak_subsystem(m, obj(m, target));
    return cloak != nullptr && cloak->_cloak_state == kCloakCloaked;
}

// sensor_detection.jammed (sensor_detection.py:355)
bool jammed(const Mirror& m, int64_t observer, int64_t target) {
    const int64_t pset = GetContainingSet(m, obj(m, observer));
    if (pset == -1) return false;
    for (int64_t e : m.set(pset)->nebulae) {  // contact_index.nebulae_in
        const ObjectRow& neb = list_entry(m, e);
        // jammed does not cast: a plain App.Nebula would answer through a
        // truthy _Stub (CDM §9.14). Only the Python can say what it says.
        if (!neb.is_meta_nebula) fall_back("plain Nebula in jammed");
        if (IsObjectInNebula(m, neb, observer) ||
            IsObjectInNebula(m, neb, target))
            return true;
    }
    return false;
}

// sensor_detection.in_reach (sensor_detection.py:654)
bool in_reach(Mirror& m, int64_t observer, int64_t target) {
    const double r = effective_sensor_range(m, observer);
    if (r <= 0.0) return false;
    const auto o = _get_xyz(m, obj(m, observer));
    const auto t = _get_xyz(m, obj(m, target));
    const double dx = t[0] - o[0], dy = t[1] - o[1], dz = t[2] - o[2];
    if (dx * dx + dy * dy + dz * dz <= r * r) return true;
    return _beyond_range_reach(m, observer, target,
                               is_hidden_by_cloak(m, target)) ||
           _probe_in_reach(m, observer, target);
}

// sensor_occlusion.blocked (sensor_occlusion.py:132). Python swallows any
// exception as "not blocked"; here the fallback re-runs the Python, which
// swallows it as it always did.
bool occ_blocked(Mirror& m, int64_t observer, int64_t target, double now) {
    if (!m.globals().occ_enabled) return false;
    const int64_t pset = GetContainingSet(m, obj(m, observer));
    if (pset == -1) return false;
    const std::vector<FrozenRock>& rocks = _major_rocks(m, pset, now);
    if (rocks.empty()) return false;
    SensorState& st = m.sensor_state();
    // key_sig = (now, _tick_time, len(rocks))
    auto found = st.pair_cache.find(pset);
    if (found == st.pair_cache.end() || !same_float(found->second.now, now) ||
        !same_tick(st, found->second.tick_set, found->second.tick) ||
        found->second.n_rocks != rocks.size()) {
        found = st.pair_cache.insert_or_assign(
            pset, PairCacheEntry{now, st.tick_time_set, st.tick_time,
                                 rocks.size(), {}}).first;
    }
    auto& pairs = found->second.pairs;
    const HandlePair pair{observer, target};
    auto hit = pairs.find(pair);
    if (hit != pairs.end()) return hit->second;
    const auto a = _get_xyz(m, obj(m, observer));
    const auto b = _get_xyz(m, obj(m, target));
    bool answer = false;
    for (const FrozenRock& rk : rocks) {
        if (rk.rock == observer || rk.rock == target) continue;
        if (contains(a[0], a[1], a[2], rk.x, rk.y, rk.z, rk.r) ||
            contains(b[0], b[1], b[2], rk.x, rk.y, rk.z, rk.r))
            continue;  // beside the rock, not behind it
        if (segment_hits(a[0], a[1], a[2], b[0], b[1], b[2], rk.x, rk.y, rk.z,
                         rk.r)) {
            answer = true;
            break;
        }
    }
    pairs[pair] = answer;
    return answer;
}

namespace {

// sensor_detection._can_detect (sensor_detection.py:480): the rule itself.
bool _can_detect(Mirror& m, int64_t observer, int64_t target, double now,
                 double occ_now, bool use_memo, std::optional<double> dist_sq_gu,
                 bool apply_concealment, std::optional<double> concealment) {
    const Globals& g = m.globals();
    // ── Cloak gate
    const SubsystemRow* cloak = _cloak_subsystem(m, obj(m, target));
    const bool cloaked = cloak != nullptr && cloak->_cloak_state == kCloakCloaked;
    if (cloaked && !g.enhanced_sensor_contest) return false;

    double r = effective_sensor_range(m, observer);
    if (r <= 0.0) return false;
    if (cloaked)
        r = py_min(g.cloak_bubble_cap_gu,
                   g.CLOAK_DETECTION_BASE_GU + r * g.CLOAK_RANGE_FACTOR);

    // ── Occlusion gate
    if (g.enhanced_sensor_contest) {
        if (occ_blocked(m, observer, target, occ_now))
            return _probe_reach(m, observer, target, now, occ_now, use_memo,
                                apply_concealment, concealment);
    }

    // ── Nebula concealment gate
    if (apply_concealment) {
        const double conceal =
            !concealment ? concealment_at(m, target, now) : *concealment;
        concealment = conceal;  // sampled once; the probe walk reuses it
        const double thresh =
            g.LOCK_BREAK_T - (_latched(m, observer, target) ? g.HYSTERESIS : 0.0);
        if (conceal >= thresh) {
            _set_latched(m, observer, target, true);
            return _probe_reach(m, observer, target, now, occ_now, use_memo,
                                apply_concealment, concealment);
        }
        _set_latched(m, observer, target, false);
        r = r * (1.0 - g.CONCEAL_K * conceal);
    }

    if (!dist_sq_gu) {
        const auto o = _get_xyz(m, obj(m, observer));
        const auto t = _get_xyz(m, obj(m, target));
        const double dx = t[0] - o[0], dy = t[1] - o[1], dz = t[2] - o[2];
        dist_sq_gu = dx * dx + dy * dy + dz * dz;
    }
    if (*dist_sq_gu <= (r * r)) return true;
    // ── Beyond range: memory and over-boost, then the probe walk
    return _beyond_range_reach(m, observer, target, cloaked) ||
           _probe_reach(m, observer, target, now, occ_now, use_memo,
                        apply_concealment, concealment);
}

}  // namespace

// sensor_detection.can_detect (sensor_detection.py:377)
bool can_detect(Mirror& m, int64_t observer, int64_t target, double now,
                bool use_memo, std::optional<double> dist_sq_gu,
                bool apply_concealment, std::optional<double> concealment,
                std::optional<double> occ_now_arg) {
    const double occ_now = occ_now_arg ? *occ_now_arg : now;
    if (use_memo && !dist_sq_gu && apply_concealment && !concealment) {
        const HandlePair key{observer, target};
        auto& answers = m.sensor_state().memo;
        auto found = answers.find(key);
        if (found != answers.end()) return found->second;
        const bool answer =
            _can_detect(m, observer, target, now, occ_now, use_memo,
                        std::nullopt, true, std::nullopt);
        m.sensor_state().memo[key] = answer;
        return answer;
    }
    return _can_detect(m, observer, target, now, occ_now, use_memo,
                       dist_sq_gu, apply_concealment, concealment);
}

// sensor_occlusion.begin_tick (sensor_occlusion.py:71)
void occ_begin_tick(Mirror& m, double now_gt) {
    m.sensor_state().tick_time_set = true;
    m.sensor_state().tick_time = now_gt;
}

// sensor_occlusion.reset (sensor_occlusion.py:78)
void occ_reset(Mirror& m) {
    SensorState& st = m.sensor_state();
    st.pair_cache.clear();
    st.rock_cache.clear();
    st.tick_time_set = false;
    st.tick_time = 0.0;
}

// sensor_detection.reset_concealment_state (sensor_detection.py:176)
void latch_reset(Mirror& m) { m.sensor_state().latch.clear(); }

// sensor_detection._latched for a registered pair. Both handles must be live
// Object rows (a stale one throws), so a read and a write agree on who owns
// the pair: native, or the Python fallback.
bool latched(const Mirror& m, int64_t observer, int64_t target) {
    obj(m, observer);
    obj(m, target);
    return _latched(m, observer, target);
}

// sensor_detection._set_latched for a registered pair (Task 6, ruling R7:
// the Python's own writes land in this one latch). Both handles must be live
// Object rows, or nothing is written and the Python keeps the pair.
void set_latched(Mirror& m, int64_t observer, int64_t target, bool broken) {
    obj(m, observer);
    obj(m, target);
    _set_latched(m, observer, target, broken);
}

std::vector<int64_t> latch_snapshot(const Mirror& m, int64_t target) {
    std::vector<int64_t> out;
    for (const HandlePair& p : m.sensor_state().latch)
        if (p.b == target) out.push_back(p.a);
    std::sort(out.begin(), out.end());
    return out;
}

void latch_restore(Mirror& m, int64_t target,
                   const std::vector<int64_t>& observers) {
    auto& latch = m.sensor_state().latch;
    for (auto it = latch.begin(); it != latch.end();) {
        if (it->b == target)
            it = latch.erase(it);
        else
            ++it;
    }
    if (!m.object(target)) return;
    for (int64_t o : observers)
        if (m.object(o)) latch.insert({o, target});
}

std::vector<std::pair<int64_t, int64_t>> latch_pairs_of(const Mirror& m,
                                                        int64_t h) {
    std::vector<std::pair<int64_t, int64_t>> out;
    for (const HandlePair& p : m.sensor_state().latch)
        if (p.a == h || p.b == h) out.emplace_back(p.a, p.b);
    std::sort(out.begin(), out.end());
    return out;
}

// step_memo.forget() for sensor_detection._answers and subsystems._mounts
// (weapon_geometry.h's mount memo)
void memo_clear(Mirror& m) {
    m.sensor_state().memo.clear();
    m.sensor_state().mounts.clear();
}

// The shared leaf predicates (sensor_detect.h): the ones the detection
// kernel itself asks, so every native caller asks the same lines.
bool subsystem_is_disabled(const SubsystemRow& s) { return IsDisabled(s); }
bool subsystem_is_destroyed(const SubsystemRow& s) { return IsDestroyed(s); }
bool subsystem_is_offline(const Mirror& m, const SubsystemRow& s) {
    return _is_offline(m, &s);
}
double subsystem_max_condition(const Mirror& m, const SubsystemRow& s) {
    return GetMaxCondition(m, s);
}

}  // namespace dauntless::combat
