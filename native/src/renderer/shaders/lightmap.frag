#version 330 core

in vec2 v_uv;

uniform sampler2D u_lightmap;

out vec4 FragColor;

void main() {
    FragColor = texture(u_lightmap, v_uv);
}
