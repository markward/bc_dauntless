#version 330 core

layout(location=0) in vec3 a_pos;
layout(location=1) in vec3 a_normal;     // unused; binding compatibility with assets::Mesh VAO layout
layout(location=2) in vec2 a_uv;

uniform mat4 u_view_no_translation;
uniform mat4 u_proj;
uniform mat3 u_world_rotation;

out vec3 v_pos_local;
out vec2 v_uv;

void main() {
    vec3 rotated = u_world_rotation * a_pos;
    v_pos_local = rotated;
    v_uv = a_uv;
    vec4 clip = u_proj * u_view_no_translation * vec4(rotated, 1.0);
    // Skybox-depth idiom: force fragment to the far plane so any
    // subsequently-drawn opaque geometry always wins LEQUAL depth tests.
    clip.z = clip.w;
    gl_Position = clip;
}
