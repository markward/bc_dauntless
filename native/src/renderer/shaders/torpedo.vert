#version 410 core
layout(location = 0) in vec2 a_corner;        // unit-quad corner: (-1,-1)..(+1,+1)

// Per-instance: one quad (renderer::TorpedoSprite, torpedo_sprites.h).
layout(location = 1) in vec4 i_centre_size;   // xyz world centre, w half-size (world units)
layout(location = 2) in vec4 i_axis_x_alpha;  // xyz quad x half-axis, w alpha multiplier
layout(location = 3) in vec4 i_axis_y;        // xyz quad y half-axis
layout(location = 4) in vec4 i_tint;
// The axes are composed on the CPU per layer: spinning root frame, per-flare
// random 3D rotation, ...

uniform mat4  u_view_proj;

out vec2 v_uv;
flat out vec4  v_tint;
flat out float v_alpha;

void main() {
    vec3 world_pos = i_centre_size.xyz
        + (a_corner.x * i_axis_x_alpha.xyz + a_corner.y * i_axis_y.xyz) * i_centre_size.w;
    gl_Position = u_view_proj * vec4(world_pos, 1.0);
    v_uv = a_corner * 0.5 + 0.5;
    v_tint = i_tint;
    v_alpha = i_axis_x_alpha.w;
}
