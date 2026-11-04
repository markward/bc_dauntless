#include "dauntless/interp_buffer.h"

#include <cmath>

// Every expression below is engine/core/interpolate.py's, in the same order,
// so with -ffp-contract=off (CMakeLists.txt) it rounds exactly as CPython.

namespace dauntless {

namespace {

constexpr double kEps = 1e-9;

struct V {
    double x, y, z;
};

// _norm_or_none: unit vector, or false when the magnitude is ~0.
bool norm_or_none(const V& v, V& out) {
    const double m = std::sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
    if (m < kEps) return false;
    out = V{v.x / m, v.y / m, v.z / m};
    return true;
}

// TGMatrix3.GetCol on the row-major store layout.
V col(const Pose& p, int c) { return V{p.rot[c], p.rot[3 + c], p.rot[6 + c]}; }

// _first_valid_col(idx, (cur, prev), fallback).
V first_valid_col(int idx, const Pose& cur, const Pose& prev, const V& fallback) {
    V n;
    if (norm_or_none(col(cur, idx), n)) return n;
    if (norm_or_none(col(prev, idx), n)) return n;
    return fallback;
}

V any_perpendicular(const V& f) {
    const V axis = std::abs(f.z) < 0.9 ? V{0.0, 0.0, 1.0} : V{1.0, 0.0, 0.0};
    const V p{
        f.y * axis.z - f.z * axis.y,
        f.z * axis.x - f.x * axis.z,
        f.x * axis.y - f.y * axis.x,
    };
    V n;
    return norm_or_none(p, n) ? n : V{0.0, 0.0, 1.0};
}

V lerp_col(const Pose& a, const Pose& b, int c, double alpha) {
    const V ca = col(a, c), cb = col(b, c);
    return V{ca.x + alpha * (cb.x - ca.x),
             ca.y + alpha * (cb.y - ca.y),
             ca.z + alpha * (cb.z - ca.z)};
}

}  // namespace

Pose lerp_pose(const Pose& prev, const Pose& cur, double alpha) {
    Pose out{};
    for (int i = 0; i < 3; ++i)
        out.pos[i] = prev.pos[i] + alpha * (cur.pos[i] - prev.pos[i]);

    // nlerp_rotation: the blended right column is discarded and re-derived.
    V f;
    if (!norm_or_none(lerp_col(prev, cur, 1, alpha), f))
        f = first_valid_col(1, cur, prev, V{0.0, 1.0, 0.0});
    const V u_in = lerp_col(prev, cur, 2, alpha);
    const double dot_uf = u_in.x * f.x + u_in.y * f.y + u_in.z * f.z;
    V u;
    if (!norm_or_none(V{u_in.x - dot_uf * f.x,
                        u_in.y - dot_uf * f.y,
                        u_in.z - dot_uf * f.z}, u)) {
        const V u_src = first_valid_col(2, cur, prev, any_perpendicular(f));
        const double d = u_src.x * f.x + u_src.y * f.y + u_src.z * f.z;
        if (!norm_or_none(V{u_src.x - d * f.x, u_src.y - d * f.y,
                            u_src.z - d * f.z}, u))
            u = any_perpendicular(f);
    }
    const V r{
        f.y * u.z - f.z * u.y,
        f.z * u.x - f.x * u.z,
        f.x * u.y - f.y * u.x,
    };
    const V cols[3] = {r, f, u};
    for (int c = 0; c < 3; ++c) {
        out.rot[c] = cols[c].x;
        out.rot[3 + c] = cols[c].y;
        out.rot[6 + c] = cols[c].z;
    }
    return out;
}

bool InterpBuffer::has(Key k) const { return entries_.count(k) != 0; }

void InterpBuffer::roll() {
    for (auto& [k, e] : entries_) e.prev = e.cur;
}

void InterpBuffer::capture(Key k, const Pose& p) {
    auto [it, inserted] = entries_.try_emplace(k, Entry{p, p});
    if (!inserted) it->second.cur = p;
}

void InterpBuffer::set_previous(Key k, const Pose& p) {
    auto it = entries_.find(k);
    if (it != entries_.end()) it->second.prev = p;
}

void InterpBuffer::snap(Key k, const Pose& p) { entries_[k] = Entry{p, p}; }

void InterpBuffer::erase(Key k) { entries_.erase(k); }

void InterpBuffer::clear() { entries_.clear(); }

bool InterpBuffer::sample(Key k, double alpha, Pose& out) const {
    auto it = entries_.find(k);
    if (it == entries_.end()) return false;
    out = lerp_pose(it->second.prev, it->second.cur, alpha);
    return true;
}

bool HandoverBlend::active() const {
    return has_frozen_ && elapsed_ < kHandoverSeconds;
}

void HandoverBlend::begin(const Pose& frozen) {
    has_frozen_ = true;
    frozen_ = frozen;
    elapsed_ = 0.0;
}

void HandoverBlend::advance(double dt) {
    if (!has_frozen_) return;
    elapsed_ += dt;
}

void HandoverBlend::cancel() {
    has_frozen_ = false;
    frozen_ = Pose{};
    elapsed_ = 0.0;
}

Pose HandoverBlend::blend(const Pose& truth) const {
    if (!active()) return truth;
    const double t = elapsed_ / kHandoverSeconds;
    const double eased = t * t * (3.0 - 2.0 * t);  // smoothstep, as Python
    return lerp_pose(frozen_, truth, eased);
}

}  // namespace dauntless
