#version 330 core

// Breach interior surface. The dual-contour mesh is supplied in the source
// hull's body frame (positions + outward normals). We transform position by the
// same u_model the hull uses so the cross-section sits exactly where the hull
// interior was. The body-frame position and normal are passed through for the
// fragment shader's triplanar projection; the world position is passed for the
// view-direction used by double-sided lighting.

layout(location = 0) in vec3 a_pos;     // body-frame position (DC mesh)
layout(location = 1) in vec3 a_normal;   // body-frame outward normal

uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_proj;

out vec3 v_body_pos;     // body-frame position (triplanar UVs)
out vec3 v_body_normal;  // body-frame normal (triplanar weights + lighting)
out vec3 v_world_pos;    // world position (view direction)

void main() {
    vec4 world = u_model * vec4(a_pos, 1.0);
    gl_Position = u_proj * u_view * world;
    v_body_pos    = a_pos;
    v_body_normal = a_normal;
    v_world_pos   = world.xyz;
}
