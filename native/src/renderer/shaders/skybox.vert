#version 330 core

layout(location=0) in vec3 a_pos;
layout(location=1) in vec3 a_normal;   // unused; VAO layout compatibility
layout(location=2) in vec2 a_uv;       // unused

uniform mat4 u_view_no_translation;
uniform mat4 u_proj;

out vec3 v_dir;

void main() {
    // The sphere is drawn world-axis-aligned and camera-anchored, so each
    // vertex position IS the world-space view direction for that fragment.
    v_dir = a_pos;
    vec4 clip = u_proj * u_view_no_translation * vec4(a_pos, 1.0);
    clip.z = clip.w;            // skybox-depth idiom: force to the far plane
    gl_Position = clip;
}
