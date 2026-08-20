#version 330 core
// Star map primitives. Instanced: a_corner is the unit-quad corner for discs
// and points; lines use a_corner.x as the segment end selector.
layout(location = 0) in vec2 a_corner;

uniform mat4  u_view_proj;
uniform vec3  u_camera_right;
uniform vec3  u_camera_up;
uniform vec3  u_center;     // world position (discs, points, brackets)
uniform vec3  u_line_a;
uniform vec3  u_line_b;
uniform float u_world_size; // disc radius in world units (0 for screen-space)
uniform vec2  u_pixel_size; // half-size in NDC for screen-space primitives
uniform int   u_kind;       // 0 disc, 1 line, 2 point/bracket

out vec2 v_uv;

void main() {
    v_uv = a_corner;
    if (u_kind == 1) {
        vec3 p = (a_corner.x < 0.5) ? u_line_a : u_line_b;
        gl_Position = u_view_proj * vec4(p, 1.0);
        return;
    }
    if (u_kind == 0) {
        vec2 o = (a_corner * 2.0 - 1.0) * u_world_size;
        vec3 world = u_center + u_camera_right * o.x + u_camera_up * o.y;
        gl_Position = u_view_proj * vec4(world, 1.0);
        return;
    }
    // Screen-space: project the centre, then offset in NDC so the marker
    // keeps a constant pixel size at any zoom.
    vec4 clip = u_view_proj * vec4(u_center, 1.0);
    clip.xy += (a_corner * 2.0 - 1.0) * u_pixel_size * clip.w;
    gl_Position = clip;
}
