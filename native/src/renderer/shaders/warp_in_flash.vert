#version 410 core
// Warp-in flash (warp-in spec 6.3). Two quads per flash, one program:
//   u_mode 0 — camera-facing billboard carrying the core + ring;
//   u_mode 1 — ribbon along the flash's forward axis carrying the streak
//              (axis-ribbon basis of hit_vfx.vert: width = cross(axis, view)).
// v_local is the fragment's offset from the core in units of the flash
// radius: (x, y) on the billboard, (across, along) on the ribbon.
layout(location = 0) in vec2 a_corner;   // unit-quad corner in [-1, 1]

uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_center;        // render-space exit point
uniform vec3  u_forward;       // unit forward axis (streak direction)
uniform float u_radius;        // flash radius (GU)
uniform int   u_mode;          // 0 = billboard, 1 = ribbon
uniform float u_core_radii;
uniform float u_streak_radii;
uniform float u_ring_radii;
uniform float u_ribbon_half_w; // ribbon half-width (radii), set by the pass

out vec2 v_local;

void main() {
    vec3 cam_right = vec3(u_view[0][0], u_view[1][0], u_view[2][0]);
    vec3 cam_up    = vec3(u_view[0][1], u_view[1][1], u_view[2][1]);
    vec3 world;
    if (u_mode == 0) {
        float h = max(2.0 * u_core_radii, 1.3 * u_ring_radii);   // radii
        world = u_center + (a_corner.x * cam_right + a_corner.y * cam_up)
                           * (h * u_radius);
        v_local = a_corner * h;
    } else {
        vec3 axis = u_forward;
        float al = length(axis);
        axis = (al > 1e-6) ? axis / al : cam_up;
        vec3 view = cross(cam_right, cam_up);      // camera depth axis
        vec3 perp = cross(axis, view);
        float pl = length(perp);
        vec3 side = (pl > 1e-6) ? perp / pl : cam_right;
        float along = (a_corner.y * 0.5 + 0.5) * u_streak_radii;                   // radii
        float across = a_corner.x * u_ribbon_half_w;
        world = u_center + (side * across + axis * along) * u_radius;
        v_local = vec2(across, along);
    }
    gl_Position = u_proj * u_view * vec4(world, 1.0);
}
