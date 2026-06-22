#version 330 core
in vec2 v_uv;
out vec4 frag_color;
uniform sampler2D u_hdr;
uniform sampler2D u_bloom;
uniform float u_bloom_strength;
uniform int u_hdr_enabled;
uniform float u_warp_flash;   // 0 = identity (no flash)

// HDR color grade — the "Muted Film" profile chosen interactively. Named
// consts (eye-tunable by rebuilding, like the Fresnel rim consts): a slight
// exposure pull-down, desaturation, a low soft-shoulder knee, and a faint
// warm-cool tint. Identity-below-knee keeps BC's emissive content (nacelle
// bussards, window glow, running lights) at near-stock brightness.
const float EXPOSURE   = 0.95;
const float SATURATION = 0.90;
const float KNEE       = 0.82;                 // identity below; soft roll above
const vec3  TINT       = vec3(1.02, 1.00, 0.99);

// Highlight-only soft shoulder. Identity below KNEE; values above roll
// smoothly toward white instead of hard-clipping. Chosen over a full filmic
// tonemap (ACES), which compressed the whole range and dimmed the lights.
float shoulder(float x) {
    if (x <= KNEE) return x;
    float range = 1.0 - KNEE;                  // headroom to white
    return KNEE + range * (1.0 - exp(-(x - KNEE) / range));
}

void main() {
    vec3 c = texture(u_hdr, v_uv).rgb;
    if (u_hdr_enabled != 0) {
        c *= EXPOSURE;                                           // exposure
        c = vec3(shoulder(c.r), shoulder(c.g), shoulder(c.b));   // soft highlight roll
        c += u_bloom_strength * texture(u_bloom, v_uv).rgb;      // additive bloom glow
        float l = dot(c, vec3(0.2126, 0.7152, 0.0722));          // luma
        c = mix(vec3(l), c, SATURATION);                         // saturation
        c *= TINT;                                               // white balance
        c = clamp(c, 0.0, 1.0);                                  // bloom/grade can exceed 1
    } else {
        c = clamp(c, 0.0, 1.0);   // neutral passthrough (stock look)
    }
    c = mix(c, vec3(1.0), clamp(u_warp_flash, 0.0, 1.0));
    frag_color = vec4(c, 1.0);
}
