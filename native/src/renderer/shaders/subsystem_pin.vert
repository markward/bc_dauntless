#version 330 core
layout(location = 0) in vec2 a_corner;   // unit quad corner in [-0.5, 0.5]
uniform mat4 u_view_proj;
uniform vec3 u_center_world;
uniform vec3 u_camera_right;   // camera basis for billboarding
uniform vec3 u_camera_up;
uniform float u_size_world;    // quad world size
out vec2 v_uv;
void main() {
    vec3 offset = (u_camera_right * a_corner.x + u_camera_up * a_corner.y) * u_size_world;
    v_uv = a_corner + vec2(0.5);
    gl_Position = u_view_proj * vec4(u_center_world + offset, 1.0);
}
