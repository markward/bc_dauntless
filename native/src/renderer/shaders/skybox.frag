#version 330 core

in vec2 v_uv;
uniform sampler2D u_base_color;
out vec4 frag;

void main() {
    frag = vec4(texture(u_base_color, v_uv).rgb, 1.0);
}
