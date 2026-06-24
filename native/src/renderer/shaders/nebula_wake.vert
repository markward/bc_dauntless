#version 330 core
layout(location = 0) in vec2 a_corner;   // [-1,1] quad corner

uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_center;   // trail-point world pos
uniform float u_size;     // billboard half-size (GU)

out vec2 v_uv;
void main() {
    vec3 right = vec3(u_view[0][0], u_view[1][0], u_view[2][0]);
    vec3 up    = vec3(u_view[0][1], u_view[1][1], u_view[2][1]);
    vec3 wp = u_center + (right * a_corner.x + up * a_corner.y) * u_size;
    v_uv = a_corner;
    gl_Position = u_proj * u_view * vec4(wp, 1.0);
}
