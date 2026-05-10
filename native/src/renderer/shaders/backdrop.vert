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
    // Scale the unit sphere outward so its vertices live comfortably
    // inside the view frustum. Without this scale a vertex at distance 1
    // from origin sits exactly on the near plane (near=1.0); some
    // vertices land BEHIND the camera and get clipped, the surviving
    // ones produce w ≈ 0..1 and perspective-divide is unstable.
    // 1000.0 is well below the typical far plane (100000) so we have
    // plenty of margin; the actual depth is pinned to the far plane by
    // the z=w idiom below regardless.
    vec3 rotated = u_world_rotation * (a_pos * 1000.0);
    v_pos_local = rotated;
    v_uv = a_uv;
    vec4 clip = u_proj * u_view_no_translation * vec4(rotated, 1.0);
    clip.z = clip.w;
    gl_Position = clip;
}
