#version 330 core

// Breach interior surface. The dual-contour mesh is supplied in the source
// hull's body frame (positions + outward normals). We transform position by the
// same u_model the hull uses so the cross-section sits exactly where the hull
// interior was. The body-frame position and normal are passed through for the
// fragment shader's triplanar projection; the world position is passed for the
// view-direction used by double-sided lighting.
//
// u_inflate: inflate each vertex along its outward body-frame normal BEFORE the
// model transform. The DC isosurface sits ~1 cell inset from the real hull
// surface (lattice nodes are at cell centres, one cell inside the AABB), so the
// cavity rim appears recessed behind the clip hole → visible gap to space.
// Inflating by ~1 cell pushes the rim outward to meet the hull/clip-hole edge.
// Set from breach_pass.cc as cellSize * kInflateCells (default 1.0).

layout(location = 0) in vec3 a_pos;     // body-frame position (DC mesh)
layout(location = 1) in vec3 a_normal;   // body-frame outward normal

uniform mat4  u_model;
uniform mat4  u_view;
uniform mat4  u_proj;
uniform float u_inflate;  // outward displacement in body-frame units (~1 cell)

out vec3 v_body_pos;     // body-frame position (triplanar UVs)
out vec3 v_body_normal;  // body-frame normal (triplanar weights + lighting)
out vec3 v_world_pos;    // world position (view direction)

void main() {
    // Inflate in body frame before applying the model transform so the offset
    // is in the same space as the DC mesh (body-frame cell units).
    vec3 inflated = a_pos + normalize(a_normal) * u_inflate;
    vec4 world = u_model * vec4(inflated, 1.0);
    gl_Position = u_proj * u_view * world;
    v_body_pos    = a_pos;      // keep un-inflated for triplanar UVs
    v_body_normal = a_normal;
    v_world_pos   = world.xyz;
}
