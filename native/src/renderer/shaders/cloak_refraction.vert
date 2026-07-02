#version 330 core
// Cloak refraction — mesh transform. The pass re-draws the cloaking ship's real
// geometry at its world transform; the fragment shader bends the background
// behind each fragment and composites the hull's own textures translucently.
//
// An animated vertex displacement along the world normal makes the silhouette
// waver ("wobble"), ramped by cloak progress (u_frac) so a fully decloaked ship
// is geometrically untouched. The phase varies with world position for a
// travelling-ripple look rather than a uniform breathing pulse.
layout(location = 0) in vec3 a_pos;
layout(location = 1) in vec3 a_normal;
layout(location = 2) in vec2 a_uv;
uniform mat4  u_model;
uniform mat4  u_view_proj;
uniform float u_time;
uniform float u_frac;           // 0..1 cloak progress
uniform float u_shimmer_speed;  // shimmer angular frequency (rad/s)
uniform float u_vertex_wobble;  // displacement amplitude (game units)
out vec3 v_world_pos;
out vec3 v_world_normal;
out vec2 v_uv;
void main() {
    vec4 wp   = u_model * vec4(a_pos, 1.0);
    vec3 nrm  = normalize(mat3(u_model) * a_normal);

    // Travelling ripple: phase seeded by world position so different parts of
    // the hull crest at different times. The wobble amplitude tracks cloak
    // progress — it scales linearly from 0 (visible) up to 25% of
    // u_vertex_wobble at full cloak, so the silhouette eases into the waver over
    // the cloak-in transition and eases back out when decloaking (u_frac ramps
    // 1 -> 0). u_frac is the same 0..1 progress the opacity fade uses.
    float phase = dot(wp.xyz, vec3(0.15, 0.11, 0.13));
    float wob   = sin(u_time * u_shimmer_speed + phase)
                * u_vertex_wobble * 0.25 * u_frac;
    wp.xyz += nrm * wob;

    v_world_pos    = wp.xyz;
    v_world_normal = nrm;
    v_uv           = a_uv;
    gl_Position    = u_view_proj * wp;
}
