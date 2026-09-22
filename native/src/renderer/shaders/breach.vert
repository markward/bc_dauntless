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
// This stage performs NO deformation and NOT EVEN a box placement. It is not
// quite a passthrough either: `a_pos` is NODE-LOCAL, while every consumer of
// the damage field works in the ship's BODY frame, so v_body_pos below
// composes the node chain back in (see its own comment for the derivation and
// for the measured Galaxy.nif offset that makes this mandatory, not
// cosmetic).
//
// (Retired this round, not merely dead: the box proxy — u_hull_field_origin/
// cell/dims driving a_pos as a unit-cube corner — and, from round 1 before
// it, the per-carve oblate deformation (u_carve_center/radius/normal, the
// vh3/vnoise3 noise helpers). Both are gone from this file, not left commented
// out: there is no "Task 4 cleanup" pending on this file any more, because
// there is nothing left in it to clean up.)

layout(location = 0) in vec3 a_pos;     // hull mesh vertex position, NODE-LOCAL space
// The mesh's own normal. Free to read: draw_model_positions_only binds the
// mesh's FULL VAO (renderer/model_draw_helpers.cc) and only declines to set
// MATERIAL uniforms -- every attribute the opaque pass uses is still bound
// here, so this costs no extra buffer, upload or draw. Used ONLY by the
// interior-shell path (u_interior_shell != 0 in breach.frag), where the
// fragment IS the interior wall and there is no raymarch to take a field
// gradient from; the scoop path ignores it entirely.
layout(location = 1) in vec3 a_normal;  // hull mesh vertex normal, NODE-LOCAL space

uniform mat4 u_model;   // this mesh's own node-composed world matrix: instance_world * node_chain
                        // (set PER MESH by draw_model_positions_only)
uniform mat4 u_ship_world_inv;  // inverse of the INSTANCE world matrix ALONE (no node chain),
                                // uploaded once per draw by breach_pass.cc
uniform mat4 u_view;
uniform mat4 u_proj;

out vec3 v_body_pos;    // BODY-frame position of the actual hull surface point
out vec3 v_body_normal; // BODY-frame surface normal (interior shell only; see above)

void main() {
    // BODY frame, not node-local. `a_pos` is this mesh's NODE-LOCAL vertex
    // position; `u_model` is instance_world * node_chain (see
    // renderer::draw_model_positions_only, which composes the node chain and
    // sets u_model per mesh). Body frame -- the frame the damage field, the
    // fill volume, u_camera_pos_body and u_breach_center all live in -- is
    // node_chain * a_pos, so it is recovered by left-multiplying the finished
    // world position by the inverse of the INSTANCE world matrix alone:
    //
    //     inverse(instance_world) * (instance_world * node_chain) * a_pos
    //         == node_chain * a_pos
    //
    // This is exactly opaque.frag's own reconstruction (`p_body =
    // u_ship_world_inv * v_position_ws`, with u_ship_world_inv =
    // inverse(inst.world) set in frame.cc) -- the SAME frame, derived the
    // SAME way, which matters because opaque.frag's discard is what stamps
    // the stencil this pass keys on. It is also the frame voxelize.cc's
    // collect_hull_triangles bakes the field in (it composes the same node
    // chain), and the frame renderer/ray_trace.cc, aabb.cc and
    // glow_region.cc all walk to.
    //
    // Do NOT "simplify" this to `v_body_pos = a_pos`: that is only correct
    // for a model whose node chain is the identity. Real BC hulls are not --
    // Galaxy.nif's chain is a pure translation of (0, +128.447, +38.005)
    // model units, ~27 field cells in Y against carves whose entire
    // along-normal extent is 2.7-27 model units, so every breach fragment
    // would sample untouched field and discard.
    v_body_pos  = (u_ship_world_inv * u_model * vec4(a_pos, 1.0)).xyz;
    // Same composition as v_body_pos, as a direction: the node chain alone
    // (u_ship_world_inv * u_model), with the translation dropped by taking
    // mat3. BC hulls carry uniform scale only, so the inverse-transpose a
    // general normal matrix would need collapses to this; normalising is left
    // to the fragment stage, which has to re-normalise after interpolation
    // anyway.
    v_body_normal = mat3(u_ship_world_inv * u_model) * a_normal;
    gl_Position = u_proj * u_view * u_model * vec4(a_pos, 1.0);
}
