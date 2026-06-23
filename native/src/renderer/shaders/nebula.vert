#version 330 core
layout(location = 0) in vec3 a_pos;   // unit sphere position

uniform mat4 u_view;
uniform mat4 u_proj;
uniform vec3 u_center;   // sphere centre (GU)
uniform float u_radius;  // sphere radius (GU)

out vec3 v_world;        // world-space position of this sphere fragment
void main() {
    v_world = u_center + a_pos * u_radius;
    gl_Position = u_proj * u_view * vec4(v_world, 1.0);
}
