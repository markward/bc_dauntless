#version 330 core

layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;
layout(location = 2) in vec2 a_uv;
layout(location = 6) in vec2 a_uv1;

uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_proj;

out vec2 v_uv;
out vec2 v_uv1;

void main() {
    v_uv = a_uv;
    v_uv1 = a_uv1;
    gl_Position = u_proj * u_view * u_model * vec4(a_position, 1.0);
}
