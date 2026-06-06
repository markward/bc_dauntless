#version 330 core

in vec2  v_uv;
in float v_brightness;
in vec3  v_local;

uniform sampler2D u_dust_tex;
uniform float     u_radius;
uniform float u_sun_tint;   // [0,1] orange-mix factor near suns

out vec4 out_color;

void main() {
    float r = length(v_local);
    if (r > u_radius) discard;
    vec4 tex = texture(u_dust_tex, v_uv);
    float fade = 1.0 - smoothstep(u_radius * 0.85, u_radius, r);
    // Warm the dust toward orange (#FF8030) as the camera nears a sun.
    vec3 tint = mix(vec3(1.0), vec3(1.0, 0.502, 0.188), u_sun_tint);
    out_color = vec4(tex.rgb * v_brightness * tint, tex.a * fade);
}
