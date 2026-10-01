// native/src/renderer/minor_field.cc
// Minor rocks (docs/superpowers/specs/2026-10-01-minor-rocks-design.md).
#include "renderer/minor_field.h"

#include <algorithm>
#include <cmath>
#include <tuple>

#include <glm/gtc/matrix_access.hpp>
#include <glm/gtc/matrix_transform.hpp>

namespace renderer::minors {
namespace {

// splitmix64: deterministic, platform-independent (std::*_distribution is not).
struct Rng {
    std::uint64_t s;
    std::uint64_t next() {
        std::uint64_t z = (s += 0x9E3779B97F4A7C15ull);
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
        return z ^ (z >> 31);
    }
    float unit() { return static_cast<float>(next() >> 40) / 16777216.0f; }  // [0,1)
};

glm::vec3 unit_vector(Rng& r) {
    const float z = r.unit() * 2.0f - 1.0f;
    const float t = r.unit() * 6.28318530718f;
    const float s = std::sqrt(std::max(0.0f, 1.0f - z * z));
    return {s * std::cos(t), s * std::sin(t), z};
}

// Inverse CDF of pdf ∝ r^-a on [lo, hi].
float power_law(float u, float lo, float hi, float a) {
    if (hi <= lo) return lo;
    if (std::fabs(a - 1.0f) < 1e-4f)
        return lo * std::pow(hi / lo, u);
    const float e = 1.0f - a;
    const float l = std::pow(lo, e), h = std::pow(hi, e);
    return std::pow(l + u * (h - l), 1.0f / e);
}

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
    // Re-base every orbit minor on its anchor-relative position at t0 and stop
    // the orbit, so the minor does not jump when the anchor turns Free.
    const glm::vec3 axis = orbit_axis(c.desc.seed);
    for (auto& m : c.minors) {
        if (m.debris) continue;
        m.offset = orbit_offset(m, axis, c.desc.orbit_rate, t0);
        m.orbit_u = 0.0f;
    }
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
}

void MinorField::step(const StepInput& in) {
    const double t = in.game_time;
    bins_.clear();
    stats_ = Stats{};
    stats_.clouds = static_cast<int>(clouds_.size());

    // Frustum planes (Gribb-Hartmann), normalised: inside iff dot(n,p)+d >= -r.
    const glm::mat4 vp = in.proj * in.view;
    const glm::vec4 r0 = glm::row(vp, 0), r1 = glm::row(vp, 1),
                    r2 = glm::row(vp, 2), r3 = glm::row(vp, 3);
    glm::vec4 planes[6] = {r3 + r0, r3 - r0, r3 + r1, r3 - r1, r3 + r2, r3 - r2};
    for (auto& p : planes) p /= glm::length(glm::vec3(p));
    const float px_per_gu = in.proj[1][1] * 0.5f * in.viewport_h;
    const float tau = dials_.debris_damp_seconds / std::log(2.0f);

    std::map<std::tuple<int, int, int>, std::vector<InstanceGpu>> binned;
    for (auto& [id, c] : clouds_) {
        (void)id;
        stats_.minors += static_cast<int>(c.minors.size());
        const CloudDesc& d = c.desc;

        // Anchor in render space.
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

        // A ramp of <= 0 seconds is an instant step (no 0/0 NaN at its start).
        float fade = 1.0f;
        if (c.fading_in)
            fade *= ramp(t - c.born, dials_.cloud_fade_in_seconds);
        if (c.fade_out_start >= 0.0)
            fade *= 1.0f - ramp(t - c.fade_out_start, c.fade_out_seconds);

        const auto& frags = fragments(d.family);
        const glm::vec3 axis = orbit_axis(d.seed);
        const float debris_k =
            tau * (1.0f - std::exp(-std::max(0.0f, static_cast<float>(t - d.t0)) / tau));
        c.pos.resize(c.minors.size());
        for (std::size_t i = 0; i < c.minors.size(); ++i) {
            const Minor& m = c.minors[i];
            glm::vec3 local = m.debris ? m.offset + m.v0 * debris_k
                                       : orbit_offset(m, axis, d.orbit_rate, t);
            float spin = 0.0f;
            if (auto sh = c.shoves.find(static_cast<std::uint32_t>(i)); sh != c.shoves.end()) {
                local += sh->second.offset;
                spin = sh->second.spin;
            }
            const glm::vec3 p = c.anchor_render + local;
            c.pos[i] = p;

            if (!(fade > 0.0f) || frags.empty()) continue;   // NaN-safe
            const float r = m.radius * fade;
            bool inside = true;
            for (const auto& pl : planes)
                if (glm::dot(glm::vec3(pl), p) + pl.w < -r) { inside = false; break; }
            if (!inside) continue;
            const float z_view = (in.view * glm::vec4(p, 1.0f)).z;
            const float pixel_r = r * px_per_gu / std::max(-z_view, 1e-3f);
            if (pixel_r < dials_.min_pixel_radius) continue;
            const int lod = pixel_r >= dials_.lod0_pixel_radius ? 0 : 1;
            const int slot = static_cast<int>(m.mesh_u % frags.size());

            const float angle = m.phase
                + glm::mix(dials_.tumble_min, dials_.tumble_max, m.tumble_u) * static_cast<float>(t)
                + spin;
            const float s = r / (frags[slot].bound_radius_mu * 0.01f);
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
        stats_.drawn += static_cast<int>(items.size());
        b.items = std::move(items);
        bins_.push_back(std::move(b));
    }
    stats_.bins = static_cast<int>(bins_.size());
    last_time_ = t;
}

bool MinorField::minor_position(std::uint32_t id, std::size_t i, glm::vec3& out) const {
    auto it = clouds_.find(id);
    if (it == clouds_.end() || i >= it->second.pos.size()) return false;
    out = it->second.pos[i];
    return true;
}

}  // namespace renderer::minors
