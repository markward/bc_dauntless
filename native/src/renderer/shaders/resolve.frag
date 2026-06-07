#version 330 core
in vec2 v_uv;
out vec4 frag_color;
uniform sampler2D u_hdr;
uniform sampler2D u_bloom;
uniform float u_bloom_strength;
uniform int u_hdr_enabled;

// ACES filmic tonemap (Krzysztof Narkowicz fit). Maps HDR radiance to
// [0,1] with a filmic shoulder so highlights >1.0 roll off to white
// instead of hard-clipping.
vec3 aces(vec3 x) {
    const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

// HDR color grade (eye-tunable, like the Fresnel rim consts). Exposure
// multiplies the HDR radiance before tonemap; saturation adjusts the
// tonemapped result. Defaults are near-neutral; tune by rebuilding.
const float EXPOSURE   = 1.0;   // 1.0 = neutral
const float SATURATION = 1.05;  // 1.0 = neutral; >1 punchier

void main() {
    vec3 c = texture(u_hdr, v_uv).rgb;
    if (u_hdr_enabled != 0) {
        c += u_bloom_strength * texture(u_bloom, v_uv).rgb;   // bloom (pre-tonemap)
        c *= EXPOSURE;                                        // exposure (pre-tonemap)
        c = aces(c);                                          // filmic tonemap
        float l = dot(c, vec3(0.2126, 0.7152, 0.0722));       // luma
        c = mix(vec3(l), c, SATURATION);                      // saturation (post-tonemap)
        c = clamp(c, 0.0, 1.0);                               // SATURATION can push slightly OOR
    } else {
        c = clamp(c, 0.0, 1.0);   // neutral passthrough (stock look)
    }
    frag_color = vec4(c, 1.0);
}
