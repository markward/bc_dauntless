#version 330 core
layout(location = 0) in vec2 a_corner;   // unit quad corners in [-1, 1]

uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_center;       // world-space blast center
uniform float u_max_radius;   // ring max radius (world units)

out vec2 v_uv;                // == a_corner; radial coord in [-1, 1]

void main() {
    // World-space camera right/up are the first two columns of the view
    // matrix's rotation (view maps world->camera; its transpose's columns are
    // world axes). Same billboard basis used by subsystem_pin / dust.
    vec3 cam_right = vec3(u_view[0][0], u_view[1][0], u_view[2][0]);
    vec3 cam_up    = vec3(u_view[0][1], u_view[1][1], u_view[2][1]);
    vec3 world = u_center
               + a_corner.x * cam_right * u_max_radius
               + a_corner.y * cam_up    * u_max_radius;
    v_uv = a_corner;
    gl_Position = u_proj * u_view * vec4(world, 1.0);
}
