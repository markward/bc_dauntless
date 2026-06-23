#version 330 core
in  vec2 v_uv;
out vec4 frag;

uniform sampler2D u_external;   // nebulaexternal.tga
uniform vec3  u_rgb;
uniform float u_rim_fade;       // [0,1] 0 = at rim (suppressed), 1 = far
uniform float u_brightness;     // tunable (default 1.0)

void main() {
    vec2 d = v_uv * 2.0 - 1.0;
    float r = length(d);
    float edge = 1.0 - smoothstep(0.6, 1.0, r);     // soft circular falloff
    vec3 tex = texture(u_external, v_uv).rgb;
    float a = edge * u_rim_fade * u_brightness;
    frag = vec4(tex * u_rgb * a, a);                // additive (see blend setup)
}
