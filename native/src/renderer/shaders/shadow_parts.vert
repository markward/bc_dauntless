#version 410 core
// Depth-only shadow caster, PART-MASK variant (layered damage phase 4 §2.3):
// drawn only for an instance that has lost a structure part
// (Instance::severed_parts) or is a severed chunk (Instance::shown_parts).
// Every other caster keeps shadow.vert/.frag. Position attribute location
// MUST match opaque.vert so the same mesh VAOs feed this program unchanged.
layout(location = 0) in vec3 a_position;

uniform mat4 u_light_view_proj;
uniform mat4 u_model;
uniform mat4 u_ship_world_inv;   // inverse(instance world): world -> body
uniform mat4 u_node_rest_fix;    // per mesh: posed body -> rest body (identity unposed)

// The REST-frame body position: the same chain opaque.frag's PLATING main
// builds p_pl from (u_ship_world_inv on the world position, then
// u_node_rest_fix), so the shadow and the visible hull cut at the same place.
// Affine in a_position, so interpolating it is exact.
out vec3 v_p_rest;

void main() {
    vec4 ws = u_model * vec4(a_position, 1.0);
    v_p_rest = (u_node_rest_fix * vec4((u_ship_world_inv * ws).xyz, 1.0)).xyz;
    gl_Position = u_light_view_proj * ws;
}
