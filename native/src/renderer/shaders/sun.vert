#version 410 core

layout(location=0) in vec3 a_pos;
layout(location=1) in vec3 a_normal;   // unused; VAO layout compatibility
layout(location=2) in vec2 a_uv;

uniform mat4 u_proj;
uniform mat4 u_view;
uniform mat4 u_model;

out vec2 v_uv;

void main() {
    gl_Position = u_proj * u_view * u_model * vec4(a_pos, 1.0);
    v_uv = a_uv;
}
