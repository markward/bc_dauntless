#version 410 core
// Planet atmosphere shell (atmosphere_pass.cc): a unit geosphere scaled to
// the shell top. The fragment shader does all the work.
layout(location = 0) in vec3 a_position;   // unit geosphere
uniform mat4 u_view;
uniform mat4 u_proj;
uniform vec3 u_center;     // render space
uniform float u_r_top;
out vec3 v_world;
void main() {
    v_world = u_center + a_position * u_r_top;
    gl_Position = u_proj * u_view * vec4(v_world, 1.0);
}
