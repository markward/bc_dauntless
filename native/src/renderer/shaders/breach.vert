#version 410 core

// Breach interior BOX PROXY (raymarched-breach-interior Task 3).
//
// One draw per DAMAGED INSTANCE, not one per carve sphere. This stage places
// a unit cube ([0,1]^3, a_pos) at the instance's own damage-field box --
// u_hull_field_origin .. + u_hull_field_cell*u_hull_field_dims, the SAME
// extent InstanceFieldCache::Entry describes and breach.frag samples through
// -- and does NOTHING else: no per-carve deformation. The fragment shader
// raymarches the field per-pixel to find the actual cavity surface (see
// raymarch_breach_cavity in breach.frag); this stage's only job is to get
// pixels covering that box in front of the rasteriser.
//
// u_hull_field_origin/cell/dims are declared here AND in breach.frag with
// the SAME names: one linked program, one uniform location per name, so
// BreachPass::draw_box_proxy sets each exactly once from C++ and both stages
// see it -- no duplicate uniform, no risk of the two disagreeing.
//
// Winding (the CPU-side mesh in breach_pass.cc's build_unit_box_cpu, not
// anything in this file): EMPIRICALLY verified, not derived from
// build_uv_sphere's stated "clockwise from outside" convention -- see that
// function's own header comment for the measured result and why a naive
// per-face CW/CCW prediction didn't carry over. Rendered with
// glCullFace(GL_FRONT), so only the box's FAR faces (as seen from the
// camera) survive rasterisation -- exactly the point where the view ray
// EXITS the box at every covered pixel. breach.frag's main() relies on
// that: v_body_pos IS the ray's own box-exit point, with no separate
// computation needed.
//
// NOTE: the old per-carve deformation (u_carve_center/u_carve_radius/
// u_carve_normal, the vh3/vnoise3 noise helpers) is dead below this point --
// nothing sets those uniforms or calls those functions any more. Left in
// place deliberately: retiring them is Task 4's job (raymarched-breach-
// interior plan), not this one, so this diff stays focused on the box
// proxy itself.

layout(location = 0) in vec3 a_pos;     // unit-cube corner, [0,1]^3

uniform mat4  u_model;          // ship world matrix (same as opaque pass)
uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_carve_center;   // DEAD -- see note above (Task 4 removes)
uniform float u_carve_radius;   // DEAD -- see note above (Task 4 removes)
uniform vec3  u_carve_normal;   // DEAD -- see note above (Task 4 removes)

// Field box extent -- see this file's header comment. Body frame, model
// units. Shared uniform names with breach.frag's own copies.
uniform vec3  u_hull_field_origin;
uniform vec3  u_hull_field_cell;
uniform vec3  u_hull_field_dims;

out vec3 v_body_pos;      // body-frame position on the box surface (ray-exit point)

// breach shape — DEAD, see note above (Task 4 removes). KEPT VERBATIM so
// this diff does not also have to re-derive/re-verify shape math nobody
// calls any more.
const float kDepthFactor = 0.45;  // depth = kDepthFactor * radius (shallow)
const float kShapeAmp    = 0.25;
const float kShapeFreq   = 4.0;
const float kPhase       = 0.13;

float vh3(vec3 p){ return fract(sin(dot(p, vec3(127.1,311.7,74.7))) * 43758.5453123); }
float vnoise3(vec3 p){
    vec3 i = floor(p), f = fract(p);
    vec3 u = f*f*(3.0-2.0*f);
    float n000=vh3(i), n100=vh3(i+vec3(1,0,0)), n010=vh3(i+vec3(0,1,0)), n110=vh3(i+vec3(1,1,0));
    float n001=vh3(i+vec3(0,0,1)), n101=vh3(i+vec3(1,0,1)), n011=vh3(i+vec3(0,1,1)), n111=vh3(i+vec3(1,1,1));
    float nx00=mix(n000,n100,u.x), nx10=mix(n010,n110,u.x), nx01=mix(n001,n101,u.x), nx11=mix(n011,n111,u.x);
    return mix(mix(nx00,nx10,u.y), mix(nx01,nx11,u.y), u.z);
}

void main() {
    vec3 body_pos = u_hull_field_origin + a_pos * (u_hull_field_cell * u_hull_field_dims);
    v_body_pos    = body_pos;
    vec4 world    = u_model * vec4(body_pos, 1.0);
    gl_Position   = u_proj * u_view * world;
}
