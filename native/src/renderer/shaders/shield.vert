#version 330 core

layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;

uniform mat4 u_proj;
uniform mat4 u_view;
uniform mat4 u_world;       // ship_world transform (per ship)
uniform mat4 u_ship_local;  // ellipsoid: scale*translate; skin: identity

out vec3 v_world_pos;
out vec3 v_ship_local_pos;
out vec3 v_ship_local_normal;

void main() {
    // Bubble vertex in ship-local space (pre-world transform). This is
    // what we sample triplanar hex against — pins the hex pattern to the
    // ship so it doesn't swim as the ship moves.
    vec4 lp = u_ship_local * vec4(a_position, 1.0);
    v_ship_local_pos = lp.xyz;
    v_ship_local_normal = mat3(u_ship_local) * a_normal;

    vec4 wp = u_world * lp;
    v_world_pos = wp.xyz;
    gl_Position = u_proj * u_view * wp;
}
