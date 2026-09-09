#version 410 core

// Breach interior — real hull-mesh proxy (raymarched-breach-interior Task 3,
// round 3).
//
// One draw per DAMAGED INSTANCE, not one per carve sphere, and — as of round
// 3 — not a synthetic box proxy either: BreachPass now draws the SAME hull
// mesh geometry the opaque pass drew (via the shared
// renderer::draw_model_positions_only, also used by the shadow-depth pass),
// under the SAME carve stencil (breach_pass.cc's begin_scoop_state, GL_EQUAL
// against 1). A fragment that survives here is therefore, by construction,
// on the ACTUAL hull surface at the point the carve field made opaque.frag
// discard it — i.e. already inside carved material (sample_hull_field(p) >
// margin, the SAME condition that made the opaque pass discard and the
// stencil pass mark it 1). breach.frag's main() relies on exactly that: no
// separate search for where the ray enters the carve is needed any more,
// because this fragment already sits there.
//
// This stage performs NO deformation, NOT EVEN a box placement — it is a
// plain position/MVP passthrough, one step simpler than even
// draw_model_positions_only's own C++ side needs to be, because the vertex
// shader only ever sees one mesh's already-node-composed `u_model`.
//
// (Retired this round, not merely dead: the box proxy — u_hull_field_origin/
// cell/dims driving a_pos as a unit-cube corner — and, from round 1 before
// it, the per-carve oblate deformation (u_carve_center/radius/normal, the
// vh3/vnoise3 noise helpers). Both are gone from this file, not left commented
// out: there is no "Task 4 cleanup" pending on this file any more, because
// there is nothing left in it to clean up.)

layout(location = 0) in vec3 a_pos;     // hull mesh vertex position, MODEL/body space

uniform mat4 u_model;   // this mesh's own node-composed world matrix (draw_model_positions_only)
uniform mat4 u_view;
uniform mat4 u_proj;

out vec3 v_body_pos;    // body-frame position — the ACTUAL hull surface point

void main() {
    v_body_pos  = a_pos;
    gl_Position = u_proj * u_view * u_model * vec4(a_pos, 1.0);
}
