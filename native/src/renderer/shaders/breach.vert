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
uniform vec3  u_carve_normal;   // body-frame outward hit normal

out vec3 v_body_pos;      // body-frame position (fill mask TC + triplanar UVs)
out vec3 v_body_normal;   // unit-sphere outward normal in body frame
out vec3 v_world_pos;     // world position (double-sided lighting)

// breach shape — KEEP IN SYNC with opaque.frag.
// The breach is an OBLATE spheroid centred on the hull surface: FULL lateral
// radius (original hole width) but compressed to kDepthFactor along the normal
// (shallow). Noise perturbs the lateral radius by azimuth (jagged rim).
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
    vec3  nrm     = normalize(u_carve_normal);
    float along   = dot(a_pos, nrm);            // unit-sphere component along the normal
    vec3  lateral = a_pos - along * nrm;         // unit-sphere lateral component
    float ll      = length(lateral);
    // Azimuthal direction (around the normal) drives the noise — identical on
    // both the hull-clip and the scoop, so the jagged rim aligns.
    vec3  az = ll > 1e-4 ? lateral / ll : vec3(1.0, 0.0, 0.0);
    float r_eff = u_carve_radius * (1.0 + kShapeAmp * (vnoise3(az * kShapeFreq + u_carve_center * kPhase) * 2.0 - 1.0));
    // Oblate spheroid: full lateral radius r_eff, compressed depth along normal.
    vec3 body_pos = u_carve_center
                  + lateral * r_eff
                  + nrm * (along * kDepthFactor * u_carve_radius);
    vec4 world    = u_model * vec4(body_pos, 1.0);
    v_body_pos    = body_pos;
    v_body_normal = a_pos;              // unit-sphere outward normal in body frame
    v_world_pos   = world.xyz;
    gl_Position   = u_proj * u_view * world;
}
