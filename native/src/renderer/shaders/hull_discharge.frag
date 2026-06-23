#version 330 core
in vec2 v_uv;             // [-1,1] quad space
out vec4 frag;

uniform vec3  u_color;
uniform float u_alpha;    // life fade (1->0)
uniform float u_stutter;  // 0 or 1 -- 2-frame on/off flicker gate
// dials
uniform int   u_filaments;  // default 5
uniform float u_jag;        // default 6.0  (radial jaggedness frequency)
uniform float u_thick;      // default 0.06 (filament thickness)
uniform float u_core;       // default 0.25 (hot core radius)

float hash(float n){ return fract(sin(n) * 43758.5453); }

void main() {
    if (u_stutter < 0.5 || u_alpha <= 0.0) { frag = vec4(0.0); return; }
    float r = length(v_uv);
    if (r > 1.0) { frag = vec4(0.0); return; }
    float ang = atan(v_uv.y, v_uv.x);

    // Forked filaments: bright where the angle is near one of N jagged spokes.
    float fil = 0.0;
    for (int i = 0; i < u_filaments; ++i) {
        float base = (6.2831853 / float(u_filaments)) * float(i);
        // jagged wobble of the spoke angle with radius
        float wob = (hash(float(i) + floor(r * u_jag)) - 0.5) * 0.8;
        float d = abs(mod(ang - base - wob + 3.14159265, 6.2831853) - 3.14159265);
        fil = max(fil, smoothstep(u_thick, 0.0, d) * (1.0 - r));
    }
    // Hot core + filaments, faded by life. Electric tint.
    float core = smoothstep(u_core, 0.0, r);
    float e = clamp(core + fil, 0.0, 1.0) * u_alpha;
    frag = vec4(u_color * e, 1.0);   // premultiplied additive (blend GL_ONE, GL_ONE)
}
