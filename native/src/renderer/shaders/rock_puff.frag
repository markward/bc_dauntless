#version 410 core
// Rock-field puffs: a soft, noise-broken blob, lit like the speck
// band (Lambert sphere phase toward the sun). PREMULTIPLIED, blended
// GL_ONE, GL_ONE_MINUS_SRC_ALPHA, depth-tested, no depth writes.
in vec2 v_corner;
flat in vec3 v_centre;
flat in vec3 v_albedo;
flat in float v_alpha;
flat in vec3 v_seed;
uniform vec3 u_camera_pos_ws;
uniform vec3 u_ambient_light;
uniform int u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[4];           // toward each light
uniform vec3 u_dir_light_color[4];
uniform float u_brightness;
out vec4 frag_color;

// Fill cut (2026-10-04, see rock_puff.vert): a fragment whose alpha cannot
// reach kMinAlpha is discarded BEFORE the noise. alpha = v_alpha * body *
// (0.55 + 0.9 n) with body <= exp(-3 rr) and n <= 1, so kAlphaMax * v_alpha *
// exp(-3 rr) bounds it. Keep both constants identical with rock_puff.vert.
const float kMinAlpha = 1.0 / 2048.0;
const float kAlphaMax = 1.45;

const float PI = 3.14159265;

float lambert_sphere_phase(float cos_alpha) {
    float c = clamp(cos_alpha, -1.0, 1.0);
    float a = acos(c);
    return (2.0 / (3.0 * PI)) * (sin(a) + (PI - a) * c);
}

float hash2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
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
    vec3 to_eye = normalize(u_camera_pos_ws - v_centre);
    vec3 light = u_ambient_light;
    for (int i = 0; i < u_dir_light_count; ++i)
        light += u_dir_light_color[i]
               * lambert_sphere_phase(dot(normalize(u_dir_light_dir_ws[i]), to_eye));
    vec3 c = v_albedo * light * u_brightness;
    frag_color = vec4(c * a, a);
}
