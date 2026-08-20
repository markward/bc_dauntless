#version 330 core
in vec2 v_uv;
out vec4 frag_color;

uniform vec3  u_color;
uniform float u_opacity;
uniform int   u_kind;   // 0 disc, 1 line, 2 point, 3 bracket

void main() {
    if (u_kind == 1) {
        frag_color = vec4(u_color, u_opacity);
        return;
    }
    vec2  d = v_uv * 2.0 - 1.0;
    float r = length(d);
    if (u_kind == 0) {
        // Soft radial falloff — no texture asset needed. Fades to zero at the
        // rim so the billboard never shows a square edge (the documented
        // particle-artifact failure mode).
        float a = smoothstep(1.0, 0.0, r);
        frag_color = vec4(u_color, a * a * u_opacity);
        return;
    }
    if (u_kind == 2) {
        float a = smoothstep(1.0, 0.55, r);
        frag_color = vec4(u_color, a * u_opacity);
        return;
    }
    // Bracket: four corner L-shapes. Keep the legs, discard the middle AND
    // the hollow inside each corner.
    //
    // Leg length and leg thickness are SEPARATE knobs. They were not: `arm`
    // sat beside a hardcoded 0.55, and because 1.0 - 0.45 == 0.55 the ||
    // clause was subsumed by the && pair, collapsing the whole gate to
    // `ad.x > 0.55 && ad.y > 0.55` — four filled squares, with `arm` dead.
    // Keep the two independent, or the knob silently stops working again.
    vec2  ad = abs(d);
    float arm   = 0.45;   // leg LENGTH, as a fraction of the marker half-size
    float thick = 0.15;   // leg THICKNESS, same units
    bool corner = (ad.x > 1.0 - thick || ad.y > 1.0 - thick)
               && ad.x > 1.0 - arm && ad.y > 1.0 - arm;
    if (!corner) discard;
    frag_color = vec4(u_color, u_opacity);
}
