// native/src/renderer/planet_detail_noise.cc
#include "renderer/planet_detail_noise.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>

namespace renderer::planet_detail {

namespace {

// Rotation applied to q between fbm octaves (column-major, matches the GLSL
// twin): kRot = mat3(0.00,0.80,0.60, -0.80,0.36,-0.48, -0.60,-0.48,0.64).
const glm::mat3 kRot(0.00f, 0.80f, 0.60f,
                      -0.80f, 0.36f, -0.48f,
                      -0.60f, -0.48f, 0.64f);

// Standard cubic smoothstep, e0 < e1.
float smoothstep(float e0, float e1, float x) {
    float t = std::clamp((x - e0) / (e1 - e0), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

glm::vec3 grad3(glm::ivec3 c, std::uint32_t seed) {
    glm::uvec3 h = pcg3d(glm::uvec3(c) + glm::uvec3(seed, seed * 7919u, seed * 104729u));
    return glm::vec3(h) * (2.0f / 4294967295.0f) - 1.0f;
}

}  // namespace

glm::uvec3 pcg3d(glm::uvec3 v) {
    v = v * 1664525u + 1013904223u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    v ^= v >> 16u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    return v;
}

glm::vec4 noised(const glm::vec3& x, std::uint32_t seed) {
    glm::vec3 fl = glm::floor(x);
    glm::ivec3 i(fl);
    glm::vec3 f = x - fl;
    glm::vec3 u = f * f * f * (f * (f * 6.0f - 15.0f) + 10.0f);
    glm::vec3 du = 30.0f * f * f * (f * (f - 2.0f) + 1.0f);

    // Eight corners: a=000, b=100, c=010, d=110, e=001, f=101, g=011, h=111.
    glm::vec3 ga = grad3(i + glm::ivec3(0, 0, 0), seed);
    glm::vec3 gb = grad3(i + glm::ivec3(1, 0, 0), seed);
    glm::vec3 gc = grad3(i + glm::ivec3(0, 1, 0), seed);
    glm::vec3 gd = grad3(i + glm::ivec3(1, 1, 0), seed);
    glm::vec3 ge = grad3(i + glm::ivec3(0, 0, 1), seed);
    glm::vec3 gf = grad3(i + glm::ivec3(1, 0, 1), seed);
    glm::vec3 gg = grad3(i + glm::ivec3(0, 1, 1), seed);
    glm::vec3 gh = grad3(i + glm::ivec3(1, 1, 1), seed);

    float va = glm::dot(ga, f - glm::vec3(0, 0, 0));
    float vb = glm::dot(gb, f - glm::vec3(1, 0, 0));
    float vc = glm::dot(gc, f - glm::vec3(0, 1, 0));
    float vd = glm::dot(gd, f - glm::vec3(1, 1, 0));
    float ve = glm::dot(ge, f - glm::vec3(0, 0, 1));
    float vf = glm::dot(gf, f - glm::vec3(1, 0, 1));
    float vg = glm::dot(gg, f - glm::vec3(0, 1, 1));
    float vh = glm::dot(gh, f - glm::vec3(1, 1, 1));

    float value = va
        + u.x * (vb - va)
        + u.y * (vc - va)
        + u.z * (ve - va)
        + u.x * u.y * (va - vb - vc + vd)
        + u.y * u.z * (va - vc - ve + vg)
        + u.z * u.x * (va - vb - ve + vf)
        + u.x * u.y * u.z * (-va + vb + vc - vd + ve - vf - vg + vh);

    glm::vec3 deriv = ga
        + u.x * (gb - ga)
        + u.y * (gc - ga)
        + u.z * (ge - ga)
        + u.x * u.y * (ga - gb - gc + gd)
        + u.y * u.z * (ga - gc - ge + gg)
        + u.z * u.x * (ga - gb - ge + gf)
        + u.x * u.y * u.z * (-ga + gb + gc - gd + ge - gf - gg + gh)
        + du * (
              glm::vec3(vb - va, vc - va, ve - va)
            + glm::vec3(u.y, u.z, u.x) * glm::vec3(va - vb - vc + vd, va - vc - ve + vg, va - vb - ve + vf)
            + glm::vec3(u.z, u.x, u.y) * glm::vec3(va - vb - ve + vf, va - vb - vc + vd, va - vc - ve + vg)
            + glm::vec3(u.y, u.z, u.x) * glm::vec3(u.z, u.x, u.y) * (-va + vb + vc - vd + ve - vf - vg + vh)
          );

    return glm::vec4(value, deriv.x, deriv.y, deriv.z);
}

namespace {

struct Acc { float h; glm::vec3 g; };

// q = p_local / (base_wavelength * scale). Returns height and d h / d q.
Acc fbm(glm::vec3 q, int n, float gain, float ridged, std::uint32_t seed) {
    float a = 0.5f, s = 1.0f;
    glm::mat3 m(1.0f);
    Acc r{0.0f, glm::vec3(0.0f)};
    for (int k = 0; k < n; ++k) {
        glm::vec4 nd = noised(m * q * s, seed + static_cast<std::uint32_t>(k) * 1013u);
        glm::vec3 dn = s * (glm::transpose(m) * glm::vec3(nd.y, nd.z, nd.w));
        if (ridged > 0.5f) {
            float an = std::fabs(nd.x);
            float rr = 1.0f - an;
            float sg = nd.x >= 0.0f ? 1.0f : -1.0f;
            r.h += a * (rr * rr - 0.5f);
            r.g += a * (-2.0f * rr * sg) * dn;
        } else {
            r.h += a * nd.x;
            r.g += a * dn;
        }
        s *= 2.0f;
        m = kRot * m;
        a *= gain;
    }
    return r;
}

FieldSample rocky_field(const TypeParams& p, glm::vec3 q, std::uint32_t seed, int octaves) {
    Acc r = fbm(q, octaves, p.gain, 1.0f, seed);
    float a = std::clamp(0.5f + 0.5f * noised(q * 4.0f, seed ^ 0xA5A5u).x, 0.0f, 1.0f);
    return FieldSample{r.h * p.amplitude, r.g * p.amplitude, a};
}

FieldSample desert_field(const TypeParams& p, glm::vec3 q, std::uint32_t seed, int octaves) {
    Acc r = fbm(q, octaves, p.gain, 0.0f, seed);

    float theta_deg = static_cast<float>(seed % 360u);
    float theta = theta_deg * (3.14159265358979323846f / 180.0f);
    glm::vec3 w(std::cos(theta), std::sin(theta), 0.0f);

    glm::vec3 q8 = q * 8.0f;
    glm::vec3 qd = q8 + w * (glm::dot(q8, w) * 5.0f);
    glm::vec4 nd = noised(qd, seed ^ 0x5A5Au);

    r.h += 0.15f * nd.x;
    // Chain rule: qd = 8*(I + 5*w*w^T) * q, so d(nd)/dq = 8*(I + 5*w*w^T)^T * dn
    // (the matrix is symmetric, so transpose is a no-op).
    glm::mat3 ww(w.x * w.x, w.x * w.y, w.x * w.z,
                 w.y * w.x, w.y * w.y, w.y * w.z,
                 w.z * w.x, w.z * w.y, w.z * w.z);
    glm::mat3 chain = 8.0f * (glm::mat3(1.0f) + 5.0f * ww);
    glm::vec3 dn(nd.y, nd.z, nd.w);
    r.g += 0.15f * (chain * dn);

    float a = std::clamp(0.5f + 0.5f * noised(q * 4.0f, seed ^ 0xA5A5u).x, 0.0f, 1.0f);
    return FieldSample{r.h * p.amplitude, r.g * p.amplitude, a};
}

FieldSample ice_field(const TypeParams& p, glm::vec3 q, std::uint32_t seed, int octaves) {
    Acc r = fbm(q, octaves, p.gain, 0.0f, seed);
    float c = noised(q * 2.0f, seed ^ 0x3C3Cu).x;
    float a = 1.0f - smoothstep(0.0f, p.crack_width, std::fabs(c));
    return FieldSample{r.h * p.amplitude, r.g * p.amplitude, a};
}

FieldSample gas_field(const TypeParams& p, glm::vec3 q, std::uint32_t seed, int octaves) {
    glm::vec3 qs(q.x, q.y, q.z * p.stretch);
    glm::vec3 w(
        noised(qs * 0.5f + glm::vec3(11.0f), seed).x,
        noised(qs * 0.5f + glm::vec3(23.0f), seed).x,
        noised(qs * 0.5f + glm::vec3(37.0f), seed).x);
    glm::vec3 qw = qs + p.warp * w;

    Acc r = fbm(qw, octaves, p.gain, 0.0f, seed);
    // The gradient ignores the warp Jacobian (gas's warp is informational
    // only), but keeps the latitude-stretch applied to the z component.
    glm::vec3 g(r.g.x, r.g.y, r.g.z * p.stretch);

    Acc r2 = fbm(qw, octaves, p.gain, 0.0f, seed + 1u);
    float a = std::clamp(0.5f + 0.5f * r2.h, 0.0f, 1.0f);

    return FieldSample{r.h * p.amplitude, g * p.amplitude, a};
}

FieldSample ocean_field(const TypeParams& p, glm::vec3 q, std::uint32_t seed, int /*octaves*/) {
    float a = std::clamp(0.5f + 0.5f * noised(q * 4.0f, seed ^ 0xA5A5u).x, 0.0f, 1.0f);
    return FieldSample{0.0f, glm::vec3(0.0f), a};
}

}  // namespace

FieldSample field(SurfaceType t, const TypeParams& p, const glm::vec3& p_local_gu,
                   std::uint32_t seed, float scale, int octaves) {
    float wavelength0 = p.base_wavelength_gu * scale;
    glm::vec3 q = p_local_gu / wavelength0;
    int n = std::clamp(octaves, 1, p.max_octaves);

    switch (t) {
        case SurfaceType::Rocky:  return rocky_field(p, q, seed, n);
        case SurfaceType::Desert: return desert_field(p, q, seed, n);
        case SurfaceType::Ice:    return ice_field(p, q, seed, n);
        case SurfaceType::Gas:    return gas_field(p, q, seed, n);
        case SurfaceType::Ocean:  return ocean_field(p, q, seed, n);
        case SurfaceType::None:
        default:
            return FieldSample{0.0f, glm::vec3(0.0f), 0.0f};
    }
}

int octaves_for_texel(const TypeParams& p, float scale, float texel_gu) {
    float wavelength = p.base_wavelength_gu * scale;
    int n = static_cast<int>(std::floor(std::log2(wavelength / (2.0f * texel_gu)))) + 1;
    return std::clamp(n, 1, p.max_octaves);
}

TypeParams default_params(SurfaceType t) {
    switch (t) {
        case SurfaceType::Rocky:
            return TypeParams{40.0f, 9, 0.5f, 1.0f, 1.0f, 0.35f, 0.10f, 0.30f, 0.5f,
                               0.0f, 1.0f, 0.0f, 0.0f, 40.0f, 0.08f, 0.25f};
        case SurfaceType::Desert:
            return TypeParams{60.0f, 8, 0.45f, 0.0f, 0.6f, 0.20f, 0.08f, 0.30f, 0.5f,
                               0.0f, 1.0f, 0.0f, 0.0f, 40.0f, 0.08f, 0.25f};
        case SurfaceType::Ice:
            return TypeParams{50.0f, 8, 0.5f, 0.0f, 0.3f, 0.12f, 0.06f, 0.12f, 0.3f,
                               0.06f, 1.0f, 0.0f, 0.0f, 40.0f, 0.06f, 0.20f};
        case SurfaceType::Gas:
            return TypeParams{200.0f, 7, 0.55f, 0.0f, 0.8f, 0.0f, 0.12f, 0.5f, 0.0f,
                               0.0f, 4.0f, 0.6f, 0.5f, 40.0f, 0.0f, 0.0f};
        case SurfaceType::Ocean:
            return TypeParams{40.0f, 3, 0.5f, 0.0f, 0.0f, 0.0f, 0.0f, 0.25f, 0.6f,
                               0.0f, 1.0f, 0.0f, 0.0f, 40.0f, 0.0f, 0.0f};
        case SurfaceType::None:
        default:
            return TypeParams{};
    }
}

namespace {
std::array<TypeParams, 6> make_live_table() {
    return {
        default_params(SurfaceType::None),
        default_params(SurfaceType::Rocky),
        default_params(SurfaceType::Desert),
        default_params(SurfaceType::Ice),
        default_params(SurfaceType::Gas),
        default_params(SurfaceType::Ocean),
    };
}
}  // namespace

TypeParams& live_params(SurfaceType t) {
    static std::array<TypeParams, 6> table = make_live_table();
    return table[static_cast<std::size_t>(t)];
}

void reset_live_params() {
    for (int t = 0; t <= 5; ++t) {
        live_params(static_cast<SurfaceType>(t)) = default_params(static_cast<SurfaceType>(t));
    }
}

std::uint32_t shape_hash(const TypeParams& p) {
    // FNV-1a over the bytes of the eight shape fields that change the baked
    // field: base_wavelength_gu, max_octaves, gain, ridged, amplitude,
    // crack_width, stretch, warp.
    std::uint32_t h = 2166136261u;
    auto mix_bytes = [&h](const void* data, std::size_t n) {
        const unsigned char* bytes = static_cast<const unsigned char*>(data);
        for (std::size_t i = 0; i < n; ++i) {
            h ^= bytes[i];
            h *= 16777619u;
        }
    };
    mix_bytes(&p.base_wavelength_gu, sizeof(p.base_wavelength_gu));
    mix_bytes(&p.max_octaves, sizeof(p.max_octaves));
    mix_bytes(&p.gain, sizeof(p.gain));
    mix_bytes(&p.ridged, sizeof(p.ridged));
    mix_bytes(&p.amplitude, sizeof(p.amplitude));
    mix_bytes(&p.crack_width, sizeof(p.crack_width));
    mix_bytes(&p.stretch, sizeof(p.stretch));
    mix_bytes(&p.warp, sizeof(p.warp));
    return h;
}

Anchor make_anchor(const glm::vec3& dir_local, float R) {
    glm::vec3 a = glm::normalize(dir_local);
    glm::vec3 z(0.0f, 0.0f, 1.0f);
    glm::vec3 e = glm::cross(z, a);
    if (glm::length(e) < 1e-3f) {
        e = glm::normalize(glm::cross(a, glm::vec3(0.0f, 1.0f, 0.0f)));
    } else {
        e = glm::normalize(e);
    }
    glm::vec3 n = glm::cross(a, e);
    return Anchor{a, e, n, R};
}

glm::vec2 to_plane(const Anchor& a, const glm::vec3& p_local) {
    glm::vec3 P = p_local * (a.R / glm::dot(p_local, a.A));
    return glm::vec2(glm::dot(P, a.E), glm::dot(P, a.N));
}

glm::vec3 from_plane(const Anchor& a, const glm::vec2& xy) {
    return glm::normalize(a.A * a.R + a.E * xy.x + a.N * xy.y) * a.R;
}

}  // namespace renderer::planet_detail
