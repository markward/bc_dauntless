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

void main() {
    vec3 c = texture(u_hdr, v_uv).rgb;
    if (u_hdr_enabled != 0) {
        // Composite bloom pre-tonemap so it participates in the filmic rolloff.
        c += u_bloom_strength * texture(u_bloom, v_uv).rgb;
        c = aces(c);
    } else {
        c = clamp(c, 0.0, 1.0);   // neutral passthrough (stock look)
    }
    frag_color = vec4(c, 1.0);
}
