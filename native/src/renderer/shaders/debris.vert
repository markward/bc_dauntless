#version 330 core
layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;
layout(location = 2) in vec2 a_uv;

uniform mat4  u_model;
uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_chunk_pos;   // chunk center in body frame
uniform mat3  u_chunk_rot;   // tumble rotation
uniform float u_cell_size;   // voxel cell size (body units)

out vec3 v_normal_ws;
out vec2 v_uv;

void main() {
    vec3 body_pos = u_chunk_rot * (a_position * u_cell_size) + u_chunk_pos;
    gl_Position   = u_proj * u_view * u_model * vec4(body_pos, 1.0);
    v_normal_ws   = mat3(u_model) * (u_chunk_rot * a_normal);
    v_uv          = a_uv;
}
