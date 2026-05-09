#version 330 core

layout(location = 0) in vec3 a_position;
layout(location = 2) in vec2 a_uv;

uniform mat4 u_view_no_translation;
uniform mat4 u_proj;

out vec2 v_uv;

void main() {
    v_uv = a_uv;
    // Force depth = 1.0 (max) so skybox always passes LEQUAL depth test
    // against any geometry that writes a smaller value.
    vec4 clip = u_proj * u_view_no_translation * vec4(a_position, 1.0);
    gl_Position = clip.xyww;
}
