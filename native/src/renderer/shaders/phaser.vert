#version 330 core
// Per-vertex attributes for an N-sided prism extruded from emitter to
// target.  Per face the CPU emits 6 vertices (two triangles), each
// carrying:
//   a_emitter / a_target — beam endpoints in world space (shared per beam)
//   a_t                  — 0 at emitter, 1 at target
//   a_side_angle         — angle around the beam axis (radians) for
//                           this vertex's prism face
layout(location = 0) in vec3  a_emitter;
layout(location = 1) in vec3  a_target;
layout(location = 2) in float a_t;
layout(location = 3) in float a_side_angle;

uniform mat4  u_view_proj;
uniform float u_main_radius;       // mid-beam half-width
uniform float u_taper_radius;      // half-width at the endpoints
uniform float u_taper_ratio;
uniform float u_taper_min_length;
uniform float u_taper_max_length;
uniform float u_perimeter_tile;
uniform float u_texture_speed;
uniform float u_time;
uniform float u_tiles;

out vec2 v_uv;
out float v_t;

void main() {
    vec3 axis_v = a_target - a_emitter;
    float beam_length = length(axis_v);
    vec3 axis = (beam_length > 1e-5) ? axis_v / beam_length : vec3(0.0, 1.0, 0.0);

    vec3 ref_up = (abs(axis.z) < 0.9) ? vec3(0.0, 0.0, 1.0)
                                       : vec3(0.0, 1.0, 0.0);
    vec3 right_perp = normalize(cross(axis, ref_up));
    vec3 up_perp    = cross(axis, right_perp);

    // Taper: TaperMin/Max clamp the *beam length* used in the ratio;
    // long beams get a fixed-length taper signature.
    float clamped_length = clamp(beam_length, u_taper_min_length, u_taper_max_length);
    float taper_length = u_taper_ratio * clamped_length;
    float dist_from_end = min(a_t, 1.0 - a_t) * beam_length;
    float taper_factor = clamp(taper_length > 1e-5 ? dist_from_end / taper_length : 1.0,
                                0.0, 1.0);
    float radius = mix(u_taper_radius, u_main_radius, taper_factor);

    vec3 offset_dir = cos(a_side_angle) * right_perp + sin(a_side_angle) * up_perp;
    vec3 base       = mix(a_emitter, a_target, a_t);
    vec3 world_pos  = base + offset_dir * radius;

    gl_Position = u_view_proj * vec4(world_pos, 1.0);

    float u_scroll = u_time * u_texture_speed;
    v_uv = vec2(a_t * u_tiles + u_scroll,
                a_side_angle * (u_perimeter_tile / 6.2831853));
    v_t  = a_t;
}
