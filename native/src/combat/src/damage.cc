// The native hit and condition chain -- see damage.h. Each function ports the
// Python function named in its comment, statement by statement: keep them in
// step. DM = docs/reference/engine/native-combat/damage-map.md (§2 the walk,
// §7 the hazards H1-H15).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/damage.h"

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <string_view>
#include <vector>

#include "dauntless/combat/beam_geometry.h"
#include "dauntless/combat/py_math.h"
#include "dauntless/combat/weapon_geometry.h"
#include "geometry_internal.h"

namespace dauntless::combat {

namespace {

using detail::fall_back;
using detail::obj;
using detail::sub;
using detail::xform;

// subsystems._THRESHOLD_*.
constexpr int64_t kOperational = 0, kDisabled = 1, kDestroyed = 2;
constexpr int kNumShields = 6;  // ShieldSubsystem.NUM_SHIELDS
// The Python attributes a write names (write_log.h: storage that outlives
// every log).
constexpr std::string_view kCondition = "_condition";
constexpr std::string_view kThreshold = "_threshold_state";
constexpr std::string_view kCombinedWatcher = "_combined_watcher";
constexpr std::string_view kConditionWatcher = "_condition_watcher";
constexpr std::string_view kFaces = "_current_shields";

DamageOperand handle_op(int64_t h) {
    DamageOperand o;
    o.type = DamageOperand::Type::Handle;
    o.handle = h;
    return o;
}
DamageOperand held_op(int64_t h) {
    DamageOperand o;
    o.type = DamageOperand::Type::Held;
    o.handle = h;
    return o;
}
DamageOperand num_op(double v) {
    DamageOperand o;
    o.type = DamageOperand::Type::Number;
    o.number = v;
    return o;
}
DamageOperand int_op(int64_t v) {
    DamageOperand o;
    o.type = DamageOperand::Type::Int;
    o.integer = v;
    return o;
}
DamageOperand bool_op(bool v) {
    DamageOperand o;
    o.type = DamageOperand::Type::Bool;
    o.boolean = v;
    return o;
}

// One call's writes: the mirror is written at once (later steps read it, as
// the Python reads its own writes), each old value kept so a fallback can
// restore it (damage.h, FALLBACK), and the Python write logged.
class Session {
public:
    Session(Mirror& m, DamageOut& out)
        : m_(m), out_(out), writes0_(out.writes.size()),
          entries0_(out.entries.size()), undo0_(out.undo.size()) {}

    Mirror& m() { return m_; }

    void put_f(int64_t h, Field f, double v, std::string_view field,
               bool watcher) {
        out_.undo.push_back({h, f, false, 0, m_.get_f(h, f), 0});
        m_.set_f(h, f, v);
        if (watcher)
            out_.writes.push_back({h, field, WatcherWrite{v}});
        else
            out_.writes.push_back({h, field, v});
    }
    void put_i(int64_t h, Field f, int64_t v, std::string_view field) {
        out_.undo.push_back({h, f, false, 0, 0.0, m_.get_i(h, f)});
        m_.set_i(h, f, v);
        out_.writes.push_back({h, field, v});
    }
    void put_face(int64_t shields, size_t index, double v) {
        const SubsystemRow& s = sub(m_, shields);
        out_.undo.push_back({shields, Field::_current_shields, true, index,
                             s._current_shields.at(index), 0});
        m_.set_float_at(shields, Field::_current_shields, index, v);
        out_.writes.push_back(
            {shields, kFaces,
             SlotWrite{static_cast<int64_t>(index), WriteScalar{v}}});
    }

    void emit(DamageKind kind, std::initializer_list<DamageOperand> ops) {
        DamageEntry e;
        e.kind = kind;
        for (const DamageOperand& o : ops) e.ops[e.count++] = o;
        out_.entries.push_back(e);
    }
    void emit(const DamageEntry& e) { out_.entries.push_back(e); }

