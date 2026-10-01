// native/src/renderer/minor_field.cc
// Minor rocks (docs/superpowers/specs/2026-10-01-minor-rocks-design.md).
#include "renderer/minor_field.h"

#include <algorithm>
#include <cmath>
#include <tuple>

#include <glm/gtc/matrix_access.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <renderer/rock_random.h>

namespace renderer::minors {
namespace {

using rockrand::Rng;
using rockrand::unit_vector;
using rockrand::power_law;

// Fills tumble axis/rate and phase from `r` (draw order is part of determinism).
void fill_look(Minor& m, Rng& r) {
    m.tumble_axis = unit_vector(r);
    m.tumble_u = r.unit();
    m.phase = r.unit() * 6.28318530718f;
}

glm::mat3 rotation(float angle, const glm::vec3& axis) {
    return glm::mat3(glm::rotate(glm::mat4(1.0f), angle, axis));
}

// The one orbit axis a cloud's minors share, derived from its seed.
glm::vec3 orbit_axis(std::uint32_t seed) {
    Rng r{seed * 2654435761u};
    return unit_vector(r);
}

// Anchor-relative position of an orbiting minor at game time `t`.
glm::vec3 orbit_offset(const Minor& m, const glm::vec3& axis, float rate, double t) {
    const float angle = rate * m.orbit_u * static_cast<float>(t);
    if (angle == 0.0f) return m.offset;
    return rotation(angle, axis) * m.offset;
}

// 0 -> 1 over `seconds` from elapsed 0; `seconds <= 0` is an instant step to 1.
float ramp(double elapsed, float seconds) {
    if (!(seconds > 0.0f)) return 1.0f;
    return std::clamp(static_cast<float>(elapsed / seconds), 0.0f, 1.0f);
}

}  // namespace

std::vector<Minor> generate(const CloudDesc& d) {
    std::vector<Minor> out;
    const int n = std::max(0, d.count);
    out.reserve(static_cast<std::size_t>(n) + d.debris.size());
    Rng rng{(static_cast<std::uint64_t>(d.seed) << 1) ^ 0xA57E401DULL};
    const float i3 = d.shell_inner * d.shell_inner * d.shell_inner;
    const float o3 = d.shell_outer * d.shell_outer * d.shell_outer;
    for (int i = 0; i < n; ++i) {
        Minor m;
        // Volume-uniform in the shell when falloff == 0; u^(1+falloff)
        // biases toward the inner surface.
        const float u = std::pow(rng.unit(), 1.0f + std::max(0.0f, d.falloff));
        const float dist = std::cbrt(i3 + (o3 - i3) * u);
        m.offset = unit_vector(rng) * dist;
        m.radius = power_law(rng.unit(), d.r_min, d.r_max, d.size_exponent);
        fill_look(m, rng);
        m.orbit_u = 0.5f + 0.5f * rng.unit();
        m.mesh_u = static_cast<std::uint32_t>(rng.next() >> 32);
        out.push_back(m);
    }
    for (const auto& s : d.debris) {
        Rng dr{(static_cast<std::uint64_t>(s.seed) << 1) ^ 0xDEB815ULL};
        Minor m;
        m.offset = s.offset;
        m.v0 = s.v0;
        m.radius = s.radius;
        fill_look(m, dr);
        m.orbit_u = 0.0f;                    // debris does not orbit
        m.mesh_u = static_cast<std::uint32_t>(dr.next() >> 32);
        m.debris = true;
        out.push_back(m);
    }
    return out;
}

void MinorField::set_fragments(int family, std::vector<Fragment> f) { fragments_[family] = std::move(f); }
const std::vector<Fragment>& MinorField::fragments(int family) const {
    static const std::vector<Fragment> kNone;
    auto it = fragments_.find(family);
    return it == fragments_.end() ? kNone : it->second;
}
void MinorField::add_cloud(const CloudDesc& d, double now) {
    Cloud c;
    c.desc = d;
    c.minors = generate(d);
    c.born = now;
    c.fading_in = d.fade_in;
    clouds_[d.id] = std::move(c);   // replaces same id; shoves start empty
}

void MinorField::remove_cloud(std::uint32_t id) { clouds_.erase(id); }

void MinorField::detach(std::uint32_t id, const glm::dvec3& p0_view, const glm::vec3& v,
                        double t0, const std::vector<DebrisSpec>& debris) {
    auto it = clouds_.find(id);
    if (it == clouds_.end()) return;
    Cloud& c = it->second;
    // The minors are left as generated: a Free cloud evaluates its orbit at
    // min(t, t0) (step), so each minor stays where it was at t0, and a free
    // cloud built fresh from the same descriptor (seed, orbit_rate, t0)
    // poses identically.
    c.desc.anchor = Anchor::Free;
    c.desc.point = p0_view;
    c.desc.velocity = v;
    c.desc.t0 = t0;
    CloudDesc dd;
    dd.count = 0;
    dd.debris = debris;
    for (const auto& m : generate(dd)) c.minors.push_back(m);
}

void MinorField::fade_out(std::uint32_t id, float seconds, double now) {
    auto it = clouds_.find(id);
    if (it == clouds_.end()) return;
    it->second.fade_out_start = now;
    it->second.fade_out_seconds = seconds;
}

void MinorField::clear() {
    clouds_.clear();
    bins_.clear();
    stats_ = Stats{};
    last_time_ = -1.0;
    stepped_ = false;
    has_prev_ = false;
    contacts_.clear();     // a pending contact would puff for a dead mission's rock
    fragments_.clear();    // model handles are recycled after a reset
}

void MinorField::step(const StepInput& in) {
    const double t = in.game_time;
    // dt <= 0 is a paused frame (or the first): no contact, no integration.
    const double dt = stepped_ ? t - last_time_ : 0.0;
    bins_.clear();
    stats_ = Stats{};
    stats_.clouds = static_cast<int>(clouds_.size());

    const float tau = dials_.debris_damp_seconds / std::log(2.0f);

    // 1. Integrate every shove: the offset persists, velocity and spin decay.
    if (dt > 0.0) {
        const float fdt = static_cast<float>(dt);
        const float decay = std::pow(0.5f, fdt / dials_.shove_damp_seconds);
        for (auto& [id, c] : clouds_) {
            (void)id;
            for (auto& [i, sh] : c.shoves) {
                (void)i;
                sh.offset += sh.vel * fdt;
                sh.vel *= decay;
                sh.spin += sh.spin_rate * fdt;
                sh.spin_rate *= decay;
            }
        }
    }

    // 2. Anchors and minor positions, render space.
    for (auto& [id, c] : clouds_) {
        (void)id;
        stats_.minors += static_cast<int>(c.minors.size());
        const CloudDesc& d = c.desc;

        c.anchor_ok = true;
        switch (d.anchor) {
        case Anchor::Instance:
            c.anchor_ok = in.anchor_of && in.anchor_of(d.instance_key, c.anchor_render);
            break;
        case Anchor::Point:
            c.anchor_render = glm::vec3(d.point - in.render_origin);
            break;
        case Anchor::Free:
            c.anchor_render = glm::vec3(d.point + glm::dvec3(d.velocity) * (t - d.t0)
                                        - in.render_origin);
            break;
        }
        if (!c.anchor_ok) { c.pos.clear(); continue; }

        const glm::vec3 axis = orbit_axis(d.seed);
        // A Free cloud's orbit is frozen at t0 (the detach instant).
        const double orbit_t = d.anchor == Anchor::Free ? std::min(t, d.t0) : t;
        const float debris_k =
            tau * (1.0f - std::exp(-std::max(0.0f, static_cast<float>(t - d.t0)) / tau));
        c.pos.resize(c.minors.size());
        for (std::size_t i = 0; i < c.minors.size(); ++i) {
            const Minor& m = c.minors[i];
            glm::vec3 local = m.debris ? m.offset + m.v0 * debris_k
                                       : orbit_offset(m, axis, d.orbit_rate, orbit_t);
            if (auto sh = c.shoves.find(static_cast<std::uint32_t>(i)); sh != c.shoves.end())
                local += sh->second.offset;
            c.pos[i] = c.anchor_render + local;
        }
    }

    // 3. Player contact (spec §3): swept oriented box against the minors.
    if (in.player) step_contact(*in.player, in.render_origin, t, dt, tau);

    // 4. Cull, LOD and bin against the step's own camera.
    last_time_ = t;
    stepped_ = true;
    build_bins(in.view, in.proj, in.viewport_h, bins_, &stats_.drawn);
    stats_.bins = static_cast<int>(bins_.size());
}

void MinorField::build_bins(const glm::mat4& view, const glm::mat4& proj,
                            float viewport_h, std::vector<Bin>& out, int* drawn) const {
    out.clear();
    if (drawn != nullptr) *drawn = 0;
    if (!stepped_) return;                       // no poses yet
    const double t = last_time_;                 // the poses' game time
    // Frustum planes (Gribb-Hartmann), normalised: inside iff dot(n,p)+d >= -r.
    const glm::mat4 vp = proj * view;
    const glm::vec4 r0 = glm::row(vp, 0), r1 = glm::row(vp, 1),
                    r2 = glm::row(vp, 2), r3 = glm::row(vp, 3);
    glm::vec4 planes[6] = {r3 + r0, r3 - r0, r3 + r1, r3 - r1, r3 + r2, r3 - r2};
    for (auto& p : planes) p /= glm::length(glm::vec3(p));
    const float px_per_gu = proj[1][1] * 0.5f * viewport_h;

    std::map<std::tuple<int, int, int>, std::vector<InstanceGpu>> binned;
    for (auto& [id, c] : clouds_) {
        (void)id;
        if (!c.anchor_ok) continue;
        const CloudDesc& d = c.desc;

        // A ramp of <= 0 seconds is an instant step (no 0/0 NaN at its start).
        float fade = 1.0f;
        if (c.fading_in)
            fade *= ramp(t - c.born, dials_.cloud_fade_in_seconds);
        if (c.fade_out_start >= 0.0)
            fade *= 1.0f - ramp(t - c.fade_out_start, c.fade_out_seconds);

        const auto& frags = fragments(d.family);
        if (!(fade > 0.0f) || frags.empty()) continue;   // NaN-safe
        // pos is the last step's: a detach() since then appended debris that
        // has no pose yet, so bin only the posed prefix.
        const std::size_t posed = std::min(c.minors.size(), c.pos.size());
        for (std::size_t i = 0; i < posed; ++i) {
            const Minor& m = c.minors[i];
            const glm::vec3 p = c.pos[i];
            float spin = 0.0f;
            if (auto sh = c.shoves.find(static_cast<std::uint32_t>(i)); sh != c.shoves.end())
                spin = sh->second.spin;

            const float r = m.radius * fade;
            bool inside = true;
            for (const auto& pl : planes)
                if (glm::dot(glm::vec3(pl), p) + pl.w < -r) { inside = false; break; }
            if (!inside) continue;
            const float z_view = (view * glm::vec4(p, 1.0f)).z;
            const float pixel_r = r * px_per_gu / std::max(-z_view, 1e-3f);
            if (pixel_r < dials_.min_pixel_radius) continue;
            const int lod = pixel_r >= dials_.lod0_pixel_radius ? 0 : 1;
            const int slot = static_cast<int>(m.mesh_u % frags.size());

            const float angle = m.phase
                + glm::mix(dials_.tumble_min, dials_.tumble_max, m.tumble_u) * static_cast<float>(t)
                + spin;
            const float s = r / frags[slot].bound_radius_mu;   // model units straight to GU
            const glm::mat3 rs = rotation(angle, m.tumble_axis) * s;
            InstanceGpu g;   // rows of [R·s | t]; glm is column-major: rs[col][row]
            g.row0 = {rs[0][0], rs[1][0], rs[2][0], p.x};
            g.row1 = {rs[0][1], rs[1][1], rs[2][1], p.y};
            g.row2 = {rs[0][2], rs[1][2], rs[2][2], p.z};
            binned[{d.family, slot, lod}].push_back(g);
        }
    }

    for (auto& [key, items] : binned) {
        Bin b;
        std::tie(b.family, b.slot, b.lod) = key;
        if (drawn != nullptr) *drawn += static_cast<int>(items.size());
        b.items = std::move(items);
        out.push_back(std::move(b));
    }
}

void MinorField::step_contact(const PlayerBox& box, const glm::dvec3& render_origin,
                              double t, double dt, float tau) {
    // OBB, render space: centre, unit axes, inflated half extents, bound.
    const glm::vec3 c = glm::vec3(box.world * glm::vec4(box.center_mu, 1.0f));
    glm::vec3 a[3], h;
    for (int k = 0; k < 3; ++k) {
        const glm::vec3 col = glm::vec3(box.world[k]);
        const float len = glm::length(col);
        a[k] = len > 0.0f ? col / len : glm::vec3(k == 0, k == 1, k == 2);
        h[k] = len * box.half_mu[k] + dials_.contact_margin_gu;
    }
    const float bound = glm::length(h);

    // The previous centre lives in VIEW space so a moved render origin is not travel.
    const glm::dvec3 c_view = glm::dvec3(c) + render_origin;
    const bool had_prev = has_prev_;
    const glm::vec3 prev_render = glm::vec3(prev_center_view_ - render_origin);
    has_prev_ = true;
    prev_center_view_ = c_view;
    if (!(dt > 0.0)) return;

    glm::vec3 seg0 = c;
    float travel = had_prev ? glm::length(c - prev_render) : 0.0f;
    glm::vec3 v_player{0.0f};
    if (had_prev && travel <= dials_.teleport_gu) {
        seg0 = prev_render;
        v_player = (c - prev_render) / static_cast<float>(dt);
    } else {
        travel = 0.0f;                          // teleport / no pose: current pose only
    }
    const float rel_speed = glm::length(v_player);
    const glm::vec3 seg = c - seg0;
    const float seg_len2 = glm::dot(seg, seg);
    auto dist_to_segment = [&](const glm::vec3& p) {
        const float u = seg_len2 > 0.0f
            ? std::clamp(glm::dot(p - seg0, seg) / seg_len2, 0.0f, 1.0f) : 0.0f;
        return glm::length(p - (seg0 + seg * u));
    };
    // Closest point on the OBB centred at `ck` to `p` (orientation fixed this frame).
    auto closest_on_box = [&](const glm::vec3& ck, const glm::vec3& p) {
        const glm::vec3 d = p - ck;
        glm::vec3 q = ck;
        for (int ax = 0; ax < 3; ++ax)
            q += a[ax] * std::clamp(glm::dot(d, a[ax]), -h[ax], h[ax]);
        return q;
    };

    int touches = 0;
    for (auto& [id, cl] : clouds_) {
        (void)id;
        if (!cl.anchor_ok || cl.pos.empty()) continue;
        if (touches >= dials_.max_shoves_per_frame) break;

        // Cloud reject: anchor sphere, grown by the largest shove offset.
        float extent = cl.desc.shell_outer + cl.desc.r_max + 10.0f;
        if (cl.desc.anchor == Anchor::Free) {
            // Orbit is a rotation about the anchor (frozen at t0): |offset| holds.
            extent = 0.0f;
            for (const auto& m : cl.minors)
                extent = std::max(extent, glm::length(m.offset) + glm::length(m.v0) * tau + m.radius);
        }
        float shove_ext = 0.0f;
        for (const auto& [i, sh] : cl.shoves) { (void)i; shove_ext = std::max(shove_ext, glm::length(sh.offset)); }
        if (dist_to_segment(cl.anchor_render) > extent + shove_ext + bound) continue;

        for (std::size_t i = 0; i < cl.minors.size(); ++i) {
            if (touches >= dials_.max_shoves_per_frame) break;
            const float radius = cl.minors[i].radius;
            const glm::vec3 p = cl.pos[i];
            if (dist_to_segment(p) > radius + bound) continue;

            // Exact sweep: with the orientation fixed, f(s) = |p - box(lerp(seg0, c, s))|
            // is convex in s, so golden-section search finds its minimum. No sub-step
            // cap, so no tunnelling at any speed below teleport_gu.
            auto f = [&](float u) {
                const glm::vec3 ck = seg0 + seg * u;
                return glm::length(p - closest_on_box(ck, p));
            };
            float s = 1.0f;
            if (seg_len2 > 0.0f) {
                constexpr float kInvPhi = 0.6180339887f;
                float lo = 0.0f, hi = 1.0f;
                float x1 = hi - kInvPhi * (hi - lo), x2 = lo + kInvPhi * (hi - lo);
                float f1 = f(x1), f2 = f(x2);
                for (int it = 0; it < 30; ++it) {
                    if (f1 <= f2) { hi = x2; x2 = x1; f2 = f1; x1 = hi - kInvPhi * (hi - lo); f1 = f(x1); }
                    else          { lo = x1; x1 = x2; f1 = f2; x2 = lo + kInvPhi * (hi - lo); f2 = f(x2); }
                }
                s = 0.5f * (lo + hi);
                if (f(1.0f) <= f(s)) s = 1.0f;     // prefer the current pose on a tie
            }
            const glm::vec3 ck = seg0 + seg * s;
            const glm::vec3 d = p - ck;
            {
                // Inside is decided in box-local coordinates: q = ck + sum a_k clamp(..)
                // does not round-trip to p in float for a rotated box.
                float dl[3];
                bool inside = true;
                for (int ax = 0; ax < 3; ++ax) {
                    dl[ax] = glm::dot(d, a[ax]);
                    inside = inside && std::fabs(dl[ax]) <= h[ax];
                }
                glm::vec3 nrm, q, push;
                if (inside) {
                    // Exit through the face of least penetration, ending one radius out.
                    int k = 0;
                    for (int ax = 1; ax < 3; ++ax)
                        if (h[ax] - std::fabs(dl[ax]) < h[k] - std::fabs(dl[k])) k = ax;
                    const float depth = h[k] - std::fabs(dl[k]);
                    nrm = a[k] * (dl[k] >= 0.0f ? 1.0f : -1.0f);
                    q = p + nrm * depth;                       // on that face
                    push = nrm * (depth + radius);
                } else {
                    q = closest_on_box(ck, p);
                    const float gap = glm::length(p - q);
                    if (gap > radius) continue;
                    nrm = (p - q) / gap;
                    push = nrm * (radius - gap);
                }

                Shove& sh = cl.shoves[static_cast<std::uint32_t>(i)];
                sh.offset += push;                             // sit on the surface
                cl.pos[i] += push;
                sh.vel = nrm * (std::max(glm::dot(v_player, nrm), 0.0f) * dials_.shove_transfer
                                + dials_.shove_min_gups);
                sh.spin_rate = std::max(sh.spin_rate, dials_.shove_tumble);   // re-touches do not ramp
                if (t - sh.last_contact >= dials_.contact_cooldown_s) {
                    contacts_.push_back({glm::dvec3(q) + render_origin, radius, rel_speed});
                    sh.last_contact = t;
                }
                ++touches;
            }
        }
    }
}

bool MinorField::minor_position(std::uint32_t id, std::size_t i, glm::vec3& out) const {
    auto it = clouds_.find(id);
    if (it == clouds_.end() || i >= it->second.pos.size()) return false;
    out = it->second.pos[i];
    return true;
}

void MinorField::debug_set_phase(std::uint32_t id, std::size_t i, float phase) {
    auto it = clouds_.find(id);
    if (it == clouds_.end() || i >= it->second.minors.size()) return;
    it->second.minors[i].phase = phase;
}

}  // namespace renderer::minors
