#version 330 core

// Breach interior-voxel splat. A unit cube ([-0.5,0.5]^3) is drawn once per
// solid interior voxel that fell inside a carve sphere (instanced). Each
// instance positions the cube at its voxel's body-frame centre, scaled to the
// source volume's cell size, then transformed by the same u_model the hull
// uses — so the cubes sit exactly where the hull interior was.

layout(location = 0) in vec3 a_cube;          // unit-cube corner in [-0.5, 0.5]
layout(location = 1) in vec4 i_center_seed;    // xyz = voxel centre (body), w = seed

uniform mat4 u_model;       // instance world transform (hull's u_model)
uniform mat4 u_view;
uniform mat4 u_proj;
uniform vec3 u_cell_half;    // 0.5 * volume.cell (per-axis half extent)

flat out float v_seed;

void main() {
    vec3 local = i_center_seed.xyz + a_cube * u_cell_half;
    gl_Position = u_proj * u_view * u_model * vec4(local, 1.0);
    v_seed = i_center_seed.w;
}
