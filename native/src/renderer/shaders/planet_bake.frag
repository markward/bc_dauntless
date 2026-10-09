#version 410 core
// planet_bake.frag — bakes one scissored BakeRect of the planet surface-detail
// clipmap atlas (planet_clipmap_atlas.cc).
//
// THIS FILE IS A TWIN. The authority is native/src/renderer/planet_detail_noise.cc:
// pcg3d, grad3, noised, fbm and the per-type *_field functions below are its
// line-for-line transcription — same names, constants and evaluation order.
// Change one, change both; PlanetClipmapAtlasTest pins GPU against CPU.
// Notes on the transcription:
//   - uint arithmetic wraps mod 2^32 here exactly as std::uint32_t does.
//   - the ridged sign is a ternary, never sign() (which returns 0 at 0).
//   - smoothstep is the local twin, not the builtin (undefined for e0 >= e1).

layout(location = 0) out vec4 o;

uniform vec2  u_abs;    // absolute texel of the rect's lower-left
uniform vec2  u_tor;    // (tor_x, level*1026 + band_row) of the same texel
uniform float u_ts;     // texel size of this level, GU
uniform int   u_oct;    // octaves for this level (octaves_for_texel)
uniform vec3  u_A;
uniform vec3  u_E;
uniform vec3  u_N;
uniform float u_R;
uniform int   u_type;   // SurfaceType
uniform uint  u_seed;
uniform float u_scale;  // Surface::scale

// TypeParams, field for field.
uniform float u_p_base_wavelength_gu;
uniform int   u_p_max_octaves;
uniform float u_p_gain;
uniform float u_p_ridged;
uniform float u_p_amplitude;
uniform float u_p_bump;
uniform float u_p_albedo;
uniform float u_p_roughness;
uniform float u_p_roughness_var;
uniform float u_p_crack_width;
uniform float u_p_stretch;
uniform float u_p_warp;
uniform float u_p_gas_rate_gups;
uniform float u_p_gas_period_s;
uniform float u_p_coast_k;
uniform float u_p_coast_a;

const mat3 kRot = mat3(0.00, 0.80, 0.60,
                       -0.80, 0.36, -0.48,
                       -0.60, -0.48, 0.64);

