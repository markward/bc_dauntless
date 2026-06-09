#version 330 core
layout(location = 0) in vec2 a_corner;   // unit quad corner in [-0.5, 0.5]
uniform mat4  u_view_proj;
uniform vec3  u_center_world;
uniform vec3  u_camera_right;
uniform vec3  u_camera_up;
uniform float u_size_world;
uniform vec2  u_uv_flip;                  // (+1/-1) per axis to mirror art
out vec2 v_uv;
void main() {
    vec3 offset = (u_camera_right * a_corner.x + u_camera_up * a_corner.y) * u_size_world;
    // Negate the vertical component: the billboard places +a_corner.y at
    // screen-up, but the decoded texture is top-left origin (row 0 = top), so
    // screen-up must map to v=0. (NIF model UVs are already top-down, which is
    // why opaque/backdrop need no flip.) u_uv_flip then mirrors per corner.
    v_uv = vec2(0.5) + vec2(a_corner.x, -a_corner.y) * u_uv_flip;
    gl_Position = u_view_proj * vec4(u_center_world + offset, 1.0);
}
