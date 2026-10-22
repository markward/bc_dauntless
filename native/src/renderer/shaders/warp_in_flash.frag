#version 410 core
// Warp-in flash shape (warp-in spec 6.3). GLSL twin of
// renderer/warp_in_flash_shape.{h,cc}: the constants and the three terms MUST
// match the CPU twin (warp_in_flash_shape_test pins the constants by name).
// Distances are in units of the flash radius; t = age / lifetime.
in vec2 v_local;               // billboard: (x, y); ribbon: (across, along)

uniform int   u_mode;          // 0 = billboard (core + ring), 1 = ribbon (streak)
uniform float u_t;
uniform float u_core_radii;
uniform float u_streak_radii;
uniform float u_ring_radii;
uniform float u_intensity;
uniform vec3  u_tint;

out vec4 frag;

// MUST match warp_in_flash_shape.h.
const float kCoreRise = 0.08;
const float kCoreFalloff = 3.0;
const float kRingRise = 0.05;
const float kRingBand = 0.12;
const float kStreakEnd = 0.9;
const float kStreakThickness = 0.08;
const float kPi = 3.14159265358979;

// MUST match renderer::warp_in_core.
float core_term(float r, float t) {
    if (t >= 1.0 || u_core_radii <= 0.0) return 0.0;
    float a = smoothstep(0.0, kCoreRise, t) * (1.0 - smoothstep(kCoreRise, 1.0, t));
    float w = u_core_radii * (0.4 + 0.6 * a);
    float q = r / w;
    return a * exp(-kCoreFalloff * q * q);
}

// MUST match renderer::warp_in_ring.
float ring_term(float r, float t) {
    if (t >= 1.0 || u_ring_radii <= 0.0) return 0.0;
    float fade = (1.0 - t) * (1.0 - t) * smoothstep(0.0, kRingRise, t);
    float d = (r - u_ring_radii * t) / (kRingBand * u_ring_radii);
    return fade * exp(-d * d);
}

// MUST match renderer::warp_in_streak.
float streak_term(float along, float across, float t) {
    if (t >= kStreakEnd || u_core_radii <= 0.0) return 0.0;
    float L = u_streak_radii * sin(kPi * clamp(t / kStreakEnd, 0.0, 1.0));
    if (!(L > 0.0) || along < 0.0 || along > L) return 0.0;
    float y = across / (kStreakThickness * u_core_radii);
    return sqrt(1.0 - along / L) * exp(-y * y) * (1.0 - t);
}

void main() {
    float t = max(u_t, 0.0);
    float value;
    if (u_mode == 0) {
        float r = length(v_local);
        value = core_term(r, t) + ring_term(r, t);
    } else {
        value = streak_term(v_local.y, v_local.x, t);
    }
    if (value <= 1e-4) discard;
    // Additive (GL_ONE, GL_ONE); alpha 0 leaves the target's alpha untouched.
    frag = vec4(u_tint * u_intensity * value, 0.0);
}