    // The fallback: every mirror value back, `out` as it was at entry.
    void rollback() {
        undo_damage(m_, out_.undo, undo0_);
        out_.undo.resize(undo0_);
        out_.writes.resize(writes0_);
        out_.entries.resize(entries0_);
    }

private:
    Mirror& m_;
    DamageOut& out_;
    size_t writes0_, entries0_, undo0_;
};

// Runs `body` in a Session; a throw rolls the session back first.
template <class Body>
void run(Mirror& m, DamageOut& out, Body&& body) {
    Session s(m, out);
    try {
        body(s);
    } catch (...) {
        s.rollback();
        throw;
    }
}

// A row's class rules (dmg_class): DMG_PYTHON hands the call back.
const SubsystemRow& stock(const Mirror& m, int64_t h) {
    const SubsystemRow& s = sub(m, h);
    if (s.dmg_class != kDmgLeaf && s.dmg_class != kDmgAggregate)
        fall_back("subsystem class not stood in for (dmg_class)");
    return s;
}

// ShipSubsystem.GetMaxCondition (subsystems.py): the property template's
// MaxCondition when set and > 0, else _max_condition.
double max_condition(const Mirror& m, const SubsystemRow& s) {
    if (s._property != -1) {
        if (s._property == kRefUnrepresentable) fall_back("_property");
        const PropertyRow* p = m.property(s._property);
        if (!p) fall_back("_property");
        if (p->MaxCondition_set && p->MaxCondition > 0.0) return p->MaxCondition;
    }
    return s._max_condition;
}

// ShipSubsystem.GetConditionPercentage: max(0.0, min(1.0, cond / mx)).
double condition_percentage(const Mirror& m, const SubsystemRow& s) {
    const double mx = max_condition(m, s);
    if (mx <= 0) return 0.0;
    return py_max(0.0, py_min(1.0, s._condition / mx));
}

// ShipSubsystem.IsDisabled / IsDestroyed (reading _max_condition, not
// GetMaxCondition).
bool leaf_disabled(const SubsystemRow& s) {
    if (s._max_condition <= 0.0) return false;
    const double threshold = s._disabled_percentage * s._max_condition;
    return s._condition <= threshold;
}
bool leaf_destroyed(const SubsystemRow& s) {
    if (s._destroyed) return true;
    if (s._max_condition > 0.0 && s._condition <= 0.0) return true;
    return false;
}

constexpr int kMaxDepth = 32;  // a cyclic child chain recurses forever

// WeaponSystem.IsDisabled / IsDestroyed (weapon_subsystems.py): a system
// with no children uses the ShipSubsystem rule, else ALL children -- each
// by its own class's rule.
bool is_disabled(const Mirror& m, const SubsystemRow& s, int depth = 0) {
    if (depth > kMaxDepth) fall_back("child chain too deep");
    if (s.dmg_class != kDmgAggregate || s._children.empty())
        return leaf_disabled(s);
    for (const int64_t c : s._children) {
        if (!m.subsystem(c)) fall_back("child row");
        if (!is_disabled(m, stock(m, c), depth + 1)) return false;
    }
    return true;
}
bool is_destroyed(const Mirror& m, const SubsystemRow& s, int depth = 0) {
    if (depth > kMaxDepth) fall_back("child chain too deep");
    if (s.dmg_class != kDmgAggregate || s._children.empty())
        return leaf_destroyed(s);
    if (s._destroyed) return true;
    for (const int64_t c : s._children) {
        if (!m.subsystem(c)) fall_back("child row");
        if (!is_destroyed(m, stock(m, c), depth + 1)) return false;
    }
    return true;
}

// ShipSubsystem._threshold_state_now.
int64_t threshold_now(const Mirror& m, const SubsystemRow& s) {
    if (is_destroyed(m, s)) return kDestroyed;
    if (is_disabled(m, s)) return kDisabled;
    return kOperational;
}

// ShipSubsystem._owning_ship: `_parent_ship`, else up `_parent_subsystem`,
// at most 16 hops; -1 for None.
int64_t owning_ship(const Mirror& m, int64_t h) {
    int64_t node = h;
    for (int hops = 0; node != -1 && hops < 16; ++hops) {
        const SubsystemRow& s = sub(m, node);
        const int64_t ship = s._parent_ship;
        if (ship != -1) {
            if (ship == kRefUnrepresentable || !m.object(ship))
                fall_back("_parent_ship");
            return ship;
        }
        node = s._parent_subsystem;
        if (node == kRefUnrepresentable ||
            (node != -1 && !m.subsystem(node)))
            fall_back("_parent_subsystem");
    }
    return -1;
}

// FloatRangeWatcher._update_queued for the subsystem's watcher `which`
// (ShipSubsystem._condition_changed: combined, then condition).
void update_watcher(Session& S, int64_t h, int64_t which, double pct) {
    const SubsystemRow& s = sub(S.m(), h);
    const bool combined = which == kWatchCombined;
    const int64_t checks = combined ? s.comb_watch_checks : s.cond_watch_checks;
    if (checks == kWatchNone) return;  // never handed out: None
    if (checks < 0) fall_back("a condition watcher the chain cannot stand in for");
    const double old = combined ? s.comb_watch_value : s.cond_watch_value;
    S.put_f(h, combined ? Field::comb_watch_value : Field::cond_watch_value,
            pct, combined ? kCombinedWatcher : kConditionWatcher, true);
    if (checks > 0)
        S.emit(DamageKind::COND_WATCH,
               {handle_op(h), int_op(which), num_op(old), num_op(pct)});
}

// ShipSubsystem._condition_changed.
void condition_changed(Session& S, int64_t h) {
    Mirror& m = S.m();
    {
        const SubsystemRow& s = sub(m, h);
        if (s.comb_watch_checks != kWatchNone ||
            s.cond_watch_checks != kWatchNone) {
            const double pct = condition_percentage(m, s);
            update_watcher(S, h, kWatchCombined, pct);
            update_watcher(S, h, kWatchCondition, pct);
        }
    }
    const SubsystemRow& s = sub(m, h);
    const int64_t new_state = threshold_now(m, s);
    const int64_t old_state = s._threshold_state;
    if (new_state == old_state) return;
    S.put_i(h, Field::_threshold_state, new_state, kThreshold);
    if (new_state == kDestroyed)
        S.emit(DamageKind::SUBSYS_EVENT,
               {handle_op(h), int_op(kSubsysDestroyed)});
    else if (new_state == kDisabled && old_state == kOperational)
        S.emit(DamageKind::SUBSYS_EVENT,
               {handle_op(h), int_op(kSubsysDisabled)});
    else if (new_state == kOperational)
        S.emit(DamageKind::SUBSYS_EVENT,
               {handle_op(h), int_op(kSubsysOperational)});
    // destroyed -> disabled (partial repair from zero) is silent.
}

// ShipSubsystem._set_condition(value, killer, ship), death_check.note_write
// included.
void set_condition_in(Session& S, int64_t h, double value, int64_t killer,
                      int64_t ship) {
    Mirror& m = S.m();
    if (ship == kRefUnrepresentable || (ship != -1 && !m.object(ship)))
        fall_back("the charged ship");
    const double before = stock(m, h)._condition;
    S.put_f(h, Field::_condition, py_max(0.0, value), kCondition, false);
    condition_changed(S, h);
    const SubsystemRow& s = sub(m, h);
    if (!s._in_repair_queue && s._condition < max_condition(m, s))
        S.emit(DamageKind::REPAIR_ADD, {handle_op(h)});
    if (s._condition <= 0.0) {
        const int64_t charged = ship != -1 ? ship : owning_ship(m, h);
        // death_check.note_write
        if (charged == -1) return;
        const double after = sub(m, h)._condition;
        if (after > 0.0) return;
        const bool crossed = before > 0.0;
        if (!crossed && !sub(m, h)._critical) return;
        S.emit(DamageKind::ZERO_CROSS,
               {handle_op(charged), handle_op(h), bool_op(crossed),
                held_op(killer)});
    }
}

// DamageableObject.DamageSystem(subsystem, amount, source).
void damage_system_in(Session& S, int64_t ship, int64_t h, double amount,
                      int64_t killer) {
    if (h == -1) return;
    const double amt = amount;
    if (amt <= 0.0) return;
    const double cur = stock(S.m(), h)._condition;
    set_condition_in(S, h, py_max(0.0, cur - amt), killer, ship);
}

// ShieldSubsystem.ApplyDamage(face, amount): what reaches the hull.
double apply_damage(Session& S, int64_t shields, int face, double amt) {
    const SubsystemRow& sh = sub(S.m(), shields);
    if (sh._current_shields.size() != kNumShields ||
        sh._max_shields.size() != kNumShields ||
        sh._ramp_fraction.size() != kNumShields ||
        sh._ramp_set.size() != kNumShields)
        fall_back("shield face lists");
    const double cur = sh._current_shields[face];
    const double mx = sh._max_shields[face];
    if (mx <= 0.0 || cur <= 0.0) return amt;
    // `_ramp_fraction[f]`, None (no charge tick yet) -> the face live.
    const double frac =
        sh._ramp_set[face] != 0.0 ? sh._ramp_fraction[face] : cur / mx;
    if (frac <= 0.1) return amt;  // bypassed entirely
    double b;
    if (frac >= 0.6)
        b = 0.0;
    else
        b = 0.6 * (1.0 - 2.0 * (frac - 0.1));
    const double nw = cur - (1.0 - b) * amt;
    if (nw >= 0.0) {
        S.put_face(shields, static_cast<size_t>(face), nw);
        return b * amt;
    }
    S.put_face(shields, static_cast<size_t>(face), 0.0);
    return b * amt - nw;
}

// combat._splash_weight (DM H3).
double splash_weight(double r_sub, double r_hit, double d) {
    if (r_hit <= 0.0) return 0.0;
    const double raw = (r_sub + r_hit - d) / r_hit;
    if (raw <= 0.0) return 0.0;
    if (raw >= 1.0) return 1.0;
    return raw;
}

struct StateFlags {
    bool disabled, destroyed;
};

// combat._subsystem_state_flags (IsDamaged is read and ignored).
StateFlags state_flags(const Mirror& m, int64_t h) {
    const SubsystemRow& s = stock(m, h);
    return {is_disabled(m, s), is_destroyed(m, s)};
}

// combat._diff_state.
int64_t diff_state(const StateFlags& b, const StateFlags& a) {
    if (a.destroyed && !b.destroyed) return kTransitionDestroyed;
    if (a.disabled && !b.disabled) return kTransitionDisabled;
    return kTransitionNone;
}

void push_point(DamageEntry& e, const Vec3& p) {
    for (double c : p) e.ops[e.count++] = num_op(c);
}

}  // namespace

void undo_damage(Mirror& m, const std::vector<DamageUndo>& undo, size_t from) {
    for (size_t k = undo.size(); k > from; --k) {
        const DamageUndo& u = undo[k - 1];
        if (u.face)
            m.set_float_at(u.h, u.f, u.index, u.d);
        else if (field_type(u.f) == FieldType::F)
            m.set_f(u.h, u.f, u.d);
        else
            m.set_i(u.h, u.f, u.i);
    }
}

// ── combat.py _shield_face_from_hit_point (DM H5) ───────────────────────────

int shield_face(const Mirror& m, int64_t ship, const Vec3& p) {
    const ObjectRow& o = obj(m, ship);
    const auto& tr = xform(m, o);
    const double* R = tr.rot;
    // _body_frame_delta: dot with GetCol(i) = (R[i], R[3+i], R[6+i]).
    const double dxw = p[0] - tr.pos[0];
    const double dyw = p[1] - tr.pos[1];
    const double dzw = p[2] - tr.pos[2];
    double bx = dxw * R[0] + dyw * R[3] + dzw * R[6];
    double by = dxw * R[1] + dyw * R[4] + dzw * R[7];
    double bz = dxw * R[2] + dyw * R[5] + dzw * R[8];
    // _hull_box_for: no box, or a degenerate raw extent -> None. Python
    // rejects `hx <= 0.0`, so a NaN half-extent keeps the box.
    const Vec3& hh = o._shield_hull_box_half;
    if (o.hull_box_set && !(hh[0] <= 0.0) && !(hh[1] <= 0.0) &&
        !(hh[2] <= 0.0)) {
        const Vec3& hc = o._shield_hull_box_center;
        double scale = o._scale;
        if (scale <= 0.0) scale = 1.0;  // NaN passes
        const double cx = hc[0] * scale, cy = hc[1] * scale,
                     cz = hc[2] * scale;
        const double hx = hh[0] * scale, hy = hh[1] * scale,
                     hz = hh[2] * scale;
        if (hx == 0.0 || hy == 0.0 || hz == 0.0)
            fall_back("zero hull-box axis (Python raises)");
        bx = (bx - cx) / hx;
        by = (by - cy) / hy;
        bz = (bz - cz) / hz;
    }
    const double ax = std::fabs(bx), ay = std::fabs(by), az = std::fabs(bz);
    if (ay >= ax && ay >= az) return by >= 0 ? 0 : 1;
    if (az >= ax) return bz >= 0 ? 2 : 3;
    return bx <= 0 ? 4 : 5;
}

// ── objects.py DamageableObject.DamageSystem ────────────────────────────────

void damage_system(Mirror& m, int64_t ship, int64_t subsystem, double amount,
                   int64_t killer, DamageOut& out) {
    run(m, out, [&](Session& S) {
        damage_system_in(S, ship, subsystem, amount, killer);
    });
}

// ── subsystems.py ShipSubsystem._set_condition ──────────────────────────────

void set_condition(Mirror& m, int64_t subsystem, double value, int64_t killer,
                   int64_t ship, DamageOut& out) {
    run(m, out, [&](Session& S) {
        set_condition_in(S, subsystem, value, killer, ship);
    });
}

// ── combat.py _apply_hit (DM §2) ────────────────────────────────────────────

void apply_hit(Mirror& m, const HitInput& in, const DamageContext& ctx,
               DamageOut& out) {
    run(m, out, [&](Session& S) {
        const int64_t ship = in.ship;
        const ObjectRow& o = obj(m, ship);
        if (!o.dmg_ship) fall_back("ship class not stood in for (dmg_ship)");
        const double r_hit = in.r_hit;
        const bool target_is_player = ctx.player != -1 && ship == ctx.player;
        const bool source_is_player =
            ctx.player != -1 && in.source == ctx.player;
        double damage = in.damage;
        if (ctx.double_damage && source_is_player) damage = damage * 2.0;
        // IsImmuneToDamage: SetHurtable(0) (ruling M1).
        const bool ship_immune = !o._hurtable;
        const bool commit = !((ctx.god_mode && target_is_player) || ship_immune);

        // shields_block reads the cloak's state for cloak_shields_suspended
        // (its IsCloaking / IsDecloaking): a cloak class whose rules the
        // chain does not stand in for hands back (final review I-1).
        const int64_t cloak = o._cloaking_subsystem;
        if (cloak >= 0 && m.subsystem(cloak)) stock(m, cloak);

        // 1. The shields take the first bite.
        double remaining = damage;
        double absorbed_shields = 0.0;
        bool shields_online =
            shields_block(m, ship, ctx.npc_shields_off, ctx.player);
        if (in.bypass_shields) shields_online = false;
        if (shields_online) {
            const int64_t shields = o._shield_subsystem;
            const SubsystemRow& sh = stock(m, shields);
            const int face =
                shield_face(m, ship, in.has_shield_point ? in.shield_point
                                                         : in.point);
            const double before = remaining;
            if (commit) {
                remaining = apply_damage(S, shields, face, remaining);
            } else {
                // God mode: the overflow, the face untouched.
                if (sh._current_shields.size() != kNumShields)
                    fall_back("shield face lists");
                const double cur = sh._current_shields[face];
                remaining = py_max(0.0, remaining - cur);
            }
            absorbed_shields = before - remaining;
        }

        const double post_shield = remaining;
        double absorbed_hull = 0.0;
        double absorbed_subsystem_total = 0.0;
        int64_t primary = -1;
        double best = 0.0;
        int64_t primary_transition = kTransitionNone;
        const int64_t hull = o._hull;
        if (hull == kRefUnrepresentable || (hull != -1 && !m.subsystem(hull)))
            fall_back("_hull");

        if (post_shield > 0.0) {
            // 2. The hull takes the full post-shield damage (damage_hull).
            if (hull != -1) {
                if (commit && in.damage_hull)
                    damage_system_in(S, ship, hull, post_shield, in.source);
                absorbed_hull = post_shield;
            }
            // 3. Every overlapping subsystem is offered the full post-shield
            // damage, in combat._iter_subsystems order (mount_order).
            const std::vector<int64_t> order = obj(m, ship).mount_order;
            for (const int64_t h : order) {
                if (h == kRefUnrepresentable || !m.subsystem(h))
                    fall_back("mount order");
                const double r_sub = stock(m, h)._radius;
                const Vec3 hw = subsystem_world_position(m, h, ship, false);
                const double dx = in.point[0] - hw[0];
                const double dy = in.point[1] - hw[1];
                const double dz = in.point[2] - hw[2];
                const double d = py_pow(dx * dx + dy * dy + dz * dz, 0.5);
                if (d >= r_sub + r_hit) continue;
                const double w = splash_weight(r_sub, r_hit, d);
                if (w <= 0.0) continue;
                if (w > best) {  // _pick_primary_subsystem_for_dispatch
                    best = w;
                    primary = h;
                }
                const double amount = post_shield;
                const bool sub_immune = sub(m, h)._invincible != 0;
                const StateFlags before = state_flags(m, h);
                if (commit && !sub_immune)
                    damage_system_in(S, ship, h, amount, in.source);
                absorbed_subsystem_total += amount;
                const StateFlags after = state_flags(m, h);
                const int64_t transition = diff_state(before, after);
                if (transition != kTransitionNone &&
                    primary_transition == kTransitionNone)
                    primary_transition = transition;
            }
        }

        // 4. HIT_PRESENT (effect_queue.hit_present_operands).
        DamageEntry p;
        p.kind = DamageKind::HIT_PRESENT;
        p.ops[p.count++] = handle_op(ship);
        p.ops[p.count++] = held_op(in.source);
        p.ops[p.count++] = bool_op(in.has_instances);
        push_point(p, in.point);
        p.ops[p.count++] = bool_op(in.has_normal);
        push_point(p, in.has_normal ? in.normal : Vec3{0.0, 0.0, 0.0});
        p.ops[p.count++] = num_op(damage);
        p.ops[p.count++] = handle_op(primary);
        p.ops[p.count++] = num_op(absorbed_shields);
        p.ops[p.count++] = num_op(absorbed_subsystem_total);
        p.ops[p.count++] = num_op(absorbed_hull);
        p.ops[p.count++] = int_op(primary_transition);
        p.ops[p.count++] = int_op(in.hit_weapon);
        p.ops[p.count++] = num_op(r_hit);
        p.ops[p.count++] = bool_op(commit);
        p.ops[p.count++] = bool_op(in.damage_hull);
        p.ops[p.count++] = bool_op(in.has_shield_point);
        p.ops[p.count++] =
            bool_op(in.has_shield_point && in.shield_point_is_point);
        push_point(p, in.has_shield_point ? in.shield_point
                                          : Vec3{0.0, 0.0, 0.0});
        p.ops[p.count++] = bool_op(in.has_tangent);
        push_point(p, in.has_tangent ? in.tangent : Vec3{0.0, 0.0, 0.0});
        p.ops[p.count++] = bool_op(in.has_decal_radius);
        p.ops[p.count++] = num_op(in.has_decal_radius ? in.decal_radius : 0.0);
        p.ops[p.count++] = num_op(in.decal_dent);
        p.ops[p.count++] = bool_op(in.single_impact);
        p.ops[p.count++] = bool_op(in.has_shield_radius);
        p.ops[p.count++] =
            num_op(in.has_shield_radius ? in.shield_radius : 0.0);
        S.emit(p);

        // 5. WEAPON_HIT (effect_queue.weapon_hit_operands).
        DamageEntry h;
        h.kind = DamageKind::WEAPON_HIT;
        h.ops[h.count++] = handle_op(ship);
        h.ops[h.count++] = held_op(in.source);
        h.ops[h.count++] = num_op(damage);
        push_point(h, in.point);
        h.ops[h.count++] = bool_op(in.has_normal);
        push_point(h, in.has_normal ? in.normal : Vec3{0.0, 0.0, 0.0});
        h.ops[h.count++] = num_op(r_hit);
        h.ops[h.count++] = handle_op(primary);
        h.ops[h.count++] = int_op(in.weapon_hit_type);
        h.ops[h.count++] = bool_op(post_shield > 0.0);
        S.emit(h);
    });
}

}  // namespace dauntless::combat
