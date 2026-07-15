#version 330 core
layout(location = 0) in vec2 a_corner;   // unit-quad corner: (-1,-1)..(+1,+1)

uniform mat4  u_view_proj;
uniform vec3  u_axis_x;                   // quad's world-space unit half-axis
uniform vec3  u_axis_y;                   // (composed on the CPU per layer:
                                           // spinning root frame, per-flare
                                           // random 3D rotation, ...)
uniform vec3  u_world_position;
uniform float u_size;                     // quad half-size in world units

out vec2 v_uv;

void main() {
    vec3 world_pos = u_world_position
        + (a_corner.x * u_axis_x + a_corner.y * u_axis_y) * u_size;
    gl_Position = u_view_proj * vec4(world_pos, 1.0);
    v_uv = a_corner * 0.5 + 0.5;
}
