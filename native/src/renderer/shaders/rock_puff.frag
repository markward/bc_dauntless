#version 410 core
// Rock-field puffs: a soft, noise-broken blob, lit like the speck
// band (Lambert sphere phase toward the sun, per puff in rock_puff.vert).
// PREMULTIPLIED, blended GL_ONE, GL_ONE_MINUS_SRC_ALPHA, depth-tested, no
// depth writes.
//
// Hash table (2026-10-18, perf-register.md P-1): the value noise's lattice
// hash is read from u_puff_hash, which FarPass bakes on the GPU with the
// sine hash this shader used to evaluate 16 times per fragment (the
// expression is in rock_puff_hash.frag).
// Lattice point i is texel i + kHashOffset; the table covers every point the
// noise can read (RockPuffHashTable tests; rockfield::kPuffHash* in C++).
in vec2 v_corner;
flat in vec3 v_rgb;
flat in float v_alpha;
flat in vec3 v_seed;
uniform sampler2D u_puff_hash;
out vec4 frag_color;

const int kHashOffset = 20;
const int kHashSize = 576;

// Fill cut (2026-10-04, see rock_puff.vert): a fragment whose alpha cannot
// reach kMinAlpha is discarded BEFORE the noise. alpha = v_alpha * body *
// (0.55 + 0.9 n) with body <= exp(-3 rr) and n <= 1, so kAlphaMax * v_alpha *
// exp(-3 rr) bounds it. Keep both constants identical with rock_puff.vert.
const float kMinAlpha = 1.0 / 2048.0;
const float kAlphaMax = 1.45;

// p is a lattice point (whole numbers), so the conversion is exact.
float hash2(vec2 p) {
    return texelFetch(u_puff_hash,
                      clamp(ivec2(p) + kHashOffset, ivec2(0), ivec2(kHashSize - 1)), 0).r;
}
float vnoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash2(i), hash2(i + vec2(1, 0)), u.x),
               mix(hash2(i + vec2(0, 1)), hash2(i + vec2(1, 1)), u.x), u.y);
}
float fbm2(vec2 p) {
    float s = 0.0, a = 0.5;
    for (int o = 0; o < 4; ++o) { s += a * vnoise(p); p *= 2.03; a *= 0.5; }
    return s / 0.9375;
}

void main() {
    float rr = dot(v_corner, v_corner);
    if (rr >= 1.0) discard;
    if (kAlphaMax * v_alpha * exp(-3.0 * rr) < kMinAlpha) discard;
    // Soft core with a noise-eaten edge: no visible card or circle.
    float n = fbm2(v_corner * 2.2 + v_seed.xy);
    float body = exp(-3.0 * rr) * smoothstep(1.0, 0.55, rr + 0.35 * (n - 0.5));
    float a = v_alpha * body * (0.55 + 0.9 * n);
    if (a <= 0.0) discard;
    frag_color = vec4(v_rgb * a, a);
}
