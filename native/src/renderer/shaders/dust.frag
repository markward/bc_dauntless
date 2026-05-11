#version 330 core

in vec2  v_uv;
in float v_brightness;
in vec3  v_local;

uniform sampler2D u_dust_tex;
uniform float     u_radius;

out vec4 out_color;

void main() {
    float r = length(v_local);
    if (r > u_radius) discard;
    vec4 tex = texture(u_dust_tex, v_uv);
    float fade = 1.0 - smoothstep(u_radius * 0.85, u_radius, r);
    out_color = vec4(tex.rgb * v_brightness, tex.a * fade);
}
