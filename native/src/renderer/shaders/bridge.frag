#version 330 core

in vec2 v_uv;

uniform sampler2D u_base_color;
uniform vec3 u_ambient;
uniform float u_alpha_test_threshold;

out vec4 FragColor;

void main() {
    vec4 base = texture(u_base_color, v_uv);
    if (base.a < u_alpha_test_threshold) discard;
    FragColor = vec4(base.rgb * u_ambient, 1.0);
}
