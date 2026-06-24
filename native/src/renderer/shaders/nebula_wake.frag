#version 330 core
in vec2 v_uv;             // [-1,1] quad space
out vec4 frag;

uniform vec3  u_color;     // glow tint
uniform float u_strength;  // this point's age-faded strength (0..1)
uniform float u_glow;      // overall intensity dial
uniform float u_softness;  // radial falloff exponent (higher = softer/tighter)
uniform float u_time;      // for the slow churn

float hash(vec2 p){ return fract(sin(dot(p, vec2(41.3, 289.1))) * 43758.5453); }
float vnoise(vec2 p){
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash(i), b = hash(i + vec2(1,0));
    float c = hash(i + vec2(0,1)), d = hash(i + vec2(1,1));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

void main() {
    float r = length(v_uv);
    if (r >= 1.0 || u_strength <= 0.0) { frag = vec4(0.0); return; }
    // Soft radial falloff, modulated by a slow churn so the trail isn't a flat disc.
    float churn   = 0.7 + 0.6 * vnoise(v_uv * 2.5 + vec2(u_time * 0.3, 0.0));
    float falloff = pow(1.0 - r, u_softness);
    float e = falloff * churn * u_strength * u_glow;
    frag = vec4(u_color * e, 1.0);   // premultiplied additive (blend GL_ONE, GL_ONE)
}
