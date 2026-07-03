#version 330 core
in vec2 v_uv;
out vec4 frag_color;
uniform sampler2D u_hdr;
uniform sampler2D u_bloom;
uniform float u_bloom_strength;
uniform int u_hdr_enabled;
uniform float u_warp_flash;   // 0 = identity (no flash)
uniform sampler2D u_lens_flare;       // image-based lens flare (half-res)
uniform float u_lens_flare_strength;  // 0 = off (no lens-flare composite)

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

// Subtle procedural lens-dirt mask in screen UV: a few soft smudges + fine
// grain. Modulates the lens-flare composite so bright flares reveal grime on
// the "lens", 0..1. Cheap, asset-free; a real LensDirt.tga could replace it.
float hash21(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}
float lens_dirt(vec2 uv) {
    float d = 0.0;
    d += 0.60 * smoothstep(0.34, 0.0, length((uv - vec2(0.30, 0.62)) * vec2(1.0, 0.7)));
    d += 0.50 * smoothstep(0.24, 0.0, length((uv - vec2(0.71, 0.36)) * vec2(0.8, 1.0)));
    d += 0.40 * smoothstep(0.17, 0.0, length( uv - vec2(0.55, 0.71)));
    d += 0.15 * hash21(floor(uv * 220.0));     // fine grain
    return clamp(d, 0.0, 1.0);
}

void main() {
    vec3 c = texture(u_hdr, v_uv).rgb;
    if (u_hdr_enabled != 0) {
        c *= EXPOSURE;                                           // exposure
        c = vec3(shoulder(c.r), shoulder(c.g), shoulder(c.b));   // soft highlight roll
        c += u_bloom_strength * texture(u_bloom, v_uv).rgb;      // additive bloom glow
        if (u_lens_flare_strength > 0.0) {                       // image-based lens flare
            vec3 lf = texture(u_lens_flare, v_uv).rgb;
            // Subtle lens-dirt reveal (0.3 blend, locked in after live tuning).
            lf *= mix(1.0, 0.7 + 0.6 * lens_dirt(v_uv), 0.3);
            c += u_lens_flare_strength * lf;
        }
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
