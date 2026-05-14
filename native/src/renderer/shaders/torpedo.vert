#version 330 core
layout(location = 0) in vec2 a_corner;   // unit-quad corner: (-1,-1)..(+1,+1)

uniform mat4  u_view_proj;
uniform vec3  u_camera_right;             // camera basis vectors in world space
uniform vec3  u_camera_up;
uniform vec3  u_world_position;
uniform float u_size;                     // quad half-size in world units
uniform float u_rotation;                 // billboard-plane spin (radians)

out vec2 v_uv;

void main() {
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    vec2 rotated = vec2(a_corner.x * c - a_corner.y * s,
                        a_corner.x * s + a_corner.y * c);
    vec3 world_pos = u_world_position
        + u_camera_right * (rotated.x * u_size)
        + u_camera_up    * (rotated.y * u_size);
    gl_Position = u_view_proj * vec4(world_pos, 1.0);
    v_uv = a_corner * 0.5 + 0.5;
}
