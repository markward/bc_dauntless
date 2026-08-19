#version 330 core
layout(location = 0) in vec2 a_corner;   // unit-quad corner: (-1,-1)..(+1,+1)

uniform mat4  u_view_proj;
uniform vec3  u_camera_right;
uniform vec3  u_camera_up;
uniform vec3  u_world_position;
uniform float u_size;
uniform vec3  u_streak_axis;    // world-space velocity direction (streak long axis)
uniform float u_streak_length;  // 0 => camera-facing billboard (default)
uniform float u_roll;           // radians, in-billboard-plane; 0 => unrotated

out vec2 v_uv;

void main() {
    vec3 right;
    vec3 up;
    if (u_streak_length > 0.0 && length(u_streak_axis) > 1e-6) {
        vec3 axis = normalize(u_streak_axis);
        vec3 view = normalize(cross(u_camera_right, u_camera_up));  // camera forward
        vec3 perp = cross(axis, view);
        float pl = length(perp);
        right = (pl > 1e-6) ? (perp / pl) * u_size : u_camera_right * u_size;
        up    = axis * u_streak_length;
    } else {
        // Camera-facing: spin the quad in its own plane so N copies of one
        // sprite don't read as a repeating stamp. Deliberately NOT applied to
        // the streak branch above, where `up` IS the velocity axis and rolling
        // it would slide the sprite off its own trajectory.
        // Mirrors renderer::billboard_roll_basis in particle_math.h.
        float c = cos(u_roll);
        float s = sin(u_roll);
        right = ( u_camera_right * c + u_camera_up * s) * u_size;
        up    = (-u_camera_right * s + u_camera_up * c) * u_size;
    }
    vec3 world_pos = u_world_position + right * a_corner.x + up * a_corner.y;
    gl_Position = u_view_proj * vec4(world_pos, 1.0);
    v_uv = a_corner * 0.5 + 0.5;
}
