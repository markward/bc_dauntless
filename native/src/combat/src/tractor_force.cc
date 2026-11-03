// The tractor force -- see tractor_force.h. A port of engine/appc/tractor.py
// as it stood at 23b3845d5 (advance_tractors, _apply_mode, _speed_for,
// _standoff_distance, _displace, _spring_toward, _zero_velocity); each
// function below names the Python it stands for.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/tractor_force.h"

#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

#include "dauntless/combat/beam_geometry.h"
#include "dauntless/combat/fire_gates.h"
#include "dauntless/combat/py_math.h"

namespace dauntless::combat {

namespace {

constexpr int64_t kTractorSystem = 3, kTractorBeam = 7;

[[noreturn]] void unnamed(const char* why) {
    throw std::invalid_argument(std::string("combat tractor force: ") + why);
}

class Step {
public:
    Step(Mirror& m, TransformStore& store, double dt, TractorForceResult& out)
        : m_(m), store_(store), dt_(dt), g_(m.globals()), out_(out) {}

    // advance_tractors' loop body for one ship.
    void ship(int64_t ship_h);

private:
    struct Body {
        int64_t h = -1;
        uint32_t xi = 0, xg = 0;
        const ObjectRow* row = nullptr;
    };

    Body body(int64_t h) const {
        if (h < 0) unnamed("an object handle is none or unrepresentable");
        const ObjectRow* o = m_.object(h);
        if (!o) unnamed("an object row is gone");
        if (o->xform_index < 0 || o->xform_gen < 0 ||
            o->xform_index > std::numeric_limits<uint32_t>::max() ||
            o->xform_gen > std::numeric_limits<uint32_t>::max())
            unnamed("an object has no transform");
        Body b{h, static_cast<uint32_t>(o->xform_index),
               static_cast<uint32_t>(o->xform_gen), o};
        if (!store_.valid(b.xi, b.xg)) unnamed("an object transform is invalid");
        return b;
    }
    Vec3 at(const Body& b) const { return store_.position(b.xi, b.xg); }
    void set(const Body& b, double x, double y, double z) {
        store_.set_position(b.xi, b.xg, x, y, z);
        out_.poses.push_back(TractorPoseWrite{b.h, {x, y, z}});
    }

    // _speed_for: 0 for anything not a ShipClass; else
    // REF_SPEED * REF_MASS / m (m <= 0 reads the fallback), capped.
    double speed_for(const Body& b) const {
        if (!b.row->is_ship_class) return 0.0;
        double mass = b.row->_mass;
        if (mass <= 0.0) mass = g_.TRACTOR_FALLBACK_MASS;
        const double s =
            g_.TRACTOR_REFERENCE_SPEED_GUPS * g_.TRACTOR_REFERENCE_MASS / mass;
        return s < g_.TRACTOR_MAX_SPEED_GUPS ? s : g_.TRACTOR_MAX_SPEED_GUPS;
    }
    // _standoff_distance: rs + rt + TRACTOR_STANDOFF_MARGIN_GU, the radii
    // being the SCALED world radii (GetRadius() is base x scale).
    double standoff(const Body& source, const Body& target) const {
        return world_radius(m_, source.h) + world_radius(m_, target.h) +
               g_.TRACTOR_STANDOFF_MARGIN_GU;
    }
    // _displace: p + d.
    void displace(const Body& b, double dx, double dy, double dz) {
        const Vec3 p = at(b);
        set(b, p[0] + dx, p[1] + dy, p[2] + dz);
    }
    // _spring_toward: toward `dest`, at most max_speed * dt, snapping when
    // within one step; nothing for an immovable body or one already there.
    void spring_toward(const Body& b, const Vec3& dest, double max_speed) {
        if (max_speed <= 0.0) return;
        const Vec3 p = at(b);
        const double ex = dest[0] - p[0], ey = dest[1] - p[1],
                     ez = dest[2] - p[2];
        const double elen = py_pow(ex * ex + ey * ey + ez * ez, 0.5);
        if (elen < g_.TRACTOR_EPS) return;
        const double step = max_speed * dt_;
        if (elen <= step) {
            set(b, dest[0], dest[1], dest[2]);
        } else {
            const double f = step / elen;
            set(b, p[0] + ex * f, p[1] + ey * f, p[2] + ez * f);
        }
    }
    void capture(int64_t sys, int64_t kind, const Vec3& p) {
        m_.set_i(sys, Field::engage_kind, kind);
        m_.set_fv(sys, Field::engage_point, {p[0], p[1], p[2]});
        out_.captures.push_back(TractorEngageCapture{sys, kind, p});
    }

    // _apply_mode.
    void apply(const Body& source, int64_t sys, const Body& target,
               int64_t mode);

