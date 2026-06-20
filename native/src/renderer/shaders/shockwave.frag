#version 330 core
in vec2 v_uv;                 // radial coord; length 0 at center, ~1 at edge
uniform float u_t;            // age / lifetime, 0..1
out vec4 frag;

const float kBand      = 0.10; // ring band half-width (normalized radius)
const float kFlashFrac = 0.20; // core flash lives while t < kFlashFrac
const float kFlashSize = 0.18; // core flash radius (normalized)

void main() {
    float r = length(v_uv);
    float t = clamp(u_t, 0.0, 1.0);

    // Ring expands with ease-out (fast then decelerating): 0 -> 1.
    float ring_r = 1.0 - (1.0 - t) * (1.0 - t);
    // Thin bright band centered on the current ring radius, soft edges.
    float band = 1.0 - smoothstep(0.0, kBand, abs(r - ring_r));
    float ring_alpha = band * (1.0 - t);          // fade as it ages

    // Core flash: bright center, only early, gone by kFlashFrac.
    float flash_life = 1.0 - smoothstep(0.0, kFlashFrac, t);
    float flash = (1.0 - smoothstep(0.0, kFlashSize, r)) * flash_life;

    // White-hot core/flash; ring cools white-blue -> blue as it grows.
    vec3 ring_col  = mix(vec3(0.70, 0.90, 1.0), vec3(0.30, 0.60, 1.0), t);
    vec3 flash_col = vec3(1.0, 1.0, 1.0);

    vec3 col = ring_col * ring_alpha + flash_col * flash;
    float a  = clamp(ring_alpha + flash, 0.0, 1.0);
    if (a <= 0.002) discard;
    frag = vec4(col, a);
}
