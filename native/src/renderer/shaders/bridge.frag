#version 330 core

in vec2 v_uv;
in vec2 v_uv1;

uniform sampler2D u_base_color;
uniform sampler2D u_dark_map;  // lightmap on UV set 1; white where absent
uniform vec3 u_ambient;
uniform float u_alpha_test_threshold;

out vec4 FragColor;

void main() {
    vec4 base = texture(u_base_color, v_uv);
    if (base.a < u_alpha_test_threshold) discard;
    vec3 lm = texture(u_dark_map, v_uv1).rgb;
    FragColor = vec4(base.rgb * lm * u_ambient, 1.0);
}