    Mirror& m_;
    TransformStore& store_;
    const double dt_;
    const Globals& g_;
    TractorForceResult& out_;
};

void Step::ship(int64_t ship_h) {
    // getter = getattr(ship, "GetTractorBeamSystem", None); sys_ = getter()
    if (ship_h < 0) unnamed("a ship handle is none or unrepresentable");
    const ObjectRow* so = m_.object(ship_h);
    if (!so) unnamed("a ship row is gone");
    const int64_t sys = so->_tractor_beam_system;
    if (sys == -1) return;
    const SubsystemRow* sr = sys < 0 ? nullptr : m_.subsystem(sys);
    if (!sr || sr->weapon_kind != kTractorSystem)
        unnamed("the tractor system cannot be named");
    // if sys_ is None or not sys_.IsFiring(): continue  (any child firing)
    bool firing = false;
    for (const int64_t k : sr->_children) {
        const SubsystemRow* kr = k < 0 ? nullptr : m_.subsystem(k);
        if (!kr || kr->weapon_kind != kTractorBeam)
            unnamed("a projector cannot be named");
        if (kr->_firing) firing = true;
    }
    if (!firing) return;
    // Every read that can fail, before the first write: each firing
    // projector's target (None or dead: skipped, as `continue`). A target
    // the mirror cannot read is skipped and counted alone, as Python's
    // per-emitter loop goes on to the next.
    const Body source = body(ship_h);
    std::vector<Body> targets;
    for (const int64_t k : sr->_children) {
        const SubsystemRow* kr = m_.subsystem(k);
        if (!kr->_firing) continue;
        const int64_t t = kr->_target;
        if (t == -1) continue;
        try {
            if (ship_dead(m_, t)) continue;
            targets.push_back(body(t));
        } catch (const std::invalid_argument&) {
            ++out_.skipped;
        }
    }
    const int64_t mode = sr->_mode;  // sys_.GetMode()
    for (const Body& t : targets) apply(source, sys, t, mode);
}

void Step::apply(const Body& source, int64_t sys, const Body& target,
                 int64_t mode) {
    ++out_.applied;
    const Vec3 sp = at(source);
    const Vec3 tp = at(target);
    const double dx = tp[0] - sp[0], dy = tp[1] - sp[1], dz = tp[2] - sp[2];
    const double len = py_pow(dx * dx + dy * dy + dz * dz, 0.5);
    if (len < g_.TRACTOR_EPS) return;  // coincident: no beam direction
    const double ux = dx / len, uy = dy / len, uz = dz / len;
    const double s_t = speed_for(target);
    const double s_s = speed_for(source);
    switch (static_cast<TractorMode>(mode)) {
        case TractorMode::Pull: {
            // The target to a standoff off the source; the source drawn to
            // the same standoff off where the target was.
            const double d = standoff(source, target);
            spring_toward(target, {sp[0] + ux * d, sp[1] + uy * d,
                                   sp[2] + uz * d},
                          s_t);
            spring_toward(source, {tp[0] - ux * d, tp[1] - uy * d,
                                   tp[2] - uz * d},
                          s_s);
            return;
        }
        case TractorMode::Push:
            displace(target, ux * s_t * dt_, uy * s_t * dt_, uz * s_t * dt_);
            displace(source, -ux * s_s * dt_, -uy * s_s * dt_,
                     -uz * s_s * dt_);
            return;
        case TractorMode::Hold: {
            // The point it occupied when grabbed; its velocity damped.
            const SubsystemRow& sr = *m_.subsystem(sys);
            if (sr.engage_kind != kEngageHold) capture(sys, kEngageHold, tp);
            spring_toward(target, m_.subsystem(sys)->engage_point, s_t);
            out_.zero_velocity.push_back(target.h);
            return;
        }
        case TractorMode::Tow: {
            // The offset it held when grabbed, in the source's body frame:
            // offset.MultMatrixLeft(R.Transpose()) on capture, then
            // desired.MultMatrixLeft(R) each step (TGPoint3 sums, math.py).
            const SubsystemRow& sr = *m_.subsystem(sys);
            if (sr.engage_kind != kEngageTow) {
                const auto r = store_.rotation(source.xi, source.xg);
                capture(sys, kEngageTow,
                        {r[0] * dx + r[3] * dy + r[6] * dz,
                         r[1] * dx + r[4] * dy + r[7] * dz,
                         r[2] * dx + r[5] * dy + r[8] * dz});
            }
            const Vec3 o = m_.subsystem(sys)->engage_point;
            const auto r = store_.rotation(source.xi, source.xg);
            const double wx = r[0] * o[0] + r[1] * o[1] + r[2] * o[2];
            const double wy = r[3] * o[0] + r[4] * o[1] + r[5] * o[2];
            const double wz = r[6] * o[0] + r[7] * o[1] + r[8] * o[2];
            spring_toward(target, {sp[0] + wx, sp[1] + wy, sp[2] + wz}, s_t);
            // Reciprocal drag: a heavy tow load tugs the tower toward it.
            const double drag = s_s * g_.TRACTOR_TOW_DRAG_FRACTION;
            displace(source, ux * drag * dt_, uy * drag * dt_, uz * drag * dt_);
            return;
        }
        case TractorMode::DockStage1:
        case TractorMode::DockStage2: {
            const double d = standoff(source, target);
            spring_toward(target, {sp[0] + ux * d, sp[1] + uy * d,
                                   sp[2] + uz * d},
                          s_t * g_.TRACTOR_DOCK_GENTLE_FRACTION);
            return;
        }
    }
    // Any other mode: Python's chain of ifs matches none.
}

}  // namespace

TractorForceResult tractor_force_step(Mirror& m, TransformStore& store,
                                      const std::vector<int64_t>& ships,
                                      double dt) {
    TractorForceResult out;
    if (dt <= 0.0) return out;
    Step step(m, store, dt, out);
    for (const int64_t ship : ships) {
        // A tractor the mirror cannot name moves nothing (Step::ship makes
        // every read that can fail before its first write).
        try {
            step.ship(ship);
        } catch (const std::invalid_argument&) {
            ++out.skipped;
        }
    }
    return out;
}

}  // namespace dauntless::combat
