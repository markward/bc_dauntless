#version 410 core
// Rock-field puffs (rock_puffs.h): a camera-facing quad of the puff's
// world radius; alpha = opacity * weight * distance fade-in * near fade-out.
//
// Fill cut (2026-10-04; the picture moves by at most 1/255, pinned by
// RockPuffGLTest): kMinAlpha is 1/255 / 8, not / 2 -- inside a field the
// image is MANY faint puffs, whose dropped rims add up (1/512 moved the
// centre view over black by 1.1/255, 1/2048 by 0.26/255). rock_puff.frag
// discards every fragment whose alpha bound
// kAlphaMax * v_alpha * exp(-3 rr) is under kMinAlpha, so (1) a puff whose
// peak bound kAlphaMax * alpha is under it is collapsed here, and (2) the
// quad shrinks to the radius where that bound reaches kMinAlpha -- every
// fragment it drops would have been discarded. v_corner scales with it, so a
// kept fragment shades exactly as before.
layout(location = 0) in vec2 a_corner;        // (+-1, +-1)
layout(location = 7) in vec4 a_pos_r;         // xyz relative to the field origin, w radius (GU)
layout(location = 8) in vec4 a_albedo_w;      // rgb albedo, a density weight
uniform mat4 u_view;
uniform mat4 u_proj;
uniform vec3 u_offset;                        // render-space position of the field origin
uniform vec3 u_eye;                           // render-space camera position
uniform float u_opacity, u_start_gu, u_ramp_gu, u_near_fade;
out vec2 v_corner;
flat out vec3 v_centre;
flat out vec3 v_albedo;
flat out float v_alpha;
flat out vec3 v_seed;
const float kMinAlpha = 1.0 / 2048.0;  // rock_puff.frag's discard threshold
const float kAlphaMax = 1.45;          // rock_puff.frag: body <= exp(-3 rr), 0.55 + 0.9 n <= 1.45
void main() {
    vec3 c = a_pos_r.xyz + u_offset;
    float r = a_pos_r.w;
    float d = length(c - u_eye);
    float a_far = u_ramp_gu > 0.0 ? clamp((d - u_start_gu) / u_ramp_gu, 0.0, 1.0)
                                  : (d >= u_start_gu ? 1.0 : 0.0);
    float a_near = clamp((d - r) / max(u_near_fade * r - r, 1e-3), 0.0, 1.0);
    float alpha = u_opacity * a_albedo_w.a * a_far * a_near;
    // Camera-facing in view space.
    vec4 vc = u_view * vec4(c, 1.0);
    if (!(kAlphaMax * alpha >= kMinAlpha) || vc.z > -1.0) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        v_corner = vec2(0.0); v_centre = c; v_albedo = vec3(0.0); v_alpha = 0.0; v_seed = vec3(0.0);
        return;
    }
    // The bound reaches kMinAlpha at rr_max = ln(kAlphaMax * alpha / kMinAlpha) / 3
    // (>= 0 here); past rr 1 the fragment shader discards anyway. 1.001: the
    // boundary fragments stay rasterised.
    float rr_max = log(kAlphaMax * alpha / kMinAlpha) / 3.0;
    float s = rr_max < 1.0 ? min(1.0, sqrt(rr_max) * 1.001) : 1.0;
    vc.xy += a_corner * (r * s);
    gl_Position = u_proj * vc;
    v_corner = a_corner * s;
    v_centre = c;
    v_albedo = a_albedo_w.rgb;
    v_alpha = alpha;
    v_seed = fract(sin(a_pos_r.xyz * vec3(12.9898, 78.233, 37.719)) * 43758.5453) * 64.0;
}
