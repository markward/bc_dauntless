#version 410 core

layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;
layout(location = 2) in vec2 a_uv;

uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_proj;

out vec2 v_uv;
// World position + world normal for the ceiling downlight (bridge.frag).
// Interior sets load with generated unit normals; bridge.frag still derives a
// face normal from v_world for any mesh that reaches it with none.
out vec3 v_world;
out vec3 v_normal;

void main() {
    v_uv = a_uv;
    vec4 world = u_model * vec4(a_position, 1.0);
    v_world = world.xyz;
    v_normal = mat3(u_model) * a_normal;
    gl_Position = u_proj * u_view * world;
}
