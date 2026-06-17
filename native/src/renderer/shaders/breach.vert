#version 330 core

// Breach interior scoop — unit sphere driven per active carve sphere.
//
// Each draw call covers one active carve sphere. The breach pass sets:
//   u_carve_center : body-frame centre of the sphere
//   u_carve_radius : radius in body-frame model units
//
// The vertex is placed in body space as:
//   body_pos = u_carve_center + u_carve_radius * a_pos
// where a_pos is a unit-sphere vertex (position == outward normal on a unit
// sphere), so the sphere envelopes the carve region exactly.
//
// Rendered with glCullFace(GL_FRONT): only back faces (the far/inner wall as
// seen from outside) are drawn, so the scoop is recessed and cannot poke
// through the hull. The fill mask in breach.frag discards fragments where
// there is no solid hull material, giving genuine see-through where the sphere
// extends out of the hull volume.

layout(location = 0) in vec3 a_pos;     // unit-sphere vertex (== outward normal)

uniform mat4  u_model;          // ship world matrix (same as opaque pass)
uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_carve_center;   // body-frame sphere centre (model units)
uniform float u_carve_radius;   // sphere radius (model units)

out vec3 v_body_pos;      // body-frame position (fill mask TC + triplanar UVs)
out vec3 v_body_normal;   // unit-sphere outward normal in body frame
out vec3 v_world_pos;     // world position (double-sided lighting)

void main() {
    vec3 body_pos = u_carve_center + u_carve_radius * a_pos;
    vec4 world    = u_model * vec4(body_pos, 1.0);
    v_body_pos    = body_pos;
    v_body_normal = a_pos;              // unit-sphere outward normal in body frame
    v_world_pos   = world.xyz;
    gl_Position   = u_proj * u_view * world;
}
