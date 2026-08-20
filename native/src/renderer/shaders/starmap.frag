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
    // Bracket: four corner L-shapes. Keep the corners, discard the middle.
    vec2  ad = abs(d);
    float arm = 0.45;
    bool corner = (ad.x > 1.0 - arm || ad.y > 1.0 - arm)
               && ad.x > 0.55 && ad.y > 0.55;
    if (!corner) discard;
    frag_color = vec4(u_color, u_opacity);
}
