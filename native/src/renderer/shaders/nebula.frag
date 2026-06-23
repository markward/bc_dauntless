#version 330 core
in  vec3 v_world;
out vec4 frag;

uniform sampler2D u_overlay;    // nebulaoverlay.tga (alpha noise)
uniform vec3  u_eye;            // camera world pos (GU)
uniform vec3  u_center;         // sphere centre (GU)
uniform float u_radius;         // sphere radius (GU)
uniform vec3  u_rgb;            // nebula tint
uniform float u_visibility;     // GU falloff
// Tunable dials.
uniform float u_max_fog;        // ceiling on fog alpha (default 0.92)
uniform float u_noise_amount;   // overlay modulation 0..1 (default 0.35)
uniform float u_noise_scale;    // world->uv frequency (default 0.004)

void main() {
    // View ray from the eye toward this back-surface fragment.
    vec3 dir = normalize(v_world - u_eye);
    // Analytic ray/sphere intersection (o=u_eye, d=dir, centre=u_center, R=u_radius).
    vec3  L   = u_center - u_eye;
    float tca = dot(L, dir);
    float d2  = dot(L, L) - tca * tca;
    float r2  = u_radius * u_radius;
    if (d2 > r2) discard;                 // ray misses (shouldn't happen on the mesh)
    float thc   = sqrt(r2 - d2);
    float t0    = tca - thc;              // entry
    float t1    = tca + thc;              // exit
    float entry = max(t0, 0.0);           // clamp to camera when inside
    float path  = max(t1 - entry, 0.0);   // GU travelled through the volume

    float fog = 1.0 - exp(-path / max(u_visibility, 1.0));

    // World-projected noise breakup (cheap planar projection of the entry point).
    vec3  p  = u_eye + dir * entry;
    float n  = texture(u_overlay, p.xy * u_noise_scale).a;
    fog *= (1.0 - u_noise_amount) + u_noise_amount * n;
    fog  = clamp(fog, 0.0, u_max_fog);

    frag = vec4(u_rgb, fog);              // SRC_ALPHA blend composites the tint
}