float smoothstep_twin(float e0, float e1, float x) {
    float t = clamp((x - e0) / (e1 - e0), 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}

uvec3 pcg3d(uvec3 v) {
    v = v * 1664525u + 1013904223u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    v ^= v >> 16u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    return v;
}

vec3 grad3(ivec3 c, uint seed) {
    uvec3 h = pcg3d(uvec3(c) + uvec3(seed, seed * 7919u, seed * 104729u));
    return vec3(h) * (2.0 / 4294967295.0) - 1.0;
}

vec4 noised(vec3 x, uint seed) {
    vec3 fl = floor(x);
    ivec3 i = ivec3(fl);
    vec3 f = x - fl;
    vec3 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
    vec3 du = 30.0 * f * f * (f * (f - 2.0) + 1.0);

    // Eight corners: a=000, b=100, c=010, d=110, e=001, f=101, g=011, h=111.
    vec3 ga = grad3(i + ivec3(0, 0, 0), seed);
    vec3 gb = grad3(i + ivec3(1, 0, 0), seed);
    vec3 gc = grad3(i + ivec3(0, 1, 0), seed);
    vec3 gd = grad3(i + ivec3(1, 1, 0), seed);
    vec3 ge = grad3(i + ivec3(0, 0, 1), seed);
    vec3 gf = grad3(i + ivec3(1, 0, 1), seed);
    vec3 gg = grad3(i + ivec3(0, 1, 1), seed);
    vec3 gh = grad3(i + ivec3(1, 1, 1), seed);

    float va = dot(ga, f - vec3(0, 0, 0));
    float vb = dot(gb, f - vec3(1, 0, 0));
    float vc = dot(gc, f - vec3(0, 1, 0));
    float vd = dot(gd, f - vec3(1, 1, 0));
    float ve = dot(ge, f - vec3(0, 0, 1));
    float vf = dot(gf, f - vec3(1, 0, 1));
    float vg = dot(gg, f - vec3(0, 1, 1));
    float vh = dot(gh, f - vec3(1, 1, 1));

    float value = va
        + u.x * (vb - va)
        + u.y * (vc - va)
        + u.z * (ve - va)
        + u.x * u.y * (va - vb - vc + vd)
        + u.y * u.z * (va - vc - ve + vg)
        + u.z * u.x * (va - vb - ve + vf)
        + u.x * u.y * u.z * (-va + vb + vc - vd + ve - vf - vg + vh);

    vec3 deriv = ga
        + u.x * (gb - ga)
        + u.y * (gc - ga)
        + u.z * (ge - ga)
        + u.x * u.y * (ga - gb - gc + gd)
        + u.y * u.z * (ga - gc - ge + gg)
        + u.z * u.x * (ga - gb - ge + gf)
        + u.x * u.y * u.z * (-ga + gb + gc - gd + ge - gf - gg + gh)
        + du * (
              vec3(vb - va, vc - va, ve - va)
            + vec3(u.y, u.z, u.x) * vec3(va - vb - vc + vd, va - vc - ve + vg, va - vb - ve + vf)
            + vec3(u.z, u.x, u.y) * vec3(va - vb - ve + vf, va - vb - vc + vd, va - vc - ve + vg)
            + vec3(u.y, u.z, u.x) * vec3(u.z, u.x, u.y) * (-va + vb + vc - vd + ve - vf - vg + vh)
          );

    return vec4(value, deriv.x, deriv.y, deriv.z);
}

struct Acc { float h; vec3 g; };

// q = p_local / (base_wavelength * scale). Returns height and d h / d q.
Acc fbm(vec3 q, int n, float gain, float ridged, uint seed) {
    float a = 0.5, s = 1.0;
    mat3 m = mat3(1.0);
    Acc r = Acc(0.0, vec3(0.0));
    for (int k = 0; k < n; ++k) {
        vec4 nd = noised(m * q * s, seed + uint(k) * 1013u);
        vec3 dn = s * (transpose(m) * vec3(nd.y, nd.z, nd.w));
        if (ridged > 0.5) {
            float an = abs(nd.x);
            float rr = 1.0 - an;
            float sg = nd.x >= 0.0 ? 1.0 : -1.0;
            r.h += a * (rr * rr - 0.5);
            r.g += a * (-2.0 * rr * sg) * dn;
        } else {
            r.h += a * nd.x;
            r.g += a * dn;
        }
        s *= 2.0;
        m = kRot * m;
        a *= gain;
    }
    return r;
}

struct FieldSample { float h; vec3 grad; float a; };

FieldSample rocky_field(vec3 q, uint seed, int octaves) {
    Acc r = fbm(q, octaves, u_p_gain, 1.0, seed);
    float a = clamp(0.5 + 0.5 * noised(q * 4.0, seed ^ 0xA5A5u).x, 0.0, 1.0);
    return FieldSample(r.h * u_p_amplitude, r.g * u_p_amplitude, a);
}

FieldSample desert_field(vec3 q, uint seed, int octaves) {
    Acc r = fbm(q, octaves, u_p_gain, 0.0, seed);

    float theta_deg = float(seed % 360u);
    float theta = theta_deg * (3.14159265358979323846 / 180.0);
    vec3 w = vec3(cos(theta), sin(theta), 0.0);

    vec3 q8 = q * 8.0;
    vec3 qd = q8 + w * (dot(q8, w) * 5.0);
    vec4 nd = noised(qd, seed ^ 0x5A5Au);

    r.h += 0.15 * nd.x;
    // Chain rule: qd = 8*(I + 5*w*w^T) * q (symmetric).
    mat3 ww = mat3(w.x * w.x, w.x * w.y, w.x * w.z,
                   w.y * w.x, w.y * w.y, w.y * w.z,
                   w.z * w.x, w.z * w.y, w.z * w.z);
    mat3 chain = 8.0 * (mat3(1.0) + 5.0 * ww);
    vec3 dn = vec3(nd.y, nd.z, nd.w);
    r.g += 0.15 * (chain * dn);

    float a = clamp(0.5 + 0.5 * noised(q * 4.0, seed ^ 0xA5A5u).x, 0.0, 1.0);
    return FieldSample(r.h * u_p_amplitude, r.g * u_p_amplitude, a);
}

FieldSample ice_field(vec3 q, uint seed, int octaves) {
    Acc r = fbm(q, octaves, u_p_gain, 0.0, seed);
    float c = noised(q * 2.0, seed ^ 0x3C3Cu).x;
    // R4: a crack_width <= 0 would make smoothstep's edges coincide (0/0).
    float a = 1.0 - smoothstep_twin(0.0, max(u_p_crack_width, 1e-6), abs(c));
    return FieldSample(r.h * u_p_amplitude, r.g * u_p_amplitude, a);
}

FieldSample gas_field(vec3 q, uint seed, int octaves) {
    vec3 qs = vec3(q.x, q.y, q.z * u_p_stretch);
    vec3 w = vec3(
        noised(qs * 0.5 + vec3(11.0), seed).x,
        noised(qs * 0.5 + vec3(23.0), seed).x,
        noised(qs * 0.5 + vec3(37.0), seed).x);
    vec3 qw = qs + u_p_warp * w;

    Acc r = fbm(qw, octaves, u_p_gain, 0.0, seed);
    // The gradient ignores the warp Jacobian but keeps the latitude stretch.
    vec3 g = vec3(r.g.x, r.g.y, r.g.z * u_p_stretch);

    Acc r2 = fbm(qw, octaves, u_p_gain, 0.0, seed + 1u);
    float a = clamp(0.5 + 0.5 * r2.h, 0.0, 1.0);

    return FieldSample(r.h * u_p_amplitude, g * u_p_amplitude, a);
}

FieldSample ocean_field(vec3 q, uint seed, int octaves) {
    float a = clamp(0.5 + 0.5 * noised(q * 4.0, seed ^ 0xA5A5u).x, 0.0, 1.0);
    return FieldSample(0.0, vec3(0.0), a);
}

FieldSample field(int t, vec3 p_local_gu, uint seed, float scale, int octaves) {
    float wavelength0 = u_p_base_wavelength_gu * scale;
    vec3 q = p_local_gu / wavelength0;
    // R4: clamp needs lo <= hi, so a max_octaves < 1 dial floors at 1.
    int n = clamp(octaves, 1, max(u_p_max_octaves, 1));

    if (t == 1) return rocky_field(q, seed, n);
    if (t == 2) return desert_field(q, seed, n);
    if (t == 3) return ice_field(q, seed, n);
    if (t == 4) return gas_field(q, seed, n);
    if (t == 5) return ocean_field(q, seed, n);
    return FieldSample(0.0, vec3(0.0), 0.0);
}

void main() {
    vec2 absi = u_abs + (gl_FragCoord.xy - 0.5 - u_tor);
    vec2 pl = (absi + 0.5) * u_ts;
    // from_plane: never zero-length (its A component is u_R > 0).
    vec3 p = normalize(u_A * u_R + u_E * pl.x + u_N * pl.y) * u_R;
    FieldSample s = field(u_type, p, u_seed, u_scale, u_oct);
    o = vec4(s.h, dot(s.grad, u_E), dot(s.grad, u_N), s.a);
}
