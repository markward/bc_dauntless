#version 410 core

// Hull interior vertex stage (HullInteriorPass, hull_interior.frag): decks
// and rooms behind a plating cut.
//
// The pass draws the SAME hull mesh the opaque pass drew (via the shared
// renderer::draw_model_positions_only, also used by the shadow-depth pass)
// under the stencil the plating mark stamped, so a fragment here sits on the
// actual hull surface at a cut pixel. No deformation: `a_pos` is NODE-LOCAL,
// while the interior works in the ship's BODY frame, so v_body_pos below
// composes the node chain back in (see its own comment for the derivation and
// the measured Galaxy.nif offset that makes this mandatory, not cosmetic).
//
// Renamed from breach.vert when the old voxel carve and its breach pass were
// removed (layered damage phase 4); this program was its last user.

layout(location = 0) in vec3 a_pos;     // hull mesh vertex position, NODE-LOCAL space
// The mesh's own normal. Free to read: draw_model_positions_only binds the
// mesh's FULL VAO (renderer/model_draw_helpers.cc) and only declines to set
// MATERIAL uniforms -- every attribute the opaque pass uses is still bound
// here, so this costs no extra buffer, upload or draw.
layout(location = 1) in vec3 a_normal;  // hull mesh vertex normal, NODE-LOCAL space

uniform mat4 u_model;   // this mesh's own node-composed world matrix: instance_world * node_chain
                        // (set PER MESH by draw_model_positions_only)
uniform mat4 u_ship_world_inv;  // inverse of the INSTANCE world matrix ALONE (no node chain),
                                // uploaded once per draw by hull_interior_pass.cc
uniform mat4 u_view;
uniform mat4 u_proj;
// This mesh's node: POSED body -> REST body (node_anim.h rest_corrections),
// set per mesh by draw_model_positions_only; identity when not articulated.
// The damage records and the fill volume are rest-frame data (layered damage
// phase 4 §2.1), so the walk runs in the rest frame. Rigid: no normalize.
uniform mat4 u_node_rest_fix;

out vec3 v_body_pos;    // REST-frame position of the actual hull surface point
out vec3 v_body_normal; // REST-frame surface normal

void main() {
    // BODY frame, not node-local. `a_pos` is this mesh's NODE-LOCAL vertex
    // position; `u_model` is instance_world * node_chain (see
    // renderer::draw_model_positions_only, which composes the node chain and
    // sets u_model per mesh). Body frame -- the frame the damage records, the
    // fill volume and u_camera_pos_body live in -- is node_chain * a_pos, so
    // it is recovered by left-multiplying the finished world position by the
    // inverse of the INSTANCE world matrix alone:
    //
    //     inverse(instance_world) * (instance_world * node_chain) * a_pos
    //         == node_chain * a_pos
    //
    // This is exactly opaque.frag's own reconstruction (`p_body =
    // u_ship_world_inv * v_position_ws`, with u_ship_world_inv =
    // inverse(inst.world) set in frame.cc) -- the SAME frame, derived the
    // SAME way, which matters because the plating mark's discard (opaque.frag
    // compiled with PLATING) is what stamps the stencil this pass keys on. It
    // is also the frame the fill volume is decoded in and the frame
    // renderer/ray_trace.cc, aabb.cc and glow_region.cc all walk to.
    //
    // Do NOT "simplify" this to `v_body_pos = a_pos`: that is only correct
    // for a model whose node chain is the identity. Real BC hulls are not --
    // Galaxy.nif's chain is a pure translation of (0, +128.447, +38.005)
    // model units, far larger than a typical hole, so every interior fragment
    // would land in the wrong place.
    // Then into this mesh's node REST frame (u_node_rest_fix; identity for
    // an unarticulated hull, which keeps the body frame exactly).
    v_body_pos  = (u_node_rest_fix * u_ship_world_inv * u_model * vec4(a_pos, 1.0)).xyz;
    // Same composition as v_body_pos, as a direction: the node chain alone
    // (u_ship_world_inv * u_model), with the translation dropped by taking
    // mat3. BC hulls carry uniform scale only, so the inverse-transpose a
    // general normal matrix would need collapses to this; normalising is left
    // to the fragment stage, which has to re-normalise after interpolation
    // anyway.
    v_body_normal = mat3(u_node_rest_fix * u_ship_world_inv * u_model) * a_normal;
    gl_Position = u_proj * u_view * u_model * vec4(a_pos, 1.0);
}
