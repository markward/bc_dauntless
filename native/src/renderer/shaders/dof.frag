#version 410 core
//
// Depth of field: a thin-lens circle of confusion driving a 24-tap
// golden-angle gather, run in HDR before the tonemap so defocused highlights
// stay bright and become real bokeh rather than grey smudges.
//
// The CoC block below MIRRORS renderer/dof.h. The two must agree; the
// starfield threshold is pinned across both by dof_pass_test.cc. If you
// change the curve here, change it there in the same commit.
//
// NO look-affecting constant lives in this file. Everything an artist would
// want to touch arrives as a uniform from engine/cameras/dof.py, so tuning
// needs no rebuild. kTapCount is kernel structure, not look.

in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_src;             // HDR scene colour
uniform sampler2D u_depth;           // scene depth, same dimensions
uniform float u_near;
uniform float u_far;
uniform float u_focus_gu;
uniform float u_blend;               // 0..1 engage ramp
uniform float u_near_strength;
uniform float u_far_strength;
uniform float u_far_ceiling;
uniform float u_max_radius_px;       // already frac * framebuffer height
uniform vec2  u_texel;               // 1.0 / textureSize(u_src, 0)

const int   kTapCount   = 24;
const float kGoldenAngle = 2.39996323;   // radians

float linear_depth_gu(float d) {
    float ndc = 2.0 * d - 1.0;
    return (2.0 * u_near * u_far) / (u_far + u_near - ndc * (u_far - u_near));
}

float coc_at(vec2 uv) {
    if (u_focus_gu <= 0.0) return 0.0;
    float z = linear_depth_gu(texture(u_depth, uv).r);
    if (z <= 0.0) return 0.0;
    // Starfield: the backdrop pass never writes depth, so these pixels hold
    // the clear value. Tested on the linearized distance so the exemption
    // does not depend on the exact clear value.
    if (z >= u_far * 0.98) return 0.0;
    float dd = 1.0 - u_focus_gu / z;
    return (dd < 0.0) ? max(dd * u_near_strength, -1.0)
                      : min(dd * u_far_strength,  u_far_ceiling);
}

void main() {
    vec3  center     = texture(u_src, v_uv).rgb;
    float center_r   = abs(coc_at(v_uv)) * u_max_radius_px * u_blend;

    // Sub-pixel circle of confusion: nothing to gather. This early-out is
    // what makes an in-focus subject bit-for-bit sharp rather than merely
    // nearly sharp, and it is the fast path for most of the frame.
    if (center_r < 0.5) { frag_color = vec4(center, 1.0); return; }

    vec3  acc  = center;
    float wsum = 1.0;

    for (int i = 0; i < kTapCount; ++i) {
        // Vogel spiral: sqrt(t) radial spacing with the golden angle gives a
        // uniform distribution over the disc, so the bokeh is even rather
        // than centre-heavy.
        float t   = (float(i) + 0.5) / float(kTapCount);
        float r   = center_r * sqrt(t);
        float ang = float(i) * kGoldenAngle;
        vec2  uv  = v_uv + vec2(cos(ang), sin(ang)) * r * u_texel;

        float tap_r = abs(coc_at(uv)) * u_max_radius_px * u_blend;

        // SCATTER-AS-GATHER. A tap contributes only if ITS OWN circle of
        // confusion reaches this pixel. Without this, sharp foreground
        // objects bleed onto in-focus background and in-focus objects have
        // their edges eaten -- the two classic cheap-DOF tells. This is a
        // correctness term, NOT an optimisation: do not remove it.
        float w = clamp(tap_r - r + 1.0, 0.0, 1.0);

        acc  += texture(u_src, uv).rgb * w;
        wsum += w;
    }

    frag_color = vec4(acc / wsum, 1.0);
}
