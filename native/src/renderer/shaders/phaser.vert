#version 330 core
// Six vertex IDs per beam: build a quad spanning emitter→target with
// width perpendicular to the beam-axis × view-direction.
layout(location = 0) in vec3 a_emitter;
layout(location = 1) in vec3 a_target;
layout(location = 2) in float a_corner;   // 0..5 → which quad corner

uniform mat4  u_view_proj;
uniform vec3  u_camera_pos;
uniform float u_width;

out vec2 v_uv;

void main() {
    // Quad layout (corner index → t along beam, side perpendicular):
    //  0: t=0, side=-1    3: t=0, side=-1
    //  1: t=1, side=-1    4: t=1, side=+1
    //  2: t=1, side=+1    5: t=0, side=+1
    int idx = int(a_corner);
    float t      = (idx == 1 || idx == 2 || idx == 4) ? 1.0 : 0.0;
    float side   = (idx == 2 || idx == 4 || idx == 5) ? 1.0 : -1.0;
    vec3 base    = mix(a_emitter, a_target, t);
    vec3 axis    = normalize(a_target - a_emitter);
    vec3 to_cam  = normalize(u_camera_pos - base);
    vec3 perp    = normalize(cross(axis, to_cam));
    vec3 world   = base + perp * (side * u_width);
    gl_Position  = u_view_proj * vec4(world, 1.0);
    v_uv         = vec2(t, side * 0.5 + 0.5);
}
