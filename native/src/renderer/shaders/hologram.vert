#version 330 core
layout(location = 0) in vec3 a_pos;
layout(location = 1) in vec3 a_normal;
uniform mat4 u_model;
uniform mat4 u_view_proj;
out vec3 v_world_pos;
out vec3 v_world_normal;
void main() {
    vec4 wp = u_model * vec4(a_pos, 1.0);
    v_world_pos = wp.xyz;
    v_world_normal = mat3(u_model) * a_normal;
    gl_Position = u_view_proj * wp;
}
